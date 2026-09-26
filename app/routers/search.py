"""
Recherche globale — factures, clients, produits.
"""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models.invoice import Invoice
from app.models.client import Client
from app.models.product import Product
from app.models.company import Company
from app.services.auth import require_auth
from app.i18n import get_translator
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/search", response_class=HTMLResponse)
async def global_search(
    request: Request,
    q: str = Query(""),
    session: Session = Depends(get_session),
):
    t = get_translator(request)
    user = require_auth(request)
    company_id = user["company_id"]

    results = {"invoices": [], "clients": [], "products": []}

    if q and len(q) >= 2:
        pattern = f"%{q}%"

        # Factures — par numéro
        inv_stmt = (
            select(Invoice)
            .where(Invoice.company_id == company_id, Invoice.invoice_number.ilike(pattern))
            .order_by(Invoice.created_at.desc())
            .limit(10)
        )
        results["invoices"] = session.exec(inv_stmt).all()

        # Clients — par nom ou ICE
        client_stmt = (
            select(Client)
            .where(Client.company_id == company_id)
            .where(Client.name.ilike(pattern) | Client.ice.ilike(pattern))
            .order_by(Client.name)
            .limit(10)
        )
        results["clients"] = session.exec(client_stmt).all()

        # Produits — par nom
        prod_stmt = (
            select(Product)
            .where(Product.company_id == company_id, Product.name.ilike(pattern))
            .order_by(Product.name)
            .limit(10)
        )
        results["products"] = session.exec(prod_stmt).all()

    total = len(results["invoices"]) + len(results["clients"]) + len(results["products"])

    return templates.TemplateResponse(request, "search/results.html", {
        "t": t, "user": user, "q": q,
        "invoices": results["invoices"],
        "clients": results["clients"],
        "products": results["products"],
        "total": total,
    })
