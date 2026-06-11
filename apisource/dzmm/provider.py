"""DZMM (大嘴猫猫) provider 模块。

第三方 OpenAI 兼容 API，提供对话类模型。作为 DeepSeek 的补充/备选，
可用于 replyer 等对话任务。

入口函数 ``build(args, *, apisource_dir)`` 返回 ProviderBundle。
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any, Dict, List

_PROVIDER_DIR = Path(__file__).resolve().parent
_APISOURCE = _PROVIDER_DIR.parent
if str(_APISOURCE) not in sys.path:
    sys.path.insert(0, str(_APISOURCE))

import _common  # noqa: E402
from _common import ProviderBundle  # noqa: E402


# ---------------------------------------------------------------------------

_TEMPLATE = _PROVIDER_DIR / "models.toml"
_PROVIDER_NAME = "DZMM"


def _is_managed_provider_name(name: str) -> bool:
    return name == _PROVIDER_NAME


# ---------------------------------------------------------------------------

def _load_template() -> Dict[str, Any]:
    if not _TEMPLATE.exists():
        raise FileNotFoundError(f"DZMM 模板缺失: {_TEMPLATE}")
    return tomllib.loads(_TEMPLATE.read_text(encoding="utf-8"))


def _build_extra_params_table(raw: dict):
    """递归地把嵌套 dict 转为 tomlkit table。"""
    from tomlkit import table

    tbl = table()
    for k, v in raw.items():
        if isinstance(v, dict):
            tbl[k] = _build_extra_params_table(v)
        else:
            tbl[k] = v
    return tbl


def _build_models_aot(template: Dict[str, Any], provider_name: str):
    from tomlkit import aot, table

    arr = aot()
    for m in template.get("models", []) or []:
        code = str(m.get("model_identifier") or m.get("name") or "").strip()
        name = str(m.get("name") or code).strip()
        if not code or not name:
            continue
        t = table()
        t["model_identifier"] = code
        t["name"] = name
        t["api_provider"] = provider_name
        t["price_in"] = float(m.get("price_in", 0.0))
        t["cache"] = bool(m.get("cache", False))
        t["cache_price_in"] = float(m.get("cache_price_in", 0.0))
        t["price_out"] = float(m.get("price_out", 0.0))
        t["temperature"] = float(m.get("temperature", 1.0))
        t["force_stream_mode"] = bool(m.get("force_stream_mode", False))
        t["visual"] = bool(m.get("visual", False))
        t["extra_params"] = _build_extra_params_table(m.get("extra_params") or {})
        arr.append(t)
    return arr


def _build_providers_aot(template: Dict[str, Any], provider_name: str, api_key: str):
    from tomlkit import aot, table

    cfg = template.get("provider") or {}
    arr = aot()
    t = table()
    t["name"] = provider_name
    t["base_url"] = cfg.get("base_url", "https://www.gpt4novel.com/api/xiaoshuoai/ext/v1")
    t["api_key"] = api_key
    t["client_type"] = cfg.get("client_type", "openai")
    t["auth_type"] = cfg.get("auth_type", "bearer")
    t["auth_header_name"] = cfg.get("auth_header_name", "Authorization")
    t["auth_header_prefix"] = cfg.get("auth_header_prefix", "Bearer")
    t["auth_query_name"] = cfg.get("auth_query_name", "api_key")
    t["model_list_endpoint"] = cfg.get("model_list_endpoint", "/models")
    t["reasoning_parse_mode"] = cfg.get("reasoning_parse_mode", "auto")
    t["tool_argument_parse_mode"] = cfg.get("tool_argument_parse_mode", "auto")
    t["max_retry"] = int(cfg.get("max_retry", 2))
    t["timeout"] = int(cfg.get("timeout", 120))
    t["retry_interval"] = int(cfg.get("retry_interval", 10))
    t["default_headers"] = table()
    t["default_query"] = table()
    arr.append(t)
    return arr


def _build_tier_mapping(template: Dict[str, Any], tier: str) -> Dict[str, List[str]]:
    """DZMM 的 tier 任务槽分配规则。

    DZMM 仅提供 chat 模型，可作为 replyer 的备选。
    不覆盖 VLM / Voice / Embedding（保留百炼配置）。

    DZMM 模型在所有档位下都作为 replyer 候选（追加到列表末尾）。
    """

    chat_models: List[str] = []
    for m in template.get("models", []) or []:
        name = str(m.get("name") or m.get("model_identifier") or "").strip()
        category = str(m.get("category", "chat"))
        if name and category == "chat":
            chat_models.append(name)

    # DZMM 在所有档位下都可作为 replyer 候选
    return {
        "replyer": chat_models,
        "planner": [],
        "utils": [],
        "vlm": [],
        "voice": [],
        "embedding": [],
    }


# ---------------------------------------------------------------------------

def build(args, *, apisource_dir: Path) -> ProviderBundle:
    template = _load_template()
    provider_cfg = template.get("provider") or {}
    provider_name = str(provider_cfg.get("name") or _PROVIDER_NAME)

    existing_keys = _common.extract_existing_api_keys()
    api_key = existing_keys.get(provider_name) or args.api_key or "<API_KEY_PLACEHOLDER>"

    models_aot = _build_models_aot(template, provider_name)
    providers_aot = _build_providers_aot(template, provider_name, api_key)

    tier = args.tier or "mid"
    tier_mapping = _build_tier_mapping(template, tier) if args.tier else {}

    total_models = len(template.get("models", []) or [])
    print(f"DZMM 模板模型数: {total_models}")
    print(f"provider={provider_name}  base_url={provider_cfg.get('base_url')}")
    if args.tier:
        print(f"tier={tier}  任务槽分配:")
        for slot, lst in tier_mapping.items():
            if lst:
                print(f"  {slot:10} -> {lst}")

    return ProviderBundle(
        models_aot=models_aot,
        providers_aot=providers_aot,
        tier_mapping=dict(tier_mapping),
        embedding_name="",
        tier=tier if args.tier else "none",
        is_managed_provider_name=_is_managed_provider_name,
    )
