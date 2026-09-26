import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session

from app.models.audit import AuditLog


def log(
    session: Session,
    company_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    user_id: Optional[str] = None,
    old_values: Optional[str] = None,
    new_values: Optional[str] = None,
    ip_address: Optional[str] = None,
):
    """
    Écrit une entrée immutable dans le journal d'audit.
    """
    entry = AuditLog(
        company_id=company_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_values=old_values,
        new_values=new_values,
        user_id=user_id,
        ip_address=ip_address,
        timestamp=datetime.now(timezone.utc),
    )
    session.add(entry)
    session.flush()
