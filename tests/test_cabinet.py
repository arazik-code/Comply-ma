"""Tests for cabinet mode: data isolation, fiduciaire features."""
import pytest
from sqlmodel import Session, SQLModel, create_engine
from app.models.cabinet import Cabinet, ClientCompany
from app.models.user import User
from app.services.auth import hash_password


@pytest.fixture(name="cabinet_session")
def cabinet_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestCabinetModels:
    def test_create_cabinet(self, cabinet_session):
        cab = Cabinet(name="Test Cabinet", ice="123456789012345")
        cabinet_session.add(cab)
        cabinet_session.commit()
        assert cab.id is not None

    def test_create_client_company(self, cabinet_session):
        cab = Cabinet(name="Test Cabinet")
        cabinet_session.add(cab)
        cabinet_session.commit()

        cc = ClientCompany(
            cabinet_id=cab.id, company_name="Test Client",
            ice="987654321098765", db_path="test.db",
        )
        cabinet_session.add(cc)
        cabinet_session.commit()
        assert cc.id is not None

    def test_cabinet_admin_role(self, cabinet_session):
        user = User(
            company_id="cab1", username="admin",
            hashed_password=hash_password("test"),
            display_name="Admin", role="cabinet_admin",
        )
        cabinet_session.add(user)
        cabinet_session.commit()
        assert user.role == "cabinet_admin"


class TestDataIsolation:
    """Verify that each client company has a separate DB path."""
    def test_different_db_paths(self, cabinet_session):
        cab = Cabinet(name="Test Cabinet")
        cabinet_session.add(cab)
        cabinet_session.commit()

        cc1 = ClientCompany(cabinet_id=cab.id, company_name="Client 1", db_path="cab/clients/c1.db")
        cc2 = ClientCompany(cabinet_id=cab.id, company_name="Client 2", db_path="cab/clients/c2.db")
        cabinet_session.add(cc1)
        cabinet_session.add(cc2)
        cabinet_session.commit()

        assert cc1.db_path != cc2.db_path

    def test_client_belongs_to_cabinet(self, cabinet_session):
        cab = Cabinet(name="Test Cabinet")
        cabinet_session.add(cab)
        cabinet_session.commit()

        cc = ClientCompany(cabinet_id=cab.id, company_name="Client", db_path="test.db")
        cabinet_session.add(cc)
        cabinet_session.commit()

        from sqlmodel import select
        result = cabinet_session.exec(
            select(ClientCompany).where(ClientCompany.cabinet_id == cab.id)
        ).all()
        assert len(result) == 1
        assert result[0].company_name == "Client"


class TestMowakabaDisclaimer:
    def test_subsidy_info_has_disclaimer(self):
        from app.models.mowakaba import get_subsidy_info, DEFAULT_SUBSIDIES
        for s in DEFAULT_SUBSIDIES:
            assert not s.verified, "Subsidy should be marked as UNVERIFIED"

    def test_generate_dossier_draft(self):
        from app.models.mowakaba import generate_dossier_draft
        from app.services.data_quality.ice_validator import generate_ice
        ice = generate_ice("1234567890123")
        draft = generate_dossier_draft("Test Corp", ice, "TPE")
        assert "brouillon" in draft.lower()
        assert "vérifier" in draft.lower() or "confirmer" in draft.lower()
