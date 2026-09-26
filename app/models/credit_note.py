import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, DECIMAL, ForeignKey, Relationship


class CreditNote(SQLModel, table=True):
    __tablename__ = "credit_notes"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_id: str = Field(sa_column=Column(String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False))
    credit_note_number: Optional[str] = Field(default=None, max_length=50, index=True)
    original_invoice_id: str = Field(sa_column=Column(String(32), ForeignKey("invoices.id"), nullable=False))
    fiscal_year: int = Field()
    credit_note_date: datetime = Field(sa_column=Column(DateTime(timezone=True)))
    reason: str = Field(sa_type=Text)
    reason_code: Optional[str] = Field(default=None, max_length=10)  # Code DGI du motif
    status: str = Field(default="draft")  # draft / validated / submitted / cleared / sent / archived / cancelled / rejected
    is_locked: bool = Field(default=False)
    total_ht: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    total_tva: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    total_ttc: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    hash_sha256: Optional[str] = Field(default=None, max_length=128)
    hash_algorithm: Optional[str] = Field(default=None, max_length=16)
    rejected_reason: Optional[str] = Field(default=None, sa_type=Text)
    validated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    validated_by: Optional[str] = Field(default=None, sa_column=Column(String(32), ForeignKey("users.id")))
    submitted_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    cleared_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )

    lines: List["CreditNoteLine"] = Relationship(back_populates="credit_note")


class CreditNoteLine(SQLModel, table=True):
    __tablename__ = "credit_note_lines"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    credit_note_id: str = Field(sa_column=Column(String(32), ForeignKey("credit_notes.id", ondelete="CASCADE"), nullable=False))
    original_line_id: Optional[str] = Field(default=None, sa_column=Column(String(32), ForeignKey("invoice_lines.id")))
    description: str = Field(max_length=500)
    quantity: Decimal = Field(max_digits=10, decimal_places=3)
    unit_price: Decimal = Field(max_digits=12, decimal_places=2)
    tva_rate: Decimal = Field(max_digits=5, decimal_places=4)
    line_total_ht: Decimal = Field(max_digits=14, decimal_places=2)
    line_total_tva: Decimal = Field(max_digits=14, decimal_places=2)
    line_total_ttc: Decimal = Field(max_digits=14, decimal_places=2)
    sort_order: int = Field(default=0)
    unit_code: str = Field(default="C62", max_length=10)

    credit_note: CreditNote = Relationship(back_populates="lines")
