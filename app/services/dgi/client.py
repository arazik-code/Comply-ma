"""
Client API DGI Maroc — soumission de factures et vérification de statut.

Communique avec la plateforme DGI/xHub via REST API.
Gère la soumission, le polling de statut, et la vérification d'inscription.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from app.config import settings
from app.services.dgi.auth import DGIAuthenticator

logger = logging.getLogger("app.dgi.client")


@dataclass
class DGISubmissionResult:
    success: bool
    clearance_number: Optional[str] = None
    status: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[str] = None


class DGIClient:
    """
    Client REST pour la plateforme DGI Maroc.

    Endpoints (présumés, à confirmer avec la publication DGI) :
      POST /api/v1/invoices/submit    — Soumettre une facture signée
      GET  /api/v1/invoices/{id}/status — Vérifier le statut
      GET  /api/v1/invoices/{id}/verify — Vérifier l'inscription

    Configuration :
      COMPLY_MA_DGI_API_BASE_URL — URL de base de l'API
      COMPLY_MA_DGI_API_KEY      — Clé API
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or settings.dgi_api_base_url).rstrip("/")
        self.api_key = api_key or settings.dgi_api_key
        self.auth = DGIAuthenticator()

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _get_client(self, cert_path: str = "", key_path: str = "") -> httpx.AsyncClient:
        """Construit un client HTTP avec mTLS optionnel."""
        kwargs = {"timeout": 60.0, "base_url": self.base_url}
        if cert_path and key_path:
            kwargs["cert"] = (cert_path, key_path)
        return httpx.AsyncClient(**kwargs)

    async def submit_invoice(
        self,
        xml_bytes: bytes,
        invoice_id: str,
        clearance_number: Optional[str] = None,
    ) -> DGISubmissionResult:
        """
        Soumet une facture XML signée à la plateforme DGI.

        Args:
            xml_bytes: Facture UBL 2.1 signée en bytes
            invoice_id: ID interne de la facture
            clearance_number: Numéro de clearance existant (pour resoumission)

        Returns:
            DGISubmissionResult avec le statut et numéro DGI
        """
        if not self.is_configured:
            raise ValueError("Client DGI non configuré (COMPLY_MA_DGI_API_BASE_URL + COMPLY_MA_DGI_API_KEY)")

        try:
            headers = await self.auth.get_auth_headers()
        except Exception as e:
            logger.error("dgi_auth_failed", extra={"error": str(e)})
            return DGISubmissionResult(
                success=False,
                error_code="ERR_AUTH",
                error_message=f"Échec d'authentification DGI: {e}",
            )

        payload = {
            "invoice_id": invoice_id,
            "xml_content": xml_bytes.decode("utf-8"),
            "format": "UBL2.1",
        }
        if clearance_number:
            payload["clearance_number"] = clearance_number

        endpoint = "/api/v1/invoices/submit"

        try:
            async with self._get_client() as client:
                response = await client.post(
                    endpoint,
                    json=payload,
                    headers={**headers, "X-Invoice-ID": invoice_id},
                )
                response.raise_for_status()
                data = response.json()

            result = DGISubmissionResult(
                success=True,
                clearance_number=data.get("clearance_number"),
                status=data.get("status", "submitted"),
                raw_response=str(data),
            )
            logger.info("dgi_submission_success", extra={
                "invoice_id": invoice_id,
                "clearance_number": result.clearance_number,
            })
            return result

        except httpx.HTTPStatusError as e:
            error_data = {}
            try:
                error_data = e.response.json()
            except Exception:
                pass

            result = DGISubmissionResult(
                success=False,
                error_code=error_data.get("error_code", f"HTTP_{e.response.status_code}"),
                error_message=error_data.get("error_message", str(e)),
                raw_response=str(error_data),
            )
            logger.warning("dgi_submission_http_error", extra={
                "invoice_id": invoice_id,
                "status": e.response.status_code,
                "error": result.error_message,
            })
            return result

        except Exception as e:
            logger.error("dgi_submission_error", extra={"invoice_id": invoice_id, "error": str(e)})
            return DGISubmissionResult(
                success=False,
                error_code="ERR_NETWORK",
                error_message=f"Erreur réseau: {e}",
            )

    async def check_status(self, clearance_number: str) -> DGISubmissionResult:
        """
        Vérifie le statut d'une facture soumise à la DGI.

        Args:
            clearance_number: Numéro de clearance DGI

        Returns:
            DGISubmissionResult avec le statut actuel
        """
        if not self.is_configured:
            raise ValueError("Client DGI non configuré")

        try:
            headers = await self.auth.get_auth_headers()
            endpoint = f"/api/v1/invoices/{clearance_number}/status"

            async with self._get_client() as client:
                response = await client.get(endpoint, headers=headers)
                response.raise_for_status()
                data = response.json()

            return DGISubmissionResult(
                success=True,
                clearance_number=clearance_number,
                status=data.get("status"),
                raw_response=str(data),
            )

        except Exception as e:
            logger.error("dgi_status_check_error", extra={
                "clearance_number": clearance_number,
                "error": str(e),
            })
            return DGISubmissionResult(
                success=False,
                error_code="ERR_STATUS_CHECK",
                error_message=str(e),
            )

    async def verify_registration(self, ice: str) -> DGISubmissionResult:
        """
        Vérifie si une entreprise est inscrite sur la plateforme DGI.

        Args:
            ice: ICE de l'entreprise à vérifier

        Returns:
            DGISubmissionResult avec le statut d'inscription
        """
        if not self.is_configured:
            raise ValueError("Client DGI non configuré")

        try:
            headers = await self.auth.get_auth_headers()
            endpoint = f"/api/v1/companies/{ice}/verify"

            async with self._get_client() as client:
                response = await client.get(endpoint, headers=headers)
                response.raise_for_status()
                data = response.json()

            return DGISubmissionResult(
                success=data.get("registered", False),
                status="registered" if data.get("registered") else "not_registered",
                raw_response=str(data),
            )

        except Exception as e:
            logger.error("dgi_registration_check_error", extra={"ice": ice, "error": str(e)})
            return DGISubmissionResult(
                success=False,
                error_code="ERR_REGISTRATION_CHECK",
                error_message=str(e),
            )
