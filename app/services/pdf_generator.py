"""
Générateur de PDF — copie visuelle de la facture.

La loi marocaine exige que le XML structuré soit la source de vérité.
Le PDF doit porter le watermark :
  "COPIE VISUELLE — L'ORIGINAL EST LE FICHIER XML"
"""
import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from app.models.company import Company
from app.models.client import Client
from app.models.invoice import Invoice, InvoiceLine
from app.models.credit_note import CreditNote, CreditNoteLine


def _html_to_pdf(html: str) -> bytes | None:
    """
    Convertit du HTML en PDF avec repli en cascade :
      1. WeasyPrint (qualité maximale — natif Linux/Docker)
      2. xhtml2pdf (pur Python — fonctionne partout, dont Windows sans GTK)
    Retourne None si aucun moteur n'est disponible.
    """
    try:
        from weasyprint import HTML
        return HTML(string=html, encoding="utf-8").write_pdf()
    except Exception:
        pass
    try:
        from xhtml2pdf import pisa
        buf = io.BytesIO()
        # NB : pas de paramètre encoding avec une entrée unicode (html5lib l'interdit)
        if pisa.CreatePDF(io.StringIO(html), dest=buf).err:
            return None
        return buf.getvalue()
    except Exception:
        return None


def generate_invoice_pdf(
    invoice: Invoice,
    lines: list[InvoiceLine],
    company: Company,
    client: Client,
) -> bytes:
    """
    Génère le HTML de la facture puis le convertit en PDF.

    Retourne les bytes du PDF (repli : HTML si aucun moteur PDF).
    """
    html = _render_invoice_html(invoice, lines, company, client)
    pdf_bytes = _html_to_pdf(html)
    return pdf_bytes if pdf_bytes else html.encode("utf-8")


def _render_invoice_html(
    invoice: Invoice,
    lines: list[InvoiceLine],
    company: Company,
    client: Client,
) -> str:
    """Produit le HTML de la facture avec watermark."""
    tva_by_rate: dict[str, dict] = {}
    for line in lines:
        rk = f"{line.tva_rate:.4f}"
        if rk not in tva_by_rate:
            tva_by_rate[rk] = {
                "rate": line.tva_rate,
                "taxable": Decimal("0.00"),
                "tax": Decimal("0.00"),
            }
        tva_by_rate[rk]["taxable"] += line.line_total_ht
        tva_by_rate[rk]["tax"] += line.line_total_tva

    lines_html = ""
    for i, line in enumerate(lines):
        lines_html += f"""
        <tr>
            <td>{i + 1}</td>
            <td>{line.description[:50]}</td>
            <td class="right">{line.quantity}</td>
            <td class="right">{line.unit_price:.2f}</td>
            <td class="right">{float(line.tva_rate * 100):.0f}%</td>
            <td class="right">{line.line_total_ht:.2f}</td>
            <td class="right">{line.line_total_ttc:.2f}</td>
        </tr>"""

    tva_summary = ""
    for rk in sorted(tva_by_rate.keys()):
        d = tva_by_rate[rk]
        tva_summary += f"""
        <tr>
            <td>TVA {float(d['rate'] * 100):.0f}%</td>
            <td class="right">{d['taxable']:.2f}</td>
            <td class="right">{d['tax']:.2f}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    @page {{ size: A4; margin: 2cm; }}
    body {{ font-family: 'DejaVu Sans', sans-serif; font-size: 10pt; color: #1a1a1a; }}
    .watermark {{
        position: fixed; top: 50%; left: 0; width: 100%; text-align: center;
        font-size: 18pt; color: rgba(200,0,0,0.15); font-weight: bold;
        transform: rotate(-30deg); z-index: -1;
    }}
    h1 {{ font-size: 16pt; color: #1a56db; margin-bottom: 4px; }}
    .header {{ display: flex; justify-content: space-between; margin-bottom: 20px; }}
    .header-left {{ width: 50%; }}
    .header-right {{ width: 45%; text-align: right; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
    th, td {{ border: 1px solid #ccc; padding: 4px 6px; }}
    th {{ background: #f0f4ff; text-align: left; }}
    .right {{ text-align: right; }}
    .totals {{ width: auto; margin-left: auto; }}
    .totals td {{ border: none; padding: 2px 6px; }}
    .totals td:last-child {{ text-align: right; }}
    .footer {{ margin-top: 24px; font-size: 8pt; color: #666; text-align: center; }}
    .status-badge {{
        display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 8pt;
        background: #d1fae5; color: #065f46;
    }}
</style>
</head>
<body>
<div class="watermark">COPIE VISUELLE — L'ORIGINAL EST LE FICHIER XML</div>

<div class="header">
    <div class="header-left">
        <h1>{company.company_name}</h1>
        <p>{company.address}<br>{company.city}<br>
        RC: {company.rc} | IF: {company.if_number}<br>
        ICE: {company.ice}</p>
    </div>
    <div class="header-right">
        <h1>FACTURE</h1>
        <p><strong>N° :</strong> {invoice.invoice_number or '(brouillon)'}<br>
        <strong>Date :</strong> {invoice.invoice_date.strftime('%d/%m/%Y')}<br>
        <span class="status-badge">{invoice.status.upper()}</span>
        {f'<br><strong>Paiement :</strong> {invoice.payment_status}' if invoice.payment_status else ''}</p>
    </div>
</div>

<div style="margin-bottom: 16px;">
    <strong>Facturé à :</strong>
    <p>{client.name}<br>{client.address or ''}<br>{client.city or ''}
    {f'<br>ICE: {client.ice}' if client.ice else ''}</p>
</div>

<table>
<thead>
<tr><th>#</th><th>Désignation</th><th>Qté</th><th>Prix unit.</th><th>TVA</th><th>Montant HT</th><th>Montant TTC</th></tr>
</thead>
<tbody>
{lines_html}
</tbody>
</table>

<table class="totals">
    <tr><td><strong>Total HT</strong></td><td><strong>{invoice.total_ht:.2f} MAD</strong></td></tr>
    {tva_summary}
    <tr><td><strong>Total TVA</strong></td><td><strong>{invoice.total_tva:.2f} MAD</strong></td></tr>
    <tr><td><strong>Total TTC</strong></td><td><strong>{invoice.total_ttc:.2f} MAD</strong></td></tr>
</table>

<div class="footer">
    <p>Document généré par COMPLY-MA — Facturation électronique conforme DGI Maroc</p>
    <p>La version légale de cette facture est le fichier XML structuré (UBL 2.1 ou CII).</p>
    <p>Ce PDF est une copie visuelle non probante.</p>
</div>
</body>
</html>"""


def generate_credit_note_pdf(
    note: CreditNote,
    lines: list[CreditNoteLine],
    company: Company,
    client: Client,
    invoice: Invoice | None = None,
) -> bytes:
    html = _render_credit_note_html(note, lines, company, client, invoice)
    pdf_bytes = _html_to_pdf(html)
    return pdf_bytes if pdf_bytes else html.encode("utf-8")


def _render_credit_note_html(
    note: CreditNote,
    lines: list[CreditNoteLine],
    company: Company,
    client: Client,
    invoice: Invoice | None = None,
) -> str:
    tva_by_rate: dict[str, dict] = {}
    for line in lines:
        rk = f"{line.tva_rate:.4f}"
        if rk not in tva_by_rate:
            tva_by_rate[rk] = {"rate": line.tva_rate, "taxable": Decimal("0.00"), "tax": Decimal("0.00")}
        tva_by_rate[rk]["taxable"] += line.line_total_ht
        tva_by_rate[rk]["tax"] += line.line_total_tva

    lines_html = ""
    for i, line in enumerate(lines):
        lines_html += f"""
        <tr>
            <td>{i + 1}</td>
            <td>{line.description[:50]}</td>
            <td class="right">{line.quantity}</td>
            <td class="right">{line.unit_price:.2f}</td>
            <td class="right">{float(line.tva_rate * 100):.0f}%</td>
            <td class="right">{line.line_total_ht:.2f}</td>
            <td class="right">{line.line_total_ttc:.2f}</td>
        </tr>"""

    tva_summary = ""
    for rk in sorted(tva_by_rate.keys()):
        d = tva_by_rate[rk]
        tva_summary += f"""
        <tr><td>TVA {float(d['rate'] * 100):.0f}%</td><td class="right">{d['taxable']:.2f}</td><td class="right">{d['tax']:.2f}</td></tr>"""

    inv_info = ""
    if invoice:
        inv_info = f"<br><strong>Facture originale :</strong> {invoice.invoice_number or '-'}"

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
    @page {{ size: A4; margin: 2cm; }}
    body {{ font-family: 'DejaVu Sans', sans-serif; font-size: 10pt; color: #1a1a1a; }}
    .watermark {{
        position: fixed; top: 50%; left: 0; width: 100%; text-align: center;
        font-size: 18pt; color: rgba(200,0,0,0.15); font-weight: bold;
        transform: rotate(-30deg); z-index: -1;
    }}
    h1 {{ font-size: 16pt; color: #b91c1c; margin-bottom: 4px; }}
    .header {{ display: flex; justify-content: space-between; margin-bottom: 20px; }}
    .header-left {{ width: 50%; }}
    .header-right {{ width: 45%; text-align: right; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
    th, td {{ border: 1px solid #ccc; padding: 4px 6px; }}
    th {{ background: #fef2f2; text-align: left; }}
    .right {{ text-align: right; }}
    .totals {{ width: auto; margin-left: auto; }}
    .totals td {{ border: none; padding: 2px 6px; }}
    .totals td:last-child {{ text-align: right; }}
    .footer {{ margin-top: 24px; font-size: 8pt; color: #666; text-align: center; }}
    .status-badge {{
        display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 8pt;
        background: #fef2f2; color: #b91c1c;
    }}
</style>
</head>
<body>
<div class="watermark">COPIE VISUELLE — L'ORIGINAL EST LE FICHIER XML</div>

<div class="header">
    <div class="header-left">
        <h1>{company.company_name}</h1>
        <p>{company.address}<br>{company.city}<br>
        RC: {company.rc} | IF: {company.if_number}<br>
        ICE: {company.ice}</p>
    </div>
    <div class="header-right">
        <h1>AVOIR</h1>
        <p><strong>N° :</strong> {note.credit_note_number or '(brouillon)'}<br>
        <strong>Date :</strong> {note.credit_note_date.strftime('%d/%m/%Y')}<br>
        <span class="status-badge">{note.status.upper()}</span>{inv_info}</p>
    </div>
</div>

<div style="margin-bottom: 16px;">
    <strong>Client :</strong>
    <p>{client.name}<br>{client.address or ''}<br>{client.city or ''}
    {f'<br>ICE: {client.ice}' if client.ice else ''}</p>
</div>

<p><strong>Motif :</strong> {note.reason}</p>

<table>
<thead>
<tr><th>#</th><th>Désignation</th><th>Qté</th><th>Prix unit.</th><th>TVA</th><th>Montant HT</th><th>Montant TTC</th></tr>
</thead>
<tbody>
{lines_html}
</tbody>
</table>

<table class="totals">
    <tr><td><strong>Total HT</strong></td><td><strong>{note.total_ht:.2f} MAD</strong></td></tr>
    {tva_summary}
    <tr><td><strong>Total TVA</strong></td><td><strong>{note.total_tva:.2f} MAD</strong></td></tr>
    <tr><td><strong>Total TTC</strong></td><td><strong>{note.total_ttc:.2f} MAD</strong></td></tr>
</table>

<div class="footer">
    <p>Document généré par COMPLY-MA — Facturation électronique conforme DGI Maroc</p>
    <p>La version légale de cet avoir est le fichier XML structuré (UBL 2.1).</p>
    <p>Ce PDF est une copie visuelle non probante.</p>
</div>
</body>
</html>"""
