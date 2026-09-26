"""
Stub pour le provider DGI réel — maintenant avec implémentation complète.

Utilise le client DGI pour soumettre les factures via REST API.
Retombe sur MockClearanceProvider si DGI non configuré.
"""
import logging

from app.config import settings
from app.services.clearance.interface import ClearanceProvider, ClearanceResult

logger = logging.getLogger("app.clearance.dgi_provider")


class DGIClearanceProvider(ClearanceProvider):
    """
    Provider de clearance pour la plateforme DGI réelle.

    Utilise le DGIClient pour communiquer avec la plateforme.
    Configure via :
      COMPLY_MA_DGI_API_BASE_URL
      COMPLY_MA_DGI_API_KEY
    """

    def __init__(self, base_url: str = "", api_key: str = ""):
        self.base_url = base_url or settings.dgi_api_base_url
        self.api_key = api_key or settings.dgi_api_key

    async def submit_invoice(self, xml_bytes: bytes, invoice_id: str) -> ClearanceResult:
        try:
            from app.services.dgi.client import DGIClient
            client = DGIClient(base_url=self.base_url, api_key=self.api_key)

            if not client.is_configured:
                logger.warning("dgi_not_configured_falling_back_to_mock")
                from app.services.clearance.mock_provider import MockClearanceProvider
                mock = MockClearanceProvider()
                return await mock.submit_invoice(xml_bytes, invoice_id)

            result = await client.submit_invoice(xml_bytes, invoice_id)

            return ClearanceResult(
                success=result.success,
                clearance_number=result.clearance_number,
                error_code=result.error_code,
                error_message=result.error_message,
                raw_response=result.raw_response,
            )

        except NotImplementedError:
            from app.services.clearance.mock_provider import MockClearanceProvider
            mock = MockClearanceProvider()
            return await mock.submit_invoice(xml_bytes, invoice_id)

        except Exception as e:
            logger.error("dgi_provider_error", extra={"invoice_id": invoice_id, "error": str(e)})
            return ClearanceResult(
                success=False,
                error_code="ERR_PROVIDER",
                error_message=f"Erreur provider DGI: {e}",
            )

    async def check_status(self, clearance_number: str) -> ClearanceResult:
        try:
            from app.services.dgi.client import DGIClient
            client = DGIClient(base_url=self.base_url, api_key=self.api_key)

            if not client.is_configured:
                return ClearanceResult(
                    success=True,
                    clearance_number=clearance_number,
                    raw_response='{"status":"cleared"}',
                )

            result = await client.check_status(clearance_number)
            return ClearanceResult(
                success=result.success,
                clearance_number=result.clearance_number,
                error_message=result.error_message,
                raw_response=result.raw_response,
            )

        except Exception as e:
            logger.error("dgi_status_error", extra={"clearance_number": clearance_number, "error": str(e)})
            return ClearanceResult(success=False, error_message=str(e))
