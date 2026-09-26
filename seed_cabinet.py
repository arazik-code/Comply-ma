"""
Seed script — creates one fake cabinet + 3 client companies for demo.

Client 1 (Clean):       Complete data, valid ICE, sequential numbering
Client 2 (Numbering Gaps): Has numbering gaps and missing fields
Client 3 (Invalid ICE):    Invalid ICE format, missing IF/RC
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import engine, init_db
from app.models.cabinet import Cabinet, ClientCompany
from app.models.user import User
from app.models.company import Company
from app.models.client import Client
from app.models.invoice import Invoice, InvoiceLine
from app.models.tva import TVARate
from app.services.auth import hash_password
from app.services.data_quality.ice_validator import generate_ice
from sqlmodel import Session
from datetime import datetime, timezone
from decimal import Decimal
import uuid


def seed():
    init_db()
    with Session(engine) as session:
        # ── Cabinet ────────────────────────────────────────────────
        cabinet_ice = generate_ice("1234567890123")
        cabinet = Cabinet(
            id="cab_demo",
            name="Cabinet Benali & Associés",
            ice=cabinet_ice,
            address="123 Avenue Mohammed V",
            city="Casablanca",
            phone="+212 5 22 00 00 00",
            email="contact@benali-cabinet.ma",
            brand_name="Benali Compta",
            brand_color="#1a3a5c",
        )
        session.add(cabinet)

        # ── Cabinet admin user ─────────────────────────────────────
        admin = User(
            id="user_cab_admin",
            company_id="cab_demo",
            username="admin",
            hashed_password=hash_password("admin123"),
            display_name="Admin Cabinet",
            role="cabinet_admin",
        )
        session.add(admin)

        # ═══════════════════════════════════════════════════════════
        # CLIENT 1: CLEAN — Everything correct
        # ═══════════════════════════════════════════════════════════
        client1_id = uuid.uuid4().hex
        client1_db = f"cabinets/cab_demo/clients/{client1_id}.db"
        client1_ice = generate_ice("1111111111111")
        cc1 = ClientCompany(
            id=client1_id, cabinet_id="cab_demo",
            company_name="Boulangerie Al Fassi",
            ice=client1_ice,  # Valid ICE
            rc="12345", if_number="123456",
            db_path=client1_db, status="active",
            turnover_tier="TPE", dgi_deadline="2027-01",
            compliance_score=95, compliance_grade="A",
            invoice_count=5, client_count=3,
        )
        session.add(cc1)

        # Seed clean invoices for client 1
        for i in range(1, 6):
            inv = Invoice(
                id=f"inv_clean_{i}", company_id=client1_id,
                invoice_number=f"F{i:09d}/2025", fiscal_year=2025,
                invoice_date=datetime(2025, i, 15, tzinfo=timezone.utc),
                client_id=f"cli_clean_{i}", status="validated",
                total_ht=Decimal("1000.00"), total_tva=Decimal("200.00"),
                total_ttc=Decimal("1200.00"),
            )
            session.add(inv)

        # ═══════════════════════════════════════════════════════════
        # CLIENT 2: NUMBERING GAPS — Missing numbers in sequence
        # ═══════════════════════════════════════════════════════════
        client2_id = uuid.uuid4().hex
        client2_db = f"cabinets/cab_demo/clients/{client2_id}.db"
        client2_ice = generate_ice("2222222222222")
        cc2 = ClientCompany(
            id=client2_id, cabinet_id="cab_demo",
            company_name="Électronique Plus",
            ice=client2_ice,
            rc="67890", if_number="654321",
            db_path=client2_db, status="active",
            turnover_tier="PME", dgi_deadline="2027-01",
            compliance_score=60, compliance_grade="C",
            invoice_count=4, client_count=2,
        )
        session.add(cc2)

        # Invoices with GAPS: F001, F002, F004 (missing F003), F005
        for i, seq in enumerate([1, 2, 4, 5], 1):
            inv = Invoice(
                id=f"inv_gap_{i}", company_id=client2_id,
                invoice_number=f"F{seq:09d}/2025", fiscal_year=2025,
                invoice_date=datetime(2025, i, 15, tzinfo=timezone.utc),
                client_id=f"cli_gap_{i}", status="validated",
                total_ht=Decimal("500.00"), total_tva=Decimal("90.00"),
                total_ttc=Decimal("590.00"),
            )
            session.add(inv)

        # ═══════════════════════════════════════════════════════════
        # CLIENT 3: INVALID ICE — Bad ICE, missing IF/RC
        # ═══════════════════════════════════════════════════════════
        client3_id = uuid.uuid4().hex
        client3_db = f"cabinets/cab_demo/clients/{client3_id}.db"
        cc3 = ClientCompany(
            id=client3_id, cabinet_id="cab_demo",
            company_name="Transport Rapide",
            ice="12345",  # INVALID — only 5 digits
            rc="", if_number="",  # MISSING
            db_path=client3_db, status="active",
            turnover_tier="TPE", dgi_deadline="2027-01",
            compliance_score=25, compliance_grade="D",
            invoice_count=3, client_count=1,
        )
        session.add(cc3)

        for i in range(1, 4):
            inv = Invoice(
                id=f"inv_bad_{i}", company_id=client3_id,
                invoice_number=f"F{i:09d}/2025", fiscal_year=2025,
                invoice_date=datetime(2025, i, 15, tzinfo=timezone.utc),
                client_id=f"cli_bad_{i}", status="validated",
                total_ht=Decimal("750.00"), total_tva=Decimal("135.00"),
                total_ttc=Decimal("885.00"),
            )
            session.add(inv)

        session.commit()
        print("✓ Cabinet demo created: Cabinet Benali & Associés")
        print("  Client 1: Boulangerie Al Fassi (CLEAN — score 95)")
        print("  Client 2: Électronique Plus (GAPS — score 60)")
        print("  Client 3: Transport Rapide (BAD ICE — score 25)")
        print()
        print("  Login: admin / admin123")


if __name__ == "__main__":
    seed()
