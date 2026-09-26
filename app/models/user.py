import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, DateTime, Boolean, ForeignKey


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    company_id: str = Field(sa_column=Column(String(32), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False))
    username: str = Field(sa_column=Column(String(100), unique=True, nullable=False))
    hashed_password: str = Field(max_length=255)
    display_name: str = Field(max_length=255)
    role: str = Field(default="comptable")  # owner / comptable / cabinet_admin / client_user
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
