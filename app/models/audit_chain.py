"""
Chaîne cryptographique d'audit — garantit l'intégrité immuable des journaux.
Chaque entrée inclut le hash de l'entrée précédente, créant une chaîne
qui rend toute modification détectable.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, ForeignKey


class AuditChainEntry(SQLModel, table=True):
    """
    Entrée de la chaîne cryptographique d'audit.
    Chaque entrée contient le hash de l'entrée précédente,
    rendant toute modification rétroactive détectable.
    """
    __tablename__ = "audit_chain"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_id: str = Field(sa_column=Column(String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True))
    previous_hash: str = Field(max_length=128, nullable=False)
    current_hash: str = Field(max_length=128, nullable=False, index=True)
    entity_type: str = Field(max_length=50)
    entity_id: str = Field(max_length=36)
    action: str = Field(max_length=50)
    user_id: Optional[str] = Field(default=None, sa_column=Column(String(32), ForeignKey("users.id")))
    ip_address: Optional[str] = Field(default=None, max_length=45)
    details: Optional[str] = Field(default=None, sa_type=Text)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


def compute_entry_hash(previous_hash: str, entity_type: str, entity_id: str,
                       action: str, user_id: str, details: str, timestamp: str) -> str:
    """
    Calcule le hash SHA-256 d'une entrée d'audit.
    Inclut le hash précédent pour créer la chaîne cryptographique.
    """
    payload = f"{previous_hash}|{entity_type}|{entity_id}|{action}|{user_id}|{details}|{timestamp}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_chain_entry(
    session,
    company_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    user_id: str = "",
    ip_address: str = "",
    details: Optional[dict] = None,
) -> AuditChainEntry:
    """
    Crée une nouvelle entrée dans la chaîne d'audit.
    Récupère automatiquement le hash de la dernière entrée.
    """
    from sqlmodel import select

    # Trouver la dernière entrée de la chaîne
    last_entry = session.exec(
        select(AuditChainEntry)
        .where(AuditChainEntry.company_id == company_id)
        .order_by(AuditChainEntry.timestamp.desc())
        .limit(1)
    ).first()

    previous_hash = last_entry.current_hash if last_entry else "0" * 64
    now = datetime.now(timezone.utc)
    details_str = json.dumps(details, default=str, ensure_ascii=False) if details else ""

    current_hash = compute_entry_hash(
        previous_hash, entity_type, entity_id, action,
        user_id, details_str, now.isoformat()
    )

    entry = AuditChainEntry(
        company_id=company_id,
        previous_hash=previous_hash,
        current_hash=current_hash,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        user_id=user_id or None,
        ip_address=ip_address or None,
        details=details_str or None,
        timestamp=now,
    )
    session.add(entry)
    session.flush()
    return entry


def verify_chain(session, company_id: str, start_date: Optional[datetime] = None,
                 end_date: Optional[datetime] = None) -> tuple[bool, str]:
    """
    Vérifie l'intégrité de la chaîne d'audit pour une société.
    Vérifie que chaque hash correspond bien au contenu de l'entrée
    et au hash de l'entrée précédente.

    Returns:
        (is_valid, error_message)
    """
    from sqlmodel import select

    stmt = select(AuditChainEntry).where(AuditChainEntry.company_id == company_id)
    if start_date:
        stmt = stmt.where(AuditChainEntry.timestamp >= start_date)
    if end_date:
        stmt = stmt.where(AuditChainEntry.timestamp <= end_date)

    entries = session.exec(stmt.order_by(AuditChainEntry.timestamp)).all()

    if not entries:
        return True, "Aucune entrée à vérifier"

    expected_previous = "0" * 64
    for i, entry in enumerate(entries):
        # Vérifier le lien avec l'entrée précédente
        if entry.previous_hash != expected_previous:
            return False, f"Entrée {i+1} ({entry.id}): previous_hash ne correspond pas (chain break)"

        # Recalculer le hash
        expected_hash = compute_entry_hash(
            entry.previous_hash, entry.entity_type, entry.entity_id,
            entry.action, entry.user_id or "", entry.details or "",
            entry.timestamp.isoformat()
        )
        if entry.current_hash != expected_hash:
            return False, f"Entrée {i+1} ({entry.id}): hash invalide (modification détectée)"

        expected_previous = entry.current_hash

    return True, f"Chaîne vérifiée: {len(entries)} entrées intactes"


def get_chain_stats(session, company_id: str) -> dict:
    """Retourne des statistiques sur la chaîne d'audit."""
    from sqlmodel import func

    total = session.exec(
        select(func.count()).select_from(AuditChainEntry).where(AuditChainEntry.company_id == company_id)
    ).one()

    first_entry = session.exec(
        select(AuditChainEntry).where(AuditChainEntry.company_id == company_id)
        .order_by(AuditChainEntry.timestamp).limit(1)
    ).first()

    last_entry = session.exec(
        select(AuditChainEntry).where(AuditChainEntry.company_id == company_id)
        .order_by(AuditChainEntry.timestamp.desc()).limit(1)
    ).first()

    return {
        "total_entries": total,
        "first_entry_date": first_entry.timestamp.isoformat() if first_entry else None,
        "last_entry_date": last_entry.timestamp.isoformat() if last_entry else None,
        "chain_head": last_entry.current_hash if last_entry else None,
    }
