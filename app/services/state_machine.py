"""
Machine à états des factures — conforme DGI Maroc.

Flux DGI :
  draft -> validated (verrouillage utilisateur)
  validated -> submitted -> cleared -> sent -> archived
  validated -> cancelled
  submitted -> rejected (par DGI)
  rejected -> draft (correction et renvoi)
  draft -> cancelled

Une fois 'validated', la facture est verrouillée (is_locked=True).
Toute correction passe par un avoir (CreditNote).
"""
from enum import Enum


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    SUBMITTED = "submitted"
    CLEARED = "cleared"
    SENT = "sent"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


TRANSITIONS = {
    InvoiceStatus.DRAFT: {InvoiceStatus.VALIDATED, InvoiceStatus.CANCELLED},
    InvoiceStatus.VALIDATED: {InvoiceStatus.SUBMITTED, InvoiceStatus.SENT, InvoiceStatus.CANCELLED},
    InvoiceStatus.SUBMITTED: {InvoiceStatus.CLEARED, InvoiceStatus.REJECTED},
    InvoiceStatus.CLEARED: {InvoiceStatus.SENT},
    InvoiceStatus.SENT: {InvoiceStatus.ARCHIVED},
    InvoiceStatus.REJECTED: {InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED},
    InvoiceStatus.ARCHIVED: set(),
    InvoiceStatus.CANCELLED: set(),
}


class InvalidTransitionError(ValueError):
    """Levée quand une transition d'état n'est pas autorisée."""
    pass


def validate_transition(current: InvoiceStatus, target: InvoiceStatus):
    """Vérifie que la transition current -> target est légale."""
    allowed = TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidTransitionError(
            f"Transition interdite : {current.value} -> {target.value}. "
            f"Transitions autorisées depuis {current.value} : "
            f"{', '.join(s.value for s in allowed) if allowed else 'aucune'}"
        )
