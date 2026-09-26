"""
Configuration des tests COMPLY-MA.

Utilise une base SQLite en mémoire — chaque fonction de test obtient
une base fraîche et des données isolées.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import SQLModel, Session, create_engine

from app.models.company import Company
from app.models.tva import TVARate

_counter = 0


def _unique_ice():
    """Génère un ICE unique pour éviter les conflits entre tests."""
    global _counter
    _counter += 1
    return f"ICE{_counter:018d}"


@pytest.fixture(scope="function")
def engine():
    e = create_engine("sqlite:///:memory:", echo=False)
    SQLModel.metadata.create_all(e)
    return e


@pytest.fixture(scope="function")
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture(scope="function")
def company(session) -> Company:
    c = Company(
        company_name="Entreprise Test SARL",
        address="123 Rue de la Test, Casablanca",
        city="Casablanca",
        rc="RC12345",
        if_number="IF987654",
        ice=_unique_ice(),
        tva_regime="assujetti",
        is_setup_complete=True,
    )
    session.add(c)
    session.commit()
    return c


@pytest.fixture(scope="function")
def company_id(company) -> str:
    return str(company.id)


@pytest.fixture(scope="function")
def tva_rates(session) -> dict:
    rates = {
        "t20": TVARate(rate=Decimal("0.20"), label="TVA 20%"),
        "t14": TVARate(rate=Decimal("0.14"), label="TVA 14%"),
        "t10": TVARate(rate=Decimal("0.10"), label="TVA 10%"),
        "t07": TVARate(rate=Decimal("0.07"), label="TVA 7%"),
    }
    for r in rates.values():
        session.add(r)
    session.commit()
    return rates
