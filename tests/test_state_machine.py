"""
Tests de la machine à états des factures.

Conformité DGI : une fois validée, une facture est immuable.
Seul un avoir permet de la corriger.
"""
import pytest

from app.services.state_machine import (
    InvoiceStatus,
    validate_transition,
    InvalidTransitionError,
)


class TestInvoiceStateMachine:
    """Vérifie les transitions autorisées et interdites."""

    def test_draft_to_validated(self):
        """Draft -> Validated : transition autorisée."""
        validate_transition(InvoiceStatus.DRAFT, InvoiceStatus.VALIDATED)

    def test_draft_to_cancelled(self):
        """Draft -> Cancelled : transition autorisée."""
        validate_transition(InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)

    def test_validated_to_sent(self):
        """Validated -> Sent : transition autorisée."""
        validate_transition(InvoiceStatus.VALIDATED, InvoiceStatus.SENT)

    def test_validated_to_cancelled(self):
        """Validated -> Cancelled : transition autorisée (exceptionnel)."""
        validate_transition(InvoiceStatus.VALIDATED, InvoiceStatus.CANCELLED)

    def test_sent_to_archived(self):
        """Sent -> Archived : transition autorisée."""
        validate_transition(InvoiceStatus.SENT, InvoiceStatus.ARCHIVED)

    def test_draft_to_archived_forbidden(self):
        """Draft -> Archived : INTERDIT."""
        with pytest.raises(InvalidTransitionError):
            validate_transition(InvoiceStatus.DRAFT, InvoiceStatus.ARCHIVED)

    def test_draft_to_draft_forbidden(self):
        """Draft -> Draft : INTERDIT (pas d'auto-transition)."""
        with pytest.raises(InvalidTransitionError):
            validate_transition(InvoiceStatus.DRAFT, InvoiceStatus.DRAFT)

    def test_archived_to_anything_forbidden(self):
        """Archived -> * : tout est INTERDIT (état terminal)."""
        for target in InvoiceStatus:
            if target != InvoiceStatus.ARCHIVED:
                with pytest.raises(InvalidTransitionError):
                    validate_transition(InvoiceStatus.ARCHIVED, target)

    def test_cancelled_to_anything_forbidden(self):
        """Cancelled -> * : tout est INTERDIT (état terminal)."""
        for target in InvoiceStatus:
            if target != InvoiceStatus.CANCELLED:
                with pytest.raises(InvalidTransitionError):
                    validate_transition(InvoiceStatus.CANCELLED, target)

    def test_validated_to_draft_forbidden(self):
        """Validated -> Draft : INTERDIT (immuable après validation)."""
        with pytest.raises(InvalidTransitionError):
            validate_transition(InvoiceStatus.VALIDATED, InvoiceStatus.DRAFT)
