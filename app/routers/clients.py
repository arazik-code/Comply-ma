"""
CRUD clients avec HTMX.
"""
import csv
import io

from fastapi import APIRouter, Request, Depends, Form, Query, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select, func

from app.database import get_session
from app.pagination import Page, PAGE_SIZE
from app.models.client import Client
from app.services.auth import require_auth
from app.i18n import get_translator
from app.flash import flash
from app.templating import templates
from app.routers.portal import hash_password

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/", response_class=HTMLResponse)
async def client_list(
    request: Request,
    q: str = Query(""),
    page: int = 1,
    session: Session = Depends(get_session),
):
    t = get_translator(request)
    user = require_auth(request)
    stmt = select(Client).where(Client.company_id == user["company_id"])
    if q:
        stmt = stmt.where(Client.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Client.name)
    count_stmt = select(func.count()).select_from(Client).where(Client.company_id == user["company_id"])
    if q:
        count_stmt = count_stmt.where(Client.name.ilike(f"%{q}%"))
    total = session.exec(count_stmt).one()
    items = session.exec(stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    page_obj = Page(items=items, page=page, page_size=PAGE_SIZE, total=total)
    return templates.TemplateResponse(
        request, "clients/list.html",
        {"t": t, "clients": page_obj.items, "q": q, "user": user, "page_obj": page_obj},
    )


@router.get("/new", response_class=HTMLResponse)
async def client_create_form(request: Request):
    t = get_translator(request)
    user = require_auth(request)
    return templates.TemplateResponse(
        request, "clients/form.html",
        {"t": t, "client": None, "user": user},
    )


@router.post("/", response_class=HTMLResponse)
async def client_create(
    request: Request,
    name: str = Form(...),
    ice: str = Form(""),
    rc: str = Form(""),
    if_number: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    portal_enabled: str = Form(""),
    portal_password: str = Form(""),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    client = Client(
        company_id=user["company_id"],
        name=name,
        ice=ice or None,
        rc=rc or None,
        if_number=if_number or None,
        address=address or None,
        city=city or None,
        phone=phone or None,
        email=email or None,
        portal_enabled=(portal_enabled == "1"),
    )
    if portal_password and client.portal_enabled:
        client.portal_password_hash = hash_password(portal_password)
    session.add(client)
    session.commit()
    flash(request, "Client créé avec succès")
    return RedirectResponse(url="/clients", status_code=303)


@router.post("/import", response_class=HTMLResponse)
async def client_import_csv(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    created = 0
    errors = []
    for i, row in enumerate(reader, start=1):
        try:
            name = row.get("name", row.get("nom", row.get("raison_sociale", row.get("raison sociale", "")))).strip()
            if not name:
                errors.append(f"Ligne {i}: nom manquant")
                continue
            client = Client(
                company_id=user["company_id"],
                name=name,
                ice=row.get("ice", "").strip() or None,
                rc=row.get("rc", "").strip() or None,
                if_number=row.get("if", row.get("if_number", "")).strip() or None,
                address=row.get("address", row.get("adresse", "")).strip() or None,
                city=row.get("city", row.get("ville", "")).strip() or None,
                phone=row.get("phone", row.get("telephone", row.get("tel", ""))).strip() or None,
                email=row.get("email", "").strip() or None,
            )
            session.add(client)
            created += 1
        except Exception as e:
            errors.append(f"Ligne {i}: {e}")
    session.commit()
    msg = f"{created} client(s) importé(s)"
    if errors:
        msg += f" — {len(errors)} erreur(s): {'; '.join(errors[:5])}"
    flash(request, msg)
    return RedirectResponse(url="/clients", status_code=303)


@router.get("/{client_id}/edit", response_class=HTMLResponse)
async def client_edit_form(client_id: str, request: Request, session: Session = Depends(get_session)):
    t = get_translator(request)
    user = require_auth(request)
    client = session.get(Client, client_id)
    if not client or client.company_id != user["company_id"]:
        return RedirectResponse(url="/clients", status_code=303)
    return templates.TemplateResponse(
        request, "clients/form.html",
        {"t": t, "client": client, "user": user},
    )


@router.post("/{client_id}", response_class=HTMLResponse)
async def client_update(
    client_id: str,
    request: Request,
    name: str = Form(...),
    ice: str = Form(""),
    rc: str = Form(""),
    if_number: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    portal_enabled: str = Form(""),
    portal_password: str = Form(""),
    session: Session = Depends(get_session),
):
    user = require_auth(request)
    client = session.get(Client, client_id)
    if not client or client.company_id != user["company_id"]:
        return RedirectResponse(url="/clients", status_code=303)
    client.name = name
    client.ice = ice or None
    client.rc = rc or None
    client.if_number = if_number or None
    client.address = address or None
    client.city = city or None
    client.phone = phone or None
    client.email = email or None
    client.portal_enabled = (portal_enabled == "1")
    if portal_password:
        client.portal_password_hash = hash_password(portal_password)
    session.add(client)
    session.commit()
    flash(request, "Client mis à jour")
    return RedirectResponse(url="/clients", status_code=303)


@router.post("/{client_id}/delete", response_class=HTMLResponse)
async def client_delete(client_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    client = session.get(Client, client_id)
    if client and client.company_id == user["company_id"]:
        session.delete(client)
        session.commit()
        flash(request, "Client supprimé")
    return RedirectResponse(url="/clients", status_code=303)


@router.post("/{client_id}/toggle-active", response_class=HTMLResponse)
async def client_toggle_active(client_id: str, request: Request, session: Session = Depends(get_session)):
    user = require_auth(request)
    client = session.get(Client, client_id)
    if client and client.company_id == user["company_id"]:
        client.is_active = not client.is_active
        session.add(client)
        session.commit()
        flash(request, "Client activé" if client.is_active else "Client désactivé")
    return RedirectResponse(url="/clients", status_code=303)
