"""
Générateur d'avoirs au format UBL 2.1 (Credit Note).
Conforme au standard OASIS UBL 2.1 et aux exigences DGI Maroc.
"""
from decimal import Decimal

from lxml import etree

from app.models.company import Company
from app.models.client import Client
from app.models.credit_note import CreditNote, CreditNoteLine
from app.models.invoice import Invoice
from app.services.xml.base import (
    UBL_NS, make_ns, text, amount, address, party, party_tax_scheme,
    party_legal_entity, tva_category_code, validate_unit_code,
)


def generate_ubl_credit_note(
    credit_note: CreditNote,
    lines: list[CreditNoteLine],
    company: Company,
    client: Client,
    original_invoice: Invoice,
) -> bytes:
    """Génère le XML UBL 2.1 pour un avoir validé."""
    ns = UBL_NS.copy()
    ns["ubl"] = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
    root = etree.Element(make_ns("ubl:CreditNote", ns), nsmap=ns)

    text(root, "cbc:UBLVersionID", "2.1", ns)
    text(root, "cbc:CustomizationID", "urn:cen.eu:en16931:2017#compliant#urn:dgi.ma:creditnote", ns)
    text(root, "cbc:ProfileID", "urn:cen.eu:en16931:2017", ns)
    text(root, "cbc:ID", credit_note.credit_note_number or "", ns)
    text(root, "cbc:IssueDate", credit_note.credit_note_date.strftime("%Y-%m-%d"), ns)
    text(root, "cbc:CreditNoteTypeCode", "381", ns)
    text(root, "cbc:DocumentCurrencyCode", "MAD", ns)

    if credit_note.reason:
        text(root, "cbc:Note", credit_note.reason[:500], ns)

    # BillingReference — référence facture originale
    billing_ref = etree.SubElement(root, make_ns("cac:BillingReference", ns))
    inv_doc_ref = etree.SubElement(billing_ref, make_ns("cac:InvoiceDocumentReference", ns))
    text(inv_doc_ref, "cbc:ID", original_invoice.invoice_number or "", ns)

    # Fournisseur
    supplier = etree.SubElement(root, make_ns("cac:AccountingSupplierParty", ns))
    extra_supplier = [
        ("RC", company.rc or ""),
        ("IF", company.if_number or ""),
    ]
    party(supplier, company, company.company_name, extra_ids=extra_supplier, ns=ns)

    # Client
    customer = etree.SubElement(root, make_ns("cac:AccountingCustomerParty", ns))
    extra_client = []
    if client.rc:
        extra_client.append(("RC", client.rc))
    if client.if_number:
        extra_client.append(("IF", client.if_number))
    party(customer, client, client.name, extra_ids=extra_client, ns=ns)

    # TVA par taux
    tva_by_rate: dict[str, dict] = {}
    for line in lines:
        rate_key = f"{line.tva_rate:.4f}"
        if rate_key not in tva_by_rate:
            tva_by_rate[rate_key] = {
                "rate": line.tva_rate,
                "taxable": Decimal("0.00"),
                "tax": Decimal("0.00"),
            }
        tva_by_rate[rate_key]["taxable"] += line.line_total_ht
        tva_by_rate[rate_key]["tax"] += line.line_total_tva

    tax_total = etree.SubElement(root, make_ns("cac:TaxTotal", ns))
    amount(tax_total, "cbc:TaxAmount", credit_note.total_tva, "MAD", ns)
    for rate_key in sorted(tva_by_rate.keys()):
        data = tva_by_rate[rate_key]
        sub = etree.SubElement(tax_total, make_ns("cac:TaxSubtotal", ns))
        amount(sub, "cbc:TaxableAmount", data["taxable"], "MAD", ns)
        amount(sub, "cbc:TaxAmount", data["tax"], "MAD", ns)
        cat = etree.SubElement(sub, make_ns("cac:TaxCategory", ns))
        text(cat, "cbc:ID", tva_category_code(data["rate"]), ns)
        text(cat, "cbc:Percent", f"{float(data['rate'] * 100):.2f}", ns)
        scheme = etree.SubElement(cat, make_ns("cac:TaxScheme", ns))
        text(scheme, "cbc:ID", "VAT", ns)

    # Totaux
    monetary = etree.SubElement(root, make_ns("cac:LegalMonetaryTotal", ns))
    amount(monetary, "cbc:LineExtensionAmount", credit_note.total_ht, "MAD", ns)
    amount(monetary, "cbc:TaxExclusiveAmount", credit_note.total_ht, "MAD", ns)
    amount(monetary, "cbc:TaxInclusiveAmount", credit_note.total_ttc, "MAD", ns)
    amount(monetary, "cbc:PayableAmount", credit_note.total_ttc, "MAD", ns)

    # Lignes
    for i, line in enumerate(lines):
        cn_line = etree.SubElement(root, make_ns("cac:CreditNoteLine", ns))
        text(cn_line, "cbc:ID", str(i + 1), ns)

        qty_el = etree.SubElement(cn_line, make_ns("cbc:CreditedQuantity", ns))
        qty_el.text = f"{line.quantity}"
        qty_el.set("unitCode", "C62")

        amount(cn_line, "cbc:LineExtensionAmount", line.line_total_ht, "MAD", ns)

        item = etree.SubElement(cn_line, make_ns("cac:Item", ns))
        text(item, "cbc:Name", line.description[:100], ns)

        price = etree.SubElement(cn_line, make_ns("cac:Price", ns))
        amount(price, "cbc:PriceAmount", line.unit_price, "MAD", ns)

    xml_bytes = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    return xml_bytes
