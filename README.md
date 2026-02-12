# Lilith WhatsApp

WhatsApp context for the Lilith agent: Baileys v7 syncs history and live messages into PostgreSQL; the Python MCP server exposes search.

## Quick start

### 1. Database (shared Postgres)

This project uses a **shared** PostgreSQL server. Database name for this app: `lilith_whatsapp`.

Ensure the shared Postgres (with pgvector) is running. Clone the lilith-compose project first.

### 2. Run migrations

```bash
uv run alembic upgrade head
```
### 3. First-time WhatsApp auth (history sync)

Read README file inside wa-connector folder.

### 4. Run the embed backfill

The Node app does **not** embed message text. To enable vector search, run the Python backfill so that `body_embedding` is filled from `body_text`:

```bash
uv run python main.py embed
```

### 5. Run the message listener (ongoing)

To capture **new** messages:

```bash
cd wa-connector
npm run listen
```

Use the same **AUTH_STATE_DIR** as in step 3 so it reuses the same session.

## MCP Server (Agent Tools)

The Lilith WhatsApp MCP server.

```bash
uv run mcp
uv run mcp --transport streamable-http --port 6201
```
