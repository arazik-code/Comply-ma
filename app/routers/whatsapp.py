"""
Pont WhatsApp — webhook de réception et route de test.
Inclut la vérification de signature Meta (X-Hub-Signature-256).
"""
import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlmodel import Session

from app.config import settings
from app.database import get_session
from app.models.whatsapp_message import WhatsAppMessage
from app.services.whatsapp.client import WhatsAppClient
from app.services.auth import require_auth
from app.services.audit_service import log as audit_log

logger = logging.getLogger("app.routers.whatsapp")
router = APIRouter()


def verify_meta_signature(request_body: bytes, signature_header: str) -> bool:
    """
    Vérifie la signature Meta (X-Hub-Signature-256) du webhook WhatsApp.
    Utilise HMAC-SHA256 avec l'app_secret comme clé.
    """
    if not signature_header or not settings.whatsapp_app_secret:
        return False
    expected = "sha256=" + hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"),
        request_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@router.get("/webhook")
async def whatsapp_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        logger.info("whatsapp_webhook_verified")
        return PlainTextResponse(challenge, status_code=200)

    logger.warning("whatsapp_webhook_verify_failed", extra={"token": token})
    return PlainTextResponse("Forbidden", status_code=403)


@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    body = await request.body()

    # Vérifier la signature Meta si configurée
    signature = request.headers.get("X-Hub-Signature-256", "")
    if settings.whatsapp_app_secret and not verify_meta_signature(body, signature):
        logger.warning("whatsapp_webhook_signature_invalid")
        return PlainTextResponse("Invalid signature", status_code=403)

    payload = await request.json()
    logger.info("whatsapp_webhook_received", extra={"payload_keys": list(payload.keys())})
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    from_num = msg.get("from", "")
                    msg_id = msg.get("id", "")
                    text_body = ""
                    if msg.get("type") == "text":
                        text_body = msg.get("text", {}).get("body", "")
                    elif msg.get("type") == "interactive":
                        text_body = str(msg.get("interactive", {}))
                    with next(get_session()) as session:
                        record = WhatsAppMessage(
                            wa_message_id=msg_id,
                            from_number=from_num,
                            body=text_body,
                            direction="inbound",
                            status="received",
                        )
                        session.add(record)
                        session.commit()
                        logger.info("whatsapp_inbound_stored", extra={"from": from_num, "body": text_body[:100]})
    except Exception as e:
        logger.error("whatsapp_webhook_parse_failed", extra={"error": str(e)})
    return {"status": "ok"}


@router.get("/test", response_class=HTMLResponse)
async def whatsapp_test_form(request: Request):
    user = require_auth(request)
    return HTMLResponse(
        content="""
        <form method="post" action="/whatsapp/test">
            <label>Numéro (format international, ex: 2126XXXXXX) :</label>
            <input name="to" required><br>
            <label>Message :</label>
            <textarea name="body" required></textarea><br>
            <button type="submit">Envoyer</button>
        </form>
        """
    )


@router.post("/test")
async def whatsapp_test_send(request: Request, to: str = Form(...), body: str = Form(...)):
    require_auth(request)
    client = WhatsAppClient()
    ok = await client.send_text(to, body)
    if ok:
        return HTMLResponse("<p>Message envoyé ✅</p><a href='/whatsapp/test'>Retour</a>")
    return HTMLResponse("<p>Échec ❌ (vérifier COMPLY_MA_WHATSAPP_API_TOKEN)</p><a href='/whatsapp/test'>Retour</a>")
