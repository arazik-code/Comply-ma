"""
Middleware de sécurité — en-têtes HTTP et rate limiting login.

La protection CSRF est gérée comme dépendance FastAPI globale (voir csrf.py) :
une dépendance peut lire le formulaire sans casser le parsing FastAPI,
contrairement à un middleware qui consommerait le body.
"""
import logging
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger("app.security")

# ── En-têtes de sécurité ─────────────────────────────────────────
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    # CSP : inline styles/scripts autorisés (htmx + thème), sources externes
    # limitées à Google Fonts. frame-ancestors none double X-Frame-Options.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}

# ── Rate limiting login ──────────────────────────────────────────
LOGIN_PATHS = {"/login", "/portal/login"}
MAX_LOGIN_ATTEMPTS = 10          # tentatives
LOGIN_WINDOW_SECONDS = 300       # fenêtre de 5 minutes
LOCKOUT_SECONDS = 900            # verrouillage 15 minutes

_attempts: dict[str, deque] = defaultdict(deque)
_locked_until: dict[str, float] = {}


def _client_ip(request) -> str:
    # Derrière un reverse proxy (uvicorn --proxy-headers), client.host est l'IP réelle.
    return request.client.host if request.client else "unknown"


def is_rate_limited(ip: str) -> bool:
    """True si l'IP est verrouillée après trop d'échecs de login."""
    now = time.time()
    until = _locked_until.get(ip)
    if until is not None:
        if now < until:
            return True
        del _locked_until[ip]
        _attempts.pop(ip, None)
    return False


def record_login_failure(ip: str):
    """Enregistre un échec de login et verrouille si seuil atteint."""
    now = time.time()
    q = _attempts[ip]
    q.append(now)
    while q and now - q[0] > LOGIN_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= MAX_LOGIN_ATTEMPTS:
        _locked_until[ip] = now + LOCKOUT_SECONDS
        logger.warning("login_rate_limit_locked", extra={"ip": ip})
        q.clear()


def clear_login_failures(ip: str):
    """Réinitialise le compteur après un login réussi."""
    _attempts.pop(ip, None)
    _locked_until.pop(ip, None)


def _login_succeeded(response: Response) -> bool:
    if response.status_code != 303:
        return False
    location = response.headers.get("location", "")
    return "error" not in location and location.rstrip("/") in ("/", "/portal/invoices")


def _count_login_failure(response: Response) -> bool:
    """
    Ne compte comme échec de brute-force qu'une vraie tentative de login
    refusée pour mauvaises informations (200 = page réaffichée avec erreur).
    Les 403 CSRF et les 429 ne comptent pas.
    """
    return response.status_code == 200


def reset_rate_limits():
    """Réinitialise tout l'état de rate limiting (utilisé par les tests)."""
    _attempts.clear()
    _locked_until.clear()


class SecurityHeadersRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Applique les en-têtes de sécurité sur toutes les réponses et le rate
    limiting sur les routes de login.
    """

    async def dispatch(self, request, call_next):
        # ── Rate limiting login ──────────────────────────────────
        path = urlparse(request.url.path).path.rstrip("/") or "/"
        if path in LOGIN_PATHS and request.method == "POST":
            ip = _client_ip(request)
            if is_rate_limited(ip):
                logger.warning("login_rate_limited", extra={"ip": ip, "path": path})
                return Response(
                    "Trop de tentatives. Réessayez dans 15 minutes.",
                    status_code=429,
                    media_type="text/plain",
                )
            response = await call_next(request)
            if _login_succeeded(response):
                clear_login_failures(ip)
            elif _count_login_failure(response):
                record_login_failure(ip)
            _add_security_headers(response)
            return response

        response = await call_next(request)
        _add_security_headers(response)
        return response


def _add_security_headers(response: Response):
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response
