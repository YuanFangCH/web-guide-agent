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
    db_path: str
    admin_username: str
    admin_password: str
    account_sync_token: str
    session_secret: str
    public_base_url: str
    rag_base_url: str
    rag_service_token: str
    website_export_base_url: str
    website_export_token: str
    website_sync_enabled: bool
    website_sync_interval_seconds: int
    website_manifest_interval_seconds: int
    website_readonly_database_url: str
    website_write_base_url: str
    website_write_admin_token: str
    website_write_session_default_minutes: int
    website_write_session_max_minutes: int
    chat_base_url: str
    chat_api_key: str
    chat_model: str
    chat_fallback_base_url: str
    chat_fallback_api_key: str
    chat_fallback_model: str
    chat_thinking: str
    chat_reasoning_effort: str
    prompt_version: str
    site_id: str
    tool_config_path: str
    tool_timeout_seconds: float
    tool_max_result_chars: int
    agent_max_tool_rounds: int
    agent_max_consecutive_tool_errors: int
    page_cache_retention_days: int
    chat_rate_limit_per_minute: int
    page_cache_rate_limit_per_minute: int
    website_download_limit_mbps: float
    website_download_burst_seconds: float
    conversation_retention_days: int
    web_search_provider: str
    web_search_api_key: str
    web_search_base_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        public_base_url = _env("GUIDE_AGENT_PUBLIC_BASE_URL")
        return cls(
            db_path=_env("GUIDE_AGENT_DB_PATH", "/data/guide-agent.db"),
            admin_username=_env("GUIDE_AGENT_ADMIN_USERNAME", "admin"),
            admin_password=_env("GUIDE_AGENT_ADMIN_PASSWORD", "change-me-now"),
            account_sync_token=_env("ACCOUNT_SYNC_TOKEN"),
            session_secret=_env(
                "GUIDE_AGENT_SESSION_SECRET", "replace-with-a-long-random-secret"
            ),
            public_base_url=public_base_url,
            rag_base_url=_env("RAG_BASE_URL", "http://rag:8000").rstrip("/"),
            rag_service_token=_env("RAG_BOOTSTRAP_API_KEY"),
            website_export_base_url=_env("WEBSITE_EXPORT_BASE_URL").rstrip("/"),
            website_export_token=_env("WEBSITE_EXPORT_TOKEN"),
            website_sync_enabled=_env("WEBSITE_SYNC_ENABLED", "false").lower()
            in {"1", "true", "yes", "on"},
            website_sync_interval_seconds=max(
                30, int(_env("WEBSITE_SYNC_INTERVAL_SECONDS", "300"))
            ),
            website_manifest_interval_seconds=max(
                300, int(_env("WEBSITE_MANIFEST_INTERVAL_SECONDS", "43200"))
            ),
            website_readonly_database_url=_env(
                "WEBSITE_READONLY_DATABASE_URL"
            ),
            website_write_base_url=_env("WEBSITE_WRITE_BASE_URL").rstrip("/"),
            website_write_admin_token=_env("WEBSITE_WRITE_ADMIN_TOKEN"),
            website_write_session_default_minutes=max(
                5, int(_env("WEBSITE_WRITE_SESSION_DEFAULT_MINUTES", "30"))
            ),
            website_write_session_max_minutes=max(
                5, int(_env("WEBSITE_WRITE_SESSION_MAX_MINUTES", "60"))
            ),
            chat_base_url=_env("CHAT_BASE_URL").rstrip("/"),
            chat_api_key=_env("CHAT_API_KEY"),
            chat_model=_env("CHAT_MODEL"),
            chat_fallback_base_url=_env("CHAT_FALLBACK_BASE_URL").rstrip("/"),
            chat_fallback_api_key=_env("CHAT_FALLBACK_API_KEY"),
            chat_fallback_model=_env("CHAT_FALLBACK_MODEL"),
            chat_thinking=_env("CHAT_THINKING", "enabled").lower(),
            chat_reasoning_effort=_env("CHAT_REASONING_EFFORT", "low").lower(),
            prompt_version=_env("PROMPT_VERSION", "v1"),
            site_id=_env("GUIDE_AGENT_SITE_ID", "default-site"),
            tool_config_path=_env("TOOL_CONFIG_PATH", "tool_configure.json"),
            tool_timeout_seconds=float(_env("TOOL_TIMEOUT_SECONDS", "20")),
            tool_max_result_chars=int(_env("TOOL_MAX_RESULT_CHARS", "8192")),
            agent_max_tool_rounds=int(_env("AGENT_MAX_TOOL_ROUNDS", "10")),
            agent_max_consecutive_tool_errors=int(
                _env("AGENT_MAX_CONSECUTIVE_TOOL_ERRORS", "3")
            ),
            page_cache_retention_days=max(
                1, int(_env("PAGE_CACHE_RETENTION_DAYS", "90"))
            ),
            chat_rate_limit_per_minute=max(
                1, int(_env("CHAT_RATE_LIMIT_PER_MINUTE", "30"))
            ),
            page_cache_rate_limit_per_minute=max(
                1, int(_env("PAGE_CACHE_RATE_LIMIT_PER_MINUTE", "60"))
            ),
            website_download_limit_mbps=max(
                0.1, float(_env("WEBSITE_DOWNLOAD_LIMIT_MBPS", "10"))
            ),
            website_download_burst_seconds=max(
                0.1, float(_env("WEBSITE_DOWNLOAD_BURST_SECONDS", "0.1"))
            ),
            conversation_retention_days=max(
                1, int(_env("CONVERSATION_RETENTION_DAYS", "90"))
            ),
            web_search_provider=_env("WEB_SEARCH_PROVIDER"),
            web_search_api_key=_env("WEB_SEARCH_API_KEY"),
            web_search_base_url=_env("WEB_SEARCH_BASE_URL").rstrip("/"),
        )

    @property
    def cookie_secure(self) -> bool:
        return self.public_base_url.startswith("https://")


settings = Settings.from_env()
