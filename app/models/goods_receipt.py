"""
Modèle Bon de Réception (Goods Receipt) — 3-way matching.

Lie un bon de commande (PO) aux quantités effectivement reçues
pour le rapprochement avec la facture fournisseur.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, ForeignKey, Relationship


class GoodsReceipt(SQLModel, table=True):
    __tablename__ = "goods_receipts"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_id: str = Field(sa_column=Column(String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False))
    po_id: str = Field(sa_column=Column(String(32), ForeignKey("purchase_orders.id"), nullable=False, index=True))
    gr_number: str = Field(max_length=50, index=True)
    receipt_date: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    received_by: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, sa_type=Text)
    status: str = Field(default="draft")  # draft / confirmed / matched
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )

    lines: List["GoodsReceiptLine"] = Relationship(back_populates="goods_receipt")


class GoodsReceiptLine(SQLModel, table=True):
    __tablename__ = "goods_receipt_lines"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    goods_receipt_id: str = Field(sa_column=Column(String(32), ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False))
    po_line_id: str = Field(sa_column=Column(String(32), ForeignKey("purchase_order_lines.id"), nullable=False))
    product_id: Optional[str] = Field(default=None, sa_column=Column(String(32), ForeignKey("products.id")))
    description: str = Field(max_length=500)
    quantity_received: Decimal = Field(max_digits=10, decimal_places=3)
    quantity_expected: Decimal = Field(max_digits=10, decimal_places=3)
    condition: str = Field(default="good")  # good / damaged / rejected
    notes: Optional[str] = Field(default=None, max_length=500)
    sort_order: int = Field(default=0)

    goods_receipt: GoodsReceipt = Relationship(back_populates="lines")
