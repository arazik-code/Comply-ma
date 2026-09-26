"""
Cabinet model — one fiduciaire manages many client companies.

Each client company has its own SQLite database file for data isolation.
The cabinet model stores the mapping and metadata.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime, Boolean, Integer, ForeignKey


class Cabinet(SQLModel, table=True):
    """A fiduciaire accounting firm."""
    __tablename__ = "cabinets"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True, max_length=32)
    name: str = Field(max_length=255)  # Firm name
    ice: Optional[str] = Field(default=None, max_length=15)
    address: Optional[str] = Field(default=None, sa_type=Text)
    city: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    # White-label
    logo_path: Optional[str] = Field(default=None, max_length=500)
    brand_name: Optional[str] = Field(default=None, max_length=255)  # Custom brand for clients
    brand_color: str = Field(default="#1a3a5c", max_length=7)  # Hex color
    # Config
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class ClientCompany(SQLModel, table=True):
    """A client company managed by a cabinet. Maps to a separate SQLite DB."""
    __tablename__ = "client_companies"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True, max_length=32)
    cabinet_id: str = Field(sa_column=Column(String(32), ForeignKey("cabinets.id", ondelete="CASCADE"), nullable=False, index=True))
    company_name: str = Field(max_length=255)
    ice: Optional[str] = Field(default=None, max_length=15)
    rc: Optional[str] = Field(default=None, max_length=50)
    if_number: Optional[str] = Field(default=None, max_length=50)
    # Database isolation — each client gets their own SQLite file
    db_path: str = Field(max_length=500)  # Relative path to client SQLite file
    # Status
    status: str = Field(default="active")  # active | inactive | setup_pending
    compliance_score: int = Field(default=0)
    compliance_grade: str = Field(default="N/A", max_length=2)
    last_audit_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    # DGI deadline (based on turnover tier)
    dgi_deadline: Optional[str] = Field(default=None, max_length=50)  # e.g., "2026-07" or "2027-01"
    turnover_tier: Optional[str] = Field(default=None, max_length=20)  # TPE | PME | medium
    # Metadata
    invoice_count: int = Field(default=0)
    client_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
