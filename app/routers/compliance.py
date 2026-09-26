"""
Conformité : audit de numérotation, vue clearance, synthèse TVA, journal d'audit.
"""
import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select, func

from app.database import get_session
from app.models.invoice import Invoice, InvoiceLine
from app.models.audit import AuditLog
from app.models.clearance import ClearanceRecord
from app.models.numbering import NumberingSequence
from app.models.tva import TVARate
from app.services.auth import require_auth
from app.i18n import get_translator
from app.templating import templates

logger = logging.getLogger("app.routers.compliance")
router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/", response_class=HTMLResponse)
async def compliance_dashboard(request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    company_id = user["company_id"]

    # ── Clearance overview ────────────────────────────────────────
    clearance_records = session.exec(
        select(ClearanceRecord).where(ClearanceRecord.company_id == company_id)
    ).all()
    clearance_total = len(clearance_records)
    clearance_cleared = sum(1 for c in clearance_records if c.status == "cleared")
    clearance_rejected = sum(1 for c in clearance_records if c.status == "rejected")
    clearance_pending = sum(1 for c in clearance_records if c.status in ("pending_dgi", "submitted"))

    # ── TVA summary ───────────────────────────────────────────────
    tva_rates = session.exec(
        select(TVARate).where(TVARate.is_active == True).order_by(TVARate.rate.desc())
    ).all()
    invoices_valid = session.exec(
        select(Invoice).where(
            Invoice.company_id == company_id,
            Invoice.status.in_(["validated", "sent", "archived"]),
        )
    ).all()
    valid_ids = [i.id for i in invoices_valid]

    tva_by_rate = {}
    if valid_ids:
        lines = session.exec(
            select(InvoiceLine).where(InvoiceLine.invoice_id.in_(valid_ids))
        ).all()
        for line in lines:
            rate_key = str(line.tva_rate)
            if rate_key not in tva_by_rate:
                tva_by_rate[rate_key] = {"rate": line.tva_rate, "ht": 0, "tva": 0}
            tva_by_rate[rate_key]["ht"] += line.line_total_ht
            tva_by_rate[rate_key]["tva"] += line.line_total_tva

    # ── Sequence audit ────────────────────────────────────────────
    sequences = session.exec(
        select(NumberingSequence).where(NumberingSequence.company_id == company_id)
    ).all()

    # ── Recent audit log ──────────────────────────────────────────
    recent_audit = session.exec(
        select(AuditLog)
        .where(AuditLog.company_id == company_id)
        .order_by(AuditLog.timestamp.desc())
        .limit(20)
    ).all()

    return templates.TemplateResponse(
        request, "compliance/index.html",
        {
            "t": t, "user": user,
            "clearance_total": clearance_total,
            "clearance_cleared": clearance_cleared,
            "clearance_rejected": clearance_rejected,
            "clearance_pending": clearance_pending,
            "tva_rates": tva_rates,
            "tva_by_rate": tva_by_rate,
            "sequences": sequences,
            "recent_audit": recent_audit,
        },
    )
