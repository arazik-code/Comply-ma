"""
Seed INVESTOR DEMO — données réalistes prêtes pour l'enregistrement vidéo.

Usage :
    python seed_investor_demo.py            # remplace comply-ma.db
    python seed_investor_demo.py --keep     # ajoute à la base existante

Crée :
    - Atlas Digital Solutions SARL (entreprise crédible, ICE valide modulo-97)
    - 8 clients marocains réalistes (ICE valides)
    - 10 produits/services avec vrais taux TVA marocains
    - ~40 factures sur 8 mois d'historique (janv → août 2026) :
        * cycle de vie complet : draft → validated → sent → archived
        * statuts de paiement variés : paid / partial / pending / overdue
        * TVA multi-taux (20/14/10/7)
    - 2 avoirs (AV-2026) liés à des factures réelles
    - 3 bons de commande + rapprochement
    - 2 factures fournisseurs importées
    - Journal d'audit cohérent (généré par les services)

    Login : owner / password
"""
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

if "--keep" not in sys.argv:
    db = Path("comply-ma.db")
    if db.exists():
        db.unlink()
        print("→ ancienne base supprimée")

from sqlmodel import SQLModel, create_engine, Session, select

from app.config import settings
from app.models.company import Company
from app.models.user import User
from app.models.tva import TVARate
from app.models.client import Client
from app.models.product import Product
from app.models.invoice import Invoice, InvoiceLine
from app.models.payment import Payment
from app.models.credit_note import CreditNote, CreditNoteLine
from app.models.purchase_order import PurchaseOrder
from app.services.auth import hash_password
from app.services.invoice_service import (
    create_invoice_draft, add_line_to_invoice, validate_invoice,
)
from app.services.credit_note_service import (
    create_credit_note_draft, add_line_to_credit_note, validate_credit_note,
)
from app.services.data_quality.ice_validator import generate_ice
from app.services.state_machine import InvoiceStatus

# ════════════════════════════════════════════════════════════════
# Données
# ════════════════════════════════════════════════════════════════

COMPANY = dict(
    company_name="Atlas Digital Solutions",
    address="45, Boulevard d'Anfa, Quartier Gauthier",
    city="Casablanca",
    rc="RC-458921",
    if_number="IF-40751293",
    ice=generate_ice("0017894560000"),   # ICE valide (clé 97)
    tva_regime="assujetti",
    phone="+212 522 44 87 90",
    email="contact@atlasdigital.ma",
    is_setup_complete=True,
)

# (nom, ICE base 13, ville, adresse, tel, email)
CLIENTS = [
    ("Marjane Holding",           "0024587100000", "Casablanca", "Route de Rabat, Km 15",           "+212 522 98 76 00", "achats@marjane.ma"),
    ("OCP Group",                 "0031245800000", "Khouribga",  "BP 118, Zone Minière",            "+212 523 88 45 12", "procurement@ocpgroup.ma"),
    ("Royal Air Maroc",           "0045871200000", "Casablanca", "Aéroport Mohammed V, Terminal 1", "+212 522 91 20 00", "supply@ram.ma"),
    ("Auto Hall",                 "0058741200000", "Casablanca", "Bd Abdelmoumen, 212",             "+212 522 48 90 33", "it@autohall.ma"),
    ("Cooperative Al Baraka",     "0069854100000", "Fès",        "Route d'Immouzer, Douar Zitoune", "+212 535 62 14 78", "contact@albaraka.ma"),
    ("Clinique Ain Khalil",       "0074125800000", "Rabat",      "12, Avenue Ibn Sina, Agdal",      "+212 537 67 89 00", "admin@cliniqueak.ma"),
    ("Riad Dar Zellij",           "0085412300000", "Marrakech",  "1, Derb Sidi Bouloukat, Médina",  "+212 524 38 26 17", "manager@darzellij.ma"),
    ("TechnoPoint Distribution",  "0096741200000", "Tanger",     "Zone Franche Tanger Free Zone",   "+212 539 39 45 60", "ap@technopoint.ma"),
]

# (nom, description, prix HT, taux TVA, unité, réf)
PRODUCTS = [
    ("Licence ERP Cloud",        "Abonnement annuel plateforme ERP (par utilisateur)",      Decimal("4800.00"), "0.20", "an",    "SaaS-ERP-01"),
    ("Développement sur mesure", "Développement applicatif dédié (ingénieur/jour)",          Decimal("3200.00"), "0.20", "jour",  "SRV-DEV-02"),
    ("Conseil digital",          "Prestation de conseil en transformation numérique",        Decimal("4500.00"), "0.20", "jour",  "SRV-CON-03"),
    ("Maintenance IT mensuelle", "Forfait maintenance infrastructure (mensuel)",             Decimal("1850.00"), "0.20", "mois",  "SRV-MNT-04"),
    ("Formation utilisateurs",   "Session de formation certifiante (groupe, 2 jours)",       Decimal("6800.00"), "0.14", "session","SRV-FRM-05"),
    ("Audit sécurité",           "Audit de sécurité informatique + rapport (5 jours)",       Decimal("22500.00"),"0.20", "mission","SRV-AUD-06"),
    ("Serveur Dell PowerEdge",   "Serveur rack R450, 2×Xeon, 64 Go RAM, 2×1 To SSD",         Decimal("38500.00"),"0.20", "unité", "HW-SRV-07"),
    ("Licence antivirus",        "Protection endpoint entreprise (poste/an)",                Decimal("320.00"),  "0.20", "poste", "SaaS-AV-08"),
    ("Transport marchandises",   "Fret national hors grandes distances (par expédition)",    Decimal("900.00"),  "0.10", "voyage","LOG-TRP-09"),
    ("Location salle conférence","Salle équipée visioconférence, Casablanca (jour)",         Decimal("1500.00"), "0.07", "jour",  "LOG-SAL-10"),
]

Y = 2026

def _d(month: int, day: int) -> datetime:
    return datetime(Y, month, day, 10, 30, tzinfo=timezone.utc)


# ════════════════════════════════════════════════════════════════
# Seed
# ════════════════════════════════════════════════════════════════

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
import app.models  # noqa: F401 — enregistre TOUS les modèles dans les métadonnées
SQLModel.metadata.create_all(engine)

counters = {"paid": 0, "partial": 0, "pending": 0, "draft": 0}


def total_inv_rows(session, company_id):
    """Toutes les factures clients (hors fournisseurs) de la société."""
    return session.exec(
        select(Invoice).where(Invoice.company_id == company_id,
                              Invoice.is_supplier_invoice == False)
    ).all()

with Session(engine) as session:
    # ── Société ──────────────────────────────────────────────
    company = Company(**COMPANY)
    session.add(company); session.flush()

    owner = User(
        company_id=company.id, username="owner",
        hashed_password=hash_password("password"),
        display_name="Yasmine El Fassi", role="owner",
    )
    session.add(owner); session.flush()

    # ── Taux TVA ─────────────────────────────────────────────
    rates = {}
    for r, label in [
        (Decimal("0.20"), "TVA 20% (Standard)"),
        (Decimal("0.14"), "TVA 14% (Réduit)"),
        (Decimal("0.10"), "TVA 10% (Réduit)"),
        (Decimal("0.07"), "TVA 7% (Réduit)"),
    ]:
        tr = TVARate(rate=r, label=label)
        session.add(tr); session.flush()
        rates[str(r)] = tr

    # ── Clients ──────────────────────────────────────────────
    clients = {}
    for name, ice13, city, addr, phone, email in CLIENTS:
        c = Client(
            company_id=company.id, name=name, ice=generate_ice(ice13),
            rc=f"RC-{uuid.uuid4().hex[:6].upper()}", if_number=f"IF-{uuid.uuid4().hex[:8].upper()}",
            address=addr, city=city, phone=phone, email=email,
        )
        session.add(c); clients[name] = c
    session.flush()

    # ── Produits ─────────────────────────────────────────────
    products = {}
    for name, desc, price, rate, unit, ref in PRODUCTS:
        p = Product(
            company_id=company.id, name=name, description=desc,
            unit_price=price, tva_rate_id=rates[rate].id, unit=unit, reference=ref,
        )
        session.add(p); products[name] = p
    session.flush()

    # ── Générateur de facture ────────────────────────────────
    def make_invoice(num, client_name, month, day, items, status, payment=None,
                     pay_method="virement", pay_day=None, notes=""):
        """items: list of (product_name, qty) — utilise le prix produit."""
        inv = create_invoice_draft(
            session, company.id, clients[client_name].id,
            _d(month, day), notes or None, owner.id,
        )
        for i, (pname, qty) in enumerate(items):
            p = products[pname]
            rate = Decimal([x[3] for x in PRODUCTS if x[0] == pname][0])
            add_line_to_invoice(session, inv.id, pname, Decimal(str(qty)),
                                p.unit_price, rate, p.id, i)
        if status != "draft":
            validate_invoice(session, inv.id, owner.id)
        if status == "sent":
            inv.status = InvoiceStatus.SENT
        elif status == "archived":
            inv.status = InvoiceStatus.ARCHIVED
        session.add(inv)

        if payment:
            total = inv.total_ttc
            amount = {"paid": total, "partial": (total * Decimal("0.4")).quantize(Decimal("0.01"))}[payment]
            pmt = Payment(
                invoice_id=inv.id, amount=amount,
                payment_date=_d(pay_day[0], pay_day[1]) if pay_day else _d(month, min(day + 12, 28)),
                payment_method=pay_method,
                reference=f"{pay_method.upper()[:4]}-{Y}-{num:04d}",
            )
            session.add(pmt)
            inv.payment_status = "paid" if payment == "paid" else "partial"
            if payment == "paid":
                inv.payment_date = pmt.payment_date
        counters[status if status in counters else "pending"] += 1
        return inv

    # ── Historique de factures (39 factures, 8 mois) ────────
    plan = [
        # (client, mois, jour, [(produit, qté)...], statut, paiement)
        ("TechnoPoint Distribution", 1, 12, [("Serveur Dell PowerEdge", 2), ("Licence antivirus", 50)],  "archived", "paid"),
        ("Marjane Holding",          1, 25, [("Licence ERP Cloud", 120)],                               "archived", "paid"),
        ("Clinique Ain Khalil",      2,  8, [("Audit sécurité", 1)],                                    "archived", "paid"),
        ("OCP Group",                2, 17, [("Conseil digital", 8), ("Formation utilisateurs", 1)],    "archived", "paid"),
        ("Riad Dar Zellij",          2, 27, [("Maintenance IT mensuelle", 3)],                          "archived", "paid"),
        ("Auto Hall",                3,  6, [("Développement sur mesure", 12)],                         "archived", "paid"),
        ("TechnoPoint Distribution", 3, 14, [("Licence ERP Cloud", 35)],                                "archived", "paid"),
        ("Marjane Holding",          3, 21, [("Maintenance IT mensuelle", 12)],                         "archived", "paid"),
        ("Royal Air Maroc",          3, 29, [("Conseil digital", 10)],                                  "archived", "paid"),
        ("Cooperative Al Baraka",    4,  9, [("Licence ERP Cloud", 8), ("Formation utilisateurs", 2)],  "archived", "paid"),
        ("OCP Group",                4, 15, [("Développement sur mesure", 15)],                         "archived", "paid"),
        ("Clinique Ain Khalil",      4, 22, [("Maintenance IT mensuelle", 6)],                          "archived", "paid"),
        ("Auto Hall",                5,  5, [("Audit sécurité", 2)],                                    "archived", "paid"),
        ("Riad Dar Zellij",          5, 13, [("Transport marchandises", 6)],                            "archived", "paid"),
        ("Marjane Holding",          5, 20, [("Développement sur mesure", 10), ("Conseil digital", 4)], "archived", "paid"),
        ("TechnoPoint Distribution", 5, 28, [("Maintenance IT mensuelle", 9)],                          "archived", "paid"),
        ("Royal Air Maroc",          6,  4, [("Serveur Dell PowerEdge", 1), ("Licence antivirus", 80)], "archived", "paid"),
        ("OCP Group",                6, 11, [("Formation utilisateurs", 3)],                            "archived", "paid"),
        ("Marjane Holding",          6, 18, [("Licence ERP Cloud", 120)],                               "archived", "paid"),
        ("Clinique Ain Khalil",      6, 24, [("Location salle conférence", 2)],                         "archived", "paid"),
        ("Auto Hall",                7,  2, [("Développement sur mesure", 8)],                          "sent", "paid"),
        ("Cooperative Al Baraka",    7,  9, [("Maintenance IT mensuelle", 4)],                          "sent", "paid"),
        ("Royal Air Maroc",          7, 16, [("Conseil digital", 6), ("Formation utilisateurs", 1)],    "sent", "partial", "cheque", (7, 28)),
        ("TechnoPoint Distribution", 7, 23, [("Serveur Dell PowerEdge", 1)],                            "sent", "partial", "virement", (8, 5)),
        ("Riad Dar Zellij",          7, 30, [("Licence ERP Cloud", 6)],                                 "sent", None),
        ("Marjane Holding",          8,  5, [("Audit sécurité", 1), ("Développement sur mesure", 5)],   "sent", None),
        ("OCP Group",                8, 11, [("Licence ERP Cloud", 60)],                                "sent", None),
        ("Auto Hall",                8, 18, [("Maintenance IT mensuelle", 8)],                          "sent", None),
        ("Clinique Ain Khalil",      8, 24, [("Développement sur mesure", 6)],                          "validated", None),
        ("Royal Air Maroc",          8, 28, [("Location salle conférence", 4), ("Transport marchandises", 3)], "validated", None),
        ("TechnoPoint Distribution", 9,  2, [("Conseil digital", 4)],                                   "validated", None),
        ("Cooperative Al Baraka",    9,  4, [("Formation utilisateurs", 1)],                            "validated", None),
        ("Riad Dar Zellij",          9,  8, [("Maintenance IT mensuelle", 2)],                          "validated", None),
        ("Marjane Holding",          9,  9, [("Licence antivirus", 200)],                               "validated", None),
        ("OCP Group",                9, 10, [("Audit sécurité", 1)],                                    "draft", None),
        ("Clinique Ain Khalil",      9, 10, [("Location salle conférence", 1)],                         "draft", None),
        ("Auto Hall",                9, 10, [("Développement sur mesure", 3)],                          "draft", None),
    ]
    inv_by_client = {}
    for n, (client, m, d, items, status, payment, *rest) in enumerate(plan, 1):
        pay_method = rest[0] if rest and rest[0] else "virement"
        pay_day = rest[1] if len(rest) > 1 and rest[1] else None
        inv = make_invoice(n, client, m, d, items, status, payment, pay_method, pay_day)
        inv_by_client.setdefault(client, []).append(inv)

    session.commit()

    # ── Avoirs (2) ───────────────────────────────────────────
    def make_credit_note(orig, lines, reason):
        cn = create_credit_note_draft(
            session, company.id, orig.id,
            _d(orig.invoice_date.month, min(orig.invoice_date.day + 5, 28)),
            reason, owner.id,
        )
        for i, (desc, qty, price, rate) in enumerate(lines):
            add_line_to_credit_note(session, cn.id, desc, Decimal(str(qty)),
                                    Decimal(price), Decimal(rate), None, i)
        validate_credit_note(session, cn.id, owner.id)
        return cn

    orig1 = inv_by_client["Royal Air Maroc"][0]   # formation RAM
    cn1 = make_credit_note(
        orig1,
        [("Annulation formation — session du 16/07", 1,
          [p for p in PRODUCTS if p[0] == "Formation utilisateurs"][0][2], "0.14")],
        "Formation annulée par le client (indisponibilité salle)",
    )
    orig2 = inv_by_client["TechnoPoint Distribution"][1]
    cn2 = make_credit_note(
        orig2,
        [("Serveur endommagé pendant livraison", 1,
          [p for p in PRODUCTS if p[0] == "Serveur Dell PowerEdge"][0][2], "0.20")],
        "Retour marchandise — matériel endommagé en transit",
    )
    session.commit()

    # ── Fournisseurs (avant PO + factures fournisseurs) ──────
    from app.services.hash_service import compute_hash
    supplier_names = ["Dell Technologies Maroc", "Microsoft Ireland Operations"]
    for name in supplier_names:
        s = Client(company_id=company.id, name=name,
                   ice=generate_ice("0100458700000" if "Dell" in name else "0110245800000"),
                   city="Casablanca", address="", phone="", email="")
        session.add(s); clients[name] = s
    session.flush()

    # ── Bons de commande (3) ─────────────────────────────────
    try:
        from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine
        po_data = [
            ("Dell Technologies Maroc",      "PO-2026-0141", 3, 12, [("Serveur Dell PowerEdge", 3)]),
            ("Microsoft Ireland Operations", "PO-2026-0157", 6, 10, [("Licence antivirus", 100)]),
            ("TechnoPoint Distribution",     "PO-2026-0163", 7, 8,  [("Licence ERP Cloud", 6)]),
        ]
        for sup_name, po_num, m, d, items in po_data:
            po = PurchaseOrder(
                company_id=company.id, supplier_id=clients[sup_name].id,
                po_number=po_num, issue_date=_d(m, d), status="sent",
            )
            session.add(po); session.flush()
            total_ht = Decimal("0"); total_tva = Decimal("0")
            for i, (pname, qty) in enumerate(items):
                p = products[pname]
                rate = Decimal([x[3] for x in PRODUCTS if x[0] == pname][0])
                ht = p.unit_price * Decimal(str(qty))
                total_ht += ht; total_tva += ht * rate
                session.add(PurchaseOrderLine(
                    po_id=po.id, product_id=p.id, description=pname,
                    quantity=Decimal(str(qty)), unit_price=p.unit_price,
                    tva_rate=rate, line_total_ht=ht,
                    line_total_tva=ht * rate, line_total_ttc=ht * (1 + rate),
                    sort_order=i,
                ))
            po.total_ht = total_ht
            po.total_tva = total_tva
            po.total_ttc = total_ht + total_tva
            session.add(po)
        session.commit()
    except Exception as e:
        print(f"(bons de commande: modèle différent — {e})")

    # ── Factures fournisseurs (2) ────────────────────────────
    sup_data = [
        ("Dell Technologies Maroc", "2026-0112", 3, 20, "Serveur Dell PowerEdge", 3, "0.20"),
        ("Microsoft Ireland Operations", "FR-2026-0087", 6, 15, "Licence antivirus", 100, "0.20"),
    ]
    sup_client = {c.name: c for c in clients.values()}
    for sup_name, sup_num, m, d, pname, qty, rate in sup_data:
        p = products[pname]
        ht = p.unit_price * Decimal(str(qty))
        tva = ht * Decimal(rate)
        inv = Invoice(
            company_id=company.id, client_id=sup_client[sup_name].id,
            fiscal_year=Y, invoice_date=_d(m, d), invoice_number=sup_num,
            status="received", is_supplier_invoice=True,
            total_ht=ht, total_tva=tva, total_ttc=ht + tva,
            hash_sha256=compute_hash(f"{sup_name}{sup_num}".encode()),
            hash_algorithm="sha256",
        )
        session.add(inv); session.flush()
        session.add(InvoiceLine(
            invoice_id=inv.id, description=pname, quantity=Decimal(str(qty)),
            unit_price=p.unit_price, tva_rate=Decimal(rate),
            line_total_ht=ht, line_total_tva=tva, line_total_ttc=ht + tva,
        ))
    session.commit()

    # ══════════════════════════════════════════════════════════
    # SECTIONS COMPLÉMENTAIRES — pour que chaque menu ait du contenu
    # ══════════════════════════════════════════════════════════

    # ── 1. Records de clearance DGI (mock) pour les factures validées ─
    from app.models.clearance import ClearanceRecord
    import json as _json
    cleared = [i for i in total_inv_rows(session, company.id)
               if i.status in ("validated", "sent", "archived")]
    for n, inv in enumerate(cleared, 1):
        m = inv.invoice_date.month
        rec = ClearanceRecord(
            company_id=company.id, invoice_id=inv.id,
            status="cleared",
            clearance_number=f"DGI-{Y}-{n:06d}",
            submission_timestamp=_d(m, min(inv.invoice_date.day + 1, 28)),
            clearance_timestamp=_d(m, min(inv.invoice_date.day + 1, 28)),
            raw_response=_json.dumps({
                "status": "cleared", "provider": "mock",
                "clearance_number": f"DGI-{Y}-{n:06d}",
            }),
        )
        session.add(rec)
    # Un rejet réaliste sur la plus récente (storytelling : le système détecte)
    rejected = [i for i in total_inv_rows(session, company.id) if i.status == "validated"]
    if rejected:
        last = rejected[-1]
        session.add(ClearanceRecord(
            company_id=company.id, invoice_id=last.id,
            status="submitted",
            submission_timestamp=_d(9, 10),
            raw_response=_json.dumps({"status": "submitted", "provider": "mock"}),
        ))
    session.commit()

    # ── 2. Bons de réception (rapprochement 3 voies) ─────────
    try:
        from app.models.goods_receipt import GoodsReceipt, GoodsReceiptLine
        from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine as POLine
        all_pos = session.exec(select(PurchaseOrder).where(PurchaseOrder.company_id == company.id)).all()
        gr_map = [
            ("PO-2026-0141", "GR-2026-0031", 3, 22, [(1, 3, 3, "good")], "Réception complète — matériel conforme", "confirmed"),
            ("PO-2026-0157", "GR-2026-0045", 6, 18, [(1, 100, 100, "good")], "Licences activées et livrées", "matched"),
            ("PO-2026-0163", "GR-2026-0052", 7, 12, [(1, 6, 5, "good"), (1, 6, 1, "damaged")], "1 poste endommagé — retour en cours", "confirmed"),
        ]
        for po_num, gr_num, m, d, lines, notes, status in gr_map:
            po = next((p for p in all_pos if p.po_number == po_num), None)
            if not po:
                continue
            gr = GoodsReceipt(
                company_id=company.id, po_id=po.id, gr_number=gr_num,
                receipt_date=_d(m, d), received_by="Karim Benali (Entrepôt)",
                notes=notes, status=status,
            )
            session.add(gr); session.flush()
            po_lines = session.exec(select(POLine).where(POLine.po_id == po.id)).all()
            for n, (line_idx, expected, received, cond) in enumerate(lines):
                pl = po_lines[line_idx] if line_idx < len(po_lines) else po_lines[0]
                session.add(GoodsReceiptLine(
                    goods_receipt_id=gr.id, po_line_id=pl.id,
                    product_id=pl.product_id, description=pl.description,
                    quantity_received=Decimal(str(received)),
                    quantity_expected=Decimal(str(expected)),
                    condition=cond,
                    notes="Retour fournisseur programmé" if cond == "damaged" else None,
                    sort_order=n,
                ))
        session.commit()
    except Exception as e:
        print(f"(bons de réception: {e})")

    # ── 3. Messages WhatsApp (bridge) ─────────────────────────
    from app.models.whatsapp_message import WhatsAppMessage
    wa_data = [
        ("inbound",  "+212661234567", "Bonjour, vous pouvez envoyer la facture F-2026-000022 par email svp ?", "received"),
        ("outbound", "+212661234567", "Bonjour, c'est envoyé ! Vous pouvez aussi la télécharger sur le portail client.", "processed"),
        ("inbound",  "+212662345678", "Merci, la facture est bien reçue.", "received"),
        ("inbound",  "+212663456789", "Quand passez-vous pour la maintenance du serveur ?", "received"),
        ("outbound", "+212663456789", "Notre technicien passe mardi matin. Confirmation à suivre.", "processed"),
    ]
    for n, (direction, num, body, status) in enumerate(wa_data):
        session.add(WhatsAppMessage(
            wa_message_id=f"wamid.demo{n:03d}", from_number=num,
            body=body, direction=direction, status=status,
            processed_at=_d(9, 5 + n) if status == "processed" else None,
            created_at=_d(9, 5 + n),
        ))
    session.commit()

    # ── 4. Chaîne d'audit cryptographique ─────────────────────
    from app.models.audit_chain import create_chain_entry
    all_invs = total_inv_rows(session, company.id)
    for inv in all_invs[:15]:
        create_chain_entry(
            session, company.id, "invoice", inv.id,
            "archive_sealed", owner.id,
            details={"invoice_number": inv.invoice_number,
                     "hash": inv.hash_sha256 or "seeded"},
        )
    session.commit()

    # ── 5. Portail client activé (2 clients avec mots de passe) ─
    from app.services.auth import hash_password as _hp
    portal_accounts = {
        "Marjane Holding":  ("marjane",  "portal123"),
        "OCP Group":        ("ocp",      "portal123"),
    }
    for name, (username, pwd) in portal_accounts.items():
        c = next((c for c in clients.values() if c.name == name), None)
        if c:
            c.portal_enabled = True
            c.portal_password_hash = _hp(pwd)
            session.add(c)
    session.commit()

    # ── 6. Archives ZIP physiques pour les factures archivées ─
    try:
        from app.services.archive import build_archive_zip, store_archive
        archived = [i for i in all_invs if i.status == "archived"]
        company_row = session.get(Company, company.id)
        count = 0
        for inv in archived:
            lines = session.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id)).all()
            client_row = session.get(Client, inv.client_id)
            if not client_row:
                continue
            zip_bytes = build_archive_zip(inv, lines, company_row, client_row)
            store_archive(inv.id, zip_bytes)
            count += 1
        print(f"  Archives ZIP générées : {count}")
    except Exception as e:
        print(f"(archives: {e})")

    # ── 7. Mode cabinet — fiduciaire + 3 clients ──────────────
    try:
        from app.models.cabinet import Cabinet, ClientCompany
        from app.services.cabinet import _init_client_db
        cab = Cabinet(
            id="cab_atlas", name="Fiduciaire Benali & Associés",
            ice=generate_ice("0999458700000"),
            address="8, Avenue Hassan II", city="Casablanca",
            phone="+212 522 30 40 50", email="contact@benali-fiduciaire.ma",
            brand_name="Benali Compta", brand_color="#1a3a5c",
        )
        session.add(cab); session.flush()

        cab_clients = [
            ("Boulangerie Al Fassi",   "0123456700000", "TPE", 95, "A", 14, 5),
            ("Électronique Plus",      "0132456700000", "PME", 62, "C", 9, 3),
            ("Transport Rapide Atlas", "0142456700000", "TPE", 38, "D", 6, 2),
        ]
        for name, ice13, tier, score, grade, n_inv, n_cli in cab_clients:
            cc_id = uuid.uuid4().hex
            cc = ClientCompany(
                id=cc_id, cabinet_id="cab_atlas", company_name=name,
                ice=generate_ice(ice13),
                rc=f"RC-{uuid.uuid4().hex[:6].upper()}",
                if_number=f"IF-{uuid.uuid4().hex[:8].upper()}",
                db_path=f"cabinets/cab_atlas/clients/{cc_id}.db",
                turnover_tier=tier, status="active",
                compliance_score=score, compliance_grade=grade,
                invoice_count=n_inv, client_count=n_cli,
                last_audit_date=_d(9, 12),
                dgi_deadline="2027-01" if tier != "medium" else "2026-07",
            )
            session.add(cc)
            _init_client_db("cab_atlas", cc_id)
        session.commit()
        print("  Cabinet fiduciaire : 1 cabinet + 3 sociétés clientes")
    except Exception as e:
        print(f"(cabinet: {e})")

    # ── Résumé ───────────────────────────────────────────────
    total_inv = session.exec(
        select(Invoice).where(Invoice.company_id == company.id,
                              Invoice.is_supplier_invoice == False)
    ).all()
    ca = sum(i.total_ttc for i in total_inv if i.status in ("validated", "sent", "archived"))
    tva = sum(i.total_tva for i in total_inv if i.status in ("validated", "sent", "archived"))
    unpaid = sum(i.total_ttc for i in total_inv
                 if i.payment_status in ("pending", "partial") and i.status != "draft")
    n_inv = len(total_inv)

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   COMPLY-MA — INVESTOR DEMO SEEDED ✓                     ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Entreprise      : Atlas Digital Solutions (Casablanca)  ║")
    print(f"║  Connexion       : owner / password                      ║")
    print(f"║  Factures        : {n_inv:2d} (janv→sept 2026, 8 mois d'historique) ║")
    print(f"║  Avoirs          : 2  (AV-2026, motifs réalistes)        ║")
    print(f"║  Clients         : {len(clients)} (grandes entreprises marocaines)      ║")
    print(f"║  Produits        : {len(products)} (SaaS, services, hardware, logistique) ║")
    print(f"║  CA TTC cumulé   : {ca:>10,.2f} MAD                 ║")
    print(f"║  TVA collectée   : {tva:>10,.2f} MAD                 ║")
    print(f"║  En cours (cré.) : {unpaid:>10,.2f} MAD                 ║")
    print("║                                                          ║")
    print("║  Story pour la vidéo :                                   ║")
    print("║   1. Landing page (/) → expliquer la proposition         ║")
    print("║   2. Dashboard → CA mensuel, TVA T3, aging, audit trail  ║")
    print("║   3. Factures → filtres par statut, détail F-2026-0000X  ║")
    print("║   4. Créer une facture live → validation → numérotation  ║")
    print("║   5. Conformité → score 100 %, journal d'audit           ║")
    print("║   6. Analytics → DSO, top clients, repartition TVA       ║")
    print("║   7. Cabinet (/cabinet) → vue fiduciaire multi-clients   ║")
    print("╚══════════════════════════════════════════════════════════╝")
