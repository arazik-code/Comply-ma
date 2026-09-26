"""
Bons de commande avec rapprochement à 3 voies.
"""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select, func

from app.database import get_session
from app.pagination import Page, PAGE_SIZE
from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.models.client import Client
from app.models.product import Product
from app.models.tva import TVARate
from app.models.company import Company
from app.services.auth import require_auth
from app.services.tva import calc_line_totals, calc_invoice_totals
from app.i18n import get_translator
from app.flash import flash
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/purchase-orders", response_class=HTMLResponse)
async def po_list(
    request: Request,
    status: str = Query(""),
    page: int = Query(1),
    session: Session = Depends(get_session),
):
    t = get_translator(request)
    user = require_auth(request)
    stmt = select(PurchaseOrder).where(PurchaseOrder.company_id == user["company_id"])
    count_stmt = select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.company_id == user["company_id"])
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
        count_stmt = count_stmt.where(PurchaseOrder.status == status)
    total = session.exec(count_stmt).one()
    items = session.exec(stmt.order_by(PurchaseOrder.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    page_obj = Page(items=items, page=page, page_size=PAGE_SIZE, total=total)
    suppliers = {s.id: s for s in session.exec(select(Client).where(Client.company_id == user["company_id"])).all()}
    return templates.TemplateResponse(request, "purchase_orders/list.html", {
        "t": t, "user": user, "page_obj": page_obj, "status": status, "suppliers": suppliers,
    })


@router.get("/purchase-orders/new", response_class=HTMLResponse)
async def po_create_form(request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    suppliers = session.exec(select(Client).where(Client.company_id == user["company_id"]).order_by(Client.name)).all()
    products = session.exec(select(Product).where(Product.company_id == user["company_id"]).order_by(Product.name)).all()
    tva_rates = session.exec(select(TVARate).where(TVARate.is_active == True)).all()
    return templates.TemplateResponse(request, "purchase_orders/form.html", {
        "t": t, "user": user, "suppliers": suppliers, "products": products, "tva_rates": tva_rates,
    })


@router.post("/purchase-orders", response_class=HTMLResponse)
async def po_create(
    request: Request,
    supplier_id: str = Form(...),
    issue_date: str = Form(...),
    expected_date: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    company_id = user["company_id"]
    # Générer un numéro de commande simple
    count = session.exec(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.company_id == company_id)).one()
    po = PurchaseOrder(
        company_id=company_id,
        po_number=f"BC-{datetime.now(timezone.utc).strftime('%Y%m')}-{count + 1:04d}",
        supplier_id=supplier_id,
        issue_date=datetime.strptime(issue_date, "%Y-%m-%d").replace(tzinfo=timezone.utc),
        expected_date=datetime.strptime(expected_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if expected_date else None,
        notes=notes or None,
    )
    session.add(po)
    session.commit()
    flash(request, "Bon de commande créé")
    return RedirectResponse(url=f"/purchase-orders/{po.id}", status_code=303)


@router.get("/purchase-orders/{po_id}", response_class=HTMLResponse)
async def po_detail(po_id: str, request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    po = session.get(PurchaseOrder, po_id)
    if not po or po.company_id != user["company_id"]:
        return RedirectResponse(url="/purchase-orders", status_code=303)
    lines = session.exec(
        select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id).order_by(PurchaseOrderLine.sort_order)
    ).all()
    supplier = session.get(Client, po.supplier_id)
    products = session.exec(select(Product).where(Product.company_id == user["company_id"]).order_by(Product.name)).all()
    tva_rates = session.exec(select(TVARate).where(TVARate.is_active == True)).all()
    return templates.TemplateResponse(request, "purchase_orders/detail.html", {
        "t": t, "user": user, "po": po, "lines": lines,
        "supplier": supplier, "products": products, "tva_rates": tva_rates,
    })


@router.post("/purchase-orders/{po_id}/lines", response_class=HTMLResponse)
async def po_add_line(
    po_id: str,
    request: Request,
    product_id: str = Form(""),
    description: str = Form(...),
    quantity: str = Form(...),
    unit_price: str = Form(""),
    tva_rate: str = Form(...),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    po = session.get(PurchaseOrder, po_id)
    if not po or po.company_id != user["company_id"]:
        return RedirectResponse(url="/purchase-orders", status_code=303)
    qty = Decimal(quantity)
    rate = Decimal(tva_rate)
    if product_id:
        product = session.get(Product, product_id)
        price = product.unit_price
        if not description:
            description = product.name
    else:
        price = Decimal(unit_price)
    totals = calc_line_totals(qty, price, rate)
    lines = session.exec(select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id)).all()
    line = PurchaseOrderLine(
        po_id=po_id,
        product_id=product_id or None,
        description=description,
        quantity=qty,
        unit_price=price,
        tva_rate=rate,
        sort_order=len(lines),
        **totals,
    )
    session.add(line)
    # Recalc PO totals
    all_lines = session.exec(select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id)).all()
    line_dicts = [{"line_total_ht": l.line_total_ht, "line_total_tva": l.line_total_tva, "line_total_ttc": l.line_total_ttc} for l in all_lines]
    invoice_totals = calc_invoice_totals(line_dicts)
    po.total_ht = invoice_totals["total_ht"]
    po.total_tva = invoice_totals["total_tva"]
    po.total_ttc = invoice_totals["total_ttc"]
    session.add(po)
    session.commit()
    flash(request, "Ligne ajoutée")
    return RedirectResponse(url=f"/purchase-orders/{po_id}", status_code=303)


@router.post("/purchase-orders/{po_id}/status", response_class=HTMLResponse)
async def po_update_status(
    po_id: str,
    request: Request,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    po = session.get(PurchaseOrder, po_id)
    if po and po.company_id == user["company_id"]:
        po.status = status
        session.add(po)
        session.commit()
        flash(request, f"Statut mis à jour : {status}")
    return RedirectResponse(url=f"/purchase-orders/{po_id}", status_code=303)


@router.post("/purchase-orders/{po_id}/receive", response_class=HTMLResponse)
async def po_receive(request: Request, po_id: str, session: Session = Depends(get_session)):
    user = require_auth(request)
    po = session.get(PurchaseOrder, po_id)
    if not po or po.company_id != user["company_id"]:
        return RedirectResponse(url="/purchase-orders", status_code=303)
    lines = session.exec(select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id)).all()
    all_received = True
    for line in lines:
        line.received_quantity = line.quantity
        session.add(line)
    po.status = "fully_received"
    session.add(po)
    session.commit()
    flash(request, "Réception complète enregistrée")
    return RedirectResponse(url=f"/purchase-orders/{po_id}", status_code=303)
