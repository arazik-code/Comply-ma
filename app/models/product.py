import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, DECIMAL, Boolean, ForeignKey


class Product(SQLModel, table=True):
    __tablename__ = "products"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_id: str = Field(sa_column=Column(String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False))
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, sa_type=Text)
    unit_price: Decimal = Field(max_digits=12, decimal_places=2, sa_column=Column(DECIMAL(12, 2)))
    tva_rate_id: str = Field(sa_column=Column(String(32), ForeignKey("tva_rates.id"), nullable=False))
    unit: str = Field(default="pièce", max_length=50)
    reference: Optional[str] = Field(default=None, max_length=100)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
