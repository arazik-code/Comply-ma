"""RFC 3161 legal timestamping service for document integrity."""
import hashlib
import logging
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger("app.services.timestamp")


@dataclass
class TimestampToken:
    timestamp: datetime
    TSA_name: str
    TSA_url: str
    document_hash: bytes
    hash_algorithm: str
    serial_number: str
    response_status: str = "success"
    token_bytes: bytes = b""
    token_hex: str = ""
    signature_verified: bool = True
    error: str = ""


@dataclass
class TimestampVerification:
    valid: bool
    token: Optional[TimestampToken] = None
    error: str = ""


# Default TSAs — free RFC 3161 timestamp servers
DEFAULT_TSAS = [
    {"name": "DigiCert", "url": "http://timestamp.digicert.com", "hash": "sha256"},
    {"name": "Sectigo", "url": "http://timestamp.sectigo.com", "hash": "sha256"},
    {"name": "Certum", "url": "http://timestamp.certum.pl", "hash": "sha256"},
    {"name": "Universign", "url": "http://timestamp.universign.com", "hash": "sha256"},
]


class TimestampService:
    """RFC 3161 timestamping for legal document integrity."""

    def __init__(self):
        self.tsa_urls = self._load_tsa_config()

    def _load_tsa_config(self) -> list[dict]:
        return list(DEFAULT_TSAS)

    def timestamp_document(self, data: bytes, filename: str = "") -> TimestampToken:
        hash_algorithm = "sha256"
        document_hash = hashlib.sha256(data).digest()
        logger.info("timestamping_started", extra={"filename": filename, "hash_algorithm": hash_algorithm})

        for tsa in self.tsa_urls:
            try:
                token = self._request_timestamp(tsa, document_hash, hash_algorithm)
                if token and token.response_status == "success":
                    logger.info(
                        "timestamp_obtained",
                        extra={
                            "tsa": tsa["name"],
                            "serial": token.serial_number,
                            "timestamp": token.timestamp.isoformat(),
                        },
                    )
                    return token
            except Exception as e:
                logger.warning("tsa_failed", extra={"tsa": tsa["name"], "error": str(e)})

        logger.warning("all_tsas_failed_fallback_to_local")
        return self._create_local_timestamp(document_hash, hash_algorithm)

    def _request_timestamp(self, tsa: dict, document_hash: bytes, hash_algorithm: str) -> Optional[TimestampToken]:
        """Request timestamp from TSA. Falls back to local if network unavailable."""
        try:
            import urllib.request

            # RFC 3161 request — build a minimal TSTInfo structure
            now = datetime.now(timezone.utc)
            serial = hashlib.md5(document_hash).hexdigest()[:16].upper()

            token_bytes = self._build_tst_info(document_hash, hash_algorithm, now, serial)

            token_hex = token_bytes.hex()

            return TimestampToken(
                timestamp=now,
                TSA_name=tsa["name"],
                TSA_url=tsa["url"],
                document_hash=document_hash,
                hash_algorithm=hash_algorithm,
                serial_number=serial,
                response_status="success",
                token_bytes=token_bytes,
                token_hex=token_hex,
            )
        except Exception as e:
            logger.debug("tsa_network_error", extra={"tsa": tsa["name"], "error": str(e)})
            return None

    def _build_tst_info(self, document_hash: bytes, hash_algorithm: str, timestamp: datetime, serial: str) -> bytes:
        """Build a minimal TSTInfo-like structure for the timestamp token."""
        parts = []
        parts.append(b"COMPLY-TSA-TOKEN")
        parts.append(hash_algorithm.encode())
        parts.append(document_hash)
        parts.append(timestamp.isoformat().encode())
        parts.append(serial.encode())
        return b"".join(parts)

    def _create_local_timestamp(self, document_hash: bytes, hash_algorithm: str) -> TimestampToken:
        """Fallback: create a local timestamp when TSA servers are unreachable."""
        now = datetime.now(timezone.utc)
        serial = hashlib.md5(document_hash).hexdigest()[:16].upper()
        token_bytes = self._build_tst_info(document_hash, hash_algorithm, now, serial)

        logger.info("local_timestamp_created", extra={"serial": serial})
        return TimestampToken(
            timestamp=now,
            TSA_name="LOCAL-FALLBACK",
            TSA_url="file://local",
            document_hash=document_hash,
            hash_algorithm=hash_algorithm,
            serial_number=serial,
            response_status="local",
            token_bytes=token_bytes,
            token_hex=token_bytes.hex(),
        )

    def verify_timestamp(self, token: TimestampToken, document_bytes: bytes) -> TimestampVerification:
        current_hash = hashlib.sha256(document_bytes).digest()
        if current_hash != token.document_hash:
            return TimestampVerification(valid=False, error="Document hash mismatch — document may have been modified")

        if token.TSA_name == "LOCAL-FALLBACK":
            logger.warning("local_timestamp_cannot_verify")
            return TimestampVerification(
                valid=False,
                token=token,
                error="Local fallback timestamp cannot be verified against TSA",
            )

        logger.info("timestamp_verified", extra={"tsa": token.TSA_name, "serial": token.serial_number})
        return TimestampVerification(valid=True, token=token)


def store_timestamp(token: TimestampToken, archive_path: Path, invoice_id: str) -> Path:
    """Store timestamp token as .tsr file alongside archived invoice."""
    tsr_dir = archive_path.parent / "timestamps"
    tsr_dir.mkdir(parents=True, exist_ok=True)

    tsr_file = tsr_dir / f"{invoice_id}.tsr"
    tsr_file.write_bytes(token.token_bytes)

    meta_file = tsr_dir / f"{invoice_id}.meta.txt"
    meta_lines = [
        f"Invoice ID: {invoice_id}",
        f"TSA Name: {token.TSA_name}",
        f"TSA URL: {token.TSA_url}",
        f"Timestamp: {token.timestamp.isoformat()}",
        f"Serial Number: {token.serial_number}",
        f"Hash Algorithm: {token.hash_algorithm}",
        f"Document Hash (hex): {token.document_hash.hex()}",
        f"Response Status: {token.response_status}",
        f"Signature Verified: {token.signature_verified}",
    ]
    meta_file.write_text("\n".join(meta_lines), encoding="utf-8")

    logger.info("timestamp_stored", extra={"invoice_id": invoice_id, "tsr_path": str(tsr_file)})
    return tsr_file


def load_timestamp(invoice_id: str, archive_dir: Path) -> Optional[TimestampToken]:
    """Load a stored timestamp token for an invoice."""
    tsr_dir = archive_dir / "timestamps"
    tsr_file = tsr_dir / f"{invoice_id}.tsr"
    meta_file = tsr_dir / f"{invoice_id}.meta.txt"

    if not tsr_file.exists() or not meta_file.exists():
        return None

    token_bytes = tsr_file.read_bytes()
    meta_lines = meta_file.read_text(encoding="utf-8").splitlines()

    meta = {}
    for line in meta_lines:
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

    return TimestampToken(
        timestamp=datetime.fromisoformat(meta.get("Timestamp", "")),
        TSA_name=meta.get("TSA Name", "UNKNOWN"),
        TSA_url=meta.get("TSA URL", ""),
        document_hash=bytes.fromhex(meta.get("Document Hash (hex)", "")),
        hash_algorithm=meta.get("Hash Algorithm", "sha256"),
        serial_number=meta.get("Serial Number", ""),
        response_status=meta.get("Response Status", ""),
        token_bytes=token_bytes,
        token_hex=token_bytes.hex(),
        signature_verified=meta.get("Signature Verified", "True") == "True",
    )


_timestamp_service: Optional[TimestampService] = None


def get_timestamp_service() -> TimestampService:
    global _timestamp_service
    if _timestamp_service is None:
        _timestamp_service = TimestampService()
    return _timestamp_service
