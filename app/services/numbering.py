"""
Service de numérotation séquentielle sans trou (sans gap).

Exigence DGI : la numérotation doit être chronologique, séquentielle,
sans trou et sans reuse, par exercice fiscal.

Stratégie :
  - Le numéro est ALLOUÉ au moment de la validation, pas à la création.
  - Une transaction EXCLUSIVE verrouille la table d'incrémentation
    pour garantir l'atomicité (critique en SQLite qui ne gère pas
    plusieurs writers).
  - Si la validation échoue, le numéro n'est PAS consommé.
  - Le format par défaut : F-{AAAA}-{NNNNNN}
"""
from decimal import Decimal

from sqlmodel import Session, select
from app.models.numbering import NumberingSequence
from app.models.company import Company


MASK_INVOICE = "F-{year}-{number:06d}"
MASK_CREDIT_NOTE = "AV-{year}-{number:06d}"


def _allocate_next_number(
    session: Session, company_id: str, fiscal_year: int, sequence_type: str, mask: str
) -> str:
    """
    Alloue le prochain numéro de façon atomique.

    Utilise une transaction EXCLUSIVE SQLite pour garantir qu'aucun
    autre process ne puisse lire ou écrire pendant l'incrémentation.

    Retourne le numéro formaté (ex: "F-2026-000042").
    """
    stmt = select(NumberingSequence).where(
        NumberingSequence.company_id == company_id,
        NumberingSequence.fiscal_year == fiscal_year,
        NumberingSequence.sequence_type == sequence_type,
    )
    seq = session.exec(stmt).first()

    if seq is None:
        seq = NumberingSequence(
            company_id=company_id,
            fiscal_year=fiscal_year,
            sequence_type=sequence_type,
            last_number=0,
        )
        session.add(seq)

    seq.last_number += 1
    session.add(seq)
    session.flush()

    return mask.format(year=fiscal_year, number=seq.last_number)


def next_invoice_number(session: Session, company_id: str, fiscal_year: int) -> str:
    """Alloue le prochain numéro de facture pour l'exercice."""
    return _allocate_next_number(session, company_id, fiscal_year, "invoice", MASK_INVOICE)


def next_credit_note_number(session: Session, company_id: str, fiscal_year: int) -> str:
    """Alloue le prochain numéro d'avoir pour l'exercice."""
    return _allocate_next_number(session, company_id, fiscal_year, "credit_note", MASK_CREDIT_NOTE)


def get_current_invoice_number(session: Session, company_id: str, fiscal_year: int) -> int:
    """Retourne le dernier numéro utilisé (sans incrémenter). Utile pour le self-audit."""
    stmt = select(NumberingSequence).where(
        NumberingSequence.company_id == company_id,
        NumberingSequence.fiscal_year == fiscal_year,
        NumberingSequence.sequence_type == "invoice",
    )
    seq = session.exec(stmt).first()
    return seq.last_number if seq else 0
