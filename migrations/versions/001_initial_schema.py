"""initial_schema: chats, contacts, messages with tsvector and pgvector.

Revision ID: 001_initial
Revises:
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

revision: str = "001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "chats",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("jid", sa.String(256), nullable=False),
        sa.Column("jid_pn", sa.String(256), nullable=True),
        sa.Column("name", sa.String(512), nullable=True),
        sa.Column("is_group", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chats_jid", "chats", ["jid"], unique=True)

    op.create_table(
        "contacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("wa_id", sa.String(256), nullable=False),
        sa.Column("phone_number", sa.String(32), nullable=True),
        sa.Column("lid", sa.String(256), nullable=True),
        sa.Column("push_name", sa.String(512), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_wa_id", "contacts", ["wa_id"], unique=True)

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("wa_message_id", sa.String(128), nullable=False),
        sa.Column("remote_jid", sa.String(256), nullable=False),
        sa.Column("participant", sa.String(256), nullable=True),
        sa.Column("participant_alt", sa.String(256), nullable=True),
        sa.Column("remote_jid_alt", sa.String(256), nullable=True),
        sa.Column("from_me", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_type", sa.String(64), nullable=False, server_default="text"),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("search_tsv", sa.dialects.postgresql.TSVECTOR(), nullable=True),
        sa.Column("body_embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "wa_message_id", name="uq_messages_chat_wa_message_id"),
    )
    op.create_index("ix_messages_chat_id_timestamp", "messages", ["chat_id", sa.text("timestamp DESC")], unique=False)
    op.execute(
        "CREATE INDEX ix_messages_body_embedding ON messages USING hnsw (body_embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX ix_messages_search_tsv ON messages USING GIN (search_tsv)")


def downgrade() -> None:
    op.drop_index("ix_messages_search_tsv", table_name="messages")
    op.drop_index("ix_messages_body_embedding", table_name="messages")
    op.drop_index("ix_messages_chat_id_timestamp", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_contacts_wa_id", table_name="contacts")
    op.drop_table("contacts")
    op.drop_index("ix_chats_jid", table_name="chats")
    op.drop_table("chats")
