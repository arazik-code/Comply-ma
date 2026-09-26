from decimal import Decimal
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select, func
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.database import get_session
from app.models.invoice import Invoice, InvoiceLine
from app.models.client import Client
from app.models.company import Company
from app.models.audit import AuditLog
from app.services.auth import require_auth
from app.i18n import get_translator
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_auth)])

MONTHS_FR = ["Jan","Fév","Mar","Avr","Mai","Jui","Jul","Aoû","Sep","Oct","Nov","Déc"]

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    company_id = user["company_id"]
    now = datetime.now(timezone.utc)

    all_invoices = session.exec(
        select(Invoice).where(Invoice.company_id == company_id)
    ).all()
    total_count = len(all_invoices)
    draft_count = sum(1 for i in all_invoices if i.status == "draft")
    validated_count = sum(1 for i in all_invoices if i.status == "validated")
    sent_count = sum(1 for i in all_invoices if i.status == "sent")
    archived_count = sum(1 for i in all_invoices if i.status == "archived")
    cancelled_count = sum(1 for i in all_invoices if i.status == "cancelled")

    revenue_invoices = [i for i in all_invoices if i.status in ("validated", "sent", "archived")]
    total_revenue = sum(i.total_ttc for i in revenue_invoices)
    total_tva = sum(i.total_tva for i in revenue_invoices)

    overdue_count = sum(1 for i in all_invoices if i.payment_status == "overdue")
    paid_count = sum(1 for i in all_invoices if i.payment_status == "paid")
    pending_count = sum(1 for i in all_invoices if i.payment_status == "pending")

    client_count = session.exec(
        select(func.count(Client.id)).where(Client.company_id == company_id)
    ).one()

    company = session.get(Company, company_id)

    # Chiffre d'affaires mensuel
    monthly = defaultdict(lambda: {"ht": 0, "ttc": 0})
    for i in revenue_invoices:
        m = i.invoice_date.month
        monthly[m]["ht"] += i.total_ht
        monthly[m]["ttc"] += i.total_ttc

    monthly_labels = []
    monthly_revenue = []
    monthly_ht = []
    for m in range(1, 13):
        monthly_labels.append(MONTHS_FR[m-1])
        if m <= now.month:
            monthly_revenue.append(round(float(monthly[m]["ttc"]), 2))
            monthly_ht.append(round(float(monthly[m]["ht"]), 2))
        else:
            monthly_revenue.append(0)
            monthly_ht.append(0)

    # Prévision TVA du trimestre en cours
    current_quarter = (now.month - 1) // 3 + 1
    quarter_months = [(current_quarter - 1) * 3 + 1, current_quarter * 3]
    tva_forecast = sum(
        i.total_tva for i in revenue_invoices
        if quarter_months[0] <= i.invoice_date.month <= quarter_months[1]
        and i.invoice_date.year == now.year
    )

    # Top clients par CA
    client_revenue: dict[str, dict] = {}
    for i in revenue_invoices:
        cid = i.client_id
        if cid not in client_revenue:
            c = session.get(Client, cid)
            client_revenue[cid] = {"name": c.name if c else "Inconnu", "total": Decimal("0")}
        client_revenue[cid]["total"] += i.total_ttc
    top_clients = sorted(client_revenue.values(), key=lambda x: x["total"], reverse=True)[:5]

    # Aging report (factures impayées par tranche)
    aging_buckets = {"0-30": Decimal("0"), "31-60": Decimal("0"), "61-90": Decimal("0"), "90+": Decimal("0")}
    for i in all_invoices:
        if i.payment_status in ("pending", "overdue") and i.status != "cancelled":
            # SQLite retourne des datetimes naive — normaliser avant soustraction
            inv_date = i.invoice_date.replace(tzinfo=timezone.utc) if i.invoice_date and i.invoice_date.tzinfo is None else i.invoice_date
            days_overdue = (now - inv_date).days if inv_date else 0
            if days_overdue <= 30:
                aging_buckets["0-30"] += i.total_ttc
            elif days_overdue <= 60:
                aging_buckets["31-60"] += i.total_ttc
            elif days_overdue <= 90:
                aging_buckets["61-90"] += i.total_ttc
            else:
                aging_buckets["90+"] += i.total_ttc
    aging_total = sum(aging_buckets.values())
    aging_pcts = {}
    for k, v in aging_buckets.items():
        aging_pcts[k] = round(float(v) / float(aging_total) * 100, 1) if aging_total > 0 else 0

    # Score de conformité moyen (dernières factures)
    from app.models.tva import TVARate
    from app.services.compliance_engine import check_invoice
    tva_rates_dict = {r.rate: r for r in session.exec(select(TVARate)).all()}
    recent_20 = sorted([i for i in all_invoices if i.status != "draft" and i.client_id],
                       key=lambda x: x.created_at, reverse=True)[:20]
    compliance_scores = []
    for inv in recent_20:
        lines = session.exec(
            select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id)
        ).all()
        client = session.get(Client, inv.client_id)
        report = check_invoice(inv, lines, client, company, tva_rates_dict)
        compliance_scores.append(report.score)
    avg_compliance = round(sum(compliance_scores) / len(compliance_scores), 1) if compliance_scores else 100

    recent_audit = session.exec(
        select(AuditLog)
        .where(AuditLog.company_id == company_id)
        .order_by(AuditLog.timestamp.desc())
        .limit(10)
    ).all()

    return templates.TemplateResponse(
        request, "dashboard/index.html",
        {
            "t": t, "user": user, "company": company,
            "total_count": total_count, "draft_count": draft_count,
            "validated_count": validated_count, "sent_count": sent_count,
            "archived_count": archived_count, "cancelled_count": cancelled_count,
            "total_revenue": total_revenue, "total_tva": total_tva,
            "overdue": overdue_count, "paid_count": paid_count,
            "pending_count": pending_count,
            "client_count": client_count,
            "monthly_labels": monthly_labels,
            "monthly_revenue": monthly_revenue,
            "monthly_ht": monthly_ht,
            "recent_audit": recent_audit,
            "status_counts": [
                ("draft", draft_count),
                ("validated", validated_count),
                ("sent", sent_count),
                ("archived", archived_count),
                ("cancelled", cancelled_count),
            ],
            "tva_forecast": tva_forecast,
            "top_clients": top_clients,
            "aging_buckets": aging_buckets,
            "aging_pcts": aging_pcts,
            "aging_total": aging_total,
            "avg_compliance": avg_compliance,
            "current_quarter": current_quarter,
        },
    )
