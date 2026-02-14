import logging
import sys

from common.mcp import create_mcp_app, run_mcp_server

from core.database import db_session
from core.embeddings import Embedder
from mcp_server.hybrid_search import HybridMessageSearchEngine

logger = logging.getLogger("mcp_server")

mcp = create_mcp_app("Lilith WhatsApp")


@mcp.tool()
def search_capabilities() -> dict:
    """Return this server's search capabilities."""
    # ... unchanged implementation
    return {
        "schema_version": "1.2",
        "source_name": "whatsapp",
        "source_class": "personal",
        "display_label": "WhatsApp messages",
        "alias_hints": ["wa", "chat"],
        "freshness_window_days": 1,
        "latency_tier": "low",
        "quality_tier": "high",
        "cost_tier": "low",
        "supported_methods": ["structured", "fulltext", "vector"],
        "supported_modes": ["search", "count", "aggregate"],
        "supported_group_by_fields": ["chat_id", "contact_push_name"],
        "supported_filters": [
            {
                "name": "chat_id",
                "type": "integer",
                "operators": ["eq"],
                "description": "Filter by chat",
            },
            {
                "name": "from_me",
                "type": "boolean",
                "operators": ["eq"],
                "description": "Sent by me",
            },
            {
                "name": "date_after",
                "type": "date",
                "operators": ["gte"],
                "description": "Message on or after",
            },
            {
                "name": "date_before",
                "type": "date",
                "operators": ["lte"],
                "description": "Message on or before",
            },
        ],
        "max_limit": 100,
        "default_limit": 10,
        "sort_fields": ["timestamp", "relevance"],
        "default_ranking": "vector",
    }


@mcp.tool()
def unified_search(
    query: str = "",
    methods: list[str] | None = None,
    filters: list[dict] | None = None,
    top_k: int = 10,
    mode: str = "search",
    group_by: str | None = None,
    aggregate_top_n: int = 10,
) -> dict:
    """Hybrid search over WhatsApp messages. Supports search, count, aggregate."""
    top_k = min(max(1, top_k), 100)
    aggregate_top_n = min(max(1, aggregate_top_n), 100)
    try:
        with db_session() as db:
            embedder = Embedder()
            engine = HybridMessageSearchEngine(db, embedder)
            if mode == "count":
                return {
                    "success": True,
                    **engine.count(filters=filters),
                }
            if mode == "aggregate" and group_by in ("chat_id", "contact_push_name"):
                return {
                    "success": True,
                    **engine.aggregate(
                        group_by=group_by,
                        filters=filters,
                        top_n=aggregate_top_n,
                    ),
                }
            results, timing_ms, methods_executed = engine.search(
                query=query,
                methods=methods,
                filters=filters,
                top_k=top_k,
            )
        return {
            "success": True,
            "results": results,
            "total_available": len(results),
            "methods_executed": methods_executed,
            "timing_ms": timing_ms,
            "error": None,
        }
    except Exception as e:
        logger.exception("unified_search failed")
        return {
            "success": False,
            "results": [],
            "total_available": 0,
            "methods_executed": [],
            "timing_ms": {},
            "error": str(e),
        }


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", default="stdio")
    parser.add_argument("--port", type=int, default=8002)
    args, _ = parser.parse_known_args()
    run_mcp_server(mcp, transport=args.transport, port=args.port)


if __name__ == "__main__":
    from mcp_server.__main__ import main as _main

    sys.exit(_main())
