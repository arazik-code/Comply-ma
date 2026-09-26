import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, DECIMAL, ForeignKey, Relationship


class Invoice(SQLModel, table=True):
    __tablename__ = "invoices"
    __table_args__ = None  # SQLite doesn't support composite unique well

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_id: str = Field(sa_column=Column(String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True))
    invoice_number: Optional[str] = Field(default=None, max_length=50, index=True)
    fiscal_year: int = Field()
    invoice_date: datetime = Field(sa_column=Column(DateTime(timezone=True)))
    client_id: str = Field(sa_column=Column(String(32), ForeignKey("clients.id"), nullable=False, index=True))
    status: str = Field(default="draft", index=True)  # draft / validated / submitted / cleared / sent / archived / cancelled / rejected
    is_locked: bool = Field(default=False)
    payment_status: str = Field(default="pending")  # pending / paid / partial / overdue
    payment_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    payment_method: Optional[str] = Field(default=None, max_length=50)
    total_ht: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    total_tva: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    total_ttc: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    notes: Optional[str] = Field(default=None, sa_type=Text)
    validated_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    validated_by: Optional[str] = Field(default=None, sa_column=Column(String(32), ForeignKey("users.id")))
    hash_sha256: Optional[str] = Field(default=None, max_length=128)
    hash_algorithm: Optional[str] = Field(default=None, max_length=16)
    hash_chain_previous: Optional[str] = Field(default=None, max_length=128)
    rejected_reason: Optional[str] = Field(default=None, sa_type=Text)
    submitted_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    cleared_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    is_supplier_invoice: bool = Field(default=False)
    po_id: Optional[str] = Field(default=None, max_length=32)
    # Champs UBL 2.1 supplémentaires
    currency_code: str = Field(default="MAD", max_length=3)
    tax_category: Optional[str] = Field(default=None, max_length=10)
    payment_means_code: Optional[str] = Field(default=None, max_length=10)
    payment_means_text: Optional[str] = Field(default=None, max_length=200)
    delivery_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    delivery_address: Optional[str] = Field(default=None, max_length=500)
    billing_period_start: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    billing_period_end: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    previous_invoice_number: Optional[str] = Field(default=None, max_length=50)
    order_reference: Optional[str] = Field(default=None, max_length=50)
    # Allowances / charges
    allowance_amount: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    charge_amount: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    # Devise étrangère
    tax_exchange_rate: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=6)
    tax_exchange_rate_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )

    lines: List["InvoiceLine"] = Relationship(back_populates="invoice")


class InvoiceLine(SQLModel, table=True):
    __tablename__ = "invoice_lines"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    invoice_id: str = Field(sa_column=Column(String(32), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False))
    product_id: Optional[str] = Field(default=None, sa_column=Column(String(32), ForeignKey("products.id")))
    description: str = Field(max_length=500)
    quantity: Decimal = Field(max_digits=10, decimal_places=3)
    unit_price: Decimal = Field(max_digits=12, decimal_places=2)
    tva_rate: Decimal = Field(max_digits=5, decimal_places=4)
    line_total_ht: Decimal = Field(max_digits=14, decimal_places=2)
    line_total_tva: Decimal = Field(max_digits=14, decimal_places=2)
    line_total_ttc: Decimal = Field(max_digits=14, decimal_places=2)
    sort_order: int = Field(default=0)
    # Champs UBL 2.1 supplémentaires
    unit_code: str = Field(default="C62", max_length=10)
    item_classification_code: Optional[str] = Field(default=None, max_length=20)
    allowance_amount: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    charge_amount: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)

    invoice: Invoice = Relationship(back_populates="lines")
