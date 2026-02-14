"""Hybrid search over WhatsApp messages: structured + fulltext + vector."""

import logging
from datetime import date, datetime
from datetime import time as dtime
from typing import Any

from sqlalchemy import coalesce, func, or_, select

from core.models import Chat, Contact, Message

logger = logging.getLogger(__name__)


def _resolve_contact_for_jid(db, jid: str | None) -> tuple[str | None, str | None]:
    """Resolve contact for a message/chat JID (PN or LID). Returns (push_name, contact_wa_id).

    Matches by wa_id = jid OR lid = jid (for @lid) OR phone_number (for @s.whatsapp.net),
    so one contact row is found whether the message uses LID or PN for the same person.
    See docs/contact-matching.md.
    """
    if not jid or not jid.strip():
        return (None, None)
    jid = jid.strip()
    conditions = [Contact.wa_id == jid]
    if jid.endswith("@s.whatsapp.net"):
        number = jid.removesuffix("@s.whatsapp.net")
        conditions.extend([Contact.phone_number == number, Contact.phone_number == jid])
    elif jid.endswith("@lid"):
        conditions.append(Contact.lid == jid)
    row = db.execute(
        select(Contact.push_name, Contact.wa_id).where(or_(*conditions)).limit(1)
    ).first()
    if not row:
        return (None, None)
    return (row[0] if row[0] else None, row[1])


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
            stmt = stmt.where(
                Message.timestamp <= _parse_date_bound(str(value), end_of_day=True)
            )
    return stmt


def _message_to_result(
    msg: Message,
    chat_name: str | None,
    scores: dict[str, float],
    methods: list[str],
    *,
    timestamp_value: datetime | None = None,
    contact_push_name: str | None = None,
    contact_wa_id: str | None = None,
) -> dict[str, Any]:
    """Build SearchResultV1-compatible dict. contact_* are from contacts (matched by message JID: wa_id or lid or phone_number)."""
    ts = (
        timestamp_value
        if timestamp_value is not None
        else getattr(msg, "_explicit_ts", None) or msg.timestamp
    )
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
    title = (
        f"{direction} in {chat_label}" if chat_name else f"{direction} ({chat_label})"
    )

    metadata: dict[str, Any] = {
        "chat_id": msg.chat_id,
        "remote_jid": msg.remote_jid,
        "from_me": msg.from_me,
        "message_type": msg.message_type,
    }
    if contact_push_name and contact_push_name.strip():
        metadata["contact_push_name"] = contact_push_name.strip()
    if contact_wa_id:
        metadata["contact_wa_id"] = contact_wa_id

    return {
        "id": str(msg.id),
        "source": "whatsapp",
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

from core.models import Message


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
                stmt = stmt.where(
                    Message.timestamp <= _parse_date_bound(str(value), end_of_day=True)
                )
        return stmt

    def _get_item_id(self, item: Message) -> int:
        return item.id

    def _structured(
        self, filters: list[dict] | None, limit: int
    ) -> list[tuple[Message, float]]:
        stmt = select(Message, Chat.name, Message.timestamp).join(
            Chat, Message.chat_id == Chat.id
        )
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

    def _fulltext(
        self, query: str, filters: list[dict] | None, limit: int
    ) -> list[tuple[Message, float]]:
        tsquery = func.plainto_tsquery("simple", query)
        rank = func.ts_rank_cd(Message.search_tsv, tsquery)
        stmt = select(Message, Chat.name, rank.label("rank"), Message.timestamp).join(
            Chat, Message.chat_id == Chat.id
        )
        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.where(Message.search_tsv.isnot(None))
        stmt = stmt.where(Message.search_tsv.op("@@")(tsquery))
        stmt = stmt.order_by(rank.desc(), Message.timestamp.desc().nullslast()).limit(
            limit
        )
        rows = self.db.execute(stmt).all()
        results = []
        for row in rows:
            msg = row[0]
            msg._chat_name = row[1]
            msg._explicit_ts = row[3]
            results.append((msg, min(1.0, max(0.1, float(row[2])))))
        return results

    def _vector(
        self, query: str, filters: list[dict] | None, limit: int
    ) -> list[tuple[Message, float]]:
        if not self.embedder:
            return []
        embedding = self.embedder.encode_sync(query)
        if not embedding or not any(x != 0 for x in embedding):
            return []
        dist = Message.body_embedding.cosine_distance(embedding)
        stmt = select(
            Message, Chat.name, dist.label("distance"), Message.timestamp
        ).join(Chat, Message.chat_id == Chat.id)
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

    def count(self, filters: list[dict[str, Any]] | None = None) -> dict:
        """Return total count of matching messages."""
        stmt = select(func.count()).select_from(Message)
        stmt = self._apply_filters(stmt, filters)
        total = self.db.execute(stmt).scalar() or 0
        return {
            "results": [],
            "total_available": total,
            "count": total,
            "mode": "count",
            "methods_executed": ["count"],
            "timing_ms": {},
            "error": None,
        }

    def aggregate(
        self,
        group_by: str,
        filters: list[dict[str, Any]] | None = None,
        top_n: int = 10,
    ) -> dict:
        """Return top groups by message count. group_by: chat_id or contact_push_name."""
        if group_by == "chat_id":
            stmt = (
                select(Chat.id, Chat.name, func.count().label("cnt"))
                .select_from(Message)
                .join(Chat, Message.chat_id == Chat.id)
            )
            stmt = self._apply_filters(stmt, filters)
            stmt = stmt.group_by(Chat.id, Chat.name).order_by(
                func.count().desc()
            ).limit(top_n)
            rows = self.db.execute(stmt).all()
            aggregates = [
                {
                    "group_value": str(row[0]),
                    "count": row[2],
                    "label": str(row[1] or "Unknown") if row[1] else "Unknown",
                    "metadata": {},
                }
                for row in rows
            ]
        else:
            # contact_push_name: group by counterparty JID, resolve to push_name
            counterparty = coalesce(Message.participant, Message.remote_jid)
            stmt = (
                select(counterparty.label("jid"), func.count().label("cnt"))
                .select_from(Message)
                .where(counterparty.isnot(None))
                .where(counterparty != "")
            )
            stmt = self._apply_filters(stmt, filters)
            stmt = stmt.group_by(counterparty).order_by(
                func.count().desc()
            ).limit(top_n)
            rows = self.db.execute(stmt).all()
            aggregates = []
            for jid, cnt in rows:
                jid_str = str(jid or "")
                push_name, _ = _resolve_contact_for_jid(self.db, jid_str)
                label = (push_name or jid_str.split("@")[0] or "Unknown").strip()
                aggregates.append(
                    {
                        "group_value": jid_str,
                        "count": cnt,
                        "label": label or jid_str,
                        "metadata": {},
                    }
                )
        return {
            "results": [],
            "total_available": 0,
            "mode": "aggregate",
            "aggregates": aggregates,
            "methods_executed": ["aggregate"],
            "timing_ms": {},
            "error": None,
        }

    def _format_result(
        self, item: Message, scores: dict[str, float], methods: list[str]
    ) -> dict[str, Any]:
        chat_name = getattr(item, "_chat_name", None)
        contact_push_name: str | None = None
        contact_wa_id: str | None = None
        try:
            # Resolve contact by message remote_jid (can be wa_id or lid; contacts.wa_id / contacts.lid match)
            if item.from_me:
                jid = (
                    None
                    if (item.remote_jid or "").endswith("@g.us")
                    else item.remote_jid
                )
            else:
                jid = (
                    item.participant
                    if (item.remote_jid or "").endswith("@g.us")
                    else None
                ) or item.remote_jid
            if jid:
                contact_push_name, contact_wa_id = _resolve_contact_for_jid(
                    self.db, jid
                )
        except Exception as e:
            logger.debug(
                "Contact lookup failed for jid=%s: %s",
                getattr(item, "remote_jid", None),
                e,
            )
        return _message_to_result(
            item,
            chat_name,
            scores,
            methods,
            contact_push_name=contact_push_name,
            contact_wa_id=contact_wa_id,
        )
