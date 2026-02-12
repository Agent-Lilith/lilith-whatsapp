"""Run MCP server (stdio or HTTP). Hybrid search over WhatsApp messages."""

import sys


def main() -> int:
    from mcp_server.server import main as server_main

    server_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
