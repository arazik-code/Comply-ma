"""
Portail client — les clients peuvent consulter leurs factures et avoirs.
Sécurisé avec bcrypt pour les mots de passe.
"""
from passlib.context import CryptContext

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select

from app.database import get_session
from app.models.invoice import Invoice
from app.models.credit_note import CreditNote
from app.models.client import Client
from app.models.company import Company
from app.models.payment import Payment
from app.models.clearance import ClearanceRecord
from app.services.pdf_generator import generate_invoice_pdf
from app.services.xml.ubl_generator import generate_ubl_invoice
from app.templating import templates

router = APIRouter(prefix="/portal", tags=["portal"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, stored: str) -> bool:
    return pwd_context.verify(password, stored)


@router.get("/login", response_class=HTMLResponse)
async def portal_login(request: Request):
    t = lambda s: s
    return templates.TemplateResponse(request, "portal/login.html", {"t": t})


@router.post("/login")
async def portal_do_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    client = session.exec(select(Client).where(Client.email == email)).first()
    if not client or not client.portal_enabled or not client.portal_password_hash:
        return RedirectResponse(url="/portal/login?error=1", status_code=303)
    if not verify_password(password, client.portal_password_hash):
        return RedirectResponse(url="/portal/login?error=1", status_code=303)
    request.session["portal_client_id"] = client.id
    request.session["portal_client_name"] = client.name
    return RedirectResponse(url="/portal/invoices", status_code=303)


@router.get("/logout")
async def portal_logout(request: Request):
    request.session.pop("portal_client_id", None)
    request.session.pop("portal_client_name", None)
    return RedirectResponse(url="/portal/login", status_code=303)


@router.get("", response_class=HTMLResponse)
@router.get("/invoices", response_class=HTMLResponse)
async def portal_invoices(request: Request, session: Session = Depends(get_session)):
    if not request.session.get("portal_client_id"):
        return RedirectResponse(url="/portal/login", status_code=303)
    client = session.get(Client, request.session["portal_client_id"])
    if not client:
        return RedirectResponse(url="/portal/login", status_code=303)
    invoices = session.exec(
        select(Invoice).where(Invoice.client_id == client.id).order_by(Invoice.created_at.desc())
    ).all()
    company = session.get(Company, client.company_id)
    t = lambda s: s
    return templates.TemplateResponse(request, "portal/invoices.html", {
        "t": t, "client": client, "invoices": invoices, "company": company,
    })


@router.get("/invoices/{invoice_id}", response_class=HTMLResponse)
async def portal_invoice_detail(invoice_id: str, request: Request, session: Session = Depends(get_session)):
    if not request.session.get("portal_client_id"):
        return RedirectResponse(url="/portal/login", status_code=303)
    client = session.get(Client, request.session["portal_client_id"])
    if not client:
        return RedirectResponse(url="/portal/login", status_code=303)
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.client_id != client.id:
        return RedirectResponse(url="/portal/invoices", status_code=303)
    company = session.get(Company, client.company_id)
    payments = session.exec(
        select(Payment).where(Payment.invoice_id == invoice_id).order_by(Payment.payment_date)
    ).all()
    clearance = session.exec(
        select(ClearanceRecord).where(ClearanceRecord.invoice_id == invoice_id)
    ).first()
    from app.models.invoice import InvoiceLine
    lines = session.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.sort_order)
    ).all()
    t = lambda s: s
    return templates.TemplateResponse(request, "portal/invoice_detail.html", {
        "t": t, "client": client, "invoice": invoice, "company": company,
        "payments": payments, "clearance": clearance, "lines": lines,
    })


@router.get("/invoices/{invoice_id}/pdf")
async def portal_invoice_pdf(invoice_id: str, request: Request, session: Session = Depends(get_session)):
    if not request.session.get("portal_client_id"):
        return RedirectResponse(url="/portal/login", status_code=303)
    client = session.get(Client, request.session["portal_client_id"])
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.client_id != client.id:
        return RedirectResponse(url="/portal/invoices", status_code=303)
    company = session.get(Company, client.company_id)
    from app.models.invoice import InvoiceLine
    lines = session.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.sort_order)
    ).all()
    pdf = generate_invoice_pdf(invoice, lines, client, company)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=facture-{invoice.invoice_number}.pdf"})


@router.get("/invoices/{invoice_id}/xml")
async def portal_invoice_xml(invoice_id: str, request: Request, session: Session = Depends(get_session)):
    if not request.session.get("portal_client_id"):
        return RedirectResponse(url="/portal/login", status_code=303)
    client = session.get(Client, request.session["portal_client_id"])
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.client_id != client.id:
        return RedirectResponse(url="/portal/invoices", status_code=303)
    company = session.get(Company, client.company_id)
    from app.models.invoice import InvoiceLine
    lines = session.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.sort_order)
    ).all()
    xml_bytes = generate_ubl_invoice(invoice, lines, client, company)
    return Response(content=xml_bytes, media_type="application/xml",
                    headers={"Content-Disposition": f"attachment; filename=facture-{invoice.invoice_number}.xml"})


@router.get("/credit-notes", response_class=HTMLResponse)
async def portal_credit_notes(request: Request, session: Session = Depends(get_session)):
    if not request.session.get("portal_client_id"):
        return RedirectResponse(url="/portal/login", status_code=303)
    client = session.get(Client, request.session["portal_client_id"])
    if not client:
        return RedirectResponse(url="/portal/login", status_code=303)
    notes = session.exec(
        select(CreditNote).where(CreditNote.client_id == client.id).order_by(CreditNote.created_at.desc())
    ).all()
    company = session.get(Company, client.company_id)
    t = lambda s: s
    return templates.TemplateResponse(request, "portal/credit_notes.html", {
        "t": t, "client": client, "notes": notes, "company": company,
    })


@router.get("/credit-notes/{note_id}", response_class=HTMLResponse)
async def portal_credit_note_detail(note_id: str, request: Request, session: Session = Depends(get_session)):
    if not request.session.get("portal_client_id"):
        return RedirectResponse(url="/portal/login", status_code=303)
    client = session.get(Client, request.session["portal_client_id"])
    if not client:
        return RedirectResponse(url="/portal/login", status_code=303)
    note = session.get(CreditNote, note_id)
    if not note or note.client_id != client.id:
        return RedirectResponse(url="/portal/credit-notes", status_code=303)
    company = session.get(Company, client.company_id)
    from app.models.credit_note import CreditNoteLine
    lines = session.exec(
        select(CreditNoteLine).where(CreditNoteLine.credit_note_id == note_id).order_by(CreditNoteLine.sort_order)
    ).all()
    t = lambda s: s
    return templates.TemplateResponse(request, "portal/credit_note_detail.html", {
        "t": t, "client": client, "note": note, "company": company, "lines": lines,
    })
