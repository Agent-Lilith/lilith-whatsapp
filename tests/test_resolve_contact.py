"""
Tests for _resolve_contact_for_jid: LID and PN must resolve to the same contact.

Integration test uses the real database and the Pouyan contact we debugged:
- 60173135062@s.whatsapp.net (PN)
- 214215855980743@lid (LID)
Both must return the same push_name (and one contact_wa_id).
Run with DATABASE_URL set (or .env in project root) to run integration tests.
"""

import os
from unittest.mock import MagicMock

import pytest

from mcp_server.hybrid_search import _resolve_contact_for_jid


@pytest.fixture
def db():
    """Yield a DB session for the test. Skip if DATABASE_URL not set."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    from core.database import db_session

    with db_session() as session:
        yield session


@pytest.mark.integration
def test_resolve_contact_for_jid_pouyan_lid_and_pn_same_person(db):
    """
    Pouyan: messages may use 214215855980743@lid or 60173135062@s.whatsapp.net.
    Both must resolve to the same contact (same push_name); at least one must return contact_wa_id.
    """
    from mcp_server.hybrid_search import _resolve_contact_for_jid

    lid_jid = "214215855980743@lid"
    pn_jid = "60173135062@s.whatsapp.net"

    push_lid, wa_id_lid = _resolve_contact_for_jid(db, lid_jid)
    push_pn, wa_id_pn = _resolve_contact_for_jid(db, pn_jid)

    # Both JIDs must resolve to a contact (we have at least one row for Pouyan)
    assert (push_lid, wa_id_lid) != (None, None), (
        f"LID {lid_jid} should resolve to a contact"
    )
    assert (push_pn, wa_id_pn) != (None, None), (
        f"PN {pn_jid} should resolve to a contact"
    )

    # Same display name whether we look up by LID or PN
    assert push_lid == push_pn, (
        f"LID and PN must resolve to same push_name: got push_lid={push_lid!r} push_pn={push_pn!r}"
    )
    assert (push_lid or "").strip(), (
        "push_name should be non-empty (e.g. Pouyan latest)"
    )

    # contact_wa_id must be one of the two JIDs (the row we matched)
    assert wa_id_lid in (lid_jid, pn_jid), (
        f"contact_wa_id for LID lookup should be Pouyan's: {wa_id_lid!r}"
    )
    assert wa_id_pn in (lid_jid, pn_jid), (
        f"contact_wa_id for PN lookup should be Pouyan's: {wa_id_pn!r}"
    )


def test_resolve_contact_for_jid_none_or_empty():
    """None and empty string return (None, None) without hitting the DB."""
    mock_db = MagicMock()
    assert _resolve_contact_for_jid(mock_db, None) == (None, None)
    assert _resolve_contact_for_jid(mock_db, "") == (None, None)
    assert _resolve_contact_for_jid(mock_db, "   ") == (None, None)
    mock_db.execute.assert_not_called()


@pytest.mark.integration
def test_resolve_contact_for_jid_unknown_returns_none(db):
    """Unknown JID returns (None, None)."""
    from mcp_server.hybrid_search import _resolve_contact_for_jid

    push, wa_id = _resolve_contact_for_jid(db, "999999999999999@s.whatsapp.net")
    assert push is None and wa_id is None

    push2, wa_id2 = _resolve_contact_for_jid(db, "999999999999999@lid")
    assert push2 is None and wa_id2 is None
