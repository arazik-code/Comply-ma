import logging

import httpx

from app.config import settings

logger = logging.getLogger("app.services.whatsapp")


class WhatsAppClient:
    def __init__(self):
        self.api_token = settings.whatsapp_api_token
        self.phone_number_id = settings.whatsapp_phone_number_id
        self.base_url = f"https://graph.facebook.com/v18.0/{self.phone_number_id}"

    async def send_text(self, to: str, body: str) -> bool:
        if not self.api_token or not self.phone_number_id:
            logger.warning("whatsapp_not_configured")
            return False

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/messages",
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": body},
                },
                timeout=15,
            )

        if resp.is_success:
            logger.info("whatsapp_sent", extra={"to": to})
            return True

        logger.error(
            "whatsapp_failed",
            extra={"to": to, "status": resp.status_code, "body": resp.text},
        )
        return False
