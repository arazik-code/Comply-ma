"""
Journal d'audit — historique complet des actions avec filtres.
"""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select, func

from app.database import get_session
from app.pagination import Page, PAGE_SIZE
from app.models.audit import AuditLog
from app.services.auth import require_auth
from app.i18n import get_translator
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/audit-log", response_class=HTMLResponse)
async def audit_log_view(
    request: Request,
    entity_type: str = Query(""),
    action: str = Query(""),
    page: int = Query(1),
    session: Session = Depends(get_session),
):
    t = get_translator(request)
    user = require_auth(request)
    company_id = user["company_id"]

    stmt = select(AuditLog).where(AuditLog.company_id == company_id)
    count_stmt = select(func.count()).select_from(AuditLog).where(AuditLog.company_id == company_id)

    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
        count_stmt = count_stmt.where(AuditLog.entity_type == entity_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)

    total = session.exec(count_stmt).one()
    items = session.exec(
        stmt.order_by(AuditLog.timestamp.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ).all()
    page_obj = Page(items=items, page=page, page_size=PAGE_SIZE, total=total)

    # Récupérer les types d'entités et actions disponibles pour les filtres
    entity_types = session.exec(
        select(AuditLog.entity_type).where(AuditLog.company_id == company_id).distinct().order_by(AuditLog.entity_type)
    ).all()
    actions = session.exec(
        select(AuditLog.action).where(AuditLog.company_id == company_id).distinct().order_by(AuditLog.action)
    ).all()

    return templates.TemplateResponse(request, "audit_log/list.html", {
        "t": t, "user": user,
        "page_obj": page_obj,
        "entity_type": entity_type,
        "action": action,
        "entity_types": entity_types,
        "actions": actions,
    })
