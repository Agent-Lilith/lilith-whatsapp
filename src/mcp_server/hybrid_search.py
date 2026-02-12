"""Hybrid search over WhatsApp messages: structured + fulltext + vector."""

import logging
import time
from datetime import date, datetime, time as dtime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.embeddings import Embedder
from core.models import Chat, Contact, Message

logger = logging.getLogger(__name__)


def _parse_date_bound(s: str, end_of_day: bool = False) -> datetime:
    s = s.strip()
    if not s:
        raise ValueError("Empty date string")
    if "T" in s or " " in s:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    d = date.fromisoformat(s)
    if end_of_day:
        return datetime.combine(d, dtime(23, 59, 59, 999999))
    return datetime.combine(d, dtime(0, 0, 0))


def _cap_limit(limit: int) -> int:
    return min(max(1, limit), 100)


def _apply_filters(stmt, filters: list[dict[str, Any]] | None):
    if not filters:
        return stmt
    for f in filters:
        field = f.get("field", "")
        value = f.get("value")
        if field == "chat_id" and value is not None:
            stmt = stmt.where(Message.chat_id == int(value))
        elif field == "from_me" and value is not None:
            stmt = stmt.where(Message.from_me == bool(value))
        elif field == "date_after" and value:
            stmt = stmt.where(Message.timestamp >= _parse_date_bound(str(value)))
        elif field == "date_before" and value:
            stmt = stmt.where(Message.timestamp <= _parse_date_bound(str(value), end_of_day=True))
    return stmt


def _message_to_result(
    msg: Message,
    chat_name: str | None,
    scores: dict[str, float],
    methods: list[str],
    *,
    timestamp_value: datetime | None = None,
    contact_push_name: str | None = None,
) -> dict[str, Any]:
    """Build SearchResultV1-compatible dict. Prefer timestamp_value from query row over msg.timestamp."""
    ts = timestamp_value if timestamp_value is not None else getattr(msg, "_explicit_ts", None) or msg.timestamp
    ts_iso = ts.isoformat() if ts else None
    ts_display = ts.strftime("%Y-%m-%d %H:%M") if ts else "?"

    # Build a descriptive title: use contact push name when available, else JID/number
    direction = "You" if msg.from_me else None
    if not direction:
        if contact_push_name and contact_push_name.strip():
            direction = contact_push_name.strip()
        else:
            remote = msg.remote_jid or ""
            is_group = remote.endswith("@g.us")
            if is_group and msg.participant:
                direction = msg.participant.split("@")[0]
            elif not is_group and remote:
                direction = remote.split("@")[0]
            else:
                direction = "Unknown"
    # Prefer contact push name for DM chat label when available (so we show name instead of JID)
    is_group = (msg.remote_jid or "").endswith("@g.us")
    if chat_name:
        chat_label = chat_name
    elif not is_group and contact_push_name and contact_push_name.strip():
        chat_label = contact_push_name.strip()
    else:
        chat_label = msg.remote_jid or "Chat"
    title = f"{direction} in {chat_label}" if chat_name else f"{direction} ({chat_label})"

    metadata: dict[str, Any] = {
        "chat_id": msg.chat_id,
        "remote_jid": msg.remote_jid,
        "from_me": msg.from_me,
        "message_type": msg.message_type,
    }
    if contact_push_name and contact_push_name.strip():
        metadata["contact_push_name"] = contact_push_name.strip()

    return {
        "id": str(msg.id),
        "source": "whatsapp_messages",
        "source_class": "personal",
        "title": title,
        "snippet": (msg.body_text or "")[:500],
        "timestamp": ts_iso,
        "scores": scores,
        "methods_used": methods,
        "metadata": metadata,
        "provenance": f"WhatsApp message in {chat_label} at {ts_display}",
    }


from common.search import BaseHybridSearchEngine
from core.models import Chat, Message

class HybridMessageSearchEngine(BaseHybridSearchEngine[Message]):
    """Hybrid search over WhatsApp messages using lilith-core."""

    def _apply_filters(self, stmt, filters: list[dict[str, Any]] | None):
        if not filters:
            return stmt
        for f in filters:
            field = f.get("field", "")
            value = f.get("value")
            if field == "chat_id" and value is not None:
                stmt = stmt.where(Message.chat_id == int(value))
            elif field == "from_me" and value is not None:
                stmt = stmt.where(Message.from_me == bool(value))
            elif field == "date_after" and value:
                stmt = stmt.where(Message.timestamp >= _parse_date_bound(str(value)))
            elif field == "date_before" and value:
                stmt = stmt.where(Message.timestamp <= _parse_date_bound(str(value), end_of_day=True))
        return stmt

    def _get_item_id(self, item: Message) -> int:
        return item.id

    def _structured(self, filters: list[dict] | None, limit: int) -> list[tuple[Message, float]]:
        stmt = select(Message, Chat.name, Message.timestamp).join(Chat, Message.chat_id == Chat.id)
        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(Message.timestamp.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).all()
        results = []
        for i, row in enumerate(rows):
            msg = row[0]
            msg._chat_name = row[1]
            msg._explicit_ts = row[2]  # use timestamp from result row, not ORM
            results.append((msg, max(0.3, 1.0 - i * 0.03)))
        return results

    def _fulltext(self, query: str, filters: list[dict] | None, limit: int) -> list[tuple[Message, float]]:
        tsquery = func.plainto_tsquery("simple", query)
        rank = func.ts_rank_cd(Message.search_tsv, tsquery)
        stmt = select(Message, Chat.name, rank.label("rank"), Message.timestamp).join(
            Chat, Message.chat_id == Chat.id
        )
        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.where(Message.search_tsv.isnot(None))
        stmt = stmt.where(Message.search_tsv.op("@@")(tsquery))
        stmt = stmt.order_by(rank.desc(), Message.timestamp.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).all()
        results = []
        for row in rows:
            msg = row[0]
            msg._chat_name = row[1]
            msg._explicit_ts = row[3]
            results.append((msg, min(1.0, max(0.1, float(row[2])))))
        return results

    def _vector(self, query: str, filters: list[dict] | None, limit: int) -> list[tuple[Message, float]]:
        if not self.embedder:
            return []
        embedding = self.embedder.encode_sync(query)
        if not embedding or not any(x != 0 for x in embedding):
            return []
        dist = Message.body_embedding.cosine_distance(embedding)
        stmt = select(Message, Chat.name, dist.label("distance"), Message.timestamp).join(
            Chat, Message.chat_id == Chat.id
        )
        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.where(Message.body_embedding.isnot(None))
        stmt = stmt.order_by(dist, Message.timestamp.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).all()
        results = []
        for row in rows:
            msg = row[0]
            msg._chat_name = row[1]
            msg._explicit_ts = row[3]
            results.append((msg, max(0.0, min(1.0, 1.0 - float(row[2])))))
        return results

    def _get_item_by_id(self, item_id: int, **kwargs) -> Message | None:
        return self.db.get(Message, item_id)

    def _format_result(self, item: Message, scores: dict[str, float], methods: list[str]) -> dict[str, Any]:
        chat_name = getattr(item, "_chat_name", None)
        contact_push_name: str | None = None
        try:
            # Resolve push name for the other party (person user talked to or who wrote the message)
            if item.from_me:
                # Message from user: other party is the chat (DM) or group; for DM use remote_jid
                jid = None if (item.remote_jid or "").endswith("@g.us") else item.remote_jid
            else:
                # Message from contact: other party is participant (group) or remote_jid (DM)
                jid = (item.participant if (item.remote_jid or "").endswith("@g.us") else None) or item.remote_jid
            if jid:
                contact = self.db.execute(select(Contact.push_name).where(Contact.wa_id == jid).limit(1)).first()
                if contact and contact[0]:
                    contact_push_name = contact[0]
        except Exception as e:
            logger.debug("Contact push_name lookup failed for jid=%s: %s", getattr(item, "remote_jid", None), e)
        return _message_to_result(
            item, chat_name, scores, methods, contact_push_name=contact_push_name
        )
