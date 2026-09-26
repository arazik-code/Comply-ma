"""
Bons de réception — CRUD pour les bons de réception (Goods Receipt).
Permet d'enregistrer les réceptions de marchandises pour le 3-way matching.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select, func

from app.database import get_session
from app.pagination import Page, PAGE_SIZE
from app.models.goods_receipt import GoodsReceipt, GoodsReceiptLine
from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.models.client import Client
from app.models.company import Company
from app.models.product import Product
from app.services.auth import require_auth
from app.services.numbering import next_invoice_number
from app.i18n import get_translator
from app.flash import flash
from app.templating import templates

logger = logging.getLogger("app.routers.goods_receipts")
router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/goods-receipts", response_class=HTMLResponse)
async def goods_receipt_list(
    request: Request,
    page: int = 1,
    session: Session = Depends(get_session),
):
    t = get_translator(request)
    user = require_auth(request)
    company_id = user["company_id"]

    stmt = select(GoodsReceipt).where(GoodsReceipt.company_id == company_id)
    count_stmt = select(func.count()).select_from(GoodsReceipt).where(GoodsReceipt.company_id == company_id)
    total = session.exec(count_stmt).one()
    items = session.exec(stmt.order_by(GoodsReceipt.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    page_obj = Page(items=items, page=page, page_size=PAGE_SIZE, total=total)

    pos = {}
    for gr in items:
        po = session.get(PurchaseOrder, gr.po_id)
        pos[gr.po_id] = po

    return templates.TemplateResponse(request, "goods_receipts/list.html", {
        "t": t, "user": user, "page_obj": page_obj, "pos": pos,
    })


@router.get("/goods-receipts/new", response_class=HTMLResponse)
async def goods_receipt_new_form(request: Request, po_id: str = "", session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    company_id = user["company_id"]
    pos = session.exec(
        select(PurchaseOrder).where(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.status.in_(["sent", "partially_received"]),
        )
    ).all()
    return templates.TemplateResponse(request, "goods_receipts/form.html", {
        "t": t, "user": user, "pos": pos, "selected_po": po_id,
    })


@router.post("/goods-receipts")
async def goods_receipt_create(
    request: Request,
    po_id: str = Form(...),
    receipt_date: str = Form(...),
    received_by: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    company_id = user["company_id"]

    po = session.get(PurchaseOrder, po_id)
    if not po or po.company_id != company_id:
        flash(request, "BC introuvable", "error")
        return RedirectResponse(url="/goods-receipts", status_code=303)

    gr_number = f"BR-{datetime.now().strftime('%Y%m%d')}-{po.po_number.split('-')[-1]}"

    gr = GoodsReceipt(
        company_id=company_id,
        po_id=po_id,
        gr_number=gr_number,
        receipt_date=datetime.strptime(receipt_date, "%Y-%m-%d").replace(tzinfo=timezone.utc),
        received_by=received_by or None,
        notes=notes or None,
    )
    session.add(gr)
    session.flush()

    # Créer les lignes de réception (quantités attendues par défaut)
    po_lines = session.exec(
        select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id).order_by(PurchaseOrderLine.sort_order)
    ).all()
    for i, po_line in enumerate(po_lines):
        gr_line = GoodsReceiptLine(
            goods_receipt_id=gr.id,
            po_line_id=po_line.id,
            product_id=po_line.product_id,
            description=po_line.description,
            quantity_expected=po_line.quantity,
            quantity_received=po_line.quantity,
            sort_order=i + 1,
        )
        session.add(gr_line)

    session.commit()
    flash(request, f"Bon de réception {gr_number} créé")
    return RedirectResponse(url=f"/goods-receipts/{gr.id}", status_code=303)


@router.get("/goods-receipts/{gr_id}", response_class=HTMLResponse)
async def goods_receipt_detail(gr_id: str, request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    gr = session.get(GoodsReceipt, gr_id)
    if not gr or gr.company_id != user["company_id"]:
        return RedirectResponse(url="/goods-receipts", status_code=303)

    lines = session.exec(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == gr_id).order_by(GoodsReceiptLine.sort_order)
    ).all()
    po = session.get(PurchaseOrder, gr.po_id)
    po_lines = {}
    for line in lines:
        po_lines[line.po_line_id] = session.get(PurchaseOrderLine, line.po_line_id)

    return templates.TemplateResponse(request, "goods_receipts/detail.html", {
        "t": t, "user": user, "gr": gr, "lines": lines, "po": po, "po_lines": po_lines,
    })


@router.post("/goods-receipts/{gr_id}/confirm")
async def goods_receipt_confirm(gr_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    gr = session.get(GoodsReceipt, gr_id)
    if not gr or gr.company_id != user["company_id"]:
        return RedirectResponse(url="/goods-receipts", status_code=303)

    gr.status = "confirmed"
    session.add(gr)
    session.commit()
    flash(request, "Bon de réception confirmé")
    return RedirectResponse(url=f"/goods-receipts/{gr_id}", status_code=303)
