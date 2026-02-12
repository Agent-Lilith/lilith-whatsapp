"""Run MCP server (stdio or HTTP). Hybrid search over WhatsApp messages."""
import json
import logging
import sys

from mcp.server.fastmcp import FastMCP

from core.database import db_session
from core.embeddings import Embedder
from mcp_server.hybrid_search import HybridMessageSearchEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_server")

mcp = FastMCP("Lilith WhatsApp", json_response=True)


def get_search_capabilities() -> dict:
    return {
        "schema_version": "1.0",
        "source_name": "whatsapp_messages",
        "source_class": "personal",
        "supported_methods": ["structured", "fulltext", "vector"],
        "supported_filters": [
            {"name": "chat_id", "type": "integer", "operators": ["eq"], "description": "Filter by chat"},
            {"name": "from_me", "type": "boolean", "operators": ["eq"], "description": "Sent by me"},
            {"name": "date_after", "type": "date", "operators": ["gte"], "description": "Message on or after"},
            {"name": "date_before", "type": "date", "operators": ["lte"], "description": "Message on or before"},
        ],
        "max_limit": 100,
        "default_limit": 10,
        "sort_fields": ["timestamp", "relevance"],
        "default_ranking": "vector",
    }


@mcp.tool()
def search_capabilities() -> dict:
    """Return this server's search capabilities."""
    return get_search_capabilities()


@mcp.tool()
def unified_search(
    query: str = "",
    methods: list[str] | None = None,
    filters: list[dict] | None = None,
    top_k: int = 10,
    include_scores: bool = True,
) -> dict:
    """Hybrid search over WhatsApp messages (structured + fulltext + vector)."""
    top_k = min(max(1, top_k), 100)
    try:
        with db_session() as db:
            embedder = Embedder()
            engine = HybridMessageSearchEngine(db, embedder)
            results, timing_ms, methods_executed = engine.search(
                query=query,
                methods=methods,
                filters=filters,
                top_k=top_k,
            )
        return {
            "results": results,
            "total_available": len(results),
            "methods_executed": methods_executed,
            "timing_ms": timing_ms,
            "error": None,
        }
    except Exception as e:
        logger.exception("unified_search failed")
        return {
            "results": [],
            "total_available": 0,
            "methods_executed": [],
            "timing_ms": {},
            "error": str(e),
        }


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        app = FastMCP("Lilith WhatsApp", json_response=True, host="0.0.0.0", port=8002)
        app.tool()(search_capabilities)
        app.tool()(unified_search)
        import asyncio
        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Mount
        starlette_app = app.streamable_http_app()
        config = uvicorn.Config(starlette_app, host="0.0.0.0", port=8002, log_level="info")
        asyncio.run(uvicorn.Server(config).serve())
        return 0
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
