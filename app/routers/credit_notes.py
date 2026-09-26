import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select, func

from app.config import settings
from app.database import get_session
from app.models.credit_note import CreditNote, CreditNoteLine
from app.models.client import Client
from app.models.company import Company
from app.models.invoice import Invoice, InvoiceLine
from app.models.product import Product
from app.models.tva import TVARate
from app.models.clearance import ClearanceRecord
from app.services.auth import require_auth
from app.services.audit_service import log as audit_log
from app.services.credit_note_service import create_credit_note_draft, add_line_to_credit_note, validate_credit_note
from app.services.state_machine import InvalidTransitionError
from app.services.xml.ubl_credit_note_generator import generate_ubl_credit_note
from app.services.xml.signature import SelfSignedSigner
from app.services.clearance.mock_provider import MockClearanceProvider
from app.services.clearance.dgi_provider import DGIClearanceProvider
from app.pagination import Page, PAGE_SIZE
from app.i18n import get_translator
from app.flash import flash
from app.templating import templates


def _get_clearance_provider():
    if settings.clearance_provider == "dgi":
        return DGIClearanceProvider(settings.dgi_api_base_url, settings.dgi_api_key)
    return MockClearanceProvider()


router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/", response_class=HTMLResponse)
async def credit_note_list(
    request: Request,
    status: str = Query(""),
    page: int = 1,
    session: Session = Depends(get_session),
):
    t = get_translator(request)
    user = require_auth(request)
    stmt = select(CreditNote).where(CreditNote.company_id == user["company_id"])
    if status:
        stmt = stmt.where(CreditNote.status == status)
    stmt = stmt.order_by(CreditNote.created_at.desc())
    count_stmt = select(func.count()).select_from(CreditNote).where(CreditNote.company_id == user["company_id"])
    if status:
        count_stmt = count_stmt.where(CreditNote.status == status)
    total = session.exec(count_stmt).one()
    items = session.exec(stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    page_obj = Page(items=items, page=page, page_size=PAGE_SIZE, total=total)
    invoices = {inv.id: inv for inv in session.exec(select(Invoice)).all()}
    clients = {c.id: c for c in session.exec(select(Client)).all()}
    return templates.TemplateResponse(
        request, "credit_notes/list.html",
        {"t": t, "notes": page_obj.items, "invoices": invoices, "clients": clients, "status": status, "user": user, "page_obj": page_obj},
    )


@router.get("/new", response_class=HTMLResponse)
async def credit_note_create_form(request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    invoices = session.exec(
        select(Invoice).where(
            Invoice.company_id == user["company_id"],
            Invoice.status.in_(["validated", "sent", "archived"]),
        ).order_by(Invoice.created_at.desc())
    ).all()
    return templates.TemplateResponse(
        request, "credit_notes/form.html",
        {"t": t, "invoices": invoices, "user": user, "note": None, "original_invoice": None},
    )


@router.post("/", response_class=HTMLResponse)
async def credit_note_create(
    request: Request,
    original_invoice_id: str = Form(...),
    credit_note_date: str = Form(...),
    reason: str = Form(...),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    dt = datetime.fromisoformat(credit_note_date).replace(tzinfo=timezone.utc)
    cn = create_credit_note_draft(session, user["company_id"], original_invoice_id, dt, reason, user["id"])
    session.commit()
    return RedirectResponse(url=f"/credit-notes/{cn.id}", status_code=303)


@router.get("/{note_id}", response_class=HTMLResponse)
async def credit_note_detail(note_id: str, request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    note = session.get(CreditNote, note_id)
    if not note or note.company_id != user["company_id"]:
        return RedirectResponse(url="/credit-notes", status_code=303)
    lines = session.exec(
        select(CreditNoteLine).where(CreditNoteLine.credit_note_id == note_id).order_by(CreditNoteLine.sort_order)
    ).all()
    invoice = session.get(Invoice, note.original_invoice_id)
    client = session.get(Client, invoice.client_id) if invoice else None
    company = session.get(Company, note.company_id)
    clearance = session.exec(
        select(ClearanceRecord).where(ClearanceRecord.credit_note_id == note_id)
    ).first()
    tva_rates = session.exec(select(TVARate)).all()
    tva_rates_dict = {r.rate: r for r in session.exec(select(TVARate)).all()}
    from app.services.compliance_engine import check_credit_note
    compliance = check_credit_note(note, lines, client, company, tva_rates_dict)
    return templates.TemplateResponse(
        request, "credit_notes/detail.html",
        {
            "t": t, "note": note, "lines": lines,
            "invoice": invoice, "client": client, "company": company,
            "clearance": clearance, "tva_rates": tva_rates,
            "user": user, "compliance": compliance,
        },
    )


@router.post("/{note_id}/lines-from-invoice", response_class=HTMLResponse)
async def credit_note_copy_lines(note_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    note = session.get(CreditNote, note_id)
    if not note or note.company_id != user["company_id"]:
        return RedirectResponse(url="/credit-notes", status_code=303)
    if note.is_locked:
        return RedirectResponse(url=f"/credit-notes/{note_id}", status_code=303)

    invoice_lines = session.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == note.original_invoice_id).order_by(InvoiceLine.sort_order)
    ).all()
    for inv_line in invoice_lines:
        add_line_to_credit_note(
            session, note_id,
            description=inv_line.description,
            quantity=inv_line.quantity,
            unit_price=inv_line.unit_price,
            tva_rate=inv_line.tva_rate,
            original_line_id=inv_line.id,
            sort_order=inv_line.sort_order,
        )
    session.commit()
    flash(request, "Lignes copiées")
    return RedirectResponse(url=f"/credit-notes/{note_id}", status_code=303)


@router.post("/{note_id}/lines", response_class=HTMLResponse)
async def credit_note_add_line(
    note_id: str,
    request: Request,
    description: str = Form(...),
    quantity: str = Form(...),
    unit_price: str = Form(""),
    product_id: str = Form(""),
    tva_rate: str = Form(...),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    note = session.get(CreditNote, note_id)
    if not note or note.company_id != user["company_id"]:
        return RedirectResponse(url="/credit-notes", status_code=303)
    if note.is_locked:
        return RedirectResponse(url=f"/credit-notes/{note_id}", status_code=303)
    qty = Decimal(quantity)
    rate = Decimal(tva_rate)
    if product_id:
        product = session.get(Product, product_id)
        price = product.unit_price
        if not description:
            description = product.name
    else:
        price = Decimal(unit_price)
    line = add_line_to_credit_note(session, note_id, description, qty, price, rate, sort_order=0)
    session.commit()
    flash(request, "Ligne ajoutée")
    return RedirectResponse(url=f"/credit-notes/{note_id}", status_code=303)


@router.post("/{note_id}/validate", response_class=HTMLResponse)
async def credit_note_do_validate(note_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    t = get_translator(request)
    try:
        note = validate_credit_note(session, note_id, user["id"])

        lines = session.exec(
            select(CreditNoteLine).where(CreditNoteLine.credit_note_id == note_id).order_by(CreditNoteLine.sort_order)
        ).all()
        company = session.get(Company, note.company_id)
        invoice = session.get(Invoice, note.original_invoice_id)
        client = session.get(Client, invoice.client_id) if invoice else None
        xml_bytes = generate_ubl_credit_note(note, lines, company, client, invoice)

        if settings.xml_sign_enabled:
            signer = SelfSignedSigner()
            xml_bytes = signer.sign(xml_bytes)

        provider = _get_clearance_provider()
        clearance = ClearanceRecord(
            company_id=company.id,
            credit_note_id=note_id,
            status="submitted",
            submission_timestamp=datetime.now(timezone.utc),
        )
        session.add(clearance)
        session.flush()

        result = await provider.submit_invoice(xml_bytes, note_id)

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
            session, company.id, "credit_note", note_id,
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
    flash(request, "Avoir validé")
    return RedirectResponse(url=f"/credit-notes/{note_id}", status_code=303)


@router.post("/{note_id}/send", response_class=HTMLResponse)
async def credit_note_mark_sent(note_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    note = session.get(CreditNote, note_id)
    if not note or note.company_id != user["company_id"]:
        return RedirectResponse(url="/credit-notes", status_code=303)
    if note.status == "validated":
        note.status = "sent"
        session.add(note)
        session.commit()
        flash(request, "Avoir envoyé")
    return RedirectResponse(url=f"/credit-notes/{note_id}", status_code=303)


@router.post("/{note_id}/cancel", response_class=HTMLResponse)
async def credit_note_cancel(note_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    note = session.get(CreditNote, note_id)
    if not note or note.company_id != user["company_id"]:
        return RedirectResponse(url="/credit-notes", status_code=303)
    if note.status in ("draft", "validated"):
        note.status = "cancelled"
        session.add(note)
        session.commit()
        flash(request, "Avoir annulé")
    return RedirectResponse(url=f"/credit-notes/{note_id}", status_code=303)


@router.get("/{note_id}/xml", response_class=Response)
async def credit_note_download_xml(note_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    note = session.get(CreditNote, note_id)
    if not note or note.company_id != user["company_id"]:
        return RedirectResponse(url="/credit-notes", status_code=303)
    lines = session.exec(
        select(CreditNoteLine).where(CreditNoteLine.credit_note_id == note_id).order_by(CreditNoteLine.sort_order)
    ).all()
    company = session.get(Company, note.company_id)
    invoice = session.get(Invoice, note.original_invoice_id)
    client = session.get(Client, invoice.client_id) if invoice else None
    xml_bytes = generate_ubl_credit_note(note, lines, company, client, invoice)
    return Response(content=xml_bytes, media_type="application/xml",
                    headers={"Content-Disposition": f"attachment; filename={note.credit_note_number or 'draft'}.xml"})
