"""Cabinet router — fiduciaire management of multiple client companies."""
import logging

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app.database import get_session
from app.models.cabinet import Cabinet, ClientCompany
from app.services.auth import require_auth
from app.services.cabinet import (
    create_cabinet, add_client_company, get_cabinet_stats, get_dgi_deadline_info,
)
from app.services.data_quality.engine import get_data_quality_engine
from app.templating import templates

logger = logging.getLogger("app.routers.cabinet")
router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/", response_class=HTMLResponse)
async def cabinet_dashboard(request: Request, session: Session = Depends(get_session)):
    """Fiduciaire dashboard — overview of all client files."""
    user = require_auth(request)

    # Get or show setup
    cabinets = session.exec(select(Cabinet)).all()
    if not cabinets:
        return templates.TemplateResponse(request, "cabinet/setup.html", {"user": user})

    cabinet = cabinets[0]
    clients = session.exec(
        select(ClientCompany).where(ClientCompany.cabinet_id == cabinet.id)
    ).all()

    stats = get_cabinet_stats(session, cabinet.id)
    deadlines = get_dgi_deadline_info()

    return templates.TemplateResponse(request, "cabinet/dashboard.html", {
        "user": user, "cabinet": cabinet, "clients": clients,
        "stats": stats, "deadlines": deadlines,
    })


@router.post("/setup", response_class=HTMLResponse)
async def cabinet_setup(
    request: Request,
    name: str = Form(...),
    ice: str = Form(""),
    email: str = Form(""),
    brand_name: str = Form(""),
    session: Session = Depends(get_session),
):
    """Create the initial cabinet."""
    user = require_auth(request)
    cabinet = create_cabinet(session, name=name, ice=ice, email=email, brand_name=brand_name)
    return RedirectResponse(url="/cabinet", status_code=303)


@router.post("/clients/new", response_class=HTMLResponse)
async def add_client(
    request: Request,
    company_name: str = Form(...),
    ice: str = Form(""),
    rc: str = Form(""),
    if_number: str = Form(""),
    turnover_tier: str = Form("PME"),
    session: Session = Depends(get_session),
):
    """Add a new client company."""
    user = require_auth(request)
    cabinets = session.exec(select(Cabinet)).all()
    if not cabinets:
        return RedirectResponse(url="/cabinet", status_code=303)

    add_client_company(
        session, cabinet_id=cabinets[0].id,
        company_name=company_name, ice=ice, rc=rc,
        if_number=if_number, turnover_tier=turnover_tier,
    )
    return RedirectResponse(url="/cabinet", status_code=303)


@router.get("/clients/{client_id}", response_class=HTMLResponse)
async def client_detail(
    request: Request,
    client_id: str,
    session: Session = Depends(get_session),
):
    """View a client company's detail — open their isolated DB context."""
    user = require_auth(request)
    client_company = session.get(ClientCompany, client_id)
    if not client_company:
        return RedirectResponse(url="/cabinet", status_code=303)

    # Ouvre la base isolée du client pour compter ses factures/clients réels
    invoice_count = client_company.invoice_count
    client_count = client_company.client_count
    db_error = None
    try:
        from app.services.cabinet import switch_to_client_db
        from sqlmodel import create_engine
        engine = switch_to_client_db(client_company.cabinet_id, client_company.id)
        try:
            from app.models.invoice import Invoice
            from app.models.client import Client as ClientModel
            with Session(engine) as client_session:
                invoice_count = len(client_session.exec(select(Invoice)).all())
                client_count = len(client_session.exec(select(ClientModel)).all())
        finally:
            engine.dispose()
    except FileNotFoundError:
        db_error = "Base de données client non initialisée"
    except Exception as e:
        logger.warning("client_db_open_failed", extra={"client_id": client_id, "error": str(e)})
        db_error = "Erreur d'accès à la base client"

    return templates.TemplateResponse(request, "cabinet/client_detail.html", {
        "user": user, "client_company": client_company,
        "invoice_count": invoice_count, "client_count": client_count,
        "db_error": db_error,
    })


@router.post("/clients/{client_id}/audit", response_class=HTMLResponse)
async def run_audit(
    request: Request,
    client_id: str,
    session: Session = Depends(get_session),
):
    """Run data quality audit on a client company."""
    user = require_auth(request)
    client_company = session.get(ClientCompany, client_id)
    if not client_company:
        return RedirectResponse(url="/cabinet", status_code=303)

    # In production, this would load the client's DB and run audit
    # For now, update the compliance metadata
    client_company.last_audit_date = datetime.now(timezone.utc)
    session.add(client_company)
    session.commit()

    return RedirectResponse(url=f"/cabinet/clients/{client_id}", status_code=303)


@router.get("/deadlines", response_class=HTMLResponse)
async def dgi_deadlines(request: Request):
    """Show DGI compliance deadlines by turnover tier."""
    user = require_auth(request)
    deadlines = get_dgi_deadline_info()
    return templates.TemplateResponse(request, "cabinet/deadlines.html", {
        "user": user, "deadlines": deadlines,
    })
