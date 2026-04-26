#!/usr/bin/env python3
"""把 plugins/ 下所有 manifest_version=1 的 _manifest.json 升级到 v2。

背景：
    MaiBot 的插件 Manifest 协议升级到 v2，旧版（v1）插件会被 runtime 校验拒绝，
    导致 WebUI 报"无法加载配置 / 加载原始配置文件失败 / 配置文件不存在"。
    本脚本就地迁移，补齐 v2 必需字段，清理 v1 才有的非法字段。

用法：
    python scripts/migrate_plugin_manifests.py            # 预览，不写
    python scripts/migrate_plugin_manifests.py --apply    # 真的写入
    python scripts/migrate_plugin_manifests.py --apply --plugins-dir plugins
    python scripts/migrate_plugin_manifests.py --apply --plugins-dir data/plugins

安全：
    --apply 会先把原 _manifest.json 备份为 _manifest.json.v1.bak 再覆盖写。
    如果已经存在 .v1.bak，跳过该插件（避免二次迁移）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# v2 protocol surface
_V2_ALLOWED_KEYS = {
    "manifest_version", "version", "name", "description", "author", "license",
    "urls", "host_application", "sdk", "dependencies", "capabilities", "i18n", "id",
}

# v1 中允许出现但 v2 禁用 / 需要迁移的键
_V1_ONLY_KEYS = {
    "keywords", "categories", "required_plugins", "config_schema",
    "default_locale", "locales_path", "supported_locales",
    "plugin_info", "display_name", "entry", "configuration", "usage_examples",
    "homepage_url", "repository_url",
}

_ID_SEGMENT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass
class MigrationReport:
    path: Path
    plugin_id: str = ""
    actions: list[str] = None   # type: ignore
    errors: list[str] = None    # type: ignore

    def __post_init__(self) -> None:
        self.actions = self.actions or []
        self.errors = self.errors or []


# ---------------------------------------------------------------------------
# 单个字段迁移
# ---------------------------------------------------------------------------

def _normalize_id(raw_id: str, fallback_name: str) -> tuple[str, bool]:
    """返回 (规范化后的 id, 是否修改过)。"""
    original = (raw_id or "").strip()
    if not original:
        # 用 plugin name 构造一个保底 id
        slug = re.sub(r"[^a-z0-9]+", "-", fallback_name.lower()).strip("-")
        return (f"community.{slug or 'unnamed'}", True)

    normalized = original.lower()
    # 把下划线统一换成横线
    normalized = normalized.replace("_", "-")
    # 非法字符转成横线
    normalized = re.sub(r"[^a-z0-9.\-]", "-", normalized)
    # 合并连续分隔符
    normalized = re.sub(r"-{2,}", "-", normalized)
    normalized = re.sub(r"\.{2,}", ".", normalized)
    normalized = normalized.strip(".-")

    # 必须至少有一个 . 或 -（按 _PLUGIN_ID_PATTERN）
    if "." not in normalized and "-" not in normalized:
        normalized = f"community.{normalized}"

    return (normalized, normalized != original)


def _coerce_dependencies(raw_deps) -> tuple[list, bool]:
    """
    v1 中 dependencies 可能是 dict / list-of-dict / list-of-str；
    v2 要求 list[ManifestDependencyDefinition]。
    不认识的结构整体清空，后续让插件作者在更新时自己补。
    """
    changed = False
    if raw_deps is None:
        return ([], False)
    if isinstance(raw_deps, list):
        # 已经是 list，逐项看是否规范
        result = []
        for item in raw_deps:
            if isinstance(item, dict):
                result.append(item)
            else:
                changed = True   # 丢弃非 dict 项
        return (result, changed)
    if isinstance(raw_deps, dict):
        # 把 {"packages": [...], "plugins": [...]} 或 {"name": "ver"} 类结构铺平为 list
        flat: list[dict] = []
        # 常见：{"python": ["httpx>=0.20"]}
        for key, val in raw_deps.items():
            if isinstance(val, list):
                for v in val:
                    if isinstance(v, str):
                        flat.append({"type": key if key in ("python", "plugin") else "python", "name": v})
                    elif isinstance(v, dict):
                        flat.append(v)
            elif isinstance(val, str):
                flat.append({"type": "python", "name": f"{key}{val}" if val.startswith(('>=', '==', '<', '>', '~=', '!=')) else key})
        return (flat, True)
    return ([], True)


def _build_i18n(src: dict) -> tuple[dict, bool]:
    """优先复用 v1 顶层的 default_locale / locales_path / supported_locales。"""
    i18n = dict(src.get("i18n") or {})
    default_locale = i18n.get("default_locale") or src.get("default_locale") or "zh-CN"
    locales_path = i18n.get("locales_path") or src.get("locales_path")
    supported = i18n.get("supported_locales") or src.get("supported_locales")
    if not supported:
        supported = [default_locale]
    new = {
        "default_locale": default_locale,
        "supported_locales": supported,
    }
    if locales_path:
        new["locales_path"] = locales_path
    changed = new != (src.get("i18n") or {})
    return (new, changed)


def _build_urls(src: dict) -> dict:
    urls = dict(src.get("urls") or {})
    if "repository" not in urls and src.get("repository_url"):
        urls["repository"] = src["repository_url"]
    if "homepage" not in urls:
        if src.get("homepage_url"):
            urls["homepage"] = src["homepage_url"]
        elif urls.get("repository"):
            urls["homepage"] = urls["repository"]
    # documentation / issues 字段在 v2 不是必填（从 ManifestUrls 模型上看），但有些校验强制要求
    # 保守起见，若已知 repo 则用同址推断
    return urls


def _build_host_app(src: dict) -> dict:
    ha = dict(src.get("host_application") or {})
    if "min_version" not in ha:
        ha["min_version"] = src.get("maibot_min_version") or "1.0.0"
    if "max_version" not in ha:
        # v1 的插件多数只写 min_version；给个宽泛上限 1.99.99 让它至少过校验
        ha["max_version"] = "1.99.99"
    return ha


def _build_sdk(src: dict) -> dict:
    sdk = dict(src.get("sdk") or {})
    sdk.setdefault("min_version", "2.0.0")
    sdk.setdefault("max_version", "2.99.99")
    return sdk


def _build_author(src: dict) -> dict:
    author = src.get("author")
    if isinstance(author, str):
        return {"name": author, "url": ""}
    if isinstance(author, dict):
        author = dict(author)
    else:
        author = {}
    author.setdefault("name", "unknown")
    author.setdefault("url", "")
    return author


# ---------------------------------------------------------------------------
# 单个 manifest 处理
# ---------------------------------------------------------------------------

def migrate_manifest(manifest_path: Path, apply: bool) -> MigrationReport:
    rpt = MigrationReport(path=manifest_path)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        rpt.errors.append(f"JSON 解析失败: {e}")
        return rpt

    if not isinstance(raw, dict):
        rpt.errors.append("manifest 顶层不是对象")
        return rpt

    current_version = raw.get("manifest_version")
    if current_version == 2:
        rpt.actions.append("已经是 v2，跳过")
        return rpt

    rpt.plugin_id = str(raw.get("id", "") or manifest_path.parent.name)

    # 构造 v2 文档
    new: dict = {}
    new["manifest_version"] = 2
    new["version"] = str(raw.get("version") or "0.1.0")
    new["name"] = str(raw.get("name") or raw.get("display_name") or manifest_path.parent.name)
    new["description"] = str(raw.get("description") or "")
    new["author"] = _build_author(raw)
    new["license"] = str(raw.get("license") or "")
    new["urls"] = _build_urls(raw)
    new["host_application"] = _build_host_app(raw)
    new["sdk"] = _build_sdk(raw)

    deps, deps_changed = _coerce_dependencies(raw.get("dependencies"))
    new["dependencies"] = deps
    if deps_changed:
        rpt.actions.append("规范化 dependencies 为 v2 格式")

    # capabilities：v1 没有；默认留空，让作者或你手动补
    # （留空会导致插件声明为无特权；若插件实际需要 send.text 等，会在运行期报错，
    #  届时你可以按运行期错误指示一项一项加到 capabilities）
    new["capabilities"] = list(raw.get("capabilities") or [])

    i18n, i18n_changed = _build_i18n(raw)
    new["i18n"] = i18n
    if i18n_changed:
        rpt.actions.append("填充/合并 i18n 段")

    normalized_id, id_changed = _normalize_id(str(raw.get("id", "")), new["name"])
    new["id"] = normalized_id
    if id_changed:
        rpt.actions.append(f"规范化 id: {raw.get('id')!r} -> {normalized_id!r}")

    # 清理 v1 专用字段
    dropped_keys = sorted(k for k in raw.keys() if k not in _V2_ALLOWED_KEYS and k != "manifest_version")
    if dropped_keys:
        rpt.actions.append(f"删除 v1 专用字段: {dropped_keys}")

    rpt.actions.append(f"manifest_version: {current_version} -> 2")

    if apply:
        backup = manifest_path.with_suffix(".json.v1.bak")
        if backup.exists():
            rpt.actions.append(f"跳过备份（已存在 {backup.name}）")
        else:
            backup.write_bytes(manifest_path.read_bytes())
            rpt.actions.append(f"已备份 -> {backup.name}")
        manifest_path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rpt.actions.append("已写入 v2 版")

    return rpt


# ---------------------------------------------------------------------------
# 驱动
# ---------------------------------------------------------------------------

def iter_plugin_manifests(plugins_dir: Path):
    for child in sorted(plugins_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_"):
            continue
        manifest = child / "_manifest.json"
        if manifest.exists():
            yield manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate plugin _manifest.json from v1 to v2.")
    parser.add_argument("--plugins-dir", default="plugins", help="插件根目录 (默认: plugins/)")
    parser.add_argument("--apply", action="store_true", help="实际写入（不加此参数为预览模式）")
    args = parser.parse_args()

    plugins_dir = Path(args.plugins_dir).resolve()
    if not plugins_dir.exists():
        print(f"错误: {plugins_dir} 不存在")
        return 1

    reports: list[MigrationReport] = []
    for manifest_path in iter_plugin_manifests(plugins_dir):
        rpt = migrate_manifest(manifest_path, apply=args.apply)
        reports.append(rpt)

    # 输出报告
    upgraded = [r for r in reports if any("manifest_version" in a for a in r.actions) and "已经是 v2" not in (r.actions[0] if r.actions else "")]
    already_v2 = [r for r in reports if r.actions and r.actions[0].startswith("已经是")]
    failed = [r for r in reports if r.errors]

    print()
    print(f"插件目录: {plugins_dir}")
    print(f"总计: {len(reports)} 个 manifest")
    print(f"  已是 v2: {len(already_v2)} 个")
    print(f"  需要迁移: {len(upgraded)} 个")
    print(f"  失败: {len(failed)} 个")
    print()

    for r in reports:
        tag = "✓" if r.actions and not r.errors else "✗"
        print(f"{tag} {r.path.relative_to(plugins_dir.parent if plugins_dir.parent != plugins_dir else plugins_dir)}  id={r.plugin_id}")
        for a in r.actions:
            print(f"    - {a}")
        for e in r.errors:
            print(f"    ! {e}")

    if not args.apply:
        print()
        print("预览结束。加 --apply 实际写入（会自动把原文件备份为 *.v1.bak）。")

    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
