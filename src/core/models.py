"""WhatsApp schema: chats, contacts, messages. Baileys v7–aware (LID/PN)."""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

EMBEDDING_DIM = 768


class Base(DeclarativeBase):
    pass


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    jid: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    jid_pn: Mapped[str | None] = mapped_column(String(256), nullable=True)
    name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    wa_id: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lid: Mapped[str | None] = mapped_column(String(256), nullable=True)
    push_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    wa_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    remote_jid: Mapped[str] = mapped_column(String(256), nullable=False)
    participant: Mapped[str | None] = mapped_column(String(256), nullable=True)
    participant_alt: Mapped[str | None] = mapped_column(String(256), nullable=True)
    remote_jid_alt: Mapped[str | None] = mapped_column(String(256), nullable=True)
    from_me: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message_type: Mapped[str] = mapped_column(String(64), default="text")
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    search_tsv = mapped_column(TSVECTOR, nullable=True)
    body_embedding: Mapped[Vector | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )

    chat: Mapped["Chat"] = relationship(back_populates="messages")

    __table_args__ = (
        UniqueConstraint(
            "chat_id", "wa_message_id", name="uq_messages_chat_wa_message_id"
        ),
    )
