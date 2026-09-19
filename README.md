# Web Guide Agent

Web Guide Agent is an independent page-guidance and retrieval-augmented chat
service. It can run on its own with an empty knowledge base or connect to a
compatible Railway Memory Site deployment.

The repository does not include production knowledge documents, book imports,
vector data, conversations, caches, API keys, virtual-character assets, or
database volumes.

## Components

- `core`: FastAPI service for accounts, sessions, SSE chat, the web widget,
  page context, research notes, optional website synchronization, and guarded
  website write sessions.
- `rag`: FastAPI and Haystack service backed by PostgreSQL/pgvector for document
  ingestion, chunking, retrieval, API keys, and priority-aware ranking.
- `postgres`: a private pgvector database owned only by the agent.
- Website integration: optional read-only PostgreSQL access and optional
  short-lived website write APIs.

## Quick Start

1. Create the shared external networks, or start the website Compose stack that
   creates `guide_agent_edge`.

```bash
docker network create guide_agent_edge
docker network create web_default
```

2. Copy `.env.example` to `.env` and replace every password, token, and model
   setting.
3. Start the agent.

```bash
docker compose up -d --build
```

4. Open `http://localhost:8080/guide-agent/admin`.

The PostgreSQL, SQLite, upload, cache, and vector tables are created without
sample documents. Health information is available at `/health`.

## Public Endpoints

- Widget script: `/guide-agent/widget.js`
- Team workspace: `/guide-agent/admin`
- Core API: `/api/guide-agent/`
- External ingestion API: `/api/guide-agent/v1/`

## Agent Kernel

- `tool_configure.json` declares the available tools and `visitor`, `member`,
  `team`, and `cli` visibility.
- `core/app/tools/` is scanned at startup and tools register themselves.
- `POST /api/guide-agent/chat/stream` is the primary streaming entry point.
- `core/main-agent.py` provides a CLI for local inspection and questions.
- Tool loops are bounded, have per-tool timeouts, and open a circuit after
  repeated failures.
- SQLite stores page cache, section cache, answer cache, sessions, conversations,
  and tool audit records in the agent's private volume.

## Knowledge Ingestion

Documents can be added through the RAG API or the generic structured-document
importer:

```bash
python scripts/import_documents.py \
  --document example=/path/to/structured/document \
  --priority secondary \
  --env-file .env \
  --wait
```

The importer expects a directory containing:

```text
knowledge_base/knowledge_base.json
text_raw/pages_text/page_001.txt
```

It does not contain any book names, local paths, or topic-specific scoring.

## Website Integration

Website synchronization is disabled by default. To enable it:

1. Configure `WEBSITE_EXPORT_BASE_URL` and `WEBSITE_EXPORT_TOKEN`.
2. Set `WEBSITE_SYNC_ENABLED=true`.
3. Optionally configure `WEBSITE_READONLY_DATABASE_URL` for direct read-only
   content queries.
4. Optionally configure `WEBSITE_WRITE_BASE_URL` and
   `WEBSITE_WRITE_ADMIN_TOKEN` for short-lived draft or publish sessions.

The website remains optional. With synchronization disabled, the agent still
serves chat, page-context, cache, and retrieval features from its own database.

## Tests

```bash
docker compose run --rm --no-deps core pytest
docker compose run --rm --no-deps rag pytest
docker compose config
```

## License

MIT. See [LICENSE](LICENSE).
