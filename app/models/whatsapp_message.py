import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field, Column, String, Text, DateTime


class WhatsAppMessage(SQLModel, table=True):
    __tablename__ = "whatsapp_messages"

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        primary_key=True,
        max_length=32,
    )
    wa_message_id: Optional[str] = Field(default=None, max_length=100)
    from_number: str = Field(max_length=20)
    body: str = Field(sa_type=Text)
    direction: str = Field(max_length=10)  # "inbound" / "outbound"
    status: str = Field(default="received")  # received / processed / failed
    processed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True)),
    )
