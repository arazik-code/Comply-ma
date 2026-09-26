"""
Tests du service métier de facturation (InvoiceService).

Teste le flux complet : création brouillon -> ajout lignes -> validation.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.client import Client
from app.models.invoice import Invoice, InvoiceLine
from app.services.state_machine import InvoiceStatus
from app.services.invoice_service import (
    create_invoice_draft,
    add_line_to_invoice,
    validate_invoice,
)


@pytest.fixture
def client(session, company_id, company) -> Client:
    c = Client(
        company_id=company.id,
        name="Client Test SARL",
        ice="ICE999999999999999",
        address="456 Avenue Test, Rabat",
        city="Rabat",
    )
    session.add(c)
    session.commit()
    return c


@pytest.fixture
def client_id(client) -> str:
    return str(client.id)


@pytest.fixture
def user_id() -> str:
    return str(uuid.uuid4())


class TestInvoiceCreation:
    """Création de factures en brouillon."""

    def test_create_draft(self, session, company_id, client_id, user_id):
        """Une facture draft doit être créée sans numéro."""
        inv = create_invoice_draft(
            session, company_id, client_id,
            invoice_date=datetime.now(timezone.utc),
            user_id=user_id,
        )
        assert inv.status == InvoiceStatus.DRAFT
        assert inv.invoice_number is None
        assert inv.is_locked is False
        assert inv.total_ht == Decimal("0.00")

    def test_draft_has_correct_fiscal_year(self, session, company_id, client_id, user_id):
        """L'exercice fiscal doit correspondre à l'année de la date."""
        inv = create_invoice_draft(
            session, company_id, client_id,
            invoice_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
            user_id=user_id,
        )
        assert inv.fiscal_year == 2026


class TestInvoiceLines:
    """Ajout de lignes aux factures."""

    def test_add_line_updates_totals(self, session, company_id, client_id, user_id):
        """Ajouter une ligne doit recalculer les totaux."""
        inv = create_invoice_draft(session, company_id, client_id, datetime.now(timezone.utc), user_id=user_id)
        add_line_to_invoice(
            session, str(inv.id),
            description="Prestation conseil",
            quantity=Decimal("1"),
            unit_price=Decimal("1000"),
            tva_rate=Decimal("0.20"),
        )
        session.refresh(inv)
        assert inv.total_ht == Decimal("1000.00")
        assert inv.total_tva == Decimal("200.00")
        assert inv.total_ttc == Decimal("1200.00")

    def test_multiple_lines(self, session, company_id, client_id, user_id):
        """Plusieurs lignes doivent être agrégées correctement."""
        inv = create_invoice_draft(session, company_id, client_id, datetime.now(timezone.utc), user_id=user_id)
        add_line_to_invoice(session, str(inv.id), "Ligne 1", Decimal("2"), Decimal("100"), Decimal("0.20"))
        add_line_to_invoice(session, str(inv.id), "Ligne 2", Decimal("1"), Decimal("50"), Decimal("0.14"))
        session.refresh(inv)
        assert inv.total_ht == Decimal("250.00")
        assert inv.total_tva == Decimal("47.00")  # 40 + 7
        assert inv.total_ttc == Decimal("297.00")


class TestInvoiceValidation:
    """Validation de factures (attribution du numéro, verrouillage)."""

    def test_validate_assigns_number(self, session, company_id, client_id, user_id):
        """La validation doit attribuer un numéro séquentiel."""
        inv = create_invoice_draft(session, company_id, client_id, datetime(2026, 7, 1, tzinfo=timezone.utc), user_id=user_id)
        add_line_to_invoice(session, str(inv.id), "Test", Decimal("1"), Decimal("100"), Decimal("0.20"))

        validated = validate_invoice(session, str(inv.id), user_id)
        assert validated.invoice_number == "F-2026-000001"
        assert validated.status == InvoiceStatus.VALIDATED
        assert validated.is_locked is True

    def test_cannot_validate_empty_invoice(self, session, company_id, client_id, user_id):
        """Une facture sans ligne ne peut pas être validée."""
        inv = create_invoice_draft(session, company_id, client_id, datetime.now(timezone.utc), user_id=user_id)
        with pytest.raises(ValueError, match="sans lignes"):
            validate_invoice(session, str(inv.id), user_id)

    def test_sequential_numbers_on_validation(self, session, company_id, client_id, user_id):
        """Deux validations doivent produire des numéros séquentiels."""
        dt = datetime(2026, 7, 1, tzinfo=timezone.utc)
        inv1 = create_invoice_draft(session, company_id, client_id, dt, user_id=user_id)
        add_line_to_invoice(session, str(inv1.id), "Test", Decimal("1"), Decimal("100"), Decimal("0.20"))
        v1 = validate_invoice(session, str(inv1.id), user_id)

        inv2 = create_invoice_draft(session, company_id, client_id, dt, user_id=user_id)
        add_line_to_invoice(session, str(inv2.id), "Test", Decimal("1"), Decimal("100"), Decimal("0.20"))
        v2 = validate_invoice(session, str(inv2.id), user_id)

        assert v1.invoice_number == "F-2026-000001"
        assert v2.invoice_number == "F-2026-000002"

    def test_cannot_add_line_to_validated(self, session, company_id, client_id, user_id):
        """Ajouter une ligne à une facture validée doit échouer."""
        inv = create_invoice_draft(session, company_id, client_id, datetime.now(timezone.utc), user_id=user_id)
        add_line_to_invoice(session, str(inv.id), "Test", Decimal("1"), Decimal("100"), Decimal("0.20"))
        validate_invoice(session, str(inv.id), user_id)

        with pytest.raises(ValueError, match="verrouillée"):
            add_line_to_invoice(session, str(inv.id), "Another", Decimal("1"), Decimal("50"), Decimal("0.20"))
