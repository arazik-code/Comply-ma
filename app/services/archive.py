import io
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models.invoice import Invoice, InvoiceLine
from app.models.company import Company
from app.models.client import Client
from app.services.pdf_generator import generate_invoice_pdf
from app.services.xml.ubl_generator import generate_ubl_invoice
from app.services.xml.cii_generator import generate_cii_invoice

logger = logging.getLogger("app.services.archive")


def build_archive_zip(
    invoice: Invoice,
    lines: list[InvoiceLine],
    company: Company,
    client: Client,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        fname = invoice.invoice_number or invoice.id

        pdf_bytes = generate_invoice_pdf(invoice, lines, company, client)
        if isinstance(pdf_bytes, bytes):
            zf.writestr(f"{fname}.pdf", pdf_bytes)

        if settings.xml_format == "cii":
            xml_bytes = generate_cii_invoice(invoice, lines, company, client)
        else:
            xml_bytes = generate_ubl_invoice(invoice, lines, company, client)
        zf.writestr(f"{fname}.xml", xml_bytes)

    return buf.getvalue()


def store_archive(invoice_id: str, zip_bytes: bytes) -> Path:
    archive_dir = Path(settings.archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / f"{invoice_id}.zip"
    dest.write_bytes(zip_bytes)
    logger.info(
        "archive_stored",
        extra={"invoice_id": invoice_id, "size": len(zip_bytes), "path": str(dest)},
    )
    return dest


def enforce_retention():
    years = settings.retention_years
    archive_dir = Path(settings.archive_dir)
    if not archive_dir.exists():
        return

    cutoff = datetime.now(timezone.utc).timestamp() - (years * 365.25 * 86400)
    removed = 0
    for f in archive_dir.glob("*.zip"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1

    if removed:
        logger.info(
            "retention_enforced",
            extra={"removed": removed, "retention_years": years},
        )
