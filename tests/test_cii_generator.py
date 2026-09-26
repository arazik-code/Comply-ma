"""
Tests de génération XML CII.
"""
from datetime import datetime, timezone
from decimal import Decimal
import uuid

import pytest
from lxml import etree

from app.models.company import Company
from app.models.client import Client
from app.models.invoice import Invoice, InvoiceLine
from app.services.xml.cii_generator import generate_cii_invoice


@pytest.fixture
def company():
    return Company(
        id=uuid.uuid4().hex,
        company_name="TEST SARL",
        address="1 Rue de la Test, Casablanca",
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
        invoice_number="F-2026-000042",
        fiscal_year=2026,
        invoice_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        client_id=client.id,
        status="validated",
        total_ht=Decimal("1200.00"),
        total_tva=Decimal("220.00"),
        total_ttc=Decimal("1420.00"),
    )


@pytest.fixture
def invoice_lines(invoice):
    return [
        InvoiceLine(
            id=uuid.uuid4().hex,
            invoice_id=invoice.id,
            description="Consulting",
            quantity=Decimal("1"),
            unit_price=Decimal("1000.00"),
            tva_rate=Decimal("0.20"),
            line_total_ht=Decimal("1000.00"),
            line_total_tva=Decimal("200.00"),
            line_total_ttc=Decimal("1200.00"),
            sort_order=1,
        ),
        InvoiceLine(
            id=uuid.uuid4().hex,
            invoice_id=invoice.id,
            description="Supplies",
            quantity=Decimal("2"),
            unit_price=Decimal("100.00"),
            tva_rate=Decimal("0.10"),
            line_total_ht=Decimal("200.00"),
            line_total_tva=Decimal("20.00"),
            line_total_ttc=Decimal("220.00"),
            sort_order=2,
        ),
    ]


class TestCIIGenerator:
    def test_generates_valid_xml(self, invoice, invoice_lines, company, client):
        xml_bytes = generate_cii_invoice(invoice, invoice_lines, company, client)
        root = etree.fromstring(xml_bytes)
        assert root is not None

    def test_contains_invoice_number(self, invoice, invoice_lines, company, client):
        xml_bytes = generate_cii_invoice(invoice, invoice_lines, company, client)
        assert b"F-2026-000042" in xml_bytes

    def test_contains_company_ice(self, invoice, invoice_lines, company, client):
        xml_bytes = generate_cii_invoice(invoice, invoice_lines, company, client)
        assert b"ICE001234567000001" in xml_bytes

    def test_contains_total(self, invoice, invoice_lines, company, client):
        xml_bytes = generate_cii_invoice(invoice, invoice_lines, company, client)
        assert b"1420.00" in xml_bytes
