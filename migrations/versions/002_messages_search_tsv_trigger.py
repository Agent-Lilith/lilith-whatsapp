"""Backfill and trigger for messages.search_tsv from body_text.

Revision ID: 002_search_tsv
Revises: 001_initial
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op

revision: str = "002_search_tsv"
down_revision: Union[str, Sequence[str], None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE messages
        SET search_tsv = to_tsvector('simple', COALESCE(body_text, ''))
        WHERE search_tsv IS NULL AND body_text IS NOT NULL
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION messages_search_tsv_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_tsv := to_tsvector('simple', COALESCE(NEW.body_text, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER messages_search_tsv_trigger
        BEFORE INSERT OR UPDATE OF body_text ON messages
        FOR EACH ROW EXECUTE PROCEDURE messages_search_tsv_update()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS messages_search_tsv_trigger ON messages")
    op.execute("DROP FUNCTION IF EXISTS messages_search_tsv_update()")
