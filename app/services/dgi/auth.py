"""
Client API DGI Maroc — authentification OAuth 2.0 et mTLS.

Gère le cycle de vie des tokens et la sécurité mutuelle
pour la communication avec la plateforme DGI/xHub.
"""
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("app.dgi.auth")


@dataclass
class TokenInfo:
    access_token: str
    token_type: str
    expires_at: float
    scope: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at - 60  # 60s safety margin

    @property
    def authorization_header(self) -> str:
        return f"{self.token_type} {self.access_token}"


class DGIAuthenticator:
    """
    Authentification OAuth 2.0 pour la plateforme DGI.

    Supporte :
      - Client Credentials Grant (server-to-server)
      - mTLS (mutual Transport Layer Security)
      - Token caching et refresh automatique
    """

    def __init__(
        self,
        token_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
        mtls_cert_path: Optional[str] = None,
        mtls_key_path: Optional[str] = None,
    ):
        self.token_url = token_url or getattr(settings, "dgi_token_url", "")
        self.client_id = client_id or getattr(settings, "dgi_client_id", "")
        self.client_secret = client_secret or getattr(settings, "dgi_client_secret", "")
        self.scope = scope or getattr(settings, "dgi_scope", "invoices")
        self.mtls_cert_path = mtls_cert_path or getattr(settings, "dgi_mtls_cert_path", "")
        self.mtls_key_path = mtls_key_path or getattr(settings, "dgi_mtls_key_path", "")
        self._token: Optional[TokenInfo] = None

    def _build_mtls_client(self) -> httpx.AsyncClient:
        """Construit un client HTTP avec mTLS si configuré."""
        kwargs = {"timeout": 30.0}
        if self.mtls_cert_path and self.mtls_key_path:
            cert_path = Path(self.mtls_cert_path)
            key_path = Path(self.mtls_key_path)
            if cert_path.exists() and key_path.exists():
                kwargs["cert"] = (str(cert_path), str(key_path))
                logger.info("mtls_cert_loaded", extra={"cert": str(cert_path)})
        return httpx.AsyncClient(**kwargs)

    async def get_token(self) -> TokenInfo:
        """
        Obtient un token OAuth 2.0 via Client Credentials Grant.
        Cache le token et le refresh automatiquement avant expiration.
        """
        if self._token and not self._token.is_expired:
            return self._token

        if not self.token_url:
            raise ValueError("DGI token URL non configuré (COMPLY_MA_DGI_TOKEN_URL)")

        logger.info("dgi_token_request", extra={"token_url": self.token_url})

        async with self._build_mtls_client() as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": self.scope,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()

        self._token = TokenInfo(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_at=time.time() + data.get("expires_in", 3600),
            scope=data.get("scope"),
        )

        logger.info("dgi_token_received", extra={"expires_in": data.get("expires_in", 3600)})
        return self._token

    async def get_auth_headers(self) -> dict:
        """Retourne les headers d'authentification pour les appels API."""
        token = await self.get_token()
        return {
            "Authorization": token.authorization_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def invalidate_token(self):
        """Invalide le token cache (utile après erreur 401)."""
        self._token = None


class DGIAuthConfig:
    """Configuration centralisée de l'authentification DGI."""

    def __init__(self):
        self.authenticator = DGIAuthenticator()

    @property
    def is_configured(self) -> bool:
        return bool(self.authenticator.token_url and self.authenticator.client_id)
