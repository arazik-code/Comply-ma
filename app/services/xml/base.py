"""
Fonctions utilitaires partagées pour la génération XML UBL 2.1 et CII.
Extraites de ubl_generator.py et ubl_credit_note_generator.py pour éliminer la duplication.
"""
from decimal import Decimal
from typing import Optional

from lxml import etree


# --- Namespaces UBL 2.1 ---
UBL_NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}

# --- Codes TVA Maroc ---
TVA_CATEGORY_CODES = {
    Decimal("0.20"): "S",
    Decimal("0.14"): "AA",
    Decimal("0.10"): "Z",
    Decimal("0.07"): "E",
    Decimal("0.00"): "E",
}

# --- Codes unités UN/ECE communs ---
VALID_UNIT_CODES = {"C62", "KGM", "LTR", "MTR", "M2", "M3", "HUR", "DAY", "MON", "YRD", "INH", "FTK", "LTR", "MTK"}


def make_ns(tag: str, ns: dict) -> str:
    """Retourne un tag Clark notation pour lxml."""
    prefix, local = tag.split(":")
    return f"{{{ns[prefix]}}}{local}"


def text(parent, tag: str, value: str, ns: dict) -> etree._Element:
    """Ajoute un élément texte sous parent."""
    el = etree.SubElement(parent, make_ns(tag, ns))
    el.text = str(value)
    return el


def amount(parent, tag: str, value: Decimal, currency: str = "MAD", ns: dict = None) -> etree._Element:
    """Ajoute un élément montant avec attribut currencyID."""
    ns = ns or UBL_NS
    el = etree.SubElement(parent, make_ns(tag, ns))
    el.text = f"{value:.2f}"
    el.set("currencyID", currency)
    return el


def address(parent, company_or_client, tag: str = "cac:Address", ns: dict = None) -> etree._Element:
    """Construit cac:Address."""
    ns = ns or UBL_NS
    addr = etree.SubElement(parent, make_ns(tag, ns))
    street = ""
    if company_or_client.address:
        street = company_or_client.address.split(",")[0]
    text(addr, "cbc:StreetName", street, ns)
    text(addr, "cbc:CityName", getattr(company_or_client, "city", "") or "", ns)
    text(addr, "cbc:CitySubdivisionName", getattr(company_or_client, "city", "") or "", ns)
    country = etree.SubElement(addr, make_ns("cac:Country", ns))
    text(country, "cbc:IdentificationCode", "MA", ns)
    return addr


def party_tax_scheme(parent, obj, tag: str = "cac:PartyTaxScheme", ns: dict = None) -> etree._Element:
    """Construit cac:PartyTaxScheme avec ICE."""
    ns = ns or UBL_NS
    pts = etree.SubElement(parent, make_ns(tag, ns))
    text(pts, "cbc:CompanyID", getattr(obj, "ice", "") or "", ns)
    text(pts, "cbc:TaxLevelCode", "VAT", ns)
    tax_scheme = etree.SubElement(pts, make_ns("cac:TaxScheme", ns))
    text(tax_scheme, "cbc:ID", "VAT", ns)
    return pts


def party_legal_entity(parent, name: str, address_el, tag: str = "cac:PartyLegalEntity", ns: dict = None) -> etree._Element:
    """Construit cac:PartyLegalEntity."""
    ns = ns or UBL_NS
    ple = etree.SubElement(parent, make_ns(tag, ns))
    text(ple, "cbc:RegistrationName", (name or "")[:100], ns)
    ple.append(address_el)
    return ple


def party(container, obj, name: str, extra_ids: Optional[list[tuple[str, str]]] = None, ns: dict = None) -> etree._Element:
    """Construit cac:Party complet avec identification, tax scheme, legal entity, contact."""
    ns = ns or UBL_NS
    party_el = etree.SubElement(container, make_ns("cac:Party", ns))

    # ICE identification
    party_id = text(party_el, "cbc:PartyIdentification", "", ns)
    id_el = party_id.getparent().find(make_ns("cbc:ID", ns))
    if id_el is not None:
        id_el.set("schemeID", "ICE")
        id_el.text = getattr(obj, "ice", "") or ""

    # Identifiants supplémentaires (RC, IF)
    if extra_ids:
        for scheme, value in extra_ids:
            eid = etree.SubElement(party_el, make_ns("cac:PartyIdentification", ns))
            eid_el = etree.SubElement(eid, make_ns("cbc:ID", ns))
            eid_el.set("schemeID", scheme)
            eid_el.text = value

    # Nom
    party_name = etree.SubElement(party_el, make_ns("cac:PartyName", ns))
    text(party_name, "cbc:Name", (name or "")[:100], ns)

    # Adresse
    addr = address(party_el, obj, ns=ns)

    # Tax scheme
    party_tax_scheme(party_el, obj, ns=ns)

    # Legal entity
    party_legal_entity(party_el, name, addr, ns=ns)

    # Contact
    contact = etree.SubElement(party_el, make_ns("cac:Contact", ns))
    text(contact, "cbc:Name", (name or "")[:100], ns)
    if getattr(obj, "email", None):
        text(contact, "cbc:ElectronicMail", obj.email, ns)
    if getattr(obj, "phone", None):
        text(contact, "cbc:Telephone", obj.phone, ns)

    return party_el


def tva_category_code(rate: Decimal) -> str:
    """Retourne le code catégorie TVA selon le taux."""
    return TVA_CATEGORY_CODES.get(rate, "S")


def validate_unit_code(code: str) -> str:
    """Valide et retourne un code unité UN/ECE, C62 par défaut."""
    if code and code.upper() in VALID_UNIT_CODES:
        return code.upper()
    return "C62"
