import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, ForeignKey


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_id: str = Field(sa_column=Column(String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False))
    entity_type: str = Field(max_length=50)
    entity_id: str = Field(max_length=36)
    action: str = Field(max_length=50)
    old_values: Optional[str] = Field(default=None, sa_type=Text)
    new_values: Optional[str] = Field(default=None, sa_type=Text)
    user_id: Optional[str] = Field(default=None, sa_column=Column(String(32), ForeignKey("users.id")))
    ip_address: Optional[str] = Field(default=None, max_length=45)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
