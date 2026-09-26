"""
Cabinet Service — multi-tenant management for fiduciaires.

Each client company gets its own SQLite database file.
The cabinet database stores metadata; each client DB stores their invoices, clients, etc.
"""
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from app.config import settings
from app.models.cabinet import Cabinet, ClientCompany

logger = logging.getLogger("app.services.cabinet")

# Template DB — used to initialize new client databases
TEMPLATE_DB_PATH = Path("./data/template.db")


def get_cabinet_db_path(cabinet_id: str) -> Path:
    """Get the path to a cabinet's metadata database."""
    return Path(settings.data_dir) / "cabinets" / f"{cabinet_id}.db"


def get_client_db_path(cabinet_id: str, client_company_id: str) -> Path:
    """Get the path to a client company's isolated database."""
    return Path(settings.data_dir) / "cabinets" / cabinet_id / "clients" / f"{client_company_id}.db"


def create_cabinet(
    session: Session,
    name: str,
    ice: str = "",
    address: str = "",
    city: str = "",
    phone: str = "",
    email: str = "",
    brand_name: str = "",
    brand_color: str = "#1a3a5c",
) -> Cabinet:
    """Create a new cabinet (fiduciaire firm)."""
    cabinet = Cabinet(
        name=name, ice=ice, address=address, city=city,
        phone=phone, email=email,
        brand_name=brand_name or name, brand_color=brand_color,
    )
    session.add(cabinet)
    session.commit()
    session.refresh(cabinet)

    # Create cabinet directory
    cabinet_dir = Path(settings.data_dir) / "cabinets" / cabinet.id
    cabinet_dir.mkdir(parents=True, exist_ok=True)

    logger.info("cabinet_created", extra={"cabinet_id": cabinet.id, "name": name})
    return cabinet


def add_client_company(
    session: Session,
    cabinet_id: str,
    company_name: str,
    ice: str = "",
    rc: str = "",
    if_number: str = "",
    turnover_tier: str = "PME",
) -> ClientCompany:
    """Add a new client company with isolated database."""
    # Determine DGI deadline based on turnover tier
    deadline_map = {
        "TPE": "2027-01",
        "PME": "2027-01",
        "medium": "2026-07",
    }
    dgi_deadline = deadline_map.get(turnover_tier, "2027-01")

    # Create client DB path
    client_id = uuid.uuid4().hex
    db_path = f"cabinets/{cabinet_id}/clients/{client_id}.db"

    client_company = ClientCompany(
        id=client_id,
        cabinet_id=cabinet_id,
        company_name=company_name,
        ice=ice, rc=rc, if_number=if_number,
        db_path=db_path,
        turnover_tier=turnover_tier,
        dgi_deadline=dgi_deadline,
        status="active",
    )
    session.add(client_company)
    session.commit()
    session.refresh(client_company)

    # Initialize client database
    _init_client_db(cabinet_id, client_id)

    logger.info("client_company_added", extra={"cabinet_id": cabinet_id, "client_id": client_id, "name": company_name})
    return client_company


def _init_client_db(cabinet_id: str, client_company_id: str):
    """Initialize a new client database from template or create fresh."""
    client_db_path = get_client_db_path(cabinet_id, client_company_id)
    client_db_path.parent.mkdir(parents=True, exist_ok=True)

    if TEMPLATE_DB_PATH.exists():
        shutil.copy2(TEMPLATE_DB_PATH, client_db_path)
        logger.info("client_db_initialized_from_template", extra={"path": str(client_db_path)})
    else:
        # Create fresh DB with all tables
        from sqlmodel import create_engine, SQLModel
        import app.models  # noqa: force metadata registration
        engine = create_engine(f"sqlite:///{client_db_path}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        engine.dispose()
        logger.info("client_db_created_fresh", extra={"path": str(client_db_path)})


def switch_to_client_db(cabinet_id: str, client_company_id: str):
    """
    Switch the active database to a specific client's database.
    Returns a new engine for that client.

    IMPORTANT: In cabinet mode, each request operates on ONE client DB.
    The cabinet metadata DB is separate.
    """
    client_db_path = get_client_db_path(cabinet_id, client_company_id)
    if not client_db_path.exists():
        raise FileNotFoundError(f"Client database not found: {client_db_path}")

    from sqlmodel import create_engine
    return create_engine(
        f"sqlite:///{client_db_path}",
        connect_args={"check_same_thread": False},
    )


def get_cabinet_stats(session: Session, cabinet_id: str) -> dict:
    """Get overview stats for the fiduciaire dashboard."""
    clients = session.exec(
        select(ClientCompany).where(ClientCompany.cabinet_id == cabinet_id)
    ).all()

    total = len(clients)
    active = sum(1 for c in clients if c.status == "active")
    with_issues = sum(1 for c in clients if c.compliance_score < 75)
    ready = sum(1 for c in clients if c.compliance_score >= 90)

    return {
        "total_clients": total,
        "active_clients": active,
        "ready_for_dgi": ready,
        "with_issues": with_issues,
        "avg_compliance": round(sum(c.compliance_score for c in clients) / total, 1) if total > 0 else 0,
    }


def get_dgi_deadline_info() -> dict:
    """Get DGI compliance deadline information by turnover tier."""
    return {
        "medium": {
            "label": "Entreprises de taille intermédiaire",
            "deadline": "Juillet 2026",
            "deadline_date": "2026-07-01",
            "description": "Entreprises dont le CA >= 100M MAD",
        },
        "pme": {
            "label": "PME (> 500K DH)",
            "deadline": "Janvier 2027",
            "deadline_date": "2027-01-01",
            "description": "Entreprises dont le CA >= 500K MAD",
        },
        "tpe": {
            "label": "TPE / Auto-entrepreneurs",
            "deadline": "À confirmer",
            "deadline_date": None,
            "description": "En attente de publication DGI",
        },
    }


import uuid
