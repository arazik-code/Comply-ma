"""
Factures : création, lignes, validation, PDF/XML, paiements.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select, func, or_

from app.config import settings
from app.database import get_session
from app.models.invoice import Invoice, InvoiceLine
from app.models.client import Client
from app.models.product import Product
from app.models.tva import TVARate
from app.models.company import Company
from app.models.payment import Payment
from app.models.clearance import ClearanceRecord
from app.services.auth import require_auth
from app.services.audit_service import log as audit_log
from app.services.invoice_service import create_invoice_draft, add_line_to_invoice, validate_invoice
from app.services.state_machine import InvoiceStatus, validate_transition, InvalidTransitionError
from app.services.pdf_generator import generate_invoice_pdf
from app.services.xml.ubl_generator import generate_ubl_invoice
from app.services.xml.signature import SelfSignedSigner
from app.services.archive import build_archive_zip, store_archive
from app.services.clearance.mock_provider import MockClearanceProvider
from app.services.clearance.dgi_provider import DGIClearanceProvider
from app.pagination import Page
from app.i18n import get_translator
from app.flash import flash
from app.templating import templates


def _get_clearance_provider():
    if settings.clearance_provider == "dgi":
        return DGIClearanceProvider(settings.dgi_api_base_url, settings.dgi_api_key)
    return MockClearanceProvider()

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/", response_class=HTMLResponse)
async def invoice_list(
    request: Request,
    status: str = Query(""),
    q: str = Query(""),
    page: int = 1,
    session: Session = Depends(get_session),
):
    t = get_translator(request)
    user = require_auth(request)
    stmt = select(Invoice).where(Invoice.company_id == user["company_id"])
    count_stmt = select(func.count()).select_from(Invoice).where(Invoice.company_id == user["company_id"])
    if status:
        stmt = stmt.where(Invoice.status == status)
        count_stmt = count_stmt.where(Invoice.status == status)
    if q.strip():
        term = f"%{q.strip()}%"
        client_ids = select(Client.id).where(
            Client.company_id == user["company_id"], Client.name.ilike(term)
        )
        search_filter = or_(Invoice.invoice_number.ilike(term), Invoice.client_id.in_(client_ids))
        stmt = stmt.where(search_filter)
        count_stmt = count_stmt.where(search_filter)
    stmt = stmt.order_by(Invoice.created_at.desc())
    total = session.exec(count_stmt).one()
    items = session.exec(stmt.offset((page - 1) * 20).limit(20)).all()
    page_obj = Page(items=items, page=page, page_size=20, total=total)
    clients = {c.id: c for c in session.exec(select(Client).where(Client.company_id == user["company_id"])).all()}
    return templates.TemplateResponse(
        request, "invoices/list.html",
        {"t": t, "invoices": page_obj.items, "clients": clients, "status": status, "q": q, "user": user, "page_obj": page_obj},
    )


@router.get("/new", response_class=HTMLResponse)
async def invoice_create_form(request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    clients = session.exec(
        select(Client).where(Client.company_id == user["company_id"], Client.is_active == True).order_by(Client.name)
    ).all()
    products = session.exec(
        select(Product).where(Product.company_id == user["company_id"], Product.is_active == True).order_by(Product.name)
    ).all()
    tva_rates = session.exec(select(TVARate).where(TVARate.is_active == True)).all()
    return templates.TemplateResponse(
        request, "invoices/form.html",
        {
            "t": t, "clients": clients,
            "products": products, "tva_rates": tva_rates, "user": user,
            "invoice": None,
        },
    )


@router.post("/", response_class=HTMLResponse)
async def invoice_create(
    request: Request,
    client_id: str = Form(...),
    invoice_date: str = Form(...),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    dt = datetime.fromisoformat(invoice_date).replace(tzinfo=timezone.utc)
    invoice = create_invoice_draft(session, user["company_id"], client_id, dt, notes or None, user["id"])
    session.commit()
    return RedirectResponse(url=f"/invoices/{invoice.id}", status_code=303)


@router.post("/bulk", response_class=HTMLResponse)
async def invoices_bulk(
    request: Request,
    ids: str = Form(...),
    action: str = Form(...),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    t = get_translator(request)
    invoice_ids = [i for i in ids.split(",") if i]
    if not invoice_ids:
        return RedirectResponse(url="/invoices", status_code=303)
    invoices = session.exec(
        select(Invoice).where(Invoice.id.in_(invoice_ids), Invoice.company_id == user["company_id"])
    ).all()
    count = 0
    for inv in invoices:
        if action == "validate" and inv.status == "draft" and not inv.is_locked:
            from app.services.invoice_service import validate_invoice
            validate_invoice(session, inv.id, user["id"])
            count += 1
        elif action == "send" and inv.status == "validated":
            inv.status = "sent"
            session.add(inv)
            count += 1
        elif action == "archive" and inv.status == "sent":
            inv.status = "archived"
            session.add(inv)
            count += 1
        elif action == "cancel" and inv.status in ("draft", "validated", "sent"):
            inv.status = "cancelled"
            session.add(inv)
            count += 1
    session.commit()
    flash(request, f"{count} facture(s) {action}ée(s)")
    return RedirectResponse(url="/invoices", status_code=303)


@router.get("/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail(invoice_id: str, request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.company_id != user["company_id"]:
        return RedirectResponse(url="/invoices", status_code=303)
    lines = session.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.sort_order)
    ).all()
    client = session.get(Client, invoice.client_id)
    company = session.get(Company, invoice.company_id)
    payments = session.exec(
        select(Payment).where(Payment.invoice_id == invoice_id).order_by(Payment.payment_date)
    ).all()
    clearance = session.exec(
        select(ClearanceRecord).where(ClearanceRecord.invoice_id == invoice_id)
    ).first()
    tva_rates = session.exec(select(TVARate)).all()
    tva_rates_dict = {r.rate: r for r in session.exec(select(TVARate)).all()}
    products = session.exec(
        select(Product).where(Product.company_id == user["company_id"]).order_by(Product.name)
    ).all()
    from app.services.compliance_engine import check_invoice
    compliance = check_invoice(invoice, lines, client, company, tva_rates_dict)
    return templates.TemplateResponse(
        request, "invoices/detail.html",
        {
            "t": t, "invoice": invoice, "lines": lines,
            "client": client, "company": company, "payments": payments,
            "clearance": clearance, "tva_rates": tva_rates, "products": products,
            "user": user, "compliance": compliance,
        },
    )


@router.post("/{invoice_id}/lines", response_class=HTMLResponse)
async def invoice_add_line(
    invoice_id: str,
    request: Request,
    description: str = Form(...),
    quantity: str = Form(...),
    unit_price: str = Form(""),
    product_id: str = Form(""),
    tva_rate: str = Form(...),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.company_id != user["company_id"]:
        return RedirectResponse(url="/invoices", status_code=303)
    if invoice.is_locked:
        return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)
    qty = Decimal(quantity)
    rate = Decimal(tva_rate)
    if product_id:
        product = session.get(Product, product_id)
        price = product.unit_price
        if not description:
            description = product.name
    else:
        price = Decimal(unit_price)
    line = add_line_to_invoice(session, invoice_id, description, qty, price, rate, product_id or None)
    session.commit()
    flash(request, "Ligne ajoutée")
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/validate", response_class=HTMLResponse)
async def invoice_do_validate(invoice_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    t = get_translator(request)
    try:
        invoice = validate_invoice(session, invoice_id, user["id"])

        # Générer le XML UBL / CII pour le clearance
        lines = session.exec(
            select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.sort_order)
        ).all()
        company = session.get(Company, invoice.company_id)
        client = session.get(Client, invoice.client_id)
        if settings.xml_format == "cii":
            from app.services.xml.cii_generator import generate_cii_invoice
            xml_bytes = generate_cii_invoice(invoice, lines, company, client)
        else:
            xml_bytes = generate_ubl_invoice(invoice, lines, company, client)

        if settings.xml_sign_enabled:
            signer = SelfSignedSigner()
            xml_bytes = signer.sign(xml_bytes)

        # Soumettre au clearance
        provider = _get_clearance_provider()
        clearance = ClearanceRecord(
            company_id=company.id,
            invoice_id=invoice_id,
            status="submitted",
            submission_timestamp=datetime.now(timezone.utc),
        )
        session.add(clearance)
        session.flush()

        result = await provider.submit_invoice(xml_bytes, invoice_id)

        if result.success:
            clearance.status = "cleared"
            clearance.clearance_number = result.clearance_number
            clearance.clearance_timestamp = datetime.now(timezone.utc)
            clearance.raw_response = result.raw_response
        else:
            clearance.status = "rejected"
            clearance.error_code = result.error_code
            clearance.error_message = result.error_message
            clearance.raw_response = result.raw_response

        audit_log(
            session, company.id, "invoice", invoice_id,
            "clearance_accepted" if result.success else "clearance_rejected",
            user_id=user["id"],
            new_values=json.dumps({
                "clearance_id": clearance.id,
                "clearance_number": result.clearance_number,
                "success": result.success,
            }),
        )
        session.commit()
    except (ValueError, InvalidTransitionError) as e:
        flash(request, str(e), "error")
        return templates.TemplateResponse(
            request, "_toast.html",
            {"t": t, "error": str(e)},
        )
    flash(request, "Facture validée")
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/send", response_class=HTMLResponse)
async def invoice_mark_sent(invoice_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.company_id != user["company_id"]:
        return RedirectResponse(url="/invoices", status_code=303)
    try:
        validate_transition(invoice.status, InvoiceStatus.SENT)
        invoice.status = InvoiceStatus.SENT
        session.add(invoice)
        session.commit()
        flash(request, "Facture envoyée")
    except InvalidTransitionError:
        pass
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/cancel", response_class=HTMLResponse)
async def invoice_cancel(invoice_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.company_id != user["company_id"]:
        return RedirectResponse(url="/invoices", status_code=303)
    try:
        validate_transition(invoice.status, InvoiceStatus.CANCELLED)
        invoice.status = InvoiceStatus.CANCELLED
        session.add(invoice)
        session.commit()
        flash(request, "Facture annulée")
    except InvalidTransitionError:
        pass
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/archive", response_class=HTMLResponse)
async def invoice_archive(invoice_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.company_id != user["company_id"]:
        return RedirectResponse(url="/invoices", status_code=303)
    try:
        validate_transition(invoice.status, InvoiceStatus.ARCHIVED)
        lines = session.exec(
            select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.sort_order)
        ).all()
        company = session.get(Company, invoice.company_id)
        client = session.get(Client, invoice.client_id)
        zip_bytes = build_archive_zip(invoice, lines, company, client)
        store_archive(invoice_id, zip_bytes)
        invoice.status = InvoiceStatus.ARCHIVED
        session.add(invoice)
        session.commit()
        flash(request, "Facture archivée")
    except InvalidTransitionError:
        pass
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/payment", response_class=HTMLResponse)
async def invoice_add_payment(
    invoice_id: str,
    request: Request,
    amount: str = Form(...),
    payment_date: str = Form(...),
    payment_method: str = Form(...),
    reference: str = Form(""),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.company_id != user["company_id"]:
        return RedirectResponse(url="/invoices", status_code=303)
    pmt = Payment(
        invoice_id=invoice_id,
        amount=Decimal(amount),
        payment_date=datetime.fromisoformat(payment_date).replace(tzinfo=timezone.utc),
        payment_method=payment_method,
        reference=reference or None,
    )
    session.add(pmt)
    # Recalculer le statut de paiement
    total_paid = sum(
        p.amount for p in session.exec(select(Payment).where(Payment.invoice_id == invoice_id)).all()
    ) + pmt.amount
    if total_paid >= invoice.total_ttc:
        invoice.payment_status = "paid"
    elif total_paid > 0:
        invoice.payment_status = "partial"
    session.add(invoice)
    session.commit()
    flash(request, "Paiement enregistré")
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.get("/{invoice_id}/pdf", response_class=Response)
async def invoice_download_pdf(invoice_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.company_id != user["company_id"]:
        return RedirectResponse(url="/invoices", status_code=303)
    lines = session.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.sort_order)
    ).all()
    company = session.get(Company, invoice.company_id)
    client = session.get(Client, invoice.client_id)
    pdf_bytes = generate_invoice_pdf(invoice, lines, company, client)
    if isinstance(pdf_bytes, bytes):
        return Response(content=pdf_bytes, media_type="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename={invoice.invoice_number or 'draft'}.pdf"})
    return Response(content=pdf_bytes, media_type="text/html",
                    headers={"Content-Disposition": f"inline; filename={invoice.invoice_number or 'draft'}.html"})


@router.post("/{invoice_id}/email", response_class=HTMLResponse)
async def invoice_send_email(
    invoice_id: str,
    request: Request,
    to: str = Form(...),
    session: Session = Depends(get_session),
):
    from app.services.email import send_invoice_email
    t = get_translator(request)
    user = require_auth(request)
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.company_id != user["company_id"]:
        return RedirectResponse(url="/invoices", status_code=303)
    lines = session.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.sort_order)
    ).all()
    company = session.get(Company, invoice.company_id)
    client = session.get(Client, invoice.client_id)
    pdf_bytes = generate_invoice_pdf(invoice, lines, company, client)
    if settings.xml_format == "cii":
        from app.services.xml.cii_generator import generate_cii_invoice
        xml_bytes = generate_cii_invoice(invoice, lines, company, client)
    else:
        xml_bytes = generate_ubl_invoice(invoice, lines, company, client)
    ok = await send_invoice_email(
        to=to,
        subject=f"Facture {invoice.invoice_number or ''}",
        body=f"Bonjour,\n\nVeuillez trouver ci-joint la facture {invoice.invoice_number or ''}.\n\nCordialement,\n{company.company_name}",
        pdf_bytes=pdf_bytes if isinstance(pdf_bytes, bytes) else None,
        xml_bytes=xml_bytes,
        invoice_number=invoice.invoice_number or "draft",
    )
    if ok:
        flash(request, "Email envoyé")
        return templates.TemplateResponse(request, "_toast.html", {"t": t, "success": "Email envoyé"})
    flash(request, "Échec envoi email (SMTP non configuré ?)", "error")
    return templates.TemplateResponse(request, "_toast.html", {"t": t, "error": "Échec envoi email (SMTP non configuré ?)"})


@router.get("/{invoice_id}/xml", response_class=Response)
async def invoice_download_xml(invoice_id: str, request: Request, session: Session = Depends(get_session)):
    from app.config import settings
    user = require_auth(request)
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.company_id != user["company_id"]:
        return RedirectResponse(url="/invoices", status_code=303)
    lines = session.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.sort_order)
    ).all()
    company = session.get(Company, invoice.company_id)
    client = session.get(Client, invoice.client_id)
    if settings.xml_format == "cii":
        from app.services.xml.cii_generator import generate_cii_invoice
        xml_bytes = generate_cii_invoice(invoice, lines, company, client)
    else:
        xml_bytes = generate_ubl_invoice(invoice, lines, company, client)
    return Response(content=xml_bytes, media_type="application/xml",
                    headers={"Content-Disposition": f"attachment; filename={invoice.invoice_number or 'draft'}.xml"})
