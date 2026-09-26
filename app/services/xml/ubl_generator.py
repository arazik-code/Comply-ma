"""
Générateur de factures au format UBL 2.1 (Universal Business Language).

Conforme au standard OASIS UBL 2.1 et aux exigences DGI Maroc :
  - ICE / IF / RC dans les identifiants fournisseur
  - Numérotation séquentielle par exercice
  - TVA détaillée par taux (TaxSubtotal)
  - Total LegalMonetaryTotal
  - Signature XML-DSig (ajoutée après par signature.py)
  - Champs UBL 2.1 complets (payment means, delivery, allowances)
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from lxml import etree

from app.models.company import Company
from app.models.client import Client
from app.models.invoice import Invoice, InvoiceLine
from app.services.xml.base import (
    UBL_NS, make_ns, text, amount, address, party, party_tax_scheme,
    party_legal_entity, tva_category_code, validate_unit_code,
)


def generate_ubl_invoice(
    invoice: Invoice,
    lines: list[InvoiceLine],
    company: Company,
    client: Client,
) -> bytes:
    """Génère le XML UBL 2.1 pour une facture validée."""
    ns = UBL_NS.copy()
    root = etree.Element(make_ns("ubl:Invoice", ns), nsmap=ns)

    # Entête
    text(root, "cbc:UBLVersionID", "2.1", ns)
    text(root, "cbc:CustomizationID", "urn:cen.eu:en16931:2017#compliant#urn:dgi.ma:invoice", ns)
    text(root, "cbc:ProfileID", "urn:cen.eu:en16931:2017", ns)
    text(root, "cbc:ID", invoice.invoice_number or "", ns)
    text(root, "cbc:IssueDate", invoice.invoice_date.strftime("%Y-%m-%d"), ns)
    text(root, "cbc:InvoiceTypeCode", "380", ns)
    text(root, "cbc:DocumentCurrencyCode", invoice.currency_code or "MAD", ns)

    # TaxPointDate (date d'exigibilité TVA)
    if invoice.invoice_date:
        text(root, "cbc:TaxPointDate", invoice.invoice_date.strftime("%Y-%m-%d"), ns)

    # Note / Observations
    if invoice.notes:
        text(root, "cbc:Note", invoice.notes[:500], ns)

    # OrderReference
    if invoice.order_reference:
        order_ref = etree.SubElement(root, make_ns("cac:OrderReference", ns))
        text(order_ref, "cbc:ID", invoice.order_reference, ns)

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

    # PaymentMeans
    pmt_means = etree.SubElement(root, make_ns("cac:PaymentMeans", ns))
    payment_code = invoice.payment_means_code or "30"  # 30 = virement bancaire par défaut
    text(pmt_means, "cbc:PaymentMeansCode", payment_code, ns)
    if invoice.payment_means_text:
        text(pmt_means, "cbc:PaymentNote", invoice.payment_means_text, ns)

    # PaymentTerms
    pmt = etree.SubElement(root, make_ns("cac:PaymentTerms", ns))
    text(pmt, "cbc:Note", f"Statut paiement : {invoice.payment_status}", ns)

    # Delivery (si renseigné)
    if invoice.delivery_date or invoice.delivery_address:
        delivery = etree.SubElement(root, make_ns("cac:Delivery", ns))
        if invoice.delivery_date:
            text(delivery, "cbc:ActualDeliveryDate", invoice.delivery_date.strftime("%Y-%m-%d"), ns)

    # BillingPeriod (si renseigné)
    if invoice.billing_period_start and invoice.billing_period_end:
        period = etree.SubElement(root, make_ns("cac:InvoicePeriod", ns))
        text(period, "cbc:StartDate", invoice.billing_period_start.strftime("%Y-%m-%d"), ns)
        text(period, "cbc:EndDate", invoice.billing_period_end.strftime("%Y-%m-%d"), ns)

    # AllowanceCharge (remises majorations document)
    if invoice.allowance_amount > 0:
        allowance = etree.SubElement(root, make_ns("cac:AllowanceCharge", ns))
        text(allowance, "cbc:ChargeIndicator", "false", ns)
        amount(allowance, "cbc:Amount", invoice.allowance_amount, invoice.currency_code or "MAD", ns)

    if invoice.charge_amount > 0:
        charge = etree.SubElement(root, make_ns("cac:AllowanceCharge", ns))
        text(charge, "cbc:ChargeIndicator", "true", ns)
        amount(charge, "cbc:Amount", invoice.charge_amount, invoice.currency_code or "MAD", ns)

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
    amount(tax_total, "cbc:TaxAmount", invoice.total_tva, invoice.currency_code or "MAD", ns)
    for rate_key in sorted(tva_by_rate.keys()):
        data = tva_by_rate[rate_key]
        sub = etree.SubElement(tax_total, make_ns("cac:TaxSubtotal", ns))
        amount(sub, "cbc:TaxableAmount", data["taxable"], invoice.currency_code or "MAD", ns)
        amount(sub, "cbc:TaxAmount", data["tax"], invoice.currency_code or "MAD", ns)
        cat = etree.SubElement(sub, make_ns("cac:TaxCategory", ns))
        text(cat, "cbc:ID", tva_category_code(data["rate"]), ns)
        text(cat, "cbc:Percent", f"{float(data['rate'] * 100):.2f}", ns)
        scheme = etree.SubElement(cat, make_ns("cac:TaxScheme", ns))
        text(scheme, "cbc:ID", "VAT", ns)

    # Totaux
    monetary = etree.SubElement(root, make_ns("cac:LegalMonetaryTotal", ns))
    amount(monetary, "cbc:LineExtensionAmount", invoice.total_ht, invoice.currency_code or "MAD", ns)
    amount(monetary, "cbc:TaxExclusiveAmount", invoice.total_ht, invoice.currency_code or "MAD", ns)
    amount(monetary, "cbc:TaxInclusiveAmount", invoice.total_ttc, invoice.currency_code or "MAD", ns)

    # AllowanceTotalAmount
    if invoice.allowance_amount > 0:
        amount(monetary, "cbc:AllowanceTotalAmount", invoice.allowance_amount, invoice.currency_code or "MAD", ns)

    # ChargeTotalAmount
    if invoice.charge_amount > 0:
        amount(monetary, "cbc:ChargeTotalAmount", invoice.charge_amount, invoice.currency_code or "MAD", ns)

    amount(monetary, "cbc:PayableAmount", invoice.total_ttc, invoice.currency_code or "MAD", ns)

    # Lignes
    for i, line in enumerate(lines):
        inv_line = etree.SubElement(root, make_ns("cac:InvoiceLine", ns))
        text(inv_line, "cbc:ID", str(i + 1), ns)

        qty_el = etree.SubElement(inv_line, make_ns("cbc:InvoicedQuantity", ns))
        qty_el.text = f"{line.quantity}"
        qty_el.set("unitCode", validate_unit_code(line.unit_code))

        amount(inv_line, "cbc:LineExtensionAmount", line.line_total_ht, invoice.currency_code or "MAD", ns)

        # Allowance/Charge sur ligne
        if line.allowance_amount > 0:
            line_allowance = etree.SubElement(inv_line, make_ns("cac:AllowanceCharge", ns))
            text(line_allowance, "cbc:ChargeIndicator", "false", ns)
            amount(line_allowance, "cbc:Amount", line.allowance_amount, invoice.currency_code or "MAD", ns)

        item = etree.SubElement(inv_line, make_ns("cac:Item", ns))
        text(item, "cbc:Name", line.description[:100], ns)
        if line.item_classification_code:
            text(item, "cbc:ClassificationCode", line.item_classification_code, ns)

        # Item / ItemClassificationCode
        item_class = etree.SubElement(item, make_ns("cac:CommodityClassification", ns))
        text(item_class, "cbc:ItemClassificationCode", line.item_classification_code or "01011", ns)

        price = etree.SubElement(inv_line, make_ns("cac:Price", ns))
        amount(price, "cbc:PriceAmount", line.unit_price, invoice.currency_code or "MAD", ns)
        price[-1].set("unitCode", validate_unit_code(line.unit_code))

    xml_bytes = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    return xml_bytes
