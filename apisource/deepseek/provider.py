"""DeepSeek provider 模块。

不同于 aliyun 的按配额 JSON 自动发现，DeepSeek 从 ``models.toml`` 读取显式模板。
覆盖 MaiBot 的 chat 相关任务槽（replyer / planner / utils）；VLM / Voice /
Embedding 留空——DeepSeek 官方暂不提供这三类服务，请配合其他 provider（阿里云
等）使用。

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
_PROVIDER_NAME = "DeepSeek"


def _is_managed_provider_name(name: str) -> bool:
    return name == _PROVIDER_NAME


# ---------------------------------------------------------------------------

def _load_template() -> Dict[str, Any]:
    if not _TEMPLATE.exists():
        raise FileNotFoundError(f"DeepSeek 模板缺失: {_TEMPLATE}")
    return tomllib.loads(_TEMPLATE.read_text(encoding="utf-8"))


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
        extra_tbl = table()
        for k, v in (m.get("extra_params") or {}).items():
            extra_tbl[k] = v
        t["extra_params"] = extra_tbl
        arr.append(t)
    return arr


def _build_providers_aot(template: Dict[str, Any], provider_name: str, api_key: str):
    from tomlkit import aot, table

    cfg = template.get("provider") or {}
    arr = aot()
    t = table()
    t["name"] = provider_name
    t["base_url"] = cfg.get("base_url", "https://api.deepseek.com/v1")
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
    """DeepSeek 的 tier 规则：

    - low       → flash
    - mid       → chat + flash
    - high      → reasoner + pro
    - extreme   → pro + reasoner
    - free      → 所有 chat 模型（DeepSeek 没有严格免费档，这里把全部塞进去让
                  selection_strategy=random 分摊调用）

    任务槽分配：
        replyer / planner → 当前 tier 的 chat 列表
        utils             → 任意 low / mid（成本最低）
        vlm / voice / embedding → 不写入（让 merge 保留原配置）
    """

    by_tier: Dict[str, List[str]] = {"low": [], "mid": [], "high": [], "extreme": [], "free": []}
    for m in template.get("models", []) or []:
        name = str(m.get("name") or m.get("model_identifier") or "").strip()
        if not name:
            continue
        tier_name = str(m.get("tier", "mid"))
        category = str(m.get("category", "chat"))
        if category != "chat":
            continue
        by_tier.setdefault(tier_name, []).append(name)
        # free 档：所有 chat 都视为可用候选
        if name not in by_tier["free"]:
            by_tier["free"].append(name)

    def chain(*levels: str) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for lvl in levels:
            for n in by_tier.get(lvl, []):
                if n not in seen:
                    seen.add(n)
                    out.append(n)
        return out

    if tier == "low":
        replyer = chain("low", "mid")
        planner = chain("low", "mid")
        utils = chain("low", "mid")
    elif tier == "mid":
        replyer = chain("mid", "high", "low")
        planner = chain("mid", "high")
        utils = chain("low", "mid")
    elif tier == "high":
        replyer = chain("high", "extreme", "mid")
        planner = chain("high", "mid")
        utils = chain("low", "mid")
    elif tier == "extreme":
        replyer = chain("extreme", "high")
        planner = chain("extreme", "high", "mid")
        utils = chain("low", "mid")
    elif tier == "free":
        replyer = chain("free")
        planner = chain("free")
        utils = chain("low", "mid")
    else:
        replyer = chain("mid", "high", "low")
        planner = chain("mid", "high")
        utils = chain("low", "mid")

    return {
        "replyer": replyer,
        "planner": planner,
        "utils": utils,
        "vlm": [],
        "voice": [],
        "embedding": [],
    }


# ---------------------------------------------------------------------------

def build(args, *, apisource_dir: Path) -> ProviderBundle:
    template = _load_template()
    provider_cfg = template.get("provider") or {}
    provider_name = str(provider_cfg.get("name") or _PROVIDER_NAME)

    # api_key：优先回填现有 config，再退到 --api-key，最后 placeholder
    existing_keys = _common.extract_existing_api_keys()
    api_key = existing_keys.get(provider_name) or args.api_key or "<API_KEY_PLACEHOLDER>"

    models_aot = _build_models_aot(template, provider_name)
    providers_aot = _build_providers_aot(template, provider_name, api_key)

    tier = args.tier or "mid"
    tier_mapping = _build_tier_mapping(template, tier) if args.tier else {}

    # 简要报告
    total_models = len(template.get("models", []) or [])
    print(f"DeepSeek 模板模型数: {total_models}")
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
