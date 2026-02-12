"""Hybrid search over WhatsApp messages: structured + fulltext + vector."""

import logging
import time
from datetime import date, datetime, time as dtime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.embeddings import Embedder
from core.models import Chat, Message

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


def _message_to_result(msg: Message, chat_name: str | None, scores: dict[str, float], methods: list[str]) -> dict[str, Any]:
    return {
        "id": str(msg.id),
        "source": "whatsapp_messages",
        "source_class": "personal",
        "title": chat_name or msg.remote_jid or "Chat",
        "snippet": (msg.body_text or "")[:500],
        "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
        "scores": scores,
        "methods_used": methods,
        "metadata": {
            "chat_id": msg.chat_id,
            "remote_jid": msg.remote_jid,
            "from_me": msg.from_me,
            "message_type": msg.message_type,
        },
        "provenance": f"WhatsApp message in {chat_name or msg.remote_jid} at {msg.timestamp.strftime('%Y-%m-%d %H:%M') if msg.timestamp else '?'}",
    }


class HybridMessageSearchEngine:
    """Hybrid search over WhatsApp messages: structured + fulltext + vector."""

    def __init__(self, db: Session, embedder: Embedder | None = None) -> None:
        self.db = db
        self.embedder = embedder

    def search(
        self,
        query: str = "",
        methods: list[str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        top_k: int = 10,
    ) -> tuple[list[dict[str, Any]], dict[str, float], list[str]]:
        """Returns (results, timing_ms, methods_executed)."""
        top_k = _cap_limit(top_k)
        if methods is None:
            methods = self._auto_select(query, filters)

        all_results: dict[int, dict] = {}
        timing_ms: dict[str, float] = {}
        methods_executed: list[str] = []

        if "structured" in methods:
            t0 = time.monotonic()
            for msg, chat_name, score in self._structured(filters, top_k):
                mid = msg.id
                if mid not in all_results:
                    all_results[mid] = {"msg": msg, "chat_name": chat_name, "scores": {}, "methods": []}
                all_results[mid]["scores"]["structured"] = score
                all_results[mid]["methods"].append("structured")
            timing_ms["structured"] = round((time.monotonic() - t0) * 1000, 1)
            methods_executed.append("structured")

        if "fulltext" in methods and query.strip():
            t0 = time.monotonic()
            for msg, chat_name, score in self._fulltext(query, filters, top_k):
                mid = msg.id
                if mid not in all_results:
                    all_results[mid] = {"msg": msg, "chat_name": chat_name, "scores": {}, "methods": []}
                all_results[mid]["scores"]["fulltext"] = score
                if "fulltext" not in all_results[mid]["methods"]:
                    all_results[mid]["methods"].append("fulltext")
            timing_ms["fulltext"] = round((time.monotonic() - t0) * 1000, 1)
            methods_executed.append("fulltext")

        if "vector" in methods and query.strip() and self.embedder:
            t0 = time.monotonic()
            for msg, chat_name, score in self._vector(query, filters, top_k):
                mid = msg.id
                if mid not in all_results:
                    all_results[mid] = {"msg": msg, "chat_name": chat_name, "scores": {}, "methods": []}
                all_results[mid]["scores"]["vector"] = score
                if "vector" not in all_results[mid]["methods"]:
                    all_results[mid]["methods"].append("vector")
            timing_ms["vector"] = round((time.monotonic() - t0) * 1000, 1)
            methods_executed.append("vector")

        weights = {"structured": 1.0, "fulltext": 0.85, "vector": 0.7}
        scored: list[tuple[float, dict]] = []
        for data in all_results.values():
            total_w = sum(weights.get(m, 0.5) for m in data["scores"])
            total_s = sum(data["scores"][m] * weights.get(m, 0.5) for m in data["scores"])
            final = total_s / total_w if total_w > 0 else 0.0
            result = _message_to_result(data["msg"], data["chat_name"], data["scores"], data["methods"])
            scored.append((final, result))

        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:top_k]], timing_ms, list(dict.fromkeys(methods_executed))

    def _auto_select(self, query: str, filters: list[dict] | None) -> list[str]:
        methods = []
        if filters:
            methods.append("structured")
        if query and query.strip():
            methods.append("fulltext")
            if self.embedder and self.embedder.endpoint_url:
                methods.append("vector")
        if not methods:
            methods = ["structured"]
        return methods

    def _structured(self, filters: list[dict] | None, limit: int) -> list[tuple[Message, str | None, float]]:
        stmt = select(Message, Chat.name).join(Chat, Message.chat_id == Chat.id)
        stmt = _apply_filters(stmt, filters)
        stmt = stmt.order_by(Message.timestamp.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).all()
        return [(row[0], row[1], max(0.3, 1.0 - i * 0.03)) for i, row in enumerate(rows)]

    def _fulltext(self, query: str, filters: list[dict] | None, limit: int) -> list[tuple[Message, str | None, float]]:
        tsquery = func.plainto_tsquery("simple", query)
        rank = func.ts_rank_cd(Message.search_tsv, tsquery)
        stmt = select(Message, Chat.name, rank.label("rank")).join(Chat, Message.chat_id == Chat.id)
        stmt = _apply_filters(stmt, filters)
        stmt = stmt.where(Message.search_tsv.isnot(None))
        stmt = stmt.where(Message.search_tsv.op("@@")(tsquery))
        stmt = stmt.order_by(rank.desc(), Message.timestamp.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).all()
        return [(row[0], row[1], min(1.0, max(0.1, float(row[2])))) for row in rows]

    def _vector(self, query: str, filters: list[dict] | None, limit: int) -> list[tuple[Message, str | None, float]]:
        if not self.embedder or not self.embedder.endpoint_url:
            return []
        embedding = self.embedder.encode_sync(query)
        if not embedding or not any(x != 0 for x in embedding):
            return []
        dist = Message.body_embedding.cosine_distance(embedding)
        stmt = select(Message, Chat.name, dist.label("distance")).join(Chat, Message.chat_id == Chat.id)
        stmt = _apply_filters(stmt, filters)
        stmt = stmt.where(Message.body_embedding.isnot(None))
        stmt = stmt.order_by(dist, Message.timestamp.desc().nullslast()).limit(limit)
        rows = self.db.execute(stmt).all()
        return [(row[0], row[1], max(0.0, min(1.0, 1.0 - float(row[2])))) for row in rows]
