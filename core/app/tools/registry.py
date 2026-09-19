from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path
from typing import Any

from .base import ToolContext, ToolResult, ToolSpec


class ToolRegistry:
    def __init__(self, specs: dict[str, ToolSpec], profiles: dict[str, list[str]]):
        self.specs = specs
        self.profiles = profiles

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "ToolRegistry":
        config_path = (
            Path(path)
            if path
            else Path(__file__).resolve().parents[2] / "tool_configure.json"
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        specs = cls._discover_specs()
        configured = {
            item["name"]
            for item in config.get("tools", [])
            if item.get("enabled", True)
        }
        missing = configured - specs.keys()
        if missing:
            raise RuntimeError(f"configured tools are missing: {sorted(missing)}")
        specs = {name: spec for name, spec in specs.items() if name in configured}
        profiles = {
            profile: [name for name in names if name in specs]
            for profile, names in config.get("profiles", {}).items()
        }
        unknown = {
            name
            for names in profiles.values()
            for name in names
            if name not in specs
        }
        if unknown:
            raise RuntimeError(f"profiles reference unknown tools: {sorted(unknown)}")
        return cls(specs, profiles)

    @staticmethod
    def _discover_specs() -> dict[str, ToolSpec]:
        import app.tools as tools_package

        specs: dict[str, ToolSpec] = {}
        for module_info in pkgutil.iter_modules(tools_package.__path__):
            if module_info.name in {"base", "registry"}:
                continue
            module = importlib.import_module(f"app.tools.{module_info.name}")
            for name, spec in getattr(module, "TOOLS", {}).items():
                if name in specs:
                    raise RuntimeError(f"duplicate tool: {name}")
                specs[name] = spec
        return specs

    def names_for_profile(
        self,
        profile: str,
        *,
        include_write: bool = False,
        write_mode: str | None = None,
    ) -> list[str]:
        if profile not in self.profiles:
            raise KeyError(f"unknown profile: {profile}")
        effective_mode = write_mode
        if effective_mode is None and include_write:
            effective_mode = "draft-and-publish"
        return [
            name
            for name in self.profiles[profile]
            if self._write_tool_allowed(self.specs[name], effective_mode)
        ]

    def specs_for_profile(
        self,
        profile: str,
        *,
        include_write: bool = False,
        write_mode: str | None = None,
    ) -> list[ToolSpec]:
        return [
            self.specs[name]
            for name in self.names_for_profile(
                profile,
                include_write=include_write,
                write_mode=write_mode,
            )
        ]

    def openai_tools(
        self,
        profile: str,
        *,
        include_write: bool = False,
        write_mode: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            spec.openai_schema()
            for spec in self.specs_for_profile(
                profile,
                include_write=include_write,
                write_mode=write_mode,
            )
        ]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        if name not in self.names_for_profile(
            context.profile,
            write_mode=(
                str(context.write_session.get("mode") or "draft-only")
                if context.write_session
                else None
            ),
        ):
            return ToolResult(
                ok=False,
                error=f"tool_not_allowed:{name}",
                content=f"工具 {name} 当前不可用。",
            )
        spec = self.specs[name]
        if spec.required_write_mode and not context.write_session:
            return ToolResult(
                ok=False,
                error="write_session_required",
                content="当前没有有效的网站写入授权会话。",
            )
        try:
            return await spec.handler(arguments, context)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                ok=False,
                error=str(exc),
                content=f"工具 {name} 执行失败：{exc}",
            )

    def describe(
        self,
        profile: str,
        *,
        include_write: bool = False,
        write_mode: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "sideEffect": spec.side_effect,
                "requiresWrite": spec.requires_write,
                "requiredWriteMode": spec.required_write_mode,
                "timeoutSeconds": spec.timeout_seconds,
            }
            for spec in self.specs_for_profile(
                profile,
                include_write=include_write,
                write_mode=write_mode,
            )
        ]

    @staticmethod
    def _write_tool_allowed(
        spec: ToolSpec, write_mode: str | None
    ) -> bool:
        if not spec.required_write_mode:
            return True
        if write_mode == "draft-and-publish":
            return spec.required_write_mode in {"draft", "publish"}
        if write_mode == "draft-only":
            return spec.required_write_mode == "draft"
        return False
