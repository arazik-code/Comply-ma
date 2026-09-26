import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import init_db, engine, get_session
from app.models import *  # noqa: F401, F403 — force SQLModel metadata registration
from app.i18n import get_translator
from app.templating import templates
from app.services.csrf import get_csrf_token
templates.env.globals["csrf_token"] = get_csrf_token
from app.services.auth import authenticate_user, login_user, logout_user, require_auth, get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.archive_dir.mkdir(parents=True, exist_ok=True)
    settings.logo_dir.mkdir(parents=True, exist_ok=True)
    settings.cert_dir.mkdir(parents=True, exist_ok=True)
    from app.logging_config import setup_logging
    setup_logging()
    import logging
    logger = logging.getLogger("app")
    init_db()
    from app.services.xml.signature import generate_self_signed_cert
    generate_self_signed_cert()
    from app.services.archive import enforce_retention
    try:
        enforce_retention()
    except Exception:
        logger.warning("retention_enforcement_failed", exc_info=True)
    # Traiter la file d'attente de clearance au démarrage
    from app.services.clearance_queue import process_queue
    try:
        process_queue()
    except Exception:
        logger.warning("clearance_queue_processing_failed", exc_info=True)
    # Initialiser la file d'attente de tâches
    from app.services.task_queue import get_task_queue
    try:
        queue = get_task_queue()
        logger.info("task_queue_initialized", extra=queue.get_stats())
    except Exception:
        logger.warning("task_queue_init_failed", exc_info=True)
    logger.info("app_started", extra={"version": settings.app_version})

    # ── Avertissements de configuration production ────────────────
    if settings.environment == "production":
        if settings.is_default_secret:
            raise RuntimeError(
                "COMPLY_MA_SECRET_KEY est la valeur par défaut — refusez de démarrer en production. "
                "Générez une clé : python -c 'import secrets; print(secrets.token_urlsafe(48))'"
            )
        if settings.debug:
            raise RuntimeError("COMPLY_MA_DEBUG=true est interdit en production.")
        if settings.clearance_provider == "mock":
            logger.warning(
                "clearance_provider_is_mock",
                extra={"hint": "Les factures seront marquées 'cleared' sans transmission DGI réelle."},
            )
        if not settings.pkcs12_cert_path:
            logger.warning(
                "xml_signing_self_signed",
                extra={"hint": "Configurez COMPLY_MA_PKCS12_CERT_PATH pour un certificat de production."},
            )

    yield
    engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# En-têtes de sécurité + rate limiting login (middleware externe, sans lecture du body)
from app.services.security_middleware import SecurityHeadersRateLimitMiddleware
app.add_middleware(SecurityHeadersRateLimitMiddleware)

app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, max_age=settings.session_max_age,
                   same_site="lax", https_only=settings.https_only)

# Protection CSRF globale — dépendance appliquée à tous les routers (post-route,
# après session middleware, sans consommer le body des formulaires)
from app.services.csrf import verify_csrf_dependency

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    from fastapi.responses import HTMLResponse
    from app.templating import templates
    return templates.TemplateResponse(request, "404.html", status_code=404)


@app.exception_handler(500)
async def server_error(request: Request, exc):
    from fastapi.responses import HTMLResponse
    from app.templating import templates
    return templates.TemplateResponse(request, "500.html", status_code=500)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Landing page marketing — CTA Connexion ou Mon espace selon la session."""
    user = get_current_user(request)
    return templates.TemplateResponse(request, "landing.html", {"user": user})


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}


_FAVICON_SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#c89b3c" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect width="24" height="24" rx="5" fill="#0f1e36" stroke="none"/><path d="M15 5H8a1.5 1.5 0 0 0-1.5 1.5v11A1.5 1.5 0 0 0 8 19h8a1.5 1.5 0 0 0 1.5-1.5V7.5z"/><polyline points="15 5 15 9.5 17.5 9.5"/><line x1="14.5" y1="12.5" x2="9.5" y2="12.5"/><line x1="14.5" y1="15.5" x2="9.5" y2="15.5"/></svg>'''


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/logo")
async def company_logo():
    from app.database import get_session
    from app.models.company import Company
    from fastapi.responses import FileResponse
    from sqlmodel import select
    from pathlib import Path
    with next(get_session()) as session:
        company = session.exec(select(Company)).first()
    if company and company.logo_path:
        p = Path(company.logo_path)
        if p.exists():
            return FileResponse(str(p), media_type="image/png")
    return Response(status_code=204)


# --- Langue ---
@app.get("/lang/{lang}")
async def set_language(lang: str, request: Request):
    if lang in ("fr", "ar"):
        request.session["lang"] = lang
    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=303)


# --- Authentification ---
@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    t = get_translator(request)
    return templates.TemplateResponse(request, "login.html", {"t": t})


@app.post("/login", response_class=HTMLResponse, dependencies=[Depends(verify_csrf_dependency)])
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session=Depends(get_session),
):
    t = get_translator(request)
    user = authenticate_user(session, username, password)
    if not user:
        return templates.TemplateResponse(
            request, "login.html", {"t": t, "error": "Identifiants incorrects"},
        )
    login_user(request, user)
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    logout_user(request)
    return RedirectResponse(url="/login", status_code=303)


# --- Routers ---
def register_routers():
    from app.routers import setup, clients, products, invoices, dashboard, export, compliance, whatsapp, credit_notes

    dependencies = [Depends(verify_csrf_dependency)]
    app.include_router(setup.router, prefix="/setup", tags=["Configuration"], dependencies=dependencies)
    app.include_router(clients.router, prefix="/clients", tags=["Clients"], dependencies=dependencies)
    app.include_router(products.router, prefix="/products", tags=["Produits"], dependencies=dependencies)
    app.include_router(invoices.router, prefix="/invoices", tags=["Factures"], dependencies=dependencies)
    app.include_router(dashboard.router, prefix="/dashboard", tags=["Tableau de bord"], dependencies=dependencies)
    app.include_router(export.router, prefix="/export", tags=["Export"], dependencies=dependencies)
    app.include_router(compliance.router, prefix="/compliance", tags=["Conformité"], dependencies=dependencies)
    app.include_router(whatsapp.router, prefix="/whatsapp", tags=["WhatsApp"], dependencies=dependencies)
    app.include_router(credit_notes.router, prefix="/credit-notes", tags=["Avoirs"], dependencies=dependencies)
    from app.routers.portal import router as portal_router
    app.include_router(portal_router, tags=["Portail client"], dependencies=dependencies)
    from app.routers.search import router as search_router
    app.include_router(search_router, tags=["Recherche"], dependencies=dependencies)
    from app.routers.audit_log import router as audit_log_router
    app.include_router(audit_log_router, tags=["Journal d'audit"], dependencies=dependencies)
    from app.routers.purchase_orders import router as po_router
    app.include_router(po_router, tags=["Bons de commande"], dependencies=dependencies)
    from app.routers.supplier_invoices import router as supplier_inv_router
    app.include_router(supplier_inv_router, tags=["Factures fournisseurs"], dependencies=dependencies)
    from app.routers.goods_receipts import router as gr_router
    app.include_router(gr_router, tags=["Bons de réception"], dependencies=dependencies)
    from app.routers.analytics import router as analytics_router
    app.include_router(analytics_router, prefix="/analytics", tags=["Analytics"], dependencies=dependencies)
    from app.routers.cabinet import router as cabinet_router
    app.include_router(cabinet_router, prefix="/cabinet", tags=["Cabinet"], dependencies=dependencies)


register_routers()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.debug)
