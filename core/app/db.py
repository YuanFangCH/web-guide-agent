from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import settings


def _connect() -> sqlite3.Connection:
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                visitor_id TEXT NOT NULL,
                page_url TEXT NOT NULL DEFAULT '',
                page_title TEXT NOT NULL DEFAULT '',
                reasoning_effort TEXT NOT NULL DEFAULT 'low',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS page_cache (
                page_key TEXT PRIMARY KEY,
                site_id TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL,
                page_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS page_sections (
                page_key TEXT NOT NULL,
                anchor TEXT NOT NULL,
                selector TEXT NOT NULL DEFAULT '',
                heading TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (page_key, anchor),
                FOREIGN KEY (page_key) REFERENCES page_cache(page_key)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS section_answers (
                section_hash TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                model TEXT NOT NULL,
                answer TEXT NOT NULL,
                sources_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                hit_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (section_hash, prompt_version, model)
            );

            CREATE TABLE IF NOT EXISTS tool_audit_logs (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL DEFAULT '',
                profile TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                ok INTEGER NOT NULL DEFAULT 1,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS website_write_sessions (
                id TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                scopes_json TEXT NOT NULL DEFAULT '[]',
                mode TEXT NOT NULL DEFAULT 'draft-only',
                purpose TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            );

            CREATE INDEX IF NOT EXISTS messages_conversation_idx
                ON messages (conversation_id, created_at);
            CREATE INDEX IF NOT EXISTS conversations_updated_idx
                ON conversations (updated_at);
            CREATE INDEX IF NOT EXISTS page_sections_page_idx
                ON page_sections (page_key, ordinal);
            CREATE INDEX IF NOT EXISTS tool_audit_created_idx
                ON tool_audit_logs (created_at);
            CREATE INDEX IF NOT EXISTS website_write_sessions_expiry_idx
                ON website_write_sessions (expires_at);
            """
        )
        write_session_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(website_write_sessions)"
            ).fetchall()
        }
        if "mode" not in write_session_columns:
            conn.execute(
                "ALTER TABLE website_write_sessions "
                "ADD COLUMN mode TEXT NOT NULL DEFAULT 'draft-only'"
            )
        conversation_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(conversations)"
            ).fetchall()
        }
        if "reasoning_effort" not in conversation_columns:
            conn.execute(
                "ALTER TABLE conversations "
                "ADD COLUMN reasoning_effort TEXT NOT NULL DEFAULT 'low'"
            )
        conn.execute(
            "UPDATE users SET role = 'member' "
            "WHERE role NOT IN ('owner', 'member')"
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 240_000
    ).hex()


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    return _hash_password(password, salt), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    return hmac.compare_digest(
        password_hash, _hash_password(password, salt)
    )


def ensure_admin() -> None:
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (settings.admin_username,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE users
                SET display_name = ?, role = 'owner'
                WHERE username = ?
                """,
                (settings.admin_username, settings.admin_username),
            )
            return
        password_hash, salt = hash_password(settings.admin_password)
        conn.execute(
            """
            INSERT INTO users
                (id, username, display_name, role, password_hash, salt, created_at)
            VALUES (?, ?, ?, 'owner', ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                settings.admin_username,
                settings.admin_username,
                password_hash,
                salt,
                now_iso(),
            ),
        )


def get_user_account(username: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, username, display_name, role, created_at
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row["display_name"],
        "role": row["role"],
        "createdAt": row["created_at"],
    }


def list_user_accounts() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, username, display_name, role, created_at
            FROM users
            ORDER BY created_at, username
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "username": row["username"],
            "displayName": row["display_name"],
            "role": row["role"],
            "createdAt": row["created_at"],
        }
        for row in rows
    ]


def sync_user_account(
    *,
    username: str,
    display_name: str,
    role: str,
    password: str = "",
    previous_username: str = "",
) -> dict[str, Any]:
    if role not in {"owner", "member"}:
        raise ValueError("invalid_role")
    username = username.strip()
    display_name = display_name.strip()
    if not username or not display_name:
        raise ValueError("username_and_display_name_required")

    with _connect() as conn:
        previous = None
        if previous_username and previous_username != username:
            previous = conn.execute(
                "SELECT * FROM users WHERE username = ?", (previous_username,)
            ).fetchone()
        existing = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if previous and existing and previous["id"] != existing["id"]:
            raise ValueError("username_exists")

        current = previous or existing
        if current and current["role"] == "owner" and role != "owner":
            owner_count = conn.execute(
                "SELECT COUNT(*) AS count FROM users WHERE role = 'owner'"
            ).fetchone()["count"]
            if owner_count <= 1:
                raise ValueError("last_owner_required")

        if current:
            password_hash = current["password_hash"]
            salt = current["salt"]
            if password:
                password_hash, salt = hash_password(password)
            conn.execute(
                """
                UPDATE users
                SET username = ?, display_name = ?, role = ?,
                    password_hash = ?, salt = ?
                WHERE id = ?
                """,
                (
                    username,
                    display_name,
                    role,
                    password_hash,
                    salt,
                    current["id"],
                ),
            )
            account_id = current["id"]
        else:
            if not password:
                raise ValueError("password_required")
            password_hash, salt = hash_password(password)
            account_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO users
                    (id, username, display_name, role, password_hash, salt, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    username,
                    display_name,
                    role,
                    password_hash,
                    salt,
                    now_iso(),
                ),
            )

    account = get_user_account(username)
    if not account:
        raise RuntimeError("account_sync_failed")
    return account


def delete_user_account(username: str) -> None:
    with _connect() as conn:
        existing = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not existing:
            return
        if existing["role"] == "owner":
            owner_count = conn.execute(
                "SELECT COUNT(*) AS count FROM users WHERE role = 'owner'"
            ).fetchone()["count"]
            if owner_count <= 1:
                raise ValueError("last_owner_required")
        conn.execute("DELETE FROM users WHERE id = ?", (existing["id"],))


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    with _connect() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    if not user:
        return None
    if not verify_password(password, user["password_hash"], user["salt"]):
        return None
    return {
        "id": user["id"],
        "username": user["username"],
        "displayName": user["display_name"],
        "role": user["role"],
    }


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, username, display_name, role
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row["display_name"],
        "role": row["role"],
    }


def _session_hash(token: str) -> str:
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_session(user_id: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(36)
    session_id = uuid.uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions
                (id, user_id, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                _session_hash(token),
                expires_at.isoformat(),
                now_iso(),
            ),
        )
    return token, expires_at.isoformat()


def get_session_user(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.display_name, u.role
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ?
            """,
            (_session_hash(token), now_iso()),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row["display_name"],
        "role": row["role"],
    }


def delete_session(token: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE token_hash = ?", (_session_hash(token),)
        )


def create_conversation(
    visitor_id: str,
    page_url: str,
    page_title: str,
    reasoning_effort: str = "low",
) -> str:
    conversation_id = uuid.uuid4().hex
    timestamp = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO conversations
                (
                    id, visitor_id, page_url, page_title, reasoning_effort,
                    created_at, updated_at
                )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                visitor_id,
                page_url[:2000],
                page_title[:500],
                reasoning_effort,
                timestamp,
                timestamp,
            ),
        )
    return conversation_id


def conversation_exists(conversation_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    return bool(row)


def get_conversation_reasoning_effort(conversation_id: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT reasoning_effort FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    return str(row["reasoning_effort"]) if row else None


def set_conversation_reasoning_effort(
    conversation_id: str, reasoning_effort: str
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE conversations
            SET reasoning_effort = ?, updated_at = ?
            WHERE id = ?
            """,
            (reasoning_effort, now_iso(), conversation_id),
        )


def append_message(
    conversation_id: str,
    role: str,
    content: str,
    sources: list[dict[str, Any]] | None = None,
) -> None:
    timestamp = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO messages
                (id, conversation_id, role, content, sources_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                conversation_id,
                role,
                content,
                json.dumps(sources or [], ensure_ascii=False),
                timestamp,
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (timestamp, conversation_id),
        )


def list_conversations(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.*, COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_messages(conversation_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, sources_json, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at
            """,
            (conversation_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "sources": json.loads(row["sources_json"] or "[]"),
            "createdAt": row["created_at"],
        }
        for row in rows
    ]


def recent_messages(conversation_id: str, limit: int = 6) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def _section_hash(heading: str, text: str) -> str:
    return hashlib.sha256(f"{heading}\0{text}".encode("utf-8")).hexdigest()


def section_hash(heading: str, text: str) -> str:
    return _section_hash(heading, text)


def upsert_page_cache(
    *,
    page_key: str,
    site_id: str,
    url: str,
    title: str,
    content_hash: str,
    page_text: str,
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    timestamp = now_iso()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT content_hash FROM page_cache WHERE page_key = ?",
            (page_key,),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO page_cache (
                page_key, site_id, url, title, content_hash, page_text,
                created_at, updated_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (page_key) DO UPDATE SET
                site_id = EXCLUDED.site_id,
                url = EXCLUDED.url,
                title = EXCLUDED.title,
                content_hash = EXCLUDED.content_hash,
                page_text = EXCLUDED.page_text,
                updated_at = CASE
                    WHEN page_cache.content_hash = EXCLUDED.content_hash
                    THEN page_cache.updated_at
                    ELSE EXCLUDED.updated_at
                END,
                last_seen_at = EXCLUDED.last_seen_at
            """,
            (
                page_key,
                site_id,
                url[:2000],
                title[:500],
                content_hash,
                page_text,
                timestamp,
                timestamp,
                timestamp,
            ),
        )

        if existing and existing["content_hash"] == content_hash:
            return {
                "pageKey": page_key,
                "changed": False,
                "sectionCount": len(sections),
            }

        anchors = [str(section.get("anchor") or "") for section in sections]
        if anchors:
            placeholders = ",".join("?" for _ in anchors)
            conn.execute(
                f"DELETE FROM page_sections WHERE page_key = ? "
                f"AND anchor NOT IN ({placeholders})",
                (page_key, *anchors),
            )
        else:
            conn.execute("DELETE FROM page_sections WHERE page_key = ?", (page_key,))

        for index, section in enumerate(sections):
            anchor = str(section.get("anchor") or f"section-{index + 1}")
            heading = str(section.get("heading") or "")
            text = str(section.get("text") or "")
            conn.execute(
                """
                INSERT INTO page_sections (
                    page_key, anchor, selector, heading, text, ordinal,
                    content_hash, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (page_key, anchor) DO UPDATE SET
                    selector = EXCLUDED.selector,
                    heading = EXCLUDED.heading,
                    text = EXCLUDED.text,
                    ordinal = EXCLUDED.ordinal,
                    content_hash = EXCLUDED.content_hash,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    page_key,
                    anchor,
                    str(section.get("selector") or ""),
                    heading,
                    text[:1500],
                    index,
                    _section_hash(heading, text),
                    timestamp,
                ),
            )
    return {
        "pageKey": page_key,
        "changed": True,
        "sectionCount": len(sections),
    }


def get_page_cache(page_key: str) -> dict[str, Any] | None:
    with _connect() as conn:
        page = conn.execute(
            "SELECT * FROM page_cache WHERE page_key = ?", (page_key,)
        ).fetchone()
        if not page:
            return None
        sections = conn.execute(
            """
            SELECT anchor, selector, heading, text, ordinal, content_hash
            FROM page_sections
            WHERE page_key = ?
            ORDER BY ordinal
            """,
            (page_key,),
        ).fetchall()
    result = dict(page)
    result["sections"] = [dict(section) for section in sections]
    return result


def get_cached_section(page_key: str, anchor: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT s.*, p.url, p.title
            FROM page_sections s
            JOIN page_cache p ON p.page_key = s.page_key
            WHERE s.page_key = ? AND s.anchor = ?
            """,
            (page_key, anchor),
        ).fetchone()
    return dict(row) if row else None


def get_section_answer(
    section_hash: str, prompt_version: str, model: str
) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM section_answers
            WHERE section_hash = ? AND prompt_version = ? AND model = ?
            """,
            (section_hash, prompt_version, model),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            """
            UPDATE section_answers
            SET hit_count = hit_count + 1, updated_at = ?
            WHERE section_hash = ? AND prompt_version = ? AND model = ?
            """,
            (now_iso(), section_hash, prompt_version, model),
        )
    result = dict(row)
    result["sources"] = json.loads(result.pop("sources_json") or "[]")
    return result


def save_section_answer(
    *,
    section_hash: str,
    prompt_version: str,
    model: str,
    answer: str,
    sources: list[dict[str, Any]],
) -> None:
    timestamp = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO section_answers (
                section_hash, prompt_version, model, answer, sources_json,
                created_at, updated_at, hit_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT (section_hash, prompt_version, model) DO UPDATE SET
                answer = EXCLUDED.answer,
                sources_json = EXCLUDED.sources_json,
                updated_at = EXCLUDED.updated_at
            """,
            (
                section_hash,
                prompt_version,
                model,
                answer,
                json.dumps(sources, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )


def log_tool_call(
    *,
    conversation_id: str,
    profile: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
    ok: bool,
    duration_ms: int,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO tool_audit_logs (
                id, conversation_id, profile, tool_name, arguments_json,
                result_json, ok, duration_ms, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                conversation_id,
                profile,
                tool_name,
                json.dumps(arguments, ensure_ascii=False)[:20000],
                json.dumps(result, ensure_ascii=False)[:20000],
                1 if ok else 0,
                duration_ms,
                now_iso(),
            ),
        )


def list_tool_audit(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM tool_audit_logs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            **dict(row),
            "arguments": json.loads(row["arguments_json"] or "{}"),
            "result": json.loads(row["result_json"] or "{}"),
        }
        for row in rows
    ]


def page_cache_stats() -> dict[str, Any]:
    with _connect() as conn:
        pages = conn.execute("SELECT COUNT(*) AS count FROM page_cache").fetchone()
        sections = conn.execute(
            "SELECT COUNT(*) AS count FROM page_sections"
        ).fetchone()
        answers = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(hit_count), 0) AS hits "
            "FROM section_answers"
        ).fetchone()
    return {
        "pages": pages["count"],
        "sections": sections["count"],
        "cachedAnswers": answers["count"],
        "answerHits": answers["hits"],
    }


def save_website_write_session(
    *,
    session_id: str,
    token: str,
    scopes: list[str],
    mode: str,
    purpose: str,
    created_by: str,
    created_at: str,
    expires_at: str,
) -> dict[str, Any]:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO website_write_sessions (
                id, token, scopes_json, mode, purpose, created_by,
                created_at, expires_at, revoked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT (id) DO UPDATE SET
                token = EXCLUDED.token,
                scopes_json = EXCLUDED.scopes_json,
                mode = EXCLUDED.mode,
                purpose = EXCLUDED.purpose,
                created_by = EXCLUDED.created_by,
                created_at = EXCLUDED.created_at,
                expires_at = EXCLUDED.expires_at,
                revoked_at = NULL
            """,
            (
                session_id,
                token,
                json.dumps(scopes, ensure_ascii=False),
                mode,
                purpose,
                created_by,
                created_at,
                expires_at,
            ),
        )
    return {
        "id": session_id,
        "scopes": scopes,
        "mode": mode,
        "purpose": purpose,
        "createdBy": created_by,
        "createdAt": created_at,
        "expiresAt": expires_at,
        "revokedAt": None,
        "active": True,
    }


def get_active_website_write_session(
    created_by: str | None = None,
) -> dict[str, Any] | None:
    clauses = ["revoked_at IS NULL", "expires_at > ?"]
    params: list[Any] = [now_iso()]
    if created_by:
        clauses.append("created_by = ?")
        params.append(created_by)
    with _connect() as conn:
        conn.execute(
            """
            UPDATE website_write_sessions
            SET token = ''
            WHERE expires_at <= ? AND token <> ''
            """,
            (now_iso(),),
        )
        row = conn.execute(
            f"""
            SELECT *
            FROM website_write_sessions
            WHERE {" AND ".join(clauses)}
            ORDER BY created_at DESC
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["scopes"] = json.loads(result.pop("scopes_json") or "[]")
    result["createdBy"] = result.pop("created_by")
    result["createdAt"] = result.pop("created_at")
    result["expiresAt"] = result.pop("expires_at")
    result["revokedAt"] = result.pop("revoked_at")
    result["mode"] = result.get("mode") or "draft-only"
    result["active"] = True
    return result


def list_website_write_sessions(
    created_by: str | None = None,
) -> list[dict[str, Any]]:
    where = "WHERE created_by = ?" if created_by else ""
    params: tuple[Any, ...] = (created_by,) if created_by else ()
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM website_write_sessions
            {where}
            ORDER BY created_at DESC
            LIMIT 20
            """,
            params,
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        value = dict(row)
        value["scopes"] = json.loads(value.pop("scopes_json") or "[]")
        value["createdBy"] = value.pop("created_by")
        value["createdAt"] = value.pop("created_at")
        value["expiresAt"] = value.pop("expires_at")
        value["revokedAt"] = value.pop("revoked_at")
        value["mode"] = value.get("mode") or "draft-only"
        value["active"] = not value["revokedAt"] and value["expiresAt"] > now_iso()
        result.append(value)
    return result


def mark_website_write_session_revoked(session_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE website_write_sessions
            SET revoked_at = ?, token = ''
            WHERE id = ?
            """,
            (now_iso(), session_id),
        )


def cleanup_page_cache(retention_days: int) -> int:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=retention_days)
    ).isoformat()
    with _connect() as conn:
        result = conn.execute(
            "DELETE FROM page_cache WHERE last_seen_at < ?", (cutoff,)
        )
    return result.rowcount


def create_note(user_id: str, title: str, content: str) -> dict[str, Any]:
    timestamp = now_iso()
    note_id = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO notes
                (id, user_id, title, content, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (note_id, user_id, title, content, timestamp, timestamp),
        )
    return {
        "id": note_id,
        "title": title,
        "content": content,
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }


def list_notes(user_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, content, created_at, updated_at
            FROM notes
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def get_note(note_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return _row(row)


def get_sync_state(key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM sync_state WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_sync_state(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sync_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = EXCLUDED.updated_at
            """,
            (key, value, now_iso()),
        )


def cleanup_conversations(retention_days: int) -> int:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=retention_days)
    ).isoformat()
    with _connect() as conn:
        result = conn.execute(
            "DELETE FROM conversations WHERE updated_at < ?", (cutoff,)
        )
    return result.rowcount
