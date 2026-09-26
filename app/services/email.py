import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import Optional

from app.config import settings

logger = logging.getLogger("app.services.email")


async def send_invoice_email(
    to: str,
    subject: str,
    body: str,
    pdf_bytes: Optional[bytes] = None,
    xml_bytes: Optional[bytes] = None,
    invoice_number: str = "invoice",
) -> bool:
    if not settings.smtp_host or not settings.smtp_from:
        logger.warning("smtp_not_configured")
        return False

    msg = MIMEMultipart("mixed")
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain", "utf-8"))

    if pdf_bytes:
        part = MIMEApplication(pdf_bytes, _subtype="pdf")
        part.add_header("Content-Disposition", f"attachment; filename={invoice_number}.pdf")
        msg.attach(part)

    if xml_bytes:
        part = MIMEApplication(xml_bytes, _subtype="xml")
        part.add_header("Content-Disposition", f"attachment; filename={invoice_number}.xml")
        msg.attach(part)

    try:
        import aiosmtplib

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            use_tls=settings.smtp_tls,
            timeout=30,
        )
        logger.info("email_sent", extra={"to": to, "subject": subject})
        return True
    except Exception as e:
        logger.error("email_failed", extra={"to": to, "error": str(e)})
        return False
