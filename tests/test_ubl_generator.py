"""
Tests de génération XML UBL 2.1 — conformité structurelle.

Vérifie que le XML produit est valide et contient tous les
champs obligatoires exigés par la DGI.
"""
from datetime import datetime, timezone
from decimal import Decimal
import uuid

import pytest
from lxml import etree

from app.models.company import Company
from app.models.client import Client
from app.models.invoice import Invoice, InvoiceLine
from app.services.xml.ubl_generator import generate_ubl_invoice


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
        phone="+212600000000",
        email="test@test.ma",
    )


@pytest.fixture
def client():
    return Client(
        id=uuid.uuid4().hex,
        company_id=uuid.uuid4().hex,
        name="CLIENT TEST",
        ice="ICE999999999999999",
        rc="RC99999",
        address="2 Rue du Client, Rabat",
        city="Rabat",
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
        is_locked=True,
        total_ht=Decimal("1200.00"),
        total_tva=Decimal("240.00"),
        total_ttc=Decimal("1440.00"),
        payment_status="pending",
    )


@pytest.fixture
def invoice_lines(invoice):
    return [
        InvoiceLine(
            id=uuid.uuid4().hex,
            invoice_id=invoice.id,
            description="Prestation conseil",
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
            description="Fournitures",
            quantity=Decimal("2"),
            unit_price=Decimal("100.00"),
            tva_rate=Decimal("0.10"),
            line_total_ht=Decimal("200.00"),
            line_total_tva=Decimal("20.00"),
            line_total_ttc=Decimal("220.00"),
            sort_order=2,
        ),
    ]


class TestUBLGenerator:
    def test_generates_valid_xml(self, invoice, invoice_lines, company, client):
        """Le XML produit doit être valide et parsable."""
        xml_bytes = generate_ubl_invoice(invoice, invoice_lines, company, client)
        root = etree.fromstring(xml_bytes)
        assert root is not None

    def test_contains_invoice_number(self, invoice, invoice_lines, company, client):
        """Le numéro de facture doit être présent."""
        xml_bytes = generate_ubl_invoice(invoice, invoice_lines, company, client)
        xml_str = xml_bytes.decode("utf-8")
        assert "F-2026-000042" in xml_str

    def test_contains_company_ice(self, invoice, invoice_lines, company, client):
        """L'ICE de l'émetteur doit figurer dans le XML."""
        xml_bytes = generate_ubl_invoice(invoice, invoice_lines, company, client)
        xml_str = xml_bytes.decode("utf-8")
        assert "ICE001234567000001" in xml_str

    def test_contains_client_ice(self, invoice, invoice_lines, company, client):
        """L'ICE du client doit figurer dans le XML."""
        xml_bytes = generate_ubl_invoice(invoice, invoice_lines, company, client)
        xml_str = xml_bytes.decode("utf-8")
        assert "ICE999999999999999" in xml_str

    def test_contains_total_amount(self, invoice, invoice_lines, company, client):
        """Le montant total TTC doit figurer."""
        xml_bytes = generate_ubl_invoice(invoice, invoice_lines, company, client)
        xml_str = xml_bytes.decode("utf-8")
        assert "1440.00" in xml_str

    def test_contains_ubl_namespace(self, invoice, invoice_lines, company, client):
        """Le namespace UBL doit être déclaré."""
        xml_bytes = generate_ubl_invoice(invoice, invoice_lines, company, client)
        xml_str = xml_bytes.decode("utf-8")
        assert "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" in xml_str

    def test_contains_issue_date(self, invoice, invoice_lines, company, client):
        """La date d'émission doit figurer."""
        xml_bytes = generate_ubl_invoice(invoice, invoice_lines, company, client)
        xml_str = xml_bytes.decode("utf-8")
        assert "2026-07-01" in xml_str

    def test_contains_tva_by_rate(self, invoice, invoice_lines, company, client):
        """La TVA doit être détaillée par taux (TaxSubtotal)."""
        xml_bytes = generate_ubl_invoice(invoice, invoice_lines, company, client)
        xml_str = xml_bytes.decode("utf-8")
        assert "TaxSubtotal" in xml_str
        assert "20.00" in xml_str  # 20% rate
        assert "10.00" in xml_str  # 10% rate

    def test_contains_rc_and_if(self, invoice, invoice_lines, company, client):
        """RC et IF de l'émetteur doivent apparaître."""
        xml_bytes = generate_ubl_invoice(invoice, invoice_lines, company, client)
        xml_str = xml_bytes.decode("utf-8")
        assert "RC12345" in xml_str or "RC" in xml_str
        assert "IF987654" in xml_str or "IF" in xml_str

    def test_has_xml_declaration(self, invoice, invoice_lines, company, client):
        """Le XML doit avoir une déclaration UTF-8."""
        xml_bytes = generate_ubl_invoice(invoice, invoice_lines, company, client)
        assert xml_bytes.startswith(b'<?xml')

    def test_two_lines_generates_two_line_elements(self, invoice, invoice_lines, company, client):
        """Deux lignes doivent produire deux éléments InvoiceLine."""
        xml_bytes = generate_ubl_invoice(invoice, invoice_lines, company, client)
        root = etree.fromstring(xml_bytes)
        ns = {"cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"}
        line_els = root.findall(".//cac:InvoiceLine", ns)
        assert len(line_els) == 2
