from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings


class WebsiteDatabaseUnavailable(RuntimeError):
    pass


CONTENT_TYPES: dict[str, dict[str, Any]] = {
    "post": {
        "table": "Post",
        "search_columns": ("title", "summary", "content", "slug"),
        "identity_columns": ("id", "slug"),
    },
    "image": {
        "table": "Image",
        "search_columns": ("title", "description", "album", "slug"),
        "identity_columns": ("id", "slug"),
    },
    "video": {
        "table": "Video",
        "search_columns": ("title", "description", "slug"),
        "identity_columns": ("id", "slug"),
    },
    "media": {
        "table": "MediaAsset",
        "search_columns": ("originalName", "mimeType", "storageKey"),
        "identity_columns": ("id", "storageKey"),
    },
    "category": {
        "table": "Category",
        "search_columns": ("name", "slug", "description"),
        "identity_columns": ("id", "slug"),
    },
    "tag": {
        "table": "Tag",
        "search_columns": ("name", "slug"),
        "identity_columns": ("id", "slug"),
    },
}

CONTENT_STATUSES = {"DRAFT", "PUBLISHED", "ARCHIVED"}
DOWNLOAD_CONTENT_TYPES = {"post", "image"}


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


class WebsiteContentDatabase:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or settings.website_readonly_database_url
        self.pool: ConnectionPool | None = None

    @property
    def configured(self) -> bool:
        return bool(self.database_url)

    def start(self) -> None:
        if not self.configured or self.pool is not None:
            return
        self.pool = ConnectionPool(
            conninfo=self.database_url,
            min_size=0,
            max_size=4,
            timeout=5,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        self.pool.open(wait=True, timeout=5)

    def close(self) -> None:
        if self.pool is not None:
            self.pool.close()
            self.pool = None

    def health(self) -> dict[str, Any]:
        if not self.configured:
            return {"configured": False, "ok": False, "error": "not_configured"}
        try:
            self.start()
            with self._connection() as conn:
                conn.execute("SELECT 1").fetchone()
            return {"configured": True, "ok": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"configured": True, "ok": False, "error": str(exc)}

    def _connection(self):
        if self.pool is None:
            raise WebsiteDatabaseUnavailable("website_database_not_started")
        return self.pool.connection()

    def search(
        self,
        *,
        content_type: str,
        query: str = "",
        status: str | None = None,
        album: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        config = CONTENT_TYPES.get(content_type)
        if not config:
            raise ValueError("unsupported_content_type")
        if status and status not in CONTENT_STATUSES:
            raise ValueError("invalid_status")
        safe_limit = min(max(int(limit), 1), 50)
        table = sql.Identifier(str(config["table"]))
        search_columns = list(config["search_columns"])
        conditions: list[sql.Composable] = []
        parameters: list[Any] = []

        if query.strip():
            pattern = f"%{query.strip()}%"
            conditions.append(
                sql.SQL("(")
                + sql.SQL(" OR ").join(
                    sql.SQL("{}::text ILIKE %s").format(sql.Identifier(column))
                    for column in search_columns
                )
                + sql.SQL(")")
            )
            parameters.extend([pattern] * len(search_columns))

        if status and content_type in {"post", "image", "video"}:
            conditions.append(sql.SQL('"status"::text = %s'))
            parameters.append(status)
        if album and content_type == "image":
            conditions.append(sql.SQL('"album" ILIKE %s'))
            parameters.append(f"%{album}%")
        if category and content_type in {"post", "video"}:
            conditions.append(
                sql.SQL(
                    'EXISTS (SELECT 1 FROM {} c WHERE c."id" = {}.{} '
                    'AND (c."id" = %s OR c."slug" = %s))'
                ).format(
                    sql.Identifier("Category"),
                    table,
                    sql.Identifier("categoryId"),
                )
            )
            parameters.extend([category, category])
        if tag and content_type in {"post", "video"}:
            join_table = "_PostToTag" if content_type == "post" else "_TagToVideo"
            source_column = "A" if content_type == "post" else "B"
            target_column = "B" if content_type == "post" else "A"
            conditions.append(
                sql.SQL(
                    'EXISTS (SELECT 1 FROM {} jt JOIN {} t ON t."id" = jt.{} '
                    'WHERE jt.{} = {}.{} AND '
                    '(t."id" = %s OR t."slug" = %s OR t."name" = %s))'
                ).format(
                    sql.Identifier(join_table),
                    sql.Identifier("Tag"),
                    sql.Identifier(target_column),
                    sql.Identifier(source_column),
                    table,
                    sql.Identifier("id"),
                )
            )
            parameters.extend([tag, tag, tag])

        where_sql = (
            sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
            if conditions
            else sql.SQL("")
        )
        order_sql = (
            sql.SQL(' ORDER BY "updatedAt" DESC')
            if content_type in {"post", "video"}
            else sql.SQL(' ORDER BY "createdAt" DESC')
            if content_type in {"image", "media", "category", "tag"}
            else sql.SQL("")
        )
        select_columns = {
            "post": sql.SQL(
                'id, slug, title, summary, status::text AS status, "publishedAt", '
                '"updatedAt", "categoryId", "coverImageId", '
                'left(content, 1200) AS "contentExcerpt"'
            ),
            "image": sql.SQL(
                'id, slug, title, description, album, status::text AS status, '
                '"publishedAt", "assetId"'
            ),
            "video": sql.SQL(
                'id, slug, title, description, status::text AS status, '
                '"publishedAt", "updatedAt", "categoryId", "videoAssetId", '
                '"posterAssetId"'
            ),
            "media": sql.SQL(
                'id, kind::text AS kind, "originalName", "mimeType", size, '
                'width, height, "durationSeconds", "publicUrl", "thumbnailUrl"'
            ),
            "category": sql.SQL('id, name, slug, description'),
            "tag": sql.SQL("id, name, slug"),
        }
        statement = (
            sql.SQL("SELECT {} FROM {}").format(
                select_columns[content_type], table
            )
            + where_sql
            + order_sql
            + sql.SQL(" LIMIT %s")
        )
        parameters.append(safe_limit)
        with self._connection() as conn:
            conn.execute("SET statement_timeout = 5000")
            rows = conn.execute(statement, parameters).fetchall()
        return [_json_value(dict(row)) for row in rows]

    def get(self, *, content_type: str, identifier: str) -> dict[str, Any] | None:
        config = CONTENT_TYPES.get(content_type)
        if not config:
            raise ValueError("unsupported_content_type")
        table = sql.Identifier(str(config["table"]))
        identity_columns = list(config["identity_columns"])
        statement = sql.SQL("SELECT * FROM {} WHERE {} LIMIT 1").format(
            table,
            sql.SQL(" OR ").join(
                sql.SQL("{}::text = %s").format(sql.Identifier(column))
                for column in identity_columns
            ),
        )
        with self._connection() as conn:
            conn.execute("SET statement_timeout = 5000")
            row = conn.execute(
                statement, [identifier] * len(identity_columns)
            ).fetchone()
        return _json_value(dict(row)) if row else None

    def library_search(
        self,
        *,
        content_type: str,
        query: str = "",
        album: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        if content_type not in DOWNLOAD_CONTENT_TYPES:
            raise ValueError("unsupported_download_content_type")

        safe_limit = min(max(int(limit), 1), 50)
        safe_offset = max(0, int(offset))
        conditions: list[sql.Composable] = [
            sql.SQL('item."status"::text = %s')
        ]
        parameters: list[Any] = ["PUBLISHED"]

        search_columns = (
            ("title", "summary", "content", "slug")
            if content_type == "post"
            else ("title", "description", "album", "slug")
        )
        if query.strip():
            pattern = f"%{query.strip()}%"
            conditions.append(
                sql.SQL("(")
                + sql.SQL(" OR ").join(
                    sql.SQL("item.{}::text ILIKE %s").format(
                        sql.Identifier(column)
                    )
                    for column in search_columns
                )
                + sql.SQL(")")
            )
            parameters.extend([pattern] * len(search_columns))
        if album and content_type == "image":
            conditions.append(sql.SQL('item."album" ILIKE %s'))
            parameters.append(f"%{album.strip()}%")

        table = sql.Identifier(
            "Post" if content_type == "post" else "Image"
        )
        where_sql = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)

        if content_type == "post":
            select_sql = sql.SQL(
                'item.id, item.slug, item.title, item.summary, '
                'item."publishedAt", item."updatedAt", '
                'category.name AS "categoryName", '
                'cover_asset."thumbnailUrl" AS "coverThumbnailUrl", '
                'cover_asset."publicUrl" AS "coverUrl"'
            )
            from_sql = sql.SQL(
                "{} AS item "
                "LEFT JOIN {} AS category "
                'ON category."id" = item."categoryId" '
                "LEFT JOIN {} AS cover "
                'ON cover."id" = item."coverImageId" '
                "LEFT JOIN {} AS cover_asset "
                'ON cover_asset."id" = cover."assetId"'
            ).format(
                table,
                sql.Identifier("Category"),
                sql.Identifier("Image"),
                sql.Identifier("MediaAsset"),
            )
        else:
            select_sql = sql.SQL(
                'item.id, item.slug, item.title, item.description, item.album, '
                'item."publishedAt", asset.id AS "assetId", '
                'asset."originalName", asset."mimeType", asset.size, '
                'asset.width, asset.height, asset."storageKey", '
                'asset."publicUrl", asset."thumbnailUrl"'
            )
            from_sql = sql.SQL(
                "{} AS item JOIN {} AS asset "
                'ON asset."id" = item."assetId"'
            ).format(table, sql.Identifier("MediaAsset"))

        count_statement = (
            sql.SQL("SELECT count(*) AS count FROM {} AS item").format(table)
            + where_sql
        )
        statement = (
            sql.SQL("SELECT {} FROM {}").format(select_sql, from_sql)
            + where_sql
            + sql.SQL(' ORDER BY item."publishedAt" DESC NULLS LAST')
            + sql.SQL(" LIMIT %s OFFSET %s")
        )
        query_parameters = [*parameters, safe_limit, safe_offset]

        with self._connection() as conn:
            conn.execute("SET statement_timeout = 5000")
            total = int(
                conn.execute(count_statement, parameters).fetchone()["count"]
            )
            rows = conn.execute(statement, query_parameters).fetchall()
        return {
            "items": [_json_value(dict(row)) for row in rows],
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
        }

    def get_download_item(
        self, *, content_type: str, identifier: str
    ) -> dict[str, Any] | None:
        if content_type not in DOWNLOAD_CONTENT_TYPES:
            raise ValueError("unsupported_download_content_type")

        if content_type == "post":
            statement = sql.SQL(
                'SELECT item.*, category.name AS "categoryName" '
                "FROM {} AS item LEFT JOIN {} AS category "
                'ON category."id" = item."categoryId" '
                'WHERE (item."id" = %s OR item."slug" = %s) '
                'AND item."status"::text = %s LIMIT 1'
            ).format(sql.Identifier("Post"), sql.Identifier("Category"))
        else:
            statement = sql.SQL(
                'SELECT item.id, item.slug, item.title, item.description, '
                'item.album, item."publishedAt", asset.id AS "assetId", '
                'asset."originalName", asset."mimeType", asset.size, '
                'asset.width, asset.height, asset."storageKey", '
                'asset."publicUrl", asset."thumbnailUrl" '
                "FROM {} AS item JOIN {} AS asset "
                'ON asset."id" = item."assetId" '
                'WHERE (item."id" = %s OR item."slug" = %s) '
                'AND item."status"::text = %s LIMIT 1'
            ).format(sql.Identifier("Image"), sql.Identifier("MediaAsset"))

        with self._connection() as conn:
            conn.execute("SET statement_timeout = 5000")
            row = conn.execute(
                statement, [identifier, identifier, "PUBLISHED"]
            ).fetchone()
        return _json_value(dict(row)) if row else None

    def site_url(self) -> str:
        with self._connection() as conn:
            conn.execute("SET statement_timeout = 5000")
            row = conn.execute(
                'SELECT "siteUrl" FROM "SiteSetting" WHERE "id" = 1'
            ).fetchone()
        return str(row["siteUrl"]).rstrip("/") if row else ""

    def stats(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        with self._connection() as conn:
            conn.execute("SET statement_timeout = 5000")
            for content_type, config in CONTENT_TYPES.items():
                table = sql.Identifier(str(config["table"]))
                if content_type in {"post", "image", "video"}:
                    rows = conn.execute(
                        sql.SQL(
                            'SELECT "status"::text AS status, count(*) AS count '
                            "FROM {} GROUP BY \"status\""
                        ).format(table)
                    ).fetchall()
                    result[content_type] = {
                        str(row["status"]): int(row["count"]) for row in rows
                    }
                else:
                    count = conn.execute(
                        sql.SQL("SELECT count(*) AS count FROM {}").format(table)
                    ).fetchone()
                    result[content_type] = int(count["count"])
        return {key: _json_value(value) for key, value in result.items()}


website_content_db = WebsiteContentDatabase()
