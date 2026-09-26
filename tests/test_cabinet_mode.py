"""
Tests du mode cabinet — routes, templates, isolation DB client.
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.main import app as fastapi_app
from app.config import settings


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
def seeded_cabinet_db(monkeypatch):
    """Base fichier temporaire avec cabinet + admin."""
    import tempfile
    import os
    from app.models.cabinet import Cabinet, ClientCompany
    from app.models.company import Company
    from app.models.user import User
    from app.services.auth import hash_password
    from app.services.cabinet import get_client_db_path
    from app.services.csrf import get_csrf_token

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp.name}")

    import app.database
    old_engine = app.database.engine
    app.database.engine = create_engine(
        f"sqlite:///{tmp.name}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(app.database.engine)

    with Session(app.database.engine) as s:
        company = Company(
            id="c" * 32, company_name="CAB SARL", address="a", city="Casablanca",
            rc="r", if_number="i", ice="ICE000000000000001", is_setup_complete=True,
        )
        s.add(company)
        s.add(User(
            id="u" * 32, company_id=company.id, username="owner",
            hashed_password=hash_password("password"), display_name="Owner", role="owner",
        ))
        cabinet = Cabinet(id="cab_test", name="Cabinet Test", ice="ICE000000000000002")
        s.add(cabinet)
        # Client avec base réelle initialisée
        cc = ClientCompany(
            id="cl" + "1" * 30, cabinet_id="cab_test", company_name="Client A",
            db_path="cabinets/cab_test/clients/cl" + "1" * 30 + ".db",
        )
        s.add(cc)
        s.commit()
        # Initialise réellement la base isolée du client
        from app.services.cabinet import _init_client_db
        _init_client_db("cab_test", cc.id)

    yield {"cabinet_id": "cab_test", "client_id": cc.id}

    app.database.engine.dispose()
    app.database.engine = old_engine
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _login(client) -> bool:
    resp = client.get("/login")
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
    if not m:
        return False
    resp = client.post(
        "/login",
        data={"username": "owner", "password": "password", "csrf_token": m.group(1)},
        follow_redirects=False,
    )
    return resp.status_code == 303


class TestCabinetRoutes:
    def test_cabinet_dashboard_renders(self, client, seeded_cabinet_db):
        assert _login(client)
        resp = client.get("/cabinet")
        assert resp.status_code == 200
        assert "Cabinet Test" in resp.text

    def test_cabinet_client_detail_renders(self, client, seeded_cabinet_db):
        assert _login(client)
        resp = client.get(f"/cabinet/clients/{seeded_cabinet_db['client_id']}")
        assert resp.status_code == 200
        assert "Client A" in resp.text

    def test_cabinet_deadlines_renders(self, client, seeded_cabinet_db):
        assert _login(client)
        resp = client.get("/cabinet/deadlines")
        assert resp.status_code == 200
        assert "DGI" in resp.text or "dgi" in resp.text.lower()

    def test_cabinet_requires_auth(self, client, seeded_cabinet_db):
        resp = client.get("/cabinet", follow_redirects=False)
        assert resp.status_code in (303, 307)

    def test_add_client_form_present(self, client, seeded_cabinet_db):
        assert _login(client)
        resp = client.get("/cabinet")
        assert 'action="/cabinet/clients/new"' in resp.text

    def test_csrf_protected(self, client, seeded_cabinet_db):
        assert _login(client)
        resp = client.post(
            "/cabinet/clients/new",
            data={"company_name": "X"},
            follow_redirects=False,
        )
        assert resp.status_code == 403
