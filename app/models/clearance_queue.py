"""
File d'attente de clearance DGI — stocke les factures en attente d'envoi.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, Integer, ForeignKey


class ClearanceQueueItem(SQLModel, table=True):
    __tablename__ = "clearance_queue"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_id: str = Field(sa_column=Column(String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False))
    invoice_id: str = Field(sa_column=Column(String(32), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True))
    status: str = Field(default="pending")  # pending / processing / success / failed
    attempt_count: int = Field(default=0)
    max_attempts: int = Field(default=5)
    last_error: Optional[str] = Field(default=None, sa_type=Text)
    error_code: Optional[str] = Field(default=None, max_length=50)
    priority: int = Field(default=0)  # 0=normal, 1=high, 2=critical
    locked_by: Optional[str] = Field(default=None, max_length=100)
    locked_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    completed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
    next_retry_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
