"""
Validateur de schéma UBL 2.1 — vérifie la conformité XML avant soumission DGI.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from lxml import etree

logger = logging.getLogger("app.xml.validator")


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


# Éléments UBL 2.1 obligatoires pour une facture (EN 16931)
MANDATORY_INVOICE_ELEMENTS = [
    "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}UBLVersionID",
    "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}CustomizationID",
    "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID",
    "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}IssueDate",
    "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}InvoiceTypeCode",
    "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}DocumentCurrencyCode",
]

MANDATORY_PARTY_ELEMENTS = [
    "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}PartyIdentification",
    "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}PartyName",
]

MANDATORY_TOTAL_ELEMENTS = [
    "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}TaxExclusiveAmount",
    "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}TaxInclusiveAmount",
    "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}PayableAmount",
]


def validate_ubl_invoice(xml_bytes: bytes) -> ValidationResult:
    """
    Valide un XML UBL 2.1 Invoice contre les règles EN 16931 et DGI Maroc.

    Args:
        xml_bytes: Contenu du fichier XML UBL 2.1

    Returns:
        ValidationResult avec erreurs et avertissements
    """
    result = ValidationResult(valid=True)

    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        result.valid = False
        result.errors.append(f"XML invalide: {e}")
        return result

    ns = root.nsmap

    # Vérifier que c'est bien une facture UBL
    tag = etree.QName(root).localname
    if tag != "Invoice":
        result.warnings.append(f"Type de document inattendu: {tag} (attendu: Invoice)")

    # Éléments obligatoires
    for elem_name in MANDATORY_INVOICE_ELEMENTS:
        el = root.find(elem_name)
        if el is None:
            result.valid = False
            result.errors.append(f"Élément obligatoire manquant: {etree.QName(elem_name).localname}")
        elif not el.text or not el.text.strip():
            result.warnings.append(f"Élément vide: {etree.QName(elem_name).localname}")

    # Vérifier AccountingSupplierParty
    supplier = root.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}AccountingSupplierParty")
    if supplier is None:
        result.valid = False
        result.errors.append("AccountingSupplierParty manquant")
    else:
        for elem_name in MANDATORY_PARTY_ELEMENTS:
            el = supplier.find(f".//{elem_name}")
            if el is None:
                result.warnings.append(f"Élément supplier manquant: {etree.QName(elem_name).localname}")

    # Vérifier AccountingCustomerParty
    customer = root.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}AccountingCustomerParty")
    if customer is None:
        result.valid = False
        result.errors.append("AccountingCustomerParty manquant")

    # Vérifier TaxTotal
    tax_total = root.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}TaxTotal")
    if tax_total is None:
        result.warnings.append("TaxTotal manquant")
    else:
        tax_amount = tax_total.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}TaxAmount")
        if tax_amount is None:
            result.errors.append("TaxAmount manquant dans TaxTotal")
            result.valid = False

    # Vérifier LegalMonetaryTotal
    monetary = root.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}LegalMonetaryTotal")
    if monetary is None:
        result.valid = False
        result.errors.append("LegalMonetaryTotal manquant")
    else:
        for elem_name in MANDATORY_TOTAL_ELEMENTS:
            el = monetary.find(elem_name)
            if el is None:
                result.errors.append(f"Élément total manquant: {etree.QName(elem_name).localname}")
                result.valid = False

    # Vérifier au moins une InvoiceLine
    lines = root.findall("{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}InvoiceLine")
    if not lines:
        result.valid = False
        result.errors.append("Aucune InvoiceLine trouvée")
    else:
        for i, line in enumerate(lines):
            line_id = line.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID")
            qty = line.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}InvoicedQuantity")
            ext_amount = line.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}LineExtensionAmount")
            item = line.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}Item")
            price = line.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}Price")

            if qty is None:
                result.errors.append(f"Ligne {i+1}: InvoicedQuantity manquant")
                result.valid = False
            elif qty.get("unitCode") is None:
                result.warnings.append(f"Ligne {i+1}: unitCode manquant sur InvoicedQuantity")

            if ext_amount is None:
                result.warnings.append(f"Ligne {i+1}: LineExtensionAmount manquant")

            if item is None:
                result.errors.append(f"Ligne {i+1}: Item manquant")
                result.valid = False
            else:
                name = item.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}Name")
                if name is None or not name.text:
                    result.warnings.append(f"Ligne {i+1}: Item/Name manquant ou vide")

            if price is None:
                result.warnings.append(f"Ligne {i+1}: Price manquant")

    # Vérifier cohérence des montants
    if monetary is not None:
        try:
            tax_excl = monetary.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}TaxExclusiveAmount")
            tax_incl = monetary.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}TaxInclusiveAmount")
            if tax_excl is not None and tax_incl is not None:
                excl_val = float(tax_excl.text or "0")
                incl_val = float(tax_incl.text or "0")
                if incl_val < excl_val:
                    result.warnings.append("TaxInclusiveAmount < TaxExclusiveAmount (incohérent)")
        except (ValueError, TypeError):
            result.warnings.append("Impossible de vérifier la cohérence des montants")

    logger.info("ubl_validation", extra={"valid": result.valid, "errors": result.error_count, "warnings": result.warning_count})
    return result


def validate_ubl_credit_note(xml_bytes: bytes) -> ValidationResult:
    """Valide un XML UBL 2.1 Credit Note."""
    result = ValidationResult(valid=True)

    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        result.valid = False
        result.errors.append(f"XML invalide: {e}")
        return result

    tag = etree.QName(root).localname
    if tag != "CreditNote":
        result.warnings.append(f"Type de document inattendu: {tag} (attendu: CreditNote)")

    # Éléments obligatoires de base
    for local_name in ["UBLVersionID", "CustomizationID", "ID", "IssueDate", "CreditNoteTypeCode", "DocumentCurrencyCode"]:
        el = root.find(f"{{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}}{local_name}")
        if el is None:
            result.valid = False
            result.errors.append(f"Élément obligatoire manquant: {local_name}")

    # BillingReference
    billing_ref = root.find("{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}BillingReference")
    if billing_ref is None:
        result.warnings.append("BillingReference manquant (référence facture originale)")

    # Vérifier au moins une CreditNoteLine
    lines = root.findall("{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}CreditNoteLine")
    if not lines:
        result.valid = False
        result.errors.append("Aucune CreditNoteLine trouvée")

    return result
