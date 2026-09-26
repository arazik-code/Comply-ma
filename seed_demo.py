"""
Script de démonstration — crée des données initiales pour tester COMPLY-MA.

Usage :
    python seed_demo.py

Ajoute dans la base de données :
    - Une entreprise « TEST SARL »
    - Les 4 taux de TVA légaux (20 % / 14 % / 10 % / 7 %)
    - Un utilisateur owner (username: owner, password: password)
    - 5 clients fictifs
    - 5 produits fictifs
    - 2 factures (1 validée + 1 brouillon) avec lignes et un paiement
"""
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sqlmodel import SQLModel, create_engine, Session

from app.config import settings
from app.models.company import Company
from app.models.user import User
from app.models.tva import TVARate
from app.models.client import Client
from app.models.product import Product
from app.models.invoice import Invoice, InvoiceLine
from app.models.payment import Payment
from app.models.numbering import NumberingSequence
from app.models.audit import AuditLog
from app.models.clearance import ClearanceRecord
from app.services.auth import hash_password
from app.services.invoice_service import create_invoice_draft, add_line_to_invoice, validate_invoice


def _seed():
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        # ── Entreprise ──────────────────────────────────────────────
        company = Company(
            company_name="TEST SARL",
            address="123, Avenue Mohammed V",
            city="Casablanca",
            rc="RC-12345",
            if_number="IF-98765",
            ice="ICE-555555555555555",
            tva_regime="assujetti",
            phone="+212 5XX-XXXXXX",
            email="contact@test-sarl.ma",
            is_setup_complete=True,
        )
        session.add(company)
        session.flush()

        # ── Taux de TVA ─────────────────────────────────────────────
        tva_rates_data = [
            (Decimal("0.20"), "TVA 20% (Standard)"),
            (Decimal("0.14"), "TVA 14% (Réduit)"),
            (Decimal("0.10"), "TVA 10% (Réduit)"),
            (Decimal("0.07"), "TVA 7% (Réduit)"),
        ]
        tva_rates = []
        for rate, label in tva_rates_data:
            tr = TVARate(rate=rate, label=label)
            session.add(tr)
            tva_rates.append(tr)
        session.flush()

        # ── Utilisateur owner ───────────────────────────────────────
        owner = User(
            company_id=company.id,
            username="owner",
            hashed_password=hash_password("password"),
            display_name="Administrateur",
            role="owner",
        )
        session.add(owner)
        session.flush()

        # ── Clients ─────────────────────────────────────────────────
        clients_data = [
            ("Bazar Al Amane", "ICE-111111111111111", "RC-1111", "IF-1111", "25, Rue de la Liberté", "Casablanca", "+212 6XX-111111", "contact@alaman.ma"),
            ("Société Atlas", "ICE-222222222222222", "RC-2222", "IF-2222", "12, Boulevard Hassan II", "Rabat", "+212 6XX-222222", "info@atlas.ma"),
            ("Épicerie du Sud", "ICE-333333333333333", "RC-3333", "IF-3333", "8, Avenue Med V", "Marrakech", "+212 6XX-333333", "contact@sud.ma"),
            ("Tech Solutions", "ICE-444444444444444", "RC-4444", "IF-4444", "45, Rue Oued El Makhazine", "Tanger", "+212 6XX-444444", "info@techsolutions.ma"),
            ("Ferme Agadir", "ICE-555555555555555", "RC-5555", "IF-5555", "Km 12, Route d'Essaouira", "Agadir", "+212 6XX-555555", "ferme@agadir.ma"),
        ]
        clients = []
        for name, ice, rc, ifn, addr, city, phone, email in clients_data:
            c = Client(
                company_id=company.id, name=name, ice=ice, rc=rc,
                if_number=ifn, address=addr, city=city,
                phone=phone, email=email,
            )
            session.add(c)
            clients.append(c)
        session.flush()

        # ── Produits ────────────────────────────────────────────────
        products_data = [
            ("Ordinateur portable Dell", "PC portable Dell Latitude 3440", Decimal("8500.00"), tva_rates[0].id, "pièce", "REF-DELL-001"),
            ("Clavier mécanique", "Clavier MK Redragon K552", Decimal("350.00"), tva_rates[1].id, "pièce", "REF-KEY-002"),
            ("Service de conseil", "Prestation de conseil en transformation digitale (HT/jour)", Decimal("2500.00"), tva_rates[0].id, "jour", "REF-CONS-003"),
            ("Abonnement SaaS", "Forfait mensuel cloud (par utilisateur)", Decimal("150.00"), tva_rates[1].id, "mois", "REF-SAAS-004"),
            ("Transport logistique", "Frais de transport intra-ville (course)", Decimal("200.00"), tva_rates[2].id, "course", "REF-TRANS-005"),
        ]
        products = []
        for name, desc, price, tva_id, unit, ref in products_data:
            p = Product(
                company_id=company.id, name=name, description=desc,
                unit_price=price, tva_rate_id=tva_id, unit=unit, reference=ref,
            )
            session.add(p)
            products.append(p)
        session.flush()

        # ── Facture 1 : validée avec 3 lignes + paiement ──────────
        inv1 = create_invoice_draft(session, company.id, clients[0].id,
                                    datetime(2026, 6, 15, tzinfo=timezone.utc),
                                    notes="Première facture de démo", user_id=owner.id)
        # Ligne 1 : 2 ordinateurs
        add_line_to_invoice(session, inv1.id, products[0].name, Decimal("2"),
                            products[0].unit_price, Decimal("0.20"), products[0].id, 0)
        # Ligne 2 : 3 claviers
        add_line_to_invoice(session, inv1.id, products[1].name, Decimal("3"),
                            products[1].unit_price, Decimal("0.14"), products[1].id, 1)
        # Ligne 3 : 5 jours de conseil
        add_line_to_invoice(session, inv1.id, products[2].name, Decimal("5"),
                            products[2].unit_price, Decimal("0.20"), products[2].id, 2)
        validate_invoice(session, inv1.id, owner.id)
        # Paiement
        pmt = Payment(
            invoice_id=inv1.id,
            amount=inv1.total_ttc,
            payment_date=datetime(2026, 6, 20, tzinfo=timezone.utc),
            payment_method="virement",
            reference="VIRE-2026-001",
        )
        session.add(pmt)
        inv1.payment_status = "paid"

        # ── Facture 2 : brouillon avec 2 lignes ────────────────────
        inv2 = create_invoice_draft(session, company.id, clients[2].id,
                                    datetime(2026, 7, 1, tzinfo=timezone.utc),
                                    notes="Devis en cours", user_id=owner.id)
        add_line_to_invoice(session, inv2.id, products[3].name, Decimal("12"),
                            products[3].unit_price, Decimal("0.14"), products[3].id, 0)
        add_line_to_invoice(session, inv2.id, products[4].name, Decimal("4"),
                            products[4].unit_price, Decimal("0.10"), products[4].id, 1)

        company_name = company.company_name
        session.commit()

    print("Données de démonstration créées avec succès !")
    print(f"  Entreprise : {company_name}")
    print(f"  Propriétaire : owner / password")
    print(f"  Clients : {len(clients)}")
    print(f"  Produits : {len(products)}")
    print(f"  Factures : 1 validée (F-2026-000001) + 1 brouillon")
    session.close()


if __name__ == "__main__":
    _seed()
