"""
Service métier central pour les factures.

Coordonne :
  - Création et calcul des lignes
  - Validation (attribution du numéro, verrouillage, hash)
  - File d'attente de clearance DGI
  - Enregistrement des paiements
"""
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from app.models.invoice import Invoice, InvoiceLine
from app.models.client import Client
from app.models.company import Company
from app.services.numbering import next_invoice_number
from app.services.tva import calc_line_totals, calc_invoice_totals
from app.services.state_machine import InvoiceStatus, validate_transition, InvalidTransitionError
from app.services.audit_service import log as audit_log
from app.services.hash_service import compute_hash


def create_invoice_draft(
    session: Session,
    company_id: str,
    client_id: str,
    invoice_date: datetime,
    notes: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Invoice:
    """Crée une facture en brouillon sans numéro (numéro attribué à la validation)."""
    fiscal_year = invoice_date.year
    invoice = Invoice(
        company_id=company_id,
        client_id=client_id,
        fiscal_year=fiscal_year,
        invoice_date=invoice_date,
        status=InvoiceStatus.DRAFT,
        is_locked=False,
        notes=notes,
    )
    session.add(invoice)
    session.flush()

    audit_log(session, company_id, "invoice", str(invoice.id), "created", user_id=user_id)
    return invoice


def add_line_to_invoice(
    session: Session,
    invoice_id: str,
    description: str,
    quantity: Decimal,
    unit_price: Decimal,
    tva_rate: Decimal,
    product_id: Optional[str] = None,
    sort_order: int = 0,
) -> InvoiceLine:
    """Ajoute une ligne à une facture en brouillon."""
    invoice = session.get(Invoice, invoice_id)
    if invoice.is_locked:
        raise ValueError("Impossible de modifier une facture verrouillée")

    totals = calc_line_totals(quantity, unit_price, tva_rate)
    line = InvoiceLine(
        invoice_id=invoice_id,
        product_id=product_id,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        tva_rate=tva_rate,
        sort_order=sort_order,
        **totals,
    )
    session.add(line)
    _recalc_invoice(session, invoice_id)
    return line


def _recalc_invoice(session: Session, invoice_id: str):
    """Recalcule les totaux de la facture à partir de ses lignes."""
    invoice = session.get(Invoice, invoice_id)
    stmt = select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.sort_order)
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
    invoice.total_ht = totals["total_ht"]
    invoice.total_tva = totals["total_tva"]
    invoice.total_ttc = totals["total_ttc"]
    session.add(invoice)
    session.flush()


def validate_invoice(
    session: Session,
    invoice_id: str,
    user_id: str,
) -> Invoice:
    """
    Valide une facture : attribue le numéro, verrouille, calcule l'empreinte
    et place la facture dans la file d'attente de clearance DGI.
    """
    invoice = session.get(Invoice, invoice_id)
    if not invoice:
        raise ValueError("Facture introuvable")

    validate_transition(invoice.status, InvoiceStatus.VALIDATED)

    stmt = select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id)
    lines = session.exec(stmt).all()
    if not lines:
        raise ValueError("Impossible de valider une facture sans lignes")

    invoice_number = next_invoice_number(session, str(invoice.company_id), invoice.fiscal_year)
    invoice.invoice_number = invoice_number
    invoice.status = InvoiceStatus.VALIDATED
    invoice.is_locked = True
    invoice.validated_at = datetime.now(timezone.utc)
    invoice.validated_by = user_id
    session.add(invoice)
    session.flush()

    # Calcul de l'empreinte SHA-256 sur le XML UBL 2.1
    try:
        client = session.get(Client, invoice.client_id)
        company = session.get(Company, invoice.company_id)
        from app.services.xml.ubl_generator import generate_ubl_invoice
        xml_bytes = generate_ubl_invoice(invoice, lines, company, client)
        invoice.hash_sha256 = compute_hash(xml_bytes)
        invoice.hash_algorithm = "sha256"
        session.add(invoice)
        session.flush()
    except Exception:
        pass  # Le hash est optionnel — n'empêche pas la validation

    # File d'attente de clearance DGI
    try:
        from app.services.clearance_queue import enqueue
        enqueue(invoice_id, str(invoice.company_id), session)
    except Exception:
        pass

    audit_log(
        session, str(invoice.company_id), "invoice", str(invoice.id),
        "validated", user_id=user_id,
        new_values=json.dumps({"invoice_number": invoice_number}),
    )
    return invoice
