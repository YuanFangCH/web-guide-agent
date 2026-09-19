from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .config import settings
from .priorities import resolve_priority

pool: ConnectionPool | None = None


def init_pool() -> None:
    global pool
    if pool is None:
        pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=8,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        pool.open(wait=True)


def close_pool() -> None:
    global pool
    if pool is not None:
        pool.close()
        pool = None


def _pool() -> ConnectionPool:
    if pool is None:
        raise RuntimeError("Database pool is not initialized")
    return pool


def init_db() -> None:
    with _pool().connection() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_documents (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                content_html TEXT NOT NULL DEFAULT '',
                content_text TEXT NOT NULL DEFAULT '',
                sections JSONB NOT NULL DEFAULT '[]'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                knowledge_priority SMALLINT NOT NULL DEFAULT 3,
                checksum TEXT NOT NULL DEFAULT '',
                source_updated_at TIMESTAMPTZ NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                error TEXT,
                chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                deleted_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                modified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (source, source_id)
            )
            """
        )
        existing_priority_column = conn.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'agent_documents'
              AND column_name = 'knowledge_priority'
            """
        ).fetchone()
        if not existing_priority_column:
            conn.execute(
                """
                ALTER TABLE agent_documents
                ADD COLUMN knowledge_priority SMALLINT NOT NULL DEFAULT 3
                """
            )
            conn.execute(
                """
                UPDATE agent_documents
                SET knowledge_priority = 2
                WHERE source <> 'website'
                """
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_jobs (
                id UUID PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                document_id TEXT,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                result JSONB,
                error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                key_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
                active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_used_at TIMESTAMPTZ,
                expires_at TIMESTAMPTZ
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS agent_documents_source_idx "
            "ON agent_documents (source, source_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS agent_jobs_status_idx "
            "ON agent_jobs (status, created_at)"
        )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def document_id(source: str, source_id: str) -> str:
    return hashlib.sha256(f"{source}\0{source_id}".encode("utf-8")).hexdigest()


def parse_api_key(token: str) -> tuple[str, str] | None:
    prefix = "ga_live_"
    if not token.startswith(prefix):
        return None
    remainder = token[len(prefix) :]
    if "_" not in remainder:
        return None
    key_id, secret = remainder.split("_", 1)
    if not key_id or len(secret) < 16:
        return None
    return key_id, secret


def _hash_secret(secret: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", secret.encode("utf-8"), salt.encode("utf-8"), 240_000
    ).hex()


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    for key, item in list(value.items()):
        if isinstance(item, datetime):
            value[key] = item.isoformat()
    return value


def ensure_bootstrap_key() -> None:
    token = settings.bootstrap_api_key
    if not token:
        return
    parsed = parse_api_key(token)
    if parsed is None:
        raise RuntimeError(
            "RAG_BOOTSTRAP_API_KEY must use the format "
            "ga_live_<key-id>_<secret>"
        )
    key_id, secret = parsed
    salt = secrets.token_hex(16)
    key_hash = _hash_secret(secret, salt)
    scopes = [
        "admin",
        "documents:write",
        "documents:read",
        "ingestions:write",
        "retrieval:read",
    ]
    with _pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO agent_api_keys
                (id, name, key_prefix, key_hash, salt, scopes)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                key_hash = EXCLUDED.key_hash,
                salt = EXCLUDED.salt,
                scopes = EXCLUDED.scopes,
                active = true
            """,
            (
                key_id,
                "bootstrap",
                token[:20],
                key_hash,
                salt,
                Jsonb(scopes),
            ),
        )


def verify_api_key(token: str) -> dict[str, Any] | None:
    parsed = parse_api_key(token)
    if parsed is None:
        return None
    key_id, secret = parsed
    with _pool().connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM agent_api_keys
            WHERE id = %s AND active = true
              AND (expires_at IS NULL OR expires_at > now())
            """,
            (key_id,),
        ).fetchone()
        if not row:
            return None
        expected = row["key_hash"]
        actual = _hash_secret(secret, row["salt"])
        if not hmac.compare_digest(expected, actual):
            return None
        conn.execute(
            "UPDATE agent_api_keys SET last_used_at = now() WHERE id = %s",
            (key_id,),
        )
    return _serialize(row)


def create_api_key(name: str, scopes: list[str]) -> tuple[str, dict[str, Any]]:
    key_id = uuid.uuid4().hex[:12]
    secret = secrets.token_urlsafe(32)
    token = f"ga_live_{key_id}_{secret}"
    salt = secrets.token_hex(16)
    key_hash = _hash_secret(secret, salt)
    with _pool().connection() as conn:
        row = conn.execute(
            """
            INSERT INTO agent_api_keys
                (id, name, key_prefix, key_hash, salt, scopes)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                key_id,
                name,
                token[:20],
                key_hash,
                salt,
                Jsonb(scopes),
            ),
        ).fetchone()
    return token, _serialize(row)


def list_api_keys() -> list[dict[str, Any]]:
    with _pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, key_prefix, scopes, active, created_at, last_used_at
            FROM agent_api_keys
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [_serialize(row) for row in rows]


def revoke_api_key(key_id: str) -> bool:
    with _pool().connection() as conn:
        result = conn.execute(
            "UPDATE agent_api_keys SET active = false WHERE id = %s",
            (key_id,),
        )
    return result.rowcount > 0


def upsert_document_record(document: dict[str, Any]) -> dict[str, Any]:
    doc_id = document_id(document["source"], document["sourceId"])
    knowledge_priority = resolve_priority(
        document.get("priority"), document["source"]
    )
    with _pool().connection() as conn:
        row = conn.execute(
            """
            INSERT INTO agent_documents (
                id, source, source_id, type, title, url, content_html,
                content_text, sections, metadata, knowledge_priority, checksum,
                source_updated_at, status, deleted_at, modified_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'queued', NULL, now()
            )
            ON CONFLICT (source, source_id) DO UPDATE SET
                type = EXCLUDED.type,
                title = EXCLUDED.title,
                url = EXCLUDED.url,
                content_html = EXCLUDED.content_html,
                content_text = EXCLUDED.content_text,
                sections = EXCLUDED.sections,
                metadata = EXCLUDED.metadata,
                knowledge_priority = EXCLUDED.knowledge_priority,
                checksum = EXCLUDED.checksum,
                source_updated_at = EXCLUDED.source_updated_at,
                status = 'queued',
                error = NULL,
                deleted_at = NULL,
                modified_at = now()
            RETURNING *
            """,
            (
                doc_id,
                document["source"],
                document["sourceId"],
                document["type"],
                document.get("title", ""),
                document.get("url", ""),
                document.get("contentHtml", ""),
                document.get("contentText", ""),
                Jsonb(document.get("sections", [])),
                Jsonb(document.get("metadata", {})),
                knowledge_priority,
                document.get("checksum", ""),
                document.get("updatedAt") or now_utc().isoformat(),
            ),
        ).fetchone()
    return _serialize(row)


def update_document_content(
    doc_id: str,
    *,
    title: str | None = None,
    content_html: str | None = None,
    content_text: str | None = None,
    sections: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _pool().connection() as conn:
        row = conn.execute(
            """
            UPDATE agent_documents
            SET title = COALESCE(%s, title),
                content_html = COALESCE(%s, content_html),
                content_text = COALESCE(%s, content_text),
                sections = COALESCE(%s, sections),
                metadata = COALESCE(%s, metadata),
                modified_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (
                title,
                content_html,
                content_text,
                Jsonb(sections) if sections is not None else None,
                Jsonb(metadata) if metadata is not None else None,
                doc_id,
            ),
        ).fetchone()
    return _serialize(row)


def get_document(doc_id: str) -> dict[str, Any] | None:
    with _pool().connection() as conn:
        row = conn.execute(
            "SELECT * FROM agent_documents WHERE id = %s", (doc_id,)
        ).fetchone()
    return _serialize(row) if row else None


def list_documents(limit: int = 100) -> list[dict[str, Any]]:
    with _pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM agent_documents
            WHERE deleted_at IS NULL
            ORDER BY modified_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [_serialize(row) for row in rows]


def set_document_status(
    doc_id: str, status: str, error: str | None = None
) -> None:
    with _pool().connection() as conn:
        conn.execute(
            """
            UPDATE agent_documents
            SET status = %s, error = %s, modified_at = now()
            WHERE id = %s
            """,
            (status, error, doc_id),
        )


def set_document_ready(doc_id: str, chunk_ids: list[str]) -> None:
    with _pool().connection() as conn:
        conn.execute(
            """
            UPDATE agent_documents
            SET status = 'ready', error = NULL, chunk_ids = %s,
                deleted_at = NULL, modified_at = now()
            WHERE id = %s
            """,
            (Jsonb(chunk_ids), doc_id),
        )


def mark_document_deleted(doc_id: str) -> dict[str, Any] | None:
    with _pool().connection() as conn:
        row = conn.execute(
            """
            UPDATE agent_documents
            SET deleted_at = now(), status = 'deleting', modified_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (doc_id,),
        ).fetchone()
    return _serialize(row) if row else None


def finish_document_delete(doc_id: str) -> None:
    with _pool().connection() as conn:
        conn.execute(
            """
            UPDATE agent_documents
            SET status = 'deleted', chunk_ids = '[]'::jsonb, modified_at = now()
            WHERE id = %s
            """,
            (doc_id,),
        )


def reconcile_source(source: str, active_source_ids: list[str]) -> list[str]:
    with _pool().connection() as conn:
        rows = conn.execute(
            """
            UPDATE agent_documents
            SET deleted_at = COALESCE(deleted_at, now()),
                status = 'deleting',
                modified_at = now()
            WHERE source = %s
              AND deleted_at IS NULL
              AND source_id <> ALL(%s)
            RETURNING id
            """,
            (source, active_source_ids),
        ).fetchall()
    return [row["id"] for row in rows]


def create_job(
    kind: str,
    payload: dict[str, Any],
    document_id_value: str | None = None,
) -> dict[str, Any]:
    job_id = uuid.uuid4()
    with _pool().connection() as conn:
        row = conn.execute(
            """
            INSERT INTO agent_jobs (id, kind, document_id, payload)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (job_id, kind, document_id_value, Jsonb(payload)),
        ).fetchone()
    return _serialize(row)


def get_job(job_id: str) -> dict[str, Any] | None:
    with _pool().connection() as conn:
        row = conn.execute(
            "SELECT * FROM agent_jobs WHERE id = %s", (job_id,)
        ).fetchone()
    return _serialize(row) if row else None


def claim_job() -> dict[str, Any] | None:
    with _pool().connection() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                SELECT *
                FROM agent_jobs
                WHERE status = 'queued' AND attempts < max_attempts
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            row = conn.execute(
                """
                UPDATE agent_jobs
                SET status = 'processing', attempts = attempts + 1,
                    started_at = now(), updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (row["id"],),
            ).fetchone()
    return _serialize(row)


def complete_job(job_id: str, result: dict[str, Any]) -> None:
    with _pool().connection() as conn:
        conn.execute(
            """
            UPDATE agent_jobs
            SET status = 'succeeded', result = %s, error = NULL,
                finished_at = now(), updated_at = now()
            WHERE id = %s
            """,
            (Jsonb(result), job_id),
        )


def fail_job(job_id: str, error: str) -> None:
    with _pool().connection() as conn:
        row = conn.execute(
            "SELECT attempts, max_attempts FROM agent_jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
        status = "failed" if row and row["attempts"] >= row["max_attempts"] else "queued"
        conn.execute(
            """
            UPDATE agent_jobs
            SET status = %s, error = %s, updated_at = now(),
                finished_at = CASE WHEN %s = 'failed' THEN now() ELSE NULL END
            WHERE id = %s
            """,
            (status, error[:4000], status, job_id),
        )
