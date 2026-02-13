"""
Read-only consistency checks for chats, messages, and contacts.

Run: uv run python main.py check

Validates:
- Every message's chat has chat.jid = message.remote_jid (same conversation).
- Every DM message has a contact matching remote_jid (wa_id = jid OR lid = jid OR phone_number for PN).
- Every DM chat has a contact matching its jid/jid_pn (same rule).
- Flags duplicate chats for the same logical peer (LID vs PN).

Contact lookup uses wa_id OR lid (and phone_number for @s.whatsapp.net); one row per person is enough.
"""

from dataclasses import dataclass, field

from sqlalchemy import text

from core.database import db_session


@dataclass
class CheckResult:
    name: str
    passed: bool
    error_count: int = 0
    warning_count: int = 0
    details: list[str] = field(default_factory=list)


def _run_check_message_chat_jid_alignment(session) -> CheckResult:
    """Every message must belong to a chat whose jid equals the message's remote_jid."""
    r = session.execute(
        text("""
            SELECT m.id AS message_id, m.chat_id, m.remote_jid, c.jid AS chat_jid
            FROM messages m
            JOIN chats c ON c.id = m.chat_id
            WHERE m.remote_jid IS DISTINCT FROM c.jid
            ORDER BY m.id
            LIMIT 500
        """)
    ).fetchall()
    if not r:
        return CheckResult("Message–chat JID alignment", True)
    details = [
        f"  message_id={row[0]} chat_id={row[1]} message.remote_jid={row[2]!r} chat.jid={row[3]!r}"
        for row in r
    ]
    if len(r) >= 500:
        details.append("  ... and possibly more (capped at 500)")
    return CheckResult(
        "Message–chat JID alignment",
        False,
        error_count=len(r) if len(r) < 500 else 500,
        details=details,
    )


def _contact_matches_jid(session, jid: str) -> bool:
    """True if at least one contact row matches this JID (wa_id, lid, or phone_number)."""
    if not jid or jid.endswith("@g.us"):
        return True
    if jid.endswith("@s.whatsapp.net"):
        number = jid.removesuffix("@s.whatsapp.net")
        r = session.execute(
            text("""
                SELECT 1 FROM contacts
                WHERE wa_id = :jid
                   OR phone_number = :number
                   OR phone_number = :jid
                LIMIT 1
            """),
            {"jid": jid, "number": number},
        ).fetchone()
    else:
        # @lid or other
        r = session.execute(
            text("""
                SELECT 1 FROM contacts
                WHERE wa_id = :jid OR lid = :jid
                LIMIT 1
            """),
            {"jid": jid},
        ).fetchone()
    return r is not None


def _run_check_dm_messages_have_contact(session) -> CheckResult:
    """Every message in a DM (not group) should have a contact matching remote_jid."""
    # Get distinct DM remote_jids from messages that are not groups
    r = session.execute(
        text("""
            SELECT DISTINCT m.remote_jid
            FROM messages m
            WHERE m.remote_jid IS NOT NULL
              AND m.remote_jid NOT LIKE '%@g.us'
        """)
    ).fetchall()
    missing = []
    for (jid,) in r:
        if not _contact_matches_jid(session, jid):
            missing.append(jid)
    if not missing:
        return CheckResult("DM messages have matching contact", True)
    details = [f"  {j}" for j in sorted(missing)[:100]]
    if len(missing) > 100:
        details.append(f"  ... and {len(missing) - 100} more")
    return CheckResult(
        "DM messages have matching contact",
        False,
        error_count=len(missing),
        details=details,
    )


def _run_check_dm_chats_have_contact(session) -> CheckResult:
    """Every DM chat should have a contact matching its jid (or jid_pn)."""
    r = session.execute(
        text("""
            SELECT id, jid, jid_pn FROM chats
            WHERE jid NOT LIKE '%@g.us'
        """)
    ).fetchall()
    missing = []
    for chat_id, jid, jid_pn in r:
        if _contact_matches_jid(session, jid):
            continue
        if jid_pn and _contact_matches_jid(session, jid_pn):
            continue
        missing.append((chat_id, jid, jid_pn))
    if not missing:
        return CheckResult("DM chats have matching contact", True)
    details = [f"  chat_id={c[0]} jid={c[1]!r} jid_pn={c[2]!r}" for c in missing[:50]]
    if len(missing) > 50:
        details.append(f"  ... and {len(missing) - 50} more")
    return CheckResult(
        "DM chats have matching contact",
        False,
        error_count=len(missing),
        details=details,
    )


def _normalize_peer(jid: str | None, jid_pn: str | None) -> str | None:
    """Single canonical key for 'same person' in DMs: prefer phone number, else LID."""
    if not jid:
        return None
    if jid.endswith("@s.whatsapp.net"):
        return jid
    if jid.endswith("@lid") and jid_pn:
        return jid_pn  # normalize LID chat to PN for grouping
    return jid


def _run_check_duplicate_chats_same_peer(session) -> CheckResult:
    """Warn when multiple chats refer to the same logical peer (LID vs PN)."""
    r = session.execute(
        text("""
            SELECT id, jid, jid_pn FROM chats
            WHERE jid NOT LIKE '%@g.us'
            ORDER BY id
        """)
    ).fetchall()
    peer_to_chats: dict[str, list[tuple[int, str, str | None]]] = {}
    for chat_id, jid, jid_pn in r:
        peer = _normalize_peer(jid, jid_pn)
        if not peer:
            continue
        peer_to_chats.setdefault(peer, []).append((chat_id, jid, jid_pn))
    duplicates = [v for v in peer_to_chats.values() if len(v) > 1]
    if not duplicates:
        return CheckResult("No duplicate chats for same peer", True)
    details = []
    for group in duplicates[:20]:
        peer = _normalize_peer(group[0][1], group[0][2])
        details.append(
            f"  peer {peer!r}: chat_ids={[c[0] for c in group]} jids={[c[1] for c in group]}"
        )
    if len(duplicates) > 20:
        details.append(f"  ... and {len(duplicates) - 20} more duplicate groups")
    return CheckResult(
        "No duplicate chats for same peer",
        True,  # pass with warnings
        warning_count=sum(len(g) for g in duplicates),
        details=details,
    )


def run_consistency_checks() -> list[CheckResult]:
    """Run all read-only consistency checks. No writes."""
    results: list[CheckResult] = []
    with db_session() as session:
        results.append(_run_check_message_chat_jid_alignment(session))
        results.append(_run_check_dm_messages_have_contact(session))
        results.append(_run_check_dm_chats_have_contact(session))
        results.append(_run_check_duplicate_chats_same_peer(session))
    return results


def print_report(results: list[CheckResult]) -> None:
    for r in results:
        status = "PASS" if r.passed and r.error_count == 0 else "FAIL"
        w = f" ({r.warning_count} warnings)" if r.warning_count else ""
        print(f"[{status}] {r.name}{w}")
        for line in r.details:
            print(line)
        if r.details:
            print()
    errors = sum(x.error_count for x in results)
    warnings = sum(x.warning_count for x in results)
    if errors:
        print(
            f"Total: {errors} error(s), {warnings} warning(s) — data is inconsistent."
        )
    elif warnings:
        print(
            f"Total: 0 errors, {warnings} warning(s) — data is consistent but has duplicate chats for same peers."
        )
    else:
        print("Total: 0 errors, 0 warnings — data is consistent.")
