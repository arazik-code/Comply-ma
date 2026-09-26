"""
Tests du générateur PDF.
"""
from datetime import datetime, timezone
from decimal import Decimal
import uuid

import pytest

from app.models.company import Company
from app.models.client import Client
from app.models.invoice import Invoice, InvoiceLine
from app.services.pdf_generator import generate_invoice_pdf, _render_invoice_html


@pytest.fixture
def company():
    return Company(
        id=uuid.uuid4().hex,
        company_name="TEST SARL",
        address="1 Rue Test, Casablanca",
        city="Casablanca",
        rc="RC12345",
        if_number="IF987654",
        ice="ICE001234567000001",
        tva_regime="assujetti",
    )


@pytest.fixture
def client():
    return Client(
        id=uuid.uuid4().hex,
        company_id=uuid.uuid4().hex,
        name="CLIENT TEST",
        ice="ICE999999999999999",
    )


@pytest.fixture
def invoice(company, client):
    return Invoice(
        id=uuid.uuid4().hex,
        company_id=company.id,
        invoice_number="F-2026-000001",
        fiscal_year=2026,
        invoice_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        client_id=client.id,
        status="validated",
        total_ht=Decimal("1000.00"),
        total_tva=Decimal("200.00"),
        total_ttc=Decimal("1200.00"),
        payment_status="pending",
    )


@pytest.fixture
def lines(invoice):
    return [
        InvoiceLine(
            id=uuid.uuid4().hex,
            invoice_id=invoice.id,
            description="Prestation",
            quantity=Decimal("1"),
            unit_price=Decimal("1000.00"),
            tva_rate=Decimal("0.20"),
            line_total_ht=Decimal("1000.00"),
            line_total_tva=Decimal("200.00"),
            line_total_ttc=Decimal("1200.00"),
            sort_order=1,
        ),
    ]


class TestPDFGenerator:
    def test_html_contains_invoice_number(self, invoice, lines, company, client):
        html = _render_invoice_html(invoice, lines, company, client)
        assert "F-2026-000001" in html

    def test_html_contains_watermark(self, invoice, lines, company, client):
        html = _render_invoice_html(invoice, lines, company, client)
        assert "L'ORIGINAL EST LE FICHIER XML" in html

    def test_html_contains_company_name(self, invoice, lines, company, client):
        html = _render_invoice_html(invoice, lines, company, client)
        assert "TEST SARL" in html

    def test_html_contains_client_name(self, invoice, lines, company, client):
        html = _render_invoice_html(invoice, lines, company, client)
        assert "CLIENT TEST" in html

    def test_html_contains_totals(self, invoice, lines, company, client):
        html = _render_invoice_html(invoice, lines, company, client)
        assert "1000.00" in html
        assert "1200.00" in html

    def test_generate_invoice_pdf_returns_bytes(self, invoice, lines, company, client):
        result = generate_invoice_pdf(invoice, lines, company, client)
        assert isinstance(result, bytes)
        assert len(result) > 0
