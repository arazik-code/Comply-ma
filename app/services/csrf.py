"""
Protection CSRF — token lié à la session, vérifié par dépendance FastAPI.

Le token est généré une fois par session, intégré dans chaque formulaire
via le global Jinja `csrf_token(request)`, et vérifié par la dépendance
globale `verify_csrf_dependency` appliquée à toutes les routes non-sures.

Implémentation en dépendance (plutôt qu'en middleware) pour ne pas
consommer le body : FastAPI garde le parsing des formulaires intact.
"""
import secrets
from typing import Optional

from fastapi import Request, HTTPException, status

_CSRF_KEY = "_csrf_token"

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def get_csrf_token(request: Request) -> str:
    """Retourne (et crée si besoin) le token CSRF de la session."""
    token = request.session.get(_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_CSRF_KEY] = token
    return token


def verify_csrf_token(request: Request, submitted: Optional[str]) -> bool:
    """Comparaison en temps constant entre le token de session et celui soumis."""
    token = request.session.get(_CSRF_KEY)
    if not token or not submitted:
        return False
    return secrets.compare_digest(token, submitted)


async def verify_csrf_dependency(request: Request):
    """
    Dépendance FastAPI : vérifie le token CSRF sur les méthodes non-sures.
    Accepte le token soit dans le formulaire (csrf_token), soit dans
    l'en-tête X-CSRF-Token (clients API / fetch).
    """
    if request.method in SAFE_METHODS:
        return
    submitted: Optional[str] = request.headers.get("X-CSRF-Token")
    if not submitted:
        content_type = request.headers.get("content-type", "")
        if "form" in content_type:
            form = await request.form()
            submitted = form.get("csrf_token")
    if not verify_csrf_token(request, submitted):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token invalide ou manquant",
        )
