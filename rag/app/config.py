from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    upload_dir: str
    bootstrap_api_key: str
    embedding_provider: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_dimension: int
    vector_table_name: str
    max_upload_bytes: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=_env(
                "DATABASE_URL",
                "postgresql://guide-agent:guide-agent@localhost:5432/guide-agent",
            ),
            upload_dir=_env("UPLOAD_DIR", "/data/uploads"),
            bootstrap_api_key=_env("RAG_BOOTSTRAP_API_KEY"),
            embedding_provider=_env("EMBEDDING_PROVIDER", "openai").lower(),
            embedding_base_url=_env("EMBEDDING_BASE_URL"),
            embedding_api_key=_env("EMBEDDING_API_KEY"),
            embedding_model=_env("EMBEDDING_MODEL"),
            embedding_dimension=int(_env("EMBEDDING_DIMENSION", "1024")),
            vector_table_name=_env(
                "VECTOR_TABLE_NAME", "guide_agent_haystack_documents"
            ),
            max_upload_bytes=int(_env("MAX_UPLOAD_BYTES", "52428800")),
        )


settings = Settings.from_env()
