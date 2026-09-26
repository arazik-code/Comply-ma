import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, ForeignKey


class Client(SQLModel, table=True):
    __tablename__ = "clients"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_id: str = Field(sa_column=Column(String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False))
    name: str = Field(max_length=255)
    ice: Optional[str] = Field(default=None, max_length=50)
    rc: Optional[str] = Field(default=None, max_length=50)
    if_number: Optional[str] = Field(default=None, max_length=50)
    address: Optional[str] = Field(default=None, sa_type=Text)
    city: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    is_active: bool = Field(default=True)
    portal_enabled: bool = Field(default=False)
    portal_password_hash: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
