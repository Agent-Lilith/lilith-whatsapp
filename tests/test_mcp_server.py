"""Tests for the WhatsApp MCP server tools (search_capabilities, unified_search)."""

import os

import pytest

# Integration tests that need real DB
pytestmark_integration = pytest.mark.integration


def test_search_capabilities_shape():
    """search_capabilities() returns the expected schema."""
    from mcp_server.server import search_capabilities

    out = search_capabilities()
    assert out["schema_version"] == "1.2"
    assert out["source_name"] == "whatsapp"
    assert out["source_class"] == "personal"
    assert out["latency_tier"] == "low"
    assert out["quality_tier"] == "high"
    assert out["cost_tier"] == "low"
    assert out["freshness_window_days"] == 1
    assert "structured" in out["supported_methods"]
    assert "fulltext" in out["supported_methods"]
    assert "vector" in out["supported_methods"]
    filter_names = [f["name"] for f in out["supported_filters"]]
    assert "chat_id" in filter_names
    assert "from_me" in filter_names
    assert "date_after" in filter_names
    assert "date_before" in filter_names
    assert out["max_limit"] == 100
    assert out["default_limit"] == 10


@pytest.mark.integration
def test_unified_search_returns_success_shape():
    """unified_search() returns success dict with results list (requires DB)."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    from mcp_server.server import unified_search

    out = unified_search(query="", top_k=5)
    assert "success" in out
    assert "results" in out
    assert "total_available" in out
    assert "methods_executed" in out
    assert "timing_ms" in out
    assert isinstance(out["results"], list)
    if out["success"] and out["results"]:
        first = out["results"][0]
        assert "metadata" in first
        # When contact is resolved, metadata can contain contact_push_name and contact_wa_id
        assert "remote_jid" in first.get("metadata", {})
