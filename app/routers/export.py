"""
Export CSV et bundle XML pour le comptable / DGI.
"""
import csv
import io
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models.invoice import Invoice, InvoiceLine
from app.models.client import Client
from app.models.company import Company
from app.models.payment import Payment
from app.services.auth import require_auth
from app.services.xml.ubl_generator import generate_ubl_invoice
from app.config import settings

router = APIRouter(dependencies=[Depends(require_auth)])


def _csv_safe(value) -> str:
    """
    Neutralise l'injection de formule CSV (Excel/LibreOffice).
    Un champ commençant par = + - @ ou tab est préfixé d'une apostrophe.
    """
    s = str(value)
    if s.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + s
    return s


@router.get("/csv")
async def export_csv(request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    invoices = session.exec(
        select(Invoice).where(Invoice.company_id == user["company_id"]).order_by(Invoice.invoice_number)
    ).all()
    clients = {c.id: c for c in session.exec(select(Client)).all()}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Numéro", "Date", "Client", "ICE", "Statut", "Paiement",
        "Total HT", "TVA", "Total TTC", "Date validation",
    ])
    for inv in invoices:
        client = clients.get(inv.client_id)
        writer.writerow([
            _csv_safe(inv.invoice_number or "(brouillon)"),
            inv.invoice_date.strftime("%Y-%m-%d"),
            _csv_safe(client.name if client else ""),
            _csv_safe(client.ice if client else ""),
            _csv_safe(inv.status),
            _csv_safe(inv.payment_status),
            f"{inv.total_ht:.2f}",
            f"{inv.total_tva:.2f}",
            f"{inv.total_ttc:.2f}",
            inv.validated_at.strftime("%Y-%m-%d %H:%M") if inv.validated_at else "",
        ])

    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=export_{datetime.now().strftime('%Y%m%d')}.csv"},
    )


@router.get("/xml-bundle")
async def export_xml_bundle(request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    company = session.get(Company, user["company_id"])
    invoices = session.exec(
        select(Invoice).where(
            Invoice.company_id == user["company_id"],
            Invoice.status.in_(["validated", "sent", "archived"]),
            Invoice.invoice_number.isnot(None),
        )
    ).all()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for inv in invoices:
            lines = session.exec(
                select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.sort_order)
            ).all()
            client = session.get(Client, inv.client_id)
            xml_bytes = generate_ubl_invoice(inv, lines, company, client)
            fname = f"{inv.invoice_number}.xml"
            zf.writestr(fname, xml_bytes)

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=xml_bundle_{datetime.now().strftime('%Y%m%d')}.zip"},
    )
