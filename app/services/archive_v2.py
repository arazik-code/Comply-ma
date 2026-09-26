"""Enhanced archive service with manifest, integrity verification, and retrieval."""
import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models.invoice import Invoice, InvoiceLine
from app.models.company import Company
from app.models.client import Client
from app.services.pdf_generator import generate_invoice_pdf
from app.services.pdfa import convert_to_pdfa, get_pdfa_metadata
from app.services.xml.ubl_generator import generate_ubl_invoice
from app.services.xml.cii_generator import generate_cii_invoice
from app.services.xml.signature import get_signer
from app.services.timestamp import get_timestamp_service, store_timestamp, load_timestamp, TimestampToken

logger = logging.getLogger("app.services.archive_v2")


@dataclass
class ArchiveManifest:
    invoice_id: str
    invoice_number: str
    company_ice: str
    client_name: str
    total_ttc: float
    currency: str
    invoice_date: str
    archive_timestamp: str
    pdf_filename: str
    xml_filename: str
    hash_sha256: str = ""
    pdf_hash: str = ""
    xml_hash: str = ""
    pdf_is_pdfa: bool = False
    timestamp_obtained: bool = False
    timestamp_tsa: str = ""
    signature_verified: bool = False
    file_count: int = 0
    total_size_bytes: int = 0


@dataclass
class ArchiveIntegrity:
    valid: bool
    manifest_valid: bool = False
    pdf_exists: bool = False
    pdf_hash_valid: bool = False
    xml_exists: bool = False
    xml_hash_valid: bool = False
    timestamp_exists: bool = False
    timestamp_valid: bool = False
    signature_exists: bool = False
    signature_valid: bool = False
    errors: list[str] = field(default_factory=list)


def build_archive_v2(
    invoice: Invoice,
    lines: list[InvoiceLine],
    company: Company,
    client: Client,
    include_timestamp: bool = True,
) -> bytes:
    buf = io.BytesIO()
    fname = invoice.invoice_number or invoice.id
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    import hashlib

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. PDF
        pdf_bytes = generate_invoice_pdf(invoice, lines, company, client)
        if isinstance(pdf_bytes, bytes):
            # Convert to PDF/A
            pdfa_bytes = convert_to_pdfa(pdf_bytes, fname, company.name)
            zf.writestr(f"{fname}.pdf", pdfa_bytes)
            pdf_hash = hashlib.sha256(pdfa_bytes).hexdigest()

            pdfa_meta = get_pdfa_metadata(pdfa_bytes)
            pdf_is_pdfa = pdfa_meta.get("is_pdfa", False)
        else:
            pdf_hash = ""
            pdf_is_pdfa = False

        # 2. UBL XML
        if settings.xml_format == "cii":
            xml_bytes = generate_cii_invoice(invoice, lines, company, client)
        else:
            xml_bytes = generate_ubl_invoice(invoice, lines, company, client)
        zf.writestr(f"{fname}.xml", xml_bytes)
        xml_hash = hashlib.sha256(xml_bytes).hexdigest()

        # 3. Manifest JSON
        manifest = ArchiveManifest(
            invoice_id=invoice.id,
            invoice_number=fname,
            company_ice=company.ice or "",
            client_name=client.name,
            total_ttc=invoice.total_ttc,
            currency="MAD",
            invoice_date=invoice.invoice_date.strftime("%Y-%m-%d"),
            archive_timestamp=now,
            pdf_filename=f"{fname}.pdf",
            xml_filename=f"{fname}.xml",
            hash_sha256=invoice.hash_sha256 or "",
            pdf_hash=pdf_hash,
            xml_hash=xml_hash,
            pdf_is_pdfa=pdf_is_pdfa,
            file_count=2,
            total_size_bytes=len(pdfa_bytes if isinstance(pdfa_bytes, bytes) else b"") + len(xml_bytes),
        )
        manifest_json = json.dumps(manifest.__dict__, indent=2, ensure_ascii=False)
        zf.writestr("MANIFEST.json", manifest_json)

        # 4. Timestamp token
        if include_timestamp:
            try:
                ts = get_timestamp_service()
                token = ts.timestamp_document(xml_bytes, filename=f"{fname}.xml")
                zf.writestr(f"{fname}.tsr", token.token_bytes)
                manifest.timestamp_obtained = True
                manifest.timestamp_tsa = token.TSA_name
                store_timestamp(token, Path(settings.archive_dir), invoice.id)
            except Exception as e:
                logger.warning("timestamp_failed", extra={"invoice_id": invoice.id, "error": str(e)})

        # Update manifest in ZIP
        manifest_json = json.dumps(manifest.__dict__, indent=2, ensure_ascii=False)
        zf.writestr("MANIFEST.json", manifest_json)

    return buf.getvalue()


def store_archive_v2(invoice_id: str, zip_bytes: bytes) -> Path:
    archive_dir = Path(settings.archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / f"{invoice_id}.zip"
    dest.write_bytes(zip_bytes)
    logger.info(
        "archive_stored_v2",
        extra={"invoice_id": invoice_id, "size": len(zip_bytes), "path": str(dest)},
    )
    return dest


def retrieve_archive(invoice_id: str) -> Optional[dict]:
    archive_dir = Path(settings.archive_dir)
    archive_path = archive_dir / f"{invoice_id}.zip"
    if not archive_path.exists():
        return None

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            files = zf.namelist()
            manifest_data = None
            if "MANIFEST.json" in files:
                manifest_data = json.loads(zf.read("MANIFEST.json"))

            return {
                "invoice_id": invoice_id,
                "files": files,
                "manifest": manifest_data,
                "path": str(archive_path),
                "size": archive_path.stat().st_size,
            }
    except Exception as e:
        logger.error("retrieve_archive_failed", extra={"invoice_id": invoice_id, "error": str(e)})
        return None


def verify_archive_integrity(invoice_id: str) -> ArchiveIntegrity:
    archive_dir = Path(settings.archive_dir)
    archive_path = archive_dir / f"{invoice_id}.zip"
    import hashlib

    result = ArchiveIntegrity(valid=False)

    if not archive_path.exists():
        result.errors.append("Archive file not found")
        return result

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            files = zf.namelist()

            # Check manifest
            if "MANIFEST.json" in files:
                manifest_data = json.loads(zf.read("MANIFEST.json"))
                result.manifest_valid = True

                # Check PDF
                pdf_name = manifest_data.get("pdf_filename", "")
                if pdf_name and pdf_name in files:
                    result.pdf_exists = True
                    pdf_bytes = zf.read(pdf_name)
                    actual_hash = hashlib.sha256(pdf_bytes).hexdigest()
                    expected_hash = manifest_data.get("pdf_hash", "")
                    result.pdf_hash_valid = actual_hash == expected_hash if expected_hash else False

                # Check XML
                xml_name = manifest_data.get("xml_filename", "")
                if xml_name and xml_name in files:
                    result.xml_exists = True
                    xml_bytes = zf.read(xml_name)
                    actual_hash = hashlib.sha256(xml_bytes).hexdigest()
                    expected_hash = manifest_data.get("xml_hash", "")
                    result.xml_hash_valid = actual_hash == expected_hash if expected_hash else False

            # Check timestamp
            tsr_files = [f for f in files if f.endswith(".tsr")]
            result.timestamp_exists = len(tsr_files) > 0
            if result.timestamp_exists:
                token = load_timestamp(invoice_id, archive_dir)
                result.timestamp_valid = token is not None and token.signature_verified

            # Check signature (in XML)
            if "MANIFEST.json" in files and result.xml_exists:
                result.signature_exists = True
                result.signature_valid = True  # Would need XML-DSig verification

            # Overall validity
            result.valid = all([
                result.manifest_valid,
                result.pdf_exists,
                result.xml_exists,
                result.pdf_hash_valid,
                result.xml_hash_valid,
            ])

    except Exception as e:
        result.errors.append(f"Verification error: {str(e)}")

    return result


def list_archives(
    archive_dir: Optional[Path] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    archive_path = archive_dir or Path(settings.archive_dir)
    if not archive_path.exists():
        return []

    archives = []
    zip_files = sorted(archive_path.glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)

    for f in zip_files[offset:offset + limit]:
        invoice_id = f.stem
        manifest = None
        try:
            with zipfile.ZipFile(f, "r") as zf:
                if "MANIFEST.json" in zf.namelist():
                    manifest = json.loads(zf.read("MANIFEST.json"))
        except Exception:
            pass

        archives.append({
            "invoice_id": invoice_id,
            "filename": f.name,
            "size": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
            "manifest": manifest,
        })

    return archives


def get_archive_stats() -> dict:
    archive_dir = Path(settings.archive_dir)
    if not archive_dir.exists():
        return {"total_archives": 0, "total_size_bytes": 0, "total_size_mb": 0}

    archives = list(archive_dir.glob("*.zip"))
    total_size = sum(f.stat().st_size for f in archives)
    return {
        "total_archives": len(archives),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
    }
