#!/usr/bin/env python3
"""CLI: uv run mcp | python main.py serve | python main.py embed."""
import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def cmd_embed(args: argparse.Namespace) -> int:
    from core.embed_backfill import run_embed_backfill
    n = run_embed_backfill(batch_size=args.batch_size, limit=args.limit)
    print(f"Embed backfill done: {n} messages updated.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lilith WhatsApp")
    parser.add_argument("command", nargs="?", default="mcp", help="mcp | serve | embed")
    parser.add_argument("--batch-size", type=int, default=32, help="Embed backfill batch size (default 32)")
    parser.add_argument("--limit", type=int, default=None, help="Max messages to embed (default: all)")
    args = parser.parse_args()

    if args.command == "embed":
        return cmd_embed(args)
    if args.command == "serve":
        from mcp_server.__main__ import main as mcp_main
        return mcp_main()
    # default: stdio MCP
    from mcp_server.__main__ import main as mcp_main
    return mcp_main()


if __name__ == "__main__":
    sys.exit(main())
