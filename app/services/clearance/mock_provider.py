"""
Provider simulé pour le clearance — retourne un succès après un délai.

Utilisable en développement et test pour valider le flux complet
sans dépendre de la plateforme DGI.
"""
import asyncio
import uuid

from app.services.clearance.interface import ClearanceProvider, ClearanceResult


class MockClearanceProvider(ClearanceProvider):
    """
    Simule la plateforme DGI.

    Comportement :
      - Succès dans 95% des cas
      - Rejet aléatoire dans 5% des cas (pour tester la gestion d'erreur)
      - Délai simulé de ~500ms (temps de traitement DGI estimé)
    """

    async def submit_invoice(self, xml_bytes: bytes, invoice_id: str) -> ClearanceResult:
        await asyncio.sleep(0.5)

        # 95 % de succès, 5 % de rejet — déterministe via MD5 (hash() est
        # randomisé par processus, ce qui rendait le comportement non reproductible)
        import hashlib
        digest = int(hashlib.md5(invoice_id.encode()).hexdigest(), 16)
        if digest % 20 == 0:
            return ClearanceResult(
                success=False,
                error_code="ERR_FORMAT",
                error_message="[SIMULATION] Format XML invalide — vérifier les champs obligatoires",
            )

        return ClearanceResult(
            success=True,
            clearance_number=f"CLR-{uuid.uuid4().hex[:12].upper()}",
            raw_response='{"status":"cleared","timestamp":"2026-07-01T12:00:00Z"}',
        )

    async def check_status(self, clearance_number: str) -> ClearanceResult:
        return ClearanceResult(
            success=True,
            clearance_number=clearance_number,
            raw_response='{"status":"cleared"}',
        )
