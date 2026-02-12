"""Backfill body_embedding for messages that have body_text but no embedding. Run after Bun sync."""
import logging
from typing import List

from sqlalchemy import select, update

from core.database import db_session
from core.embeddings import Embedder
from core.models import Message

logger = logging.getLogger(__name__)

BATCH_SIZE = 32


def run_embed_backfill(batch_size: int = BATCH_SIZE, limit: int | None = None) -> int:
    """
    Select messages where body_embedding IS NULL and body_text IS NOT NULL;
    call embedding API and write body_embedding. Returns total messages updated.
    """
    embedder = Embedder()
    total_updated = 0
    while True:
        with db_session() as db:
            stmt = (
                select(Message.id, Message.body_text)
                .where(Message.body_embedding.is_(None))
                .where(Message.body_text.isnot(None))
                .where(Message.body_text != "")
                .limit(batch_size)
            )
            rows = db.execute(stmt).all()
            if not rows:
                break
            ids = [r[0] for r in rows]
            texts: List[str] = [r[1] or "" for r in rows]
        try:
            embeddings = embedder.encode_sync(texts)
        except Exception as e:
            logger.exception("Embedding API failed: %s", e)
            raise
        if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
            pass  # list of lists
        elif isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], (int, float)):
            embeddings = [embeddings]  # single vector
        else:
            embeddings = list(embeddings) if embeddings else []
        if len(embeddings) != len(ids):
            logger.warning("Embedding count %d != batch size %d", len(embeddings), len(ids))
        with db_session() as db:
            for mid, vec in zip(ids, embeddings):
                if vec and len(vec) > 0:
                    db.execute(update(Message).where(Message.id == mid).values(body_embedding=vec))
            # db_session commits on exit
        total_updated += len(ids)
        logger.info("Embed backfill: %d messages updated (total so far: %d)", len(ids), total_updated)
        if limit is not None and total_updated >= limit:
            break
    return total_updated
