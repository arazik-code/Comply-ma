import uuid
from decimal import Decimal
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, Boolean, DECIMAL


class TVARate(SQLModel, table=True):
    __tablename__ = "tva_rates"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    rate: Decimal = Field(max_digits=5, decimal_places=4, sa_column=Column(DECIMAL(5, 4), unique=True, nullable=False))
    label: str = Field(max_length=255)
    is_active: bool = Field(default=True)
