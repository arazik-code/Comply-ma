import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, Boolean


class Company(SQLModel, table=True):
    __tablename__ = "companies"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_name: str = Field(max_length=255)
    address: str = Field(sa_type=Text)
    city: str = Field(max_length=100)
    rc: str = Field(sa_column=Column("rc", String(50), unique=True, nullable=False))
    if_number: str = Field(sa_column=Column("if_number", String(50), unique=True, nullable=False))
    ice: str = Field(sa_column=Column("ice", String(50), unique=True, nullable=False))
    tva_regime: str = Field(default="assujetti")
    logo_path: Optional[str] = Field(default=None, max_length=500)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    is_setup_complete: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
