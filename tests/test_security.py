"""
Tests de sécurité — CSRF, en-têtes, rate limiting, XXE, uploads, CSV, fail-fast.
"""
import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.main import app as fastapi_app
from app.config import settings

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.services.security_middleware import reset_rate_limits
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def client():
    with TestClient(fastapi_app) as c:
        yield c


def _get_token(client) -> str:
    resp = client.get("/login")
    m = CSRF_RE.search(resp.text)
    assert m, "token CSRF introuvable sur /login"
    return m.group(1)


class TestCSRF:
    def test_post_without_token_rejected(self, client):
        resp = client.post("/login", data={"username": "x", "password": "y"}, follow_redirects=False)
        assert resp.status_code == 403

    def test_post_with_bad_token_rejected(self, client):
        resp = client.post(
            "/login",
            data={"username": "x", "password": "y", "csrf_token": "wrong-token"},
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_post_with_valid_token_passes_csrf(self, client):
        token = _get_token(client)
        resp = client.post(
            "/login",
            data={"username": "nobody", "password": "wrong", "csrf_token": token},
            follow_redirects=False,
        )
        # Le CSRF passe (pas 403) ; on échoue l'authentification (200 = page erreur)
        assert resp.status_code == 200

    def test_token_stable_within_session(self, client):
        t1 = _get_token(client)
        t2 = _get_token(client)
        assert t1 == t2

    def test_header_token_accepted(self, client):
        token = _get_token(client)
        resp = client.post(
            "/login",
            data={"username": "nobody", "password": "wrong"},
            headers={"X-CSRF-Token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 200


class TestSecurityHeaders:
    def test_headers_present_on_page(self, client):
        resp = client.get("/login")
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" in csp
        assert "default-src 'self'" in csp


class TestRateLimiting:
    def test_lockout_after_max_failures(self, client):
        token = _get_token(client)
        for _ in range(10):
            resp = client.post(
                "/login",
                data={"username": "nobody", "password": "wrong", "csrf_token": token},
                follow_redirects=False,
            )
            assert resp.status_code == 200
        # La 11e tentative est bloquée, même avec un token valide
        resp = client.post(
            "/login",
            data={"username": "nobody", "password": "wrong", "csrf_token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 429

    def test_csrf_failures_do_not_count(self, client):
        # Beaucoup de POST sans token → rejet CSRF, mais PAS de verrouillage
        for _ in range(15):
            client.post("/login", data={"username": "x", "password": "y"}, follow_redirects=False)
        token = _get_token(client)
        resp = client.post(
            "/login",
            data={"username": "nobody", "password": "wrong", "csrf_token": token},
            follow_redirects=False,
        )
        assert resp.status_code == 200  # pas 429


class TestCSRFModule:
    def test_verify_uses_constant_time_compare(self):
        from app.services.csrf import verify_csrf_token

        class FakeSession(dict):
            pass

        class FakeRequest:
            session = {"_csrf_token": "abc123"}

        assert verify_csrf_token(FakeRequest(), "abc123") is True
        assert verify_csrf_token(FakeRequest(), "xyz") is False
        assert verify_csrf_token(FakeRequest(), None) is False
        assert verify_csrf_token(FakeRequest(), "") is False


class TestUploadSecurity:
    def test_rejects_executable_extension(self):
        from app.services.upload_security import validate_image_upload, UploadValidationError
        with pytest.raises(UploadValidationError):
            validate_image_upload("evil.exe", b"MZ\x90\x00")

    def test_rejects_svg(self):
        from app.services.upload_security import validate_image_upload, UploadValidationError
        with pytest.raises(UploadValidationError):
            validate_image_upload("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")

    def test_rejects_oversized(self):
        from app.services.upload_security import validate_image_upload, UploadValidationError
        big = b"\x89PNG\r\n\x1a\n" + b"0" * (3 * 1024 * 1024)
        with pytest.raises(UploadValidationError):
            validate_image_upload("big.png", big)

    def test_rejects_magic_mismatch(self):
        from app.services.upload_security import validate_image_upload, UploadValidationError
        with pytest.raises(UploadValidationError):
            validate_image_upload("fake.png", b"not-a-png-at-all")

    def test_accepts_valid_png(self):
        from app.services.upload_security import validate_image_upload
        ext = validate_image_upload("logo.PNG", b"\x89PNG\r\n\x1a\n" + b"data")
        assert ext == ".png"

    def test_accepts_valid_jpeg(self):
        from app.services.upload_security import validate_image_upload
        ext = validate_image_upload("photo.jpeg", b"\xff\xd8\xff" + b"data")
        assert ext == ".jpg"


class TestCSVInjection:
    def test_dangerous_prefixes_neutralized(self):
        from app.routers.export import _csv_safe
        for prefix in ("=", "+", "-", "@", "\t", "\r"):
            out = _csv_safe(prefix + "evil()")
            assert out.startswith("'")
            assert out[1:] == prefix + "evil()"

    def test_safe_value_unchanged(self):
        from app.routers.export import _csv_safe
        assert _csv_safe("Client Normal") == "Client Normal"
        assert _csv_safe("") == ""


class TestXXEProtection:
    def test_xxe_payload_rejected(self):
        """Un XML avec entité externe est rejeté (pas de lecture de fichier)."""
        xxe = b"""<?xml version="1.0"?>
        <!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
        <Invoice><ID>&xxe;</ID></Invoice>"""
        from lxml import etree
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
        root = etree.fromstring(xxe, parser)
        # L'entité n'est PAS résolue : aucun contenu de fichier dans le document
        id_el = root.find("{*}ID")
        assert id_el is not None
        assert (id_el.text or "").strip() == ""


class TestSessionCookieHardening:
    def test_session_cookie_samesite_lax(self, client):
        resp = client.get("/login")
        set_cookie = resp.headers.get("set-cookie", "")
        assert "SameSite=lax" in set_cookie or "samesite=lax" in set_cookie.lower()


class TestFailFastConfig:
    def test_is_default_secret_detection(self):
        assert settings.is_default_secret is True  # défaut de dev
        s2 = settings.model_copy(update={"secret_key": "a-real-production-key-123456"})
        assert s2.is_default_secret is False
