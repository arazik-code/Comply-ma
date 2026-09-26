import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from app.models.credit_note import CreditNote, CreditNoteLine
from app.models.invoice import Invoice, InvoiceLine
from app.services.numbering import next_credit_note_number
from app.services.tva import calc_line_totals, calc_invoice_totals
from app.services.state_machine import InvoiceStatus, validate_transition, InvalidTransitionError
from app.services.audit_service import log as audit_log


def create_credit_note_draft(
    session: Session,
    company_id: str,
    original_invoice_id: str,
    credit_note_date: datetime,
    reason: str,
    user_id: Optional[str] = None,
) -> CreditNote:
    invoice = session.get(Invoice, original_invoice_id)
    if not invoice:
        raise ValueError("Facture originale introuvable")
    if invoice.company_id != company_id:
        raise ValueError("Facture originale non autorisée")

    fiscal_year = credit_note_date.year
    cn = CreditNote(
        company_id=company_id,
        original_invoice_id=original_invoice_id,
        fiscal_year=fiscal_year,
        credit_note_date=credit_note_date,
        reason=reason,
        status="draft",
        is_locked=False,
    )
    session.add(cn)
    session.flush()

    audit_log(session, company_id, "credit_note", str(cn.id), "created", user_id=user_id)
    return cn


def add_line_to_credit_note(
    session: Session,
    credit_note_id: str,
    description: str,
    quantity: Decimal,
    unit_price: Decimal,
    tva_rate: Decimal,
    original_line_id: Optional[str] = None,
    sort_order: int = 0,
) -> CreditNoteLine:
    cn = session.get(CreditNote, credit_note_id)
    if not cn:
        raise ValueError("Avoir introuvable")
    if cn.is_locked:
        raise ValueError("Impossible de modifier un avoir verrouillé")

    totals = calc_line_totals(quantity, unit_price, tva_rate)
    line = CreditNoteLine(
        credit_note_id=credit_note_id,
        original_line_id=original_line_id,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        tva_rate=tva_rate,
        sort_order=sort_order,
        **totals,
    )
    session.add(line)
    _recalc_credit_note(session, credit_note_id)
    return line


def _recalc_credit_note(session: Session, credit_note_id: str):
    cn = session.get(CreditNote, credit_note_id)
    stmt = select(CreditNoteLine).where(CreditNoteLine.credit_note_id == credit_note_id).order_by(CreditNoteLine.sort_order)
    lines = session.exec(stmt).all()
    line_dicts = [
        {
            "line_total_ht": l.line_total_ht,
            "line_total_tva": l.line_total_tva,
            "line_total_ttc": l.line_total_ttc,
        }
        for l in lines
    ]
    totals = calc_invoice_totals(line_dicts)
    cn.total_ht = totals["total_ht"]
    cn.total_tva = totals["total_tva"]
    cn.total_ttc = totals["total_ttc"]
    session.add(cn)
    session.flush()


def validate_credit_note(
    session: Session,
    credit_note_id: str,
    user_id: str,
) -> CreditNote:
    cn = session.get(CreditNote, credit_note_id)
    if not cn:
        raise ValueError("Avoir introuvable")
    if cn.status != "draft":
        raise InvalidTransitionError(f"Impossible de valider un avoir au statut {cn.status}")

    stmt = select(CreditNoteLine).where(CreditNoteLine.credit_note_id == credit_note_id)
    lines = session.exec(stmt).all()
    if not lines:
        raise ValueError("Impossible de valider un avoir sans lignes")

    cn_number = next_credit_note_number(session, str(cn.company_id), cn.fiscal_year)
    cn.credit_note_number = cn_number
    cn.status = "validated"
    cn.is_locked = True
    cn.validated_at = datetime.now(timezone.utc)
    cn.validated_by = user_id
    session.add(cn)
    session.flush()

    audit_log(
        session, str(cn.company_id), "credit_note", str(cn.id),
        "validated", user_id=user_id,
        new_values=json.dumps({"credit_note_number": cn_number}),
    )
    return cn
