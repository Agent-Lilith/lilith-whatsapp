"""Add phone_number column to messages.

Revision ID: 003_msg_sender_fields
Revises: 002_search_tsv
Create Date: 2026-02-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_msg_sender_fields"
down_revision: Union[str, Sequence[str], None] = "002_search_tsv"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("phone_number", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "phone_number")
