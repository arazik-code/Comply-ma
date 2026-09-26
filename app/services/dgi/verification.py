"""
Moteur de vérification des factures fournisseurs entrantes.

Vérifie :
  1. Signature XML-DSig du fournisseur
  2. Inscription DGI du fournisseur (ICE)
  3. Validité de la facture sur la plateforme DGI
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("app.dgi.verification")


@dataclass
class VerificationResult:
    valid: bool
    signature_valid: Optional[bool] = None
    registration_valid: Optional[bool] = None
    dgi_valid: Optional[bool] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


async def verify_supplier_signature(xml_bytes: bytes) -> tuple[bool, str]:
    """
    Vérifie la signature XML-DSig d'une facture fournisseur.

    Returns:
        (is_valid, error_message)
    """
    try:
        from app.services.xml.signature import verify_xml_signature
        is_valid = verify_xml_signature(xml_bytes)
        if is_valid:
            return True, ""
        return False, "Signature XML-DSig invalide ou absente"
    except ImportError:
        return False, "Module signxml non disponible"
    except Exception as e:
        return False, f"Erreur vérification signature: {e}"


async def verify_supplier_registration(ice: str) -> tuple[bool, str]:
    """
    Vérifie si le fournisseur (ICE) est inscrit sur la plateforme DGI.

    Returns:
        (is_registered, error_message)
    """
    try:
        from app.services.dgi.client import DGIClient
        client = DGIClient()
        if not client.is_configured:
            return True, "Client DGI non configuré — vérification ignorée"

        result = await client.verify_registration(ice)
        if result.success:
            return True, ""
        return False, result.error_message or "Fournisseur non inscrit sur DGI"
    except Exception as e:
        return False, f"Erreur vérification inscription: {e}"


async def verify_dgi_clearance(clearance_number: str) -> tuple[bool, str]:
    """
    Vérifie si une facture est enregistrée et validée sur la plateforme DGI.

    Returns:
        (is_valid, error_message)
    """
    try:
        from app.services.dgi.client import DGIClient
        client = DGIClient()
        if not client.is_configured:
            return True, "Client DGI non configuré — vérification ignorée"

        result = await client.check_status(clearance_number)
        if result.success and result.status in ("cleared", "approved", "registered"):
            return True, ""
        return False, result.error_message or f"Statut DGI: {result.status}"
    except Exception as e:
        return False, f"Erreur vérification DGI: {e}"


async def verify_supplier_invoice(
    xml_bytes: bytes,
    invoice_id: str,
    supplier_ice: Optional[str] = None,
    clearance_number: Optional[str] = None,
) -> VerificationResult:
    """
    Vérification complète d'une facture fournisseur :
    1. Signature XML-DSig
    2. Inscription DGI du fournisseur
    3. Validité sur la plateforme DGI

    Args:
        xml_bytes: Contenu XML de la facture
        invoice_id: ID interne de la facture
        supplier_ice: ICE du fournisseur (pour vérification inscription)
        clearance_number: Numéro de clearance DGI (pour vérification enregistrement)

    Returns:
        VerificationResult avec tous les résultats
    """
    result = VerificationResult(valid=True)

    # 1. Vérifier la signature
    sig_valid, sig_error = await verify_supplier_signature(xml_bytes)
    result.signature_valid = sig_valid
    if not sig_valid:
        result.errors.append(f"Signature: {sig_error}")

    # 2. Vérifier l'inscription DGI
    if supplier_ice:
        reg_valid, reg_error = await verify_supplier_registration(supplier_ice)
        result.registration_valid = reg_valid
        if not reg_valid:
            result.errors.append(f"Inscription DGI: {reg_error}")

    # 3. Vérifier la clearance DGI
    if clearance_number:
        dgi_valid, dgi_error = await verify_dgi_clearance(clearance_number)
        result.dgi_valid = dgi_valid
        if not dgi_valid:
            result.errors.append(f"Clearance DGI: {dgi_error}")

    result.valid = result.error_count == 0

    logger.info("supplier_invoice_verification", extra={
        "invoice_id": invoice_id,
        "valid": result.valid,
        "signature": result.signature_valid,
        "registration": result.registration_valid,
        "dgi": result.dgi_valid,
    })

    return result
