"""Manifest v1 → v2 迁移器。

转换规则总览：

- ``manifest_version``: 1 → 2
- ``author``: 允许字符串；补齐 ``author.url`` 为空字符串
- ``urls``: 从顶层 ``repository_url`` / ``homepage_url`` 移入；
  未提供 ``documentation`` / ``issues`` 时用 repository 兜底
- ``host_application``: 补齐 ``max_version``
- ``sdk``: 默认 ``2.0.0`` ~ ``2.99.99``
- ``dependencies``: 归一化为 ``List[Dict]`` 形式
- ``capabilities``: 保留已有；v1 无此概念时留空，并通过 context.warn 提醒
- ``i18n``: 聚合 v1 的顶层 ``default_locale`` / ``locales_path`` / ``supported_locales``
- ``id``: 强制小写 + ``-`` 分隔；自动替换下划线
- 清理 v1 专有字段：``keywords`` / ``categories`` / ``repository_url`` /
  ``homepage_url`` / ``default_locale`` / ``locales_path`` /
  ``plugin_info`` / ``display_name`` / ``entry`` / ``configuration`` /
  ``usage_examples`` / ``required_plugins`` / ``config_schema`` / ``supported_locales``
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .base import MigrationContext, VersionMigrator
from .registry import register_migrator


_V1_ONLY_TOPLEVEL_KEYS: frozenset[str] = frozenset(
    {
        "keywords",
        "categories",
        "repository_url",
        "homepage_url",
        "default_locale",
        "locales_path",
        "supported_locales",
        "plugin_info",
        "display_name",
        "entry",
        "configuration",
        "usage_examples",
        "required_plugins",
        "config_schema",
    }
)

_V2_ALLOWED_TOPLEVEL_KEYS: frozenset[str] = frozenset(
    {
        "manifest_version",
        "version",
        "name",
        "description",
        "author",
        "license",
        "urls",
        "host_application",
        "sdk",
        "dependencies",
        "capabilities",
        "i18n",
        "id",
    }
)


@register_migrator
class V1ToV2Migrator(VersionMigrator):
    """把 v1 schema 的 manifest 升级到 v2。"""

    input_version = 1
    output_version = 2

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def migrate(self, manifest: Dict[str, Any], context: MigrationContext) -> Dict[str, Any]:
        """生成一个符合 v2 schema 的新字典。"""

        result: Dict[str, Any] = {
            "manifest_version": 2,
            "version": str(manifest.get("version") or "0.1.0"),
            "name": str(
                manifest.get("name")
                or manifest.get("display_name")
                or "unnamed"
            ),
            "description": str(manifest.get("description") or ""),
            "license": str(manifest.get("license") or ""),
        }

        result["author"] = self._build_author(manifest, context)
        result["urls"] = self._build_urls(manifest, context)
        result["host_application"] = self._build_host_application(manifest, context)
        result["sdk"] = self._build_sdk(manifest)
        result["dependencies"] = self._build_dependencies(manifest, context)
        result["capabilities"] = self._build_capabilities(manifest, context)
        result["i18n"] = self._build_i18n(manifest)
        result["id"] = self._normalize_id(manifest, context, fallback_name=result["name"])

        # 警告：v1 里会被丢弃的字段
        dropped = [
            key
            for key in manifest
            if key not in _V2_ALLOWED_TOPLEVEL_KEYS
            and key != "manifest_version"
        ]
        if dropped:
            context.warn(
                f"manifest v1 字段 {sorted(dropped)} 在 v2 中已被移除，"
                f"已自动清理（不影响运行）。"
            )

        return result

    # ------------------------------------------------------------------
    # 子字段构造
    # ------------------------------------------------------------------

    @staticmethod
    def _build_author(manifest: Dict[str, Any], context: MigrationContext) -> Dict[str, str]:
        author = manifest.get("author")
        if isinstance(author, str):
            return {"name": author, "url": ""}
        if isinstance(author, dict):
            out = {"name": str(author.get("name") or "unknown"), "url": str(author.get("url") or "")}
            if not out["url"]:
                context.warn("author.url 缺失，已填充为空字符串。")
            return out
        context.warn("author 字段缺失或类型不正确，已填充默认值。")
        return {"name": "unknown", "url": ""}

    @staticmethod
    def _build_urls(manifest: Dict[str, Any], context: MigrationContext) -> Dict[str, str]:
        urls = dict(manifest.get("urls") or {})
        repo = urls.get("repository") or manifest.get("repository_url") or ""
        home = urls.get("homepage") or manifest.get("homepage_url") or repo
        documentation = urls.get("documentation") or repo
        issues = urls.get("issues") or repo
        out = {
            "repository": str(repo),
            "homepage": str(home),
        }
        if documentation:
            out["documentation"] = str(documentation)
        if issues:
            out["issues"] = str(issues)
        if not repo:
            context.warn("urls.repository 缺失；已填充为空字符串。")
        return out

    @staticmethod
    def _build_host_application(manifest: Dict[str, Any], context: MigrationContext) -> Dict[str, str]:
        ha = dict(manifest.get("host_application") or {})
        min_version = ha.get("min_version") or manifest.get("maibot_min_version") or "1.0.0"
        # v1 通常只写 min_version。给 max_version 一个宽松上限让它过 schema 校验。
        max_version = ha.get("max_version") or manifest.get("maibot_max_version") or "1.99.99"
        if not ha.get("max_version"):
            context.warn(
                f"host_application.max_version 缺失，已自动填充为 {max_version!r}。"
                "如果实际兼容范围更窄，请在插件仓库修正。"
            )
        return {"min_version": str(min_version), "max_version": str(max_version)}

    @staticmethod
    def _build_sdk(manifest: Dict[str, Any]) -> Dict[str, str]:
        sdk = dict(manifest.get("sdk") or {})
        sdk.setdefault("min_version", "2.0.0")
        sdk.setdefault("max_version", "2.99.99")
        return {k: str(v) for k, v in sdk.items()}

    @staticmethod
    def _build_dependencies(manifest: Dict[str, Any], context: MigrationContext) -> List[Dict[str, Any]]:
        raw = manifest.get("dependencies")
        if raw is None:
            return []
        if isinstance(raw, list):
            cleaned: List[Dict[str, Any]] = []
            for item in raw:
                if isinstance(item, dict):
                    cleaned.append(dict(item))
                else:
                    context.warn(f"dependencies 元素 {item!r} 非 dict 结构，已丢弃。")
            return cleaned
        if isinstance(raw, dict):
            flat: List[Dict[str, Any]] = []
            for key, val in raw.items():
                if isinstance(val, list):
                    for v in val:
                        if isinstance(v, str):
                            dep_type = key if key in {"python", "plugin"} else "python"
                            flat.append({"type": dep_type, "name": v})
                        elif isinstance(v, dict):
                            flat.append(dict(v))
                elif isinstance(val, str):
                    flat.append({"type": "python", "name": f"{key}{val}"})
            context.warn("dependencies 为 dict 结构，已归一化为 v2 要求的 list。")
            return flat
        context.warn(f"dependencies 类型 {type(raw).__name__} 无法识别，已清空。")
        return []

    @staticmethod
    def _build_capabilities(manifest: Dict[str, Any], context: MigrationContext) -> List[str]:
        caps = manifest.get("capabilities")
        if isinstance(caps, list):
            return [str(c) for c in caps if c]
        context.warn(
            "capabilities 在 v1 中不存在；已置为空列表。"
            "运行期调用未声明能力时，请根据日志提示补齐。"
        )
        return []

    @staticmethod
    def _build_i18n(manifest: Dict[str, Any]) -> Dict[str, Any]:
        i18n = dict(manifest.get("i18n") or {})
        default_locale = (
            i18n.get("default_locale")
            or manifest.get("default_locale")
            or "zh-CN"
        )
        locales_path = i18n.get("locales_path") or manifest.get("locales_path")
        supported = i18n.get("supported_locales") or manifest.get("supported_locales") or [default_locale]
        out: Dict[str, Any] = {
            "default_locale": str(default_locale),
            "supported_locales": list(supported),
        }
        if locales_path:
            out["locales_path"] = str(locales_path)
        return out

    @staticmethod
    def _normalize_id(manifest: Dict[str, Any], context: MigrationContext, *, fallback_name: str) -> str:
        raw_id = str(manifest.get("id", "") or "").strip()
        if not raw_id:
            slug = re.sub(r"[^a-z0-9]+", "-", fallback_name.lower()).strip("-") or "unnamed"
            normalized = f"community.{slug}"
            context.warn(f"id 缺失，已生成保底值 {normalized!r}。")
            return normalized

        normalized = raw_id.lower().replace("_", "-")
        normalized = re.sub(r"[^a-z0-9.\-]", "-", normalized)
        normalized = re.sub(r"-{2,}", "-", normalized)
        normalized = re.sub(r"\.{2,}", ".", normalized).strip(".-")
        if "." not in normalized and "-" not in normalized:
            normalized = f"community.{normalized}"

        if normalized != raw_id:
            context.warn(f"id 已规范化: {raw_id!r} -> {normalized!r}")
        return normalized


__all__ = ["V1ToV2Migrator"]
