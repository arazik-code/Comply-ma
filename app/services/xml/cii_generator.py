"""
Générateur de factures au format CII (Cross-Industry Invoice) — UN/CEFACT.

Format alternatif à UBL 2.1. Utilisable via le flag de configuration :
  COMPLY_MA_XML_FORMAT=cii

Structure basée sur le standard UN/CEFACT CII (D16B).
"""
from datetime import datetime
from decimal import Decimal

from lxml import etree

from app.models.company import Company
from app.models.client import Client
from app.models.invoice import Invoice, InvoiceLine

NS_CII = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
NS_RSM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
NS_QDT = "urn:un:unece:uncefact:data:standard:QualifiedDataType:100"
NS_UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"

NSMAP = {
    None: NS_CII,
    "rsm": NS_RSM,
    "qdt": NS_QDT,
    "udt": NS_UDT,
}


def _qname(uri, local):
    return f"{{{uri}}}{local}"


def _text(parent, uri, tag, value):
    el = etree.SubElement(parent, _qname(uri, tag))
    el.text = str(value)
    return el


def generate_cii_invoice(
    invoice: Invoice,
    lines: list[InvoiceLine],
    company: Company,
    client: Client,
) -> bytes:
    """
    Génère le XML CII pour une facture validée.

    Note : la spécification CII Maroc n'étant pas encore publiée par la DGI,
    cette implémentation produit un CII Basic (EN16931) qui sera adapté
    quand le sous-ensemble marocain sera disponible.
    """
    root = etree.Element(_qname(NS_CII, "CrossIndustryInvoice"), nsmap=NSMAP)

    # En-tête d'échange
    header = etree.SubElement(root, _qname(NS_RSM, "ExchangedDocument"))
    _text(header, NS_UDT, "ID", invoice.invoice_number or "")
    _text(header, NS_UDT, "TypeCode", "380")
    _text(header, NS_UDT, "IssueDateTime", invoice.invoice_date.strftime("%Y%m%d"))

    # Transaction commerciale
    trade = etree.SubElement(root, _qname(NS_RSM, "SupplyChainTradeTransaction"))

    # Fournisseur
    settlement = etree.SubElement(trade, _qname(NS_RSM, "ApplicableHeaderTradeSettlement"))

    seller = etree.SubElement(settlement, _qname(NS_RSM, "SellerTradeParty"))
    _text(seller, NS_UDT, "Name", company.company_name[:100])
    sid = _text(seller, NS_UDT, "ID", company.ice or "")
    sid.set("schemeID", "ICE")

    seller_addr = etree.SubElement(seller, _qname(NS_RSM, "PostalTradeAddress"))
    if company.address:
        _text(seller_addr, NS_UDT, "LineOne", company.address.split(",")[0])
    _text(seller_addr, NS_UDT, "CityName", company.city or "")
    _text(seller_addr, NS_UDT, "CountryID", "MA")

    # Client
    buyer = etree.SubElement(settlement, _qname(NS_RSM, "BuyerTradeParty"))
    _text(buyer, NS_UDT, "Name", client.name[:100])
    if client.ice:
        bid = _text(buyer, NS_UDT, "ID", client.ice)
        bid.set("schemeID", "ICE")

    buyer_addr = etree.SubElement(buyer, _qname(NS_RSM, "PostalTradeAddress"))
    if client.address:
        _text(buyer_addr, NS_UDT, "LineOne", client.address.split(",")[0])
    _text(buyer_addr, NS_UDT, "CityName", client.city or "")
    _text(buyer_addr, NS_UDT, "CountryID", "MA")

    # TVA
    tax_section = etree.SubElement(settlement, _qname(NS_RSM, "ApplicableHeaderTradeSettlement"))
    _text(tax_section, NS_UDT, "TaxCurrencyCode", invoice.currency_code or "MAD")

    tva_by_rate: dict[str, dict] = {}
    for line in lines:
        rk = f"{line.tva_rate:.4f}"
        if rk not in tva_by_rate:
            tva_by_rate[rk] = {"rate": line.tva_rate, "taxable": Decimal("0.00"), "tax": Decimal("0.00")}
        tva_by_rate[rk]["taxable"] += line.line_total_ht
        tva_by_rate[rk]["tax"] += line.line_total_tva

    for rk in sorted(tva_by_rate.keys()):
        d = tva_by_rate[rk]
        sub = etree.SubElement(tax_section, _qname(NS_RSM, "TradeTax"))
        _text(sub, NS_UDT, "CalculatedAmount", f"{d['tax']:.2f}")
        _text(sub, NS_UDT, "TypeCode", "VAT")
        _text(sub, NS_UDT, "RateApplicablePercent", f"{float(d['rate'] * 100):.2f}")

    # Totaux
    monetary = etree.SubElement(settlement, _qname(NS_RSM, "SpecifiedTradeSettlementHeaderMonetarySummation"))
    _text(monetary, NS_UDT, "LineTotalAmount", f"{invoice.total_ht:.2f}")
    _text(monetary, NS_UDT, "TaxTotalAmount", f"{invoice.total_tva:.2f}")
    _text(monetary, NS_UDT, "GrandTotalAmount", f"{invoice.total_ttc:.2f}")
    _text(monetary, NS_UDT, "DuePayableAmount", f"{invoice.total_ttc:.2f}")

    # Lignes
    for i, line in enumerate(lines):
        trade_line = etree.SubElement(trade, _qname(NS_RSM, "SupplyChainTradeLineItem"))
        doc_line = etree.SubElement(trade_line, _qname(NS_RSM, "DocumentLineDocument"))
        _text(doc_line, NS_UDT, "LineID", str(i + 1))

        product = etree.SubElement(trade_line, _qname(NS_RSM, "SpecifiedTradeProduct"))
        _text(product, NS_UDT, "Name", line.description[:100])

        agmt = etree.SubElement(trade_line, _qname(NS_RSM, "SpecifiedLineTradeAgreement"))
        net_price = etree.SubElement(agmt, _qname(NS_RSM, "NetPriceProductTradePrice"))
        _text(net_price, NS_UDT, "ChargeAmount", f"{line.unit_price:.2f}")

        delivery = etree.SubElement(trade_line, _qname(NS_RSM, "SpecifiedLineTradeDelivery"))
        qty = _text(delivery, NS_UDT, "BilledQuantity", f"{line.quantity}")
        qty.set("unitCode", "C62")

        settle = etree.SubElement(trade_line, _qname(NS_RSM, "SpecifiedLineTradeSettlement"))
        tax = etree.SubElement(settle, _qname(NS_RSM, "ApplicableTradeTax"))
        _text(tax, NS_UDT, "CalculatedAmount", f"{line.line_total_tva:.2f}")
        _text(tax, NS_UDT, "TypeCode", "VAT")
        _text(settle, NS_UDT, "NetLineTotalAmount", f"{line.line_total_ht:.2f}")

    xml_bytes = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    return xml_bytes
