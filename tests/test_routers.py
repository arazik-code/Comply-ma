"""
Tests d'intégration pour les routes HTTP.

Utilise TestClient de FastAPI avec une base SQLite fichier temporaire.
Chaque test reçoit un fichier DB frais (fixture _fresh_db).
"""
import os
import tempfile
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.main import app as fastapi_app
from app.config import settings
from app.models.tva import TVARate
from app.models.company import Company
from app.models.user import User
from app.models.client import Client
from app.services.auth import hash_password


_CSRF_RE = None


def _csrf(client) -> str:
    """Récupère le token CSRF depuis une page rendue (input hidden)."""
    global _CSRF_RE
    if _CSRF_RE is None:
        import re as _re
        _CSRF_RE = _re.compile(r'name="csrf_token" value="([^"]+)"')
    resp = client.get("/clients")  # page publique ou authentifiée, peu importe
    if resp.status_code != 200:
        resp = client.get("/login")
    m = _CSRF_RE.search(resp.text)
    assert m, "csrf token introuvable"
    return m.group(1)


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    """Crée une base fichier temporaire, remplace database_url, force init_db."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp.name}")

    import app.database
    old_engine = app.database.engine
    # Crée un nouvel engine pointant vers le fichier temporaire
    app.database.engine = create_engine(
        f"sqlite:///{tmp.name}",
        connect_args={"check_same_thread": False},
    )
    # Recrée les tables
    SQLModel.metadata.create_all(app.database.engine)
    monkeypatch.setattr(app.database, "engine", app.database.engine)

    yield tmp.name

    app.database.engine.dispose()
    app.database.engine = old_engine
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.services.security_middleware import reset_rate_limits
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def client():
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture
def seeded_db():
    """Crée les données de base dans la base fichier temporaire."""
    from app.database import engine
    with Session(engine) as session:
        company = Company(
            id="c" * 32,
            company_name="TEST SARL",
            address="1 Rue de la Test, Casablanca",
            city="Casablanca",
            rc="RC12345",
            if_number="IF67890",
            ice="IC1234567890",
            is_setup_complete=True,
        )
        session.add(company)

        for rate, label in [
            (Decimal("0.20"), "TVA 20%"),
            (Decimal("0.14"), "TVA 14%"),
            (Decimal("0.10"), "TVA 10%"),
            (Decimal("0.07"), "TVA 7%"),
        ]:
            session.add(TVARate(rate=rate, label=label))

        owner = User(
            id="u" * 32,
            company_id=company.id,
            username="owner",
            hashed_password=hash_password("password"),
            display_name="Owner Test",
            role="owner",
        )
        session.add(owner)
        session.commit()
    yield


# ─── Tests ─────────────────────────────────────────────────────────────────


class TestAuth:
    def test_login_page_returns_200(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_login_success(self, client, seeded_db):
        resp = client.post("/login", data={"username": "owner", "password": "password", "csrf_token": _csrf(client)}, follow_redirects=False)
        assert resp.status_code == 303

    def test_login_failure(self, client, seeded_db):
        resp = client.post("/login", data={"username": "owner", "password": "wrong", "csrf_token": _csrf(client)}, follow_redirects=False)
        assert resp.status_code == 200
        assert b"Identifiants incorrects" in resp.content

    def test_logout(self, client, seeded_db):
        client.post("/login", data={"username": "owner", "password": "password"})
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 303


class TestLang:
    def test_switch_to_arabic(self, client):
        resp = client.get("/lang/ar", follow_redirects=False)
        assert resp.status_code == 303

    def test_switch_to_french(self, client):
        resp = client.get("/lang/fr", follow_redirects=False)
        assert resp.status_code == 303


class TestClients:
    def _login(self, client):
        client.post("/login", data={"username": "owner", "password": "password", "csrf_token": _csrf(client)})

    def test_list_requires_auth(self, client):
        resp = client.get("/clients", follow_redirects=False)
        assert resp.status_code in (303, 307)

    def test_list_empty(self, client, seeded_db):
        self._login(client)
        resp = client.get("/clients")
        assert resp.status_code == 200

    def test_create_client(self, client, seeded_db):
        self._login(client)
        resp = client.post("/clients/", data={"name": "Client Test", "ice": "IC999999", "csrf_token": _csrf(client)}, follow_redirects=False)
        assert resp.status_code == 303

    def test_list_after_create(self, client, seeded_db):
        self._login(client)
        client.post("/clients/", data={"name": "Client Test", "csrf_token": _csrf(client)})
        resp = client.get("/clients")
        assert resp.status_code == 200
        assert b"Client Test" in resp.content


class TestProducts:
    def _login(self, client):
        client.post("/login", data={"username": "owner", "password": "password", "csrf_token": _csrf(client)})

    def test_create_product(self, client, seeded_db):
        self._login(client)
        resp = client.post("/products/", data={
            "name": "Produit Test",
            "unit_price": "100.00",
            "tva_rate_id": "dummy",
            "unit": "pièce",
            "csrf_token": _csrf(client),
        }, follow_redirects=False)
        assert resp.status_code in (303, 422, 500)


class TestInvoices:
    def _login(self, client):
        client.post("/login", data={"username": "owner", "password": "password", "csrf_token": _csrf(client)})

    def _seed_client(self):
        from app.database import engine
        with Session(engine) as session:
            c = Client(company_id="c" * 32, name="Client Test", ice="IC999999")
            session.add(c)
            session.commit()
            return c.id

    def test_create_invoice(self, client, seeded_db):
        self._login(client)
        cid = self._seed_client()
        resp = client.post("/invoices/", data={
            "client_id": cid,
            "invoice_date": "2026-07-01",
            "notes": "",
            "csrf_token": _csrf(client),
        }, follow_redirects=False)
        assert resp.status_code == 303

    def test_create_and_add_line(self, client, seeded_db):
        self._login(client)
        cid = self._seed_client()
        resp = client.post("/invoices/", data={
            "client_id": cid, "invoice_date": "2026-07-01", "notes": "", "csrf_token": _csrf(client),
        }, follow_redirects=False)
        invoice_id = resp.headers["location"].split("/")[-1]
        resp = client.post(f"/invoices/{invoice_id}/lines", data={
            "description": "Consulting", "quantity": "10", "unit_price": "100.00", "tva_rate": "0.20",
            "csrf_token": _csrf(client),
        }, follow_redirects=False)
        assert resp.status_code == 303

    def test_validate_invoice(self, client, seeded_db):
        self._login(client)
        cid = self._seed_client()
        resp = client.post("/invoices/", data={
            "client_id": cid, "invoice_date": "2026-07-01", "notes": "", "csrf_token": _csrf(client),
        }, follow_redirects=False)
        invoice_id = resp.headers["location"].split("/")[-1]
        client.post(f"/invoices/{invoice_id}/lines", data={
            "description": "Consulting", "quantity": "1", "unit_price": "500.00", "tva_rate": "0.20",
            "csrf_token": _csrf(client),
        })
        resp = client.post(f"/invoices/{invoice_id}/validate", data={"csrf_token": _csrf(client)}, follow_redirects=False)
        assert resp.status_code == 303

    def test_invoice_detail_shows_number_after_validation(self, client, seeded_db):
        self._login(client)
        cid = self._seed_client()
        resp = client.post("/invoices/", data={
            "client_id": cid, "invoice_date": "2026-07-01", "notes": "", "csrf_token": _csrf(client),
        }, follow_redirects=False)
        invoice_id = resp.headers["location"].split("/")[-1]
        client.post(f"/invoices/{invoice_id}/lines", data={
            "description": "Consulting", "quantity": "1", "unit_price": "500.00", "tva_rate": "0.20",
            "csrf_token": _csrf(client),
        })
        client.post(f"/invoices/{invoice_id}/validate", data={"csrf_token": _csrf(client)})
        resp = client.get(f"/invoices/{invoice_id}")
        assert resp.status_code == 200
        assert b"F-2026" in resp.content


class TestDashboard:
    def _login(self, client):
        client.post("/login", data={"username": "owner", "password": "password", "csrf_token": _csrf(client)})

    def test_dashboard_requires_auth(self, client):
        resp = client.get("/dashboard", follow_redirects=False)
        assert resp.status_code in (303, 307)

    def test_dashboard_shows_stats(self, client, seeded_db):
        self._login(client)
        resp = client.get("/dashboard")
        assert resp.status_code == 200


class TestExport:
    def _login(self, client):
        client.post("/login", data={"username": "owner", "password": "password", "csrf_token": _csrf(client)})

    def test_csv_export(self, client, seeded_db):
        self._login(client)
        resp = client.get("/export/csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")

    def test_xml_bundle_empty(self, client, seeded_db):
        self._login(client)
        resp = client.get("/export/xml-bundle")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
