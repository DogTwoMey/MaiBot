"""阿里云百炼 provider 模块（精简版）。

由 apisource/manage.py 通过 ``--provider aliyun`` 载入并调用 ``build(...)``。

本版本从 ``models.toml`` 读取人工维护的精选模型清单，不再扫描 ``response_cn_*.json``
免费配额数据。模型清单仅包含 MaiBot 需要通过百炼调用的多模态类模型：
    - VLM（视觉语言模型，visual=true）
    - Voice（语音/全模态）
    - Embedding（文本向量化）

对话类任务（replyer / planner / utils）不在此处配置，由 DeepSeek provider 覆盖。

合并语义（配合 _common.apply_bundle_to_config）：
    - ``is_managed_provider_name``: ``BaiLian`` 或以 ``BaiLian-`` 开头。
    - 其它 provider 的条目（DeepSeek、DZMM 等）不会被影响。
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
# 常量
# ---------------------------------------------------------------------------

_TEMPLATE = _PROVIDER_DIR / "models.toml"
_PROVIDER_NAME = "BaiLian"


def _is_managed_provider_name(name: str) -> bool:
    """BaiLian 或以 BaiLian- 开头的 provider 都归本模块管。"""
    return name == _PROVIDER_NAME or name.startswith(f"{_PROVIDER_NAME}-")


# ---------------------------------------------------------------------------
# 构建 helper
# ---------------------------------------------------------------------------

def _load_template() -> Dict[str, Any]:
    if not _TEMPLATE.exists():
        raise FileNotFoundError(f"百炼模板缺失: {_TEMPLATE}")
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
        t["temperature"] = float(m.get("temperature", 0.3))
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
    t["base_url"] = cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
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
    t["timeout"] = int(cfg.get("timeout", 60))
    t["retry_interval"] = int(cfg.get("retry_interval", 10))
    t["default_headers"] = table()
    t["default_query"] = table()
    arr.append(t)
    return arr


def _build_tier_mapping(template: Dict[str, Any], tier: str) -> Dict[str, List[str]]:
    """百炼的 tier 任务槽分配规则。

    百炼仅负责多模态类任务槽：vlm / voice / embedding。
    对话类槽位（replyer / planner / utils）留空，由 DeepSeek provider 覆盖。

    档位语义：
        low   → 各类别用最便宜的模型
        mid   → 各类别低+中档混合
        high  → 各类别优先高档
        ultra → 各类别仅用最高档
    """

    by_category: Dict[str, Dict[str, List[str]]] = {
        "vlm": {"low": [], "mid": [], "high": [], "all": []},
        "voice": {"low": [], "mid": [], "high": [], "all": []},
        "embedding": {"low": [], "mid": [], "high": [], "all": []},
    }

    for m in template.get("models", []) or []:
        name = str(m.get("name") or m.get("model_identifier") or "").strip()
        if not name:
            continue
        cat = str(m.get("category", ""))
        tier_name = str(m.get("tier", "mid"))
        if cat in by_category:
            by_category[cat].setdefault(tier_name, []).append(name)
            if tier_name == "all":
                for lvl in ("low", "mid", "high"):
                    by_category[cat].setdefault(lvl, []).append(name)

    def chain(cat: str, *levels: str) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for lvl in levels:
            for n in by_category.get(cat, {}).get(lvl, []):
                if n not in seen:
                    seen.add(n)
                    out.append(n)
        # "all" 类别的模型始终包含
        for n in by_category.get(cat, {}).get("all", []):
            if n not in seen:
                seen.add(n)
                out.append(n)
        return out

    if tier == "low":
        vlm = chain("vlm", "low")
        voice = chain("voice", "low")
        embedding = chain("embedding", "low")
    elif tier == "mid":
        vlm = chain("vlm", "low", "mid")
        voice = chain("voice", "low", "mid")
        embedding = chain("embedding", "low", "mid")
    elif tier == "high":
        vlm = chain("vlm", "high", "mid", "low")
        voice = chain("voice", "mid", "low")
        embedding = chain("embedding", "high", "mid")
    elif tier == "ultra":
        vlm = chain("vlm", "high")
        voice = chain("voice", "mid")
        embedding = chain("embedding", "high")
    elif tier == "free":
        vlm = chain("vlm", "low", "mid", "high")
        voice = chain("voice", "low", "mid")
        embedding = chain("embedding", "low", "mid", "high")
    else:
        vlm = chain("vlm", "mid", "low", "high")
        voice = chain("voice", "low", "mid")
        embedding = chain("embedding", "mid", "low")

    return {
        "replyer": [],
        "planner": [],
        "utils": [],
        "vlm": vlm,
        "voice": voice,
        "embedding": embedding,
    }


# ---------------------------------------------------------------------------
# 入口
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
    print(f"百炼模板模型数: {total_models}")
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
        embedding_name="text-embedding-v4",
        tier=tier if args.tier else "none",
        is_managed_provider_name=_is_managed_provider_name,
    )
