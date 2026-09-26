import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, ForeignKey


class ClearanceRecord(SQLModel, table=True):
    __tablename__ = "clearance_records"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_id: str = Field(sa_column=Column(String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False))
    invoice_id: Optional[str] = Field(default=None, sa_column=Column(String(32), ForeignKey("invoices.id")))
    credit_note_id: Optional[str] = Field(default=None, sa_column=Column(String(32), ForeignKey("credit_notes.id")))
    status: str = Field(default="pending_dgi")
    # pending_dgi / submitted / cleared / rejected / error
    clearance_number: Optional[str] = Field(default=None, max_length=100)
    submission_timestamp: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    clearance_timestamp: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    raw_request: Optional[str] = Field(default=None, sa_type=Text)
    raw_response: Optional[str] = Field(default=None, sa_type=Text)
    error_code: Optional[str] = Field(default=None, max_length=50)
    error_message: Optional[str] = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
