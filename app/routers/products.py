"""
CRUD produits avec HTMX.
"""
import csv
import io
from decimal import Decimal

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select, func

from app.database import get_session
from app.pagination import Page, PAGE_SIZE
from app.models.product import Product
from app.models.tva import TVARate
from app.services.auth import require_auth
from app.i18n import get_translator
from app.flash import flash
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/", response_class=HTMLResponse)
async def product_list(
    request: Request,
    page: int = 1,
    session: Session = Depends(get_session),
):
    t = get_translator(request)
    user = require_auth(request)
    stmt = select(Product).where(Product.company_id == user["company_id"]).order_by(Product.name)
    count_stmt = select(func.count()).select_from(Product).where(Product.company_id == user["company_id"])
    total = session.exec(count_stmt).one()
    items = session.exec(stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    page_obj = Page(items=items, page=page, page_size=PAGE_SIZE, total=total)
    tva_rates = {r.id: r for r in session.exec(select(TVARate)).all()}
    return templates.TemplateResponse(
        request, "products/list.html",
        {"t": t, "products": page_obj.items, "tva_rates": tva_rates, "user": user, "page_obj": page_obj},
    )


@router.post("/import", response_class=HTMLResponse)
async def product_import_csv(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    tva_rates = {str(r.rate): r for r in session.exec(select(TVARate)).all()}
    created = 0
    errors = []
    for i, row in enumerate(reader, start=1):
        try:
            name = row.get("name", row.get("nom", "")).strip()
            if not name:
                errors.append(f"Ligne {i}: nom manquant")
                continue
            price_str = row.get("unit_price", row.get("prix", row.get("price", "0"))).replace(",", ".").strip()
            price = Decimal(price_str) if price_str else Decimal("0")
            tva_str = row.get("tva_rate", row.get("tva", "0.20")).replace(",", ".").strip()
            tva_dec = Decimal(tva_str)
            tva_rate_id = None
            for rate_str, rate_obj in tva_rates.items():
                if abs(Decimal(rate_str) - tva_dec) < Decimal("0.001"):
                    tva_rate_id = rate_obj.id
                    break
            product = Product(
                company_id=user["company_id"],
                name=name,
                unit_price=price,
                tva_rate_id=tva_rate_id,
            )
            session.add(product)
            created += 1
        except Exception as e:
            errors.append(f"Ligne {i}: {e}")
    session.commit()
    msg = f"{created} produit(s) importé(s)"
    if errors:
        msg += f" — {len(errors)} erreur(s): {'; '.join(errors[:5])}"
    flash(request, msg)
    return RedirectResponse(url="/products", status_code=303)


@router.get("/new", response_class=HTMLResponse)
async def product_create_form(request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    tva_rates = session.exec(select(TVARate).where(TVARate.is_active == True)).all()
    return templates.TemplateResponse(
        request, "products/form.html",
        {"t": t, "product": None, "tva_rates": tva_rates, "user": user},
    )


@router.post("/", response_class=HTMLResponse)
async def product_create(
    request: Request,
    name: str = Form(...),
    unit_price: str = Form(...),
    tva_rate_id: str = Form(...),
    unit: str = Form("pièce"),
    reference: str = Form(""),
    description: str = Form(""),
    session: Session = Depends(get_session),
):
    from decimal import Decimal
    user = require_auth(request)
    product = Product(
        company_id=user["company_id"],
        name=name,
        unit_price=Decimal(unit_price),
        tva_rate_id=tva_rate_id,
        unit=unit,
        reference=reference or None,
        description=description or None,
    )
    session.add(product)
    session.commit()
    flash(request, "Produit créé avec succès")
    return RedirectResponse(url="/products", status_code=303)


@router.get("/{product_id}/edit", response_class=HTMLResponse)
async def product_edit_form(product_id: str, request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    product = session.get(Product, product_id)
    if not product or product.company_id != user["company_id"]:
        return RedirectResponse(url="/products", status_code=303)
    tva_rates = session.exec(select(TVARate)).all()
    return templates.TemplateResponse(
        request, "products/form.html",
        {"t": t, "product": product, "tva_rates": tva_rates, "user": user},
    )


@router.post("/{product_id}", response_class=HTMLResponse)
async def product_update(
    product_id: str,
    request: Request,
    name: str = Form(...),
    unit_price: str = Form(...),
    tva_rate_id: str = Form(...),
    unit: str = Form("pièce"),
    reference: str = Form(""),
    description: str = Form(""),
    session: Session = Depends(get_session),
):
    from decimal import Decimal
    user = require_auth(request)
    product = session.get(Product, product_id)
    if not product or product.company_id != user["company_id"]:
        return RedirectResponse(url="/products", status_code=303)
    product.name = name
    product.unit_price = Decimal(unit_price)
    product.tva_rate_id = tva_rate_id
    product.unit = unit
    product.reference = reference or None
    product.description = description or None
    session.add(product)
    session.commit()
    flash(request, "Produit mis à jour")
    return RedirectResponse(url="/products", status_code=303)


@router.post("/{product_id}/delete", response_class=HTMLResponse)
async def product_delete(product_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    product = session.get(Product, product_id)
    if product and product.company_id == user["company_id"]:
        session.delete(product)
        session.commit()
        flash(request, "Produit supprimé")
    return RedirectResponse(url="/products", status_code=303)


@router.post("/{product_id}/toggle-active", response_class=HTMLResponse)
async def product_toggle_active(product_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    product = session.get(Product, product_id)
    if product and product.company_id == user["company_id"]:
        product.is_active = not product.is_active
        session.add(product)
        session.commit()
        flash(request, "Produit activé" if product.is_active else "Produit désactivé")
    return RedirectResponse(url="/products", status_code=303)
