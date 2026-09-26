from typing import Optional
from pydantic import BaseModel


class ClearanceResult(BaseModel):
    success: bool
    clearance_number: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[str] = None


class ClearanceProvider:
    """
    Interface abstraite pour la soumission des factures à la plateforme DGI.

    À implémenter concrètement dans :
      - MockClearanceProvider (tests / dev)
      - DGIClearanceProvider   (production, quand l'API DGI sera publiée)

    La DGI a confié le développement de la plateforme à xHub.
    Les spécifications de l'API REST ne sont pas encore publiées.
    Surveiller : https://fatourati.gov.ma
    """

    async def submit_invoice(self, xml_bytes: bytes, invoice_id: str) -> ClearanceResult:
        """
        Soumet une facture XML à la plateforme DGI pour clearance.

        Args:
            xml_bytes: Facture au format UBL 2.1 ou CII en bytes
            invoice_id: Identifiant interne de la facture (traçabilité)

        Returns:
            ClearanceResult avec le numéro de clearance si succès
        """
        raise NotImplementedError

    async def check_status(self, clearance_number: str) -> ClearanceResult:
        """Vérifie le statut d'une clearance déjà soumise."""
        raise NotImplementedError
