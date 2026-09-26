"""
Bons de commande (Purchase Orders) pour le rapprochement à 3 voies.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, DECIMAL, ForeignKey, Relationship


class PurchaseOrder(SQLModel, table=True):
    __tablename__ = "purchase_orders"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_id: str = Field(sa_column=Column(String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False))
    po_number: str = Field(max_length=50, index=True)
    supplier_id: str = Field(sa_column=Column(String(32), ForeignKey("clients.id"), nullable=False))
    issue_date: datetime = Field(sa_column=Column(DateTime(timezone=True)))
    expected_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    status: str = Field(default="draft")  # draft / sent / partially_received / fully_received / cancelled
    total_ht: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    total_tva: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    total_ttc: Decimal = Field(default=Decimal("0.00"), max_digits=14, decimal_places=2)
    notes: Optional[str] = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )

    lines: List["PurchaseOrderLine"] = Relationship(back_populates="purchase_order")


class PurchaseOrderLine(SQLModel, table=True):
    __tablename__ = "purchase_order_lines"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    po_id: str = Field(sa_column=Column(String(32), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False))
    product_id: Optional[str] = Field(default=None, sa_column=Column(String(32), ForeignKey("products.id")))
    description: str = Field(max_length=500)
    quantity: Decimal = Field(max_digits=10, decimal_places=3)
    received_quantity: Decimal = Field(default=Decimal("0"), max_digits=10, decimal_places=3)
    unit_price: Decimal = Field(max_digits=12, decimal_places=2)
    tva_rate: Decimal = Field(max_digits=5, decimal_places=4)
    line_total_ht: Decimal = Field(max_digits=14, decimal_places=2)
    line_total_tva: Decimal = Field(max_digits=14, decimal_places=2)
    line_total_ttc: Decimal = Field(max_digits=14, decimal_places=2)
    sort_order: int = Field(default=0)

    purchase_order: PurchaseOrder = Relationship(back_populates="lines")
