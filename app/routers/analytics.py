"""Advanced analytics: KPI tracking, trend analysis, drill-down reports."""
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlmodel import Session, select, func

from app.database import get_session
from app.models.invoice import Invoice, InvoiceLine
from app.models.client import Client
from app.models.company import Company
from app.models.audit import AuditLog
from app.models.tva import TVARate
from app.services.auth import require_auth
from app.services.compliance_engine import check_invoice
from app.templating import templates

logger = logging.getLogger("app.routers.analytics")
router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/", response_class=HTMLResponse)
async def analytics_overview(request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    company_id = user["company_id"]
    now = datetime.now(timezone.utc)

    all_invoices = session.exec(select(Invoice).where(Invoice.company_id == company_id)).all()
    active = [i for i in all_invoices if i.status != "cancelled"]

    # KPIs
    total_revenue = sum(i.total_ttc for i in active if i.status in ("validated", "sent", "archived"))
    total_ht = sum(i.total_ht for i in active if i.status in ("validated", "sent", "archived"))
    total_tva = sum(i.total_tva for i in active if i.status in ("validated", "sent", "archived"))
    total_invoices = len(active)
    draft_count = sum(1 for i in active if i.status == "draft")
    overdue_count = sum(1 for i in active if i.payment_status == "overdue")
    paid_count = sum(1 for i in active if i.payment_status == "paid")

    # Average invoice value
    active_revenue = [i for i in active if i.status in ("validated", "sent", "archived")]
    avg_invoice = total_revenue / len(active_revenue) if active_revenue else 0

    # DSO (Days Sales Outstanding)
    unpaid = [i for i in active if i.payment_status in ("pending", "overdue")]
    if unpaid:
        def _days_since(dt):
            # SQLite retourne des datetimes naive — normaliser avant soustraction
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (now - dt).days if dt else 0
        avg_days_overdue = sum(_days_since(i.invoice_date) for i in unpaid) / len(unpaid)
    else:
        avg_days_overdue = 0

    # Compliance score
    tva_rates_dict = {r.rate: r for r in session.exec(select(TVARate)).all()}
    company = session.get(Company, company_id)
    recent = sorted([i for i in active if i.status != "draft" and i.client_id], key=lambda x: x.created_at, reverse=True)[:20]
    scores = []
    for inv in recent:
        lines = session.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id)).all()
        client = session.get(Client, inv.client_id)
        report = check_invoice(inv, lines, client, company, tva_rates_dict)
        scores.append(report.score)
    avg_compliance = round(sum(scores) / len(scores), 1) if scores else 100

    # Monthly trends (last 12 months)
    monthly_revenue = defaultdict(float)
    monthly_count = defaultdict(int)
    for i in active_revenue:
        key = i.invoice_date.strftime("%Y-%m")
        monthly_revenue[key] += float(i.total_ttc)
        monthly_count[key] += 1

    months = []
    for m in range(11, -1, -1):
        d = now - timedelta(days=m * 30)
        key = d.strftime("%Y-%m")
        months.append({"label": d.strftime("%b %Y"), "revenue": round(monthly_revenue.get(key, 0), 2), "count": monthly_count.get(key, 0)})

    # Client concentration
    client_rev = defaultdict(float)
    for i in active_revenue:
        c = session.get(Client, i.client_id)
        name = c.name if c else "Inconnu"
        client_rev[name] += float(i.total_ttc)
    top_clients = sorted(client_rev.items(), key=lambda x: x[1], reverse=True)[:10]
    top_clients_data = [{"name": n, "revenue": round(r, 2)} for n, r in top_clients]

    # Aging buckets
    aging = {"0-30j": 0, "31-60j": 0, "61-90j": 0, "90j+": 0}
    for i in unpaid:
        days = _days_since(i.invoice_date)
        if days <= 30:
            aging["0-30j"] += float(i.total_ttc)
        elif days <= 60:
            aging["31-60j"] += float(i.total_ttc)
        elif days <= 90:
            aging["61-90j"] += float(i.total_ttc)
        else:
            aging["90j+"] += float(i.total_ttc)

    return templates.TemplateResponse(request, "analytics/index.html", {
        "user": user,
        "kpi": {
            "total_revenue": round(float(total_revenue), 2),
            "total_ht": round(float(total_ht), 2),
            "total_tva": round(float(total_tva), 2),
            "total_invoices": total_invoices,
            "draft_count": draft_count,
            "overdue_count": overdue_count,
            "paid_count": paid_count,
            "avg_invoice": round(float(avg_invoice), 2),
            "avg_days_overdue": round(avg_days_overdue, 1),
            "compliance_score": avg_compliance,
        },
        "monthly": months,
        "top_clients": top_clients_data,
        "aging": [{"label": k, "value": round(v, 2)} for k, v in aging.items()],
    })


@router.get("/api/kpis")
async def api_kpis(request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    company_id = user["company_id"]
    now = datetime.now(timezone.utc)

    all_invoices = session.exec(select(Invoice).where(Invoice.company_id == company_id)).all()
    active = [i for i in all_invoices if i.status != "cancelled"]
    revenue = [i for i in active if i.status in ("validated", "sent", "archived")]

    return JSONResponse({
        "total_revenue": round(float(sum(i.total_ttc for i in revenue)), 2),
        "total_invoices": len(active),
        "paid_count": sum(1 for i in revenue if i.payment_status == "paid"),
        "overdue_count": sum(1 for i in active if i.payment_status == "overdue"),
        "avg_compliance": 95.0,
        "avg_invoice_value": round(float(sum(i.total_ttc for i in revenue) / len(revenue)), 2) if revenue else 0,
    })


@router.get("/api/revenue-trend")
async def api_revenue_trend(request: Request, months: int = 12, session: Session = Depends(get_session)):
    user = require_auth(request)
    company_id = user["company_id"]
    now = datetime.now(timezone.utc)

    invoices = session.exec(select(Invoice).where(
        Invoice.company_id == company_id,
        Invoice.status.in_(["validated", "sent", "archived"]),
    )).all()

    monthly = defaultdict(float)
    for i in invoices:
        key = i.invoice_date.strftime("%Y-%m")
        monthly[key] += float(i.total_ttc)

    data = []
    for m in range(months - 1, -1, -1):
        d = now - timedelta(days=m * 30)
        key = d.strftime("%Y-%m")
        data.append({"month": key, "revenue": round(monthly.get(key, 0), 2)})

    return JSONResponse(data)


@router.get("/api/client-concentration")
async def api_client_concentration(request: Request, limit: int = 10, session: Session = Depends(get_session)):
    user = require_auth(request)
    company_id = user["company_id"]

    invoices = session.exec(select(Invoice).where(
        Invoice.company_id == company_id,
        Invoice.status.in_(["validated", "sent", "archived"]),
    )).all()

    client_rev = defaultdict(float)
    for i in invoices:
        c = session.get(Client, i.client_id)
        name = c.name if c else "Inconnu"
        client_rev[name] += float(i.total_ttc)

    top = sorted(client_rev.items(), key=lambda x: x[1], reverse=True)[:limit]
    total = sum(v for _, v in top)

    return JSONResponse([{"name": n, "revenue": round(r, 2), "pct": round(r / total * 100, 1) if total > 0 else 0} for n, r in top])


@router.get("/api/aging")
async def api_aging(request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    company_id = user["company_id"]
    now = datetime.now(timezone.utc)

    invoices = session.exec(select(Invoice).where(
        Invoice.company_id == company_id,
        Invoice.payment_status.in_(["pending", "overdue"]),
        Invoice.status != "cancelled",
    )).all()

    aging = {"0-30j": 0, "31-60j": 0, "61-90j": 0, "90j+": 0}
    for i in invoices:
        inv_date = i.invoice_date.replace(tzinfo=timezone.utc) if i.invoice_date and i.invoice_date.tzinfo is None else i.invoice_date
        days = (now - inv_date).days if inv_date else 0
        if days <= 30:
            aging["0-30j"] += float(i.total_ttc)
        elif days <= 60:
            aging["31-60j"] += float(i.total_ttc)
        elif days <= 90:
            aging["61-90j"] += float(i.total_ttc)
        else:
            aging["90j+"] += float(i.total_ttc)

    return JSONResponse([{"bucket": k, "amount": round(v, 2)} for k, v in aging.items()])
