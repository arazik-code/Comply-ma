"""
Configuration de l'entreprise, utilisateurs et taux de TVA.
Accès réservé au rôle 'owner'.
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.config import settings
from app.database import get_session
from app.models.company import Company
from app.models.user import User
from app.models.tva import TVARate
from app.services.auth import hash_password, require_owner
from app.i18n import get_translator
from app.flash import flash
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_owner)])


def _get_or_create_company(session: Session) -> Company:
    company = session.exec(select(Company)).first()
    if not company:
        company = Company(company_name="", address="", city="", rc="", if_number="", ice="")
        session.add(company)
        session.flush()
    return company


@router.get("/", response_class=HTMLResponse)
async def setup_form(request: Request, session: Session = Depends(get_session)):
    from app.services.auth import get_current_user
    t = get_translator(request)
    company = session.exec(select(Company)).first()
    users = session.exec(select(User)).all()
    tva_rates = session.exec(select(TVARate)).all()
    user = get_current_user(request)
    return templates.TemplateResponse(
        request, "setup/index.html",
        {"t": t, "company": company, "users": users, "tva_rates": tva_rates, "user": user},
    )


@router.post("/company", response_class=HTMLResponse)
async def save_company(
    request: Request,
    company_name: str = Form(...),
    address: str = Form(...),
    city: str = Form(...),
    rc: str = Form(...),
    if_number: str = Form(...),
    ice: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    session: Session = Depends(get_session),
):
    company = _get_or_create_company(session)
    company.company_name = company_name
    company.address = address
    company.city = city
    company.rc = rc
    company.if_number = if_number
    company.ice = ice
    company.phone = phone
    company.email = email
    company.is_setup_complete = True
    company.updated_at = datetime.now(timezone.utc)
    session.add(company)
    session.commit()
    flash(request, "Entreprise mise à jour")
    return RedirectResponse(url="/setup", status_code=303)


@router.post("/users", response_class=HTMLResponse)
async def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(...),
    role: str = Form("comptable"),
    session: Session = Depends(get_session),
):
    company = _get_or_create_company(session)
    existing = session.exec(select(User).where(User.username == username)).first()
    if existing:
        return RedirectResponse(url="/setup", status_code=303)
    user = User(
        company_id=company.id,
        username=username,
        hashed_password=hash_password(password),
        display_name=display_name,
        role=role,
    )
    session.add(user)
    session.commit()
    flash(request, "Utilisateur créé")
    return RedirectResponse(url="/setup", status_code=303)


@router.post("/tva", response_class=HTMLResponse)
async def save_tva_rates(
    request: Request,
    rates_json: str = Form(...),
    session: Session = Depends(get_session),
):
    import json
    from decimal import Decimal
    rates = json.loads(rates_json)
    existing = session.exec(select(TVARate)).all()
    for e in existing:
        session.delete(e)
    for r in rates:
        session.add(TVARate(rate=Decimal(str(r["rate"])), label=r["label"], is_active=r.get("is_active", True)))
    session.commit()
    return RedirectResponse(url="/setup", status_code=303)


@router.post("/users/{user_id}/delete", response_class=HTMLResponse)
async def delete_user(request: Request, user_id: str, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if user:
        session.delete(user)
        session.commit()
        flash(request, "Utilisateur supprimé")
    return RedirectResponse(url="/setup", status_code=303)


@router.post("/logo", response_class=HTMLResponse)
async def upload_logo(
    request: Request,
    logo: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    company = _get_or_create_company(session)

    # ── Validation du fichier (type + taille) ─────────────────────
    from app.services.upload_security import validate_image_upload
    content = await logo.read()
    ext = validate_image_upload(logo.filename, content)

    dest = settings.logo_dir / f"company_logo{ext}"
    dest.write_bytes(content)

    existing = [p for p in settings.logo_dir.glob("company_logo.*") if p.name != dest.name]
    for p in existing:
        p.unlink(missing_ok=True)

    company.logo_path = str(dest.relative_to(settings.data_dir.parent))
    company.updated_at = datetime.now(timezone.utc)
    session.add(company)
    session.commit()
    flash(request, "Logo mis à jour")
    return RedirectResponse(url="/setup", status_code=303)
