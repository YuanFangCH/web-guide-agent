# Open-Source Export Notes

This repository was prepared from a private deployment as a clean source-only
export.

## Removed Data

- Structured book imports and source paths
- Knowledge documents, chunks, embeddings, and pgvector records
- Conversations, visitor sessions, tool audits, page cache, and answer cache
- API keys, bootstrap secrets, account records, and password hashes
- PostgreSQL and SQLite data files, Docker volumes, logs, and backups
- Original virtual-character PSD derivatives and transparent WebP assets
- Production domains, IP addresses, certificates, and local deployment values

## Empty Start

The agent creates empty schemas at startup. There are no documents, chunks,
vectors, conversations, or API keys until a deployment explicitly imports or
creates them.

Website synchronization and write capabilities are disabled unless the operator
configures both sides with matching tokens and endpoints.

## Licensing

The MIT license applies to the source code. Documents, model outputs, user
uploads, and any replacement character assets added by downstream users must be
licensed separately by those users.
