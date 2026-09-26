import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, DECIMAL, ForeignKey


class Payment(SQLModel, table=True):
    __tablename__ = "payments"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    invoice_id: str = Field(sa_column=Column(String(32), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False))
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    payment_date: datetime = Field(sa_column=Column(DateTime(timezone=True)))
    payment_method: str = Field(max_length=50)
    reference: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
