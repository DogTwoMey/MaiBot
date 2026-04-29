"""阿里云百炼 provider 模块。

由 apisource/manage.py 通过 ``--provider aliyun`` 载入并调用 ``build(...)``。
核心能力：

    - 扫描 ``apisource/aliyun/response*.json``，每个文件代表一个区域的免费配额
      数据，文件名里可附加 tab 标签（如 ``response_cn_llm.json``）；
    - 按区域生成 [[api_providers]]（命名规则：``BaiLian`` / ``BaiLian-<region>``）；
    - 对每个 model_code 进行分类 + 档位归属（classify / tier），产出 [[models]]；
    - 按 5 档（low / mid / high / extreme / free）生成任务槽映射。

合并语义（配合 _common.apply_bundle_to_config）：
    - ``is_managed_provider_name``: ``BaiLian`` 或以 ``BaiLian-`` 开头。
    - 其它 provider 的条目（DeepSeek、OpenAI 等）不会被影响。
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# 保证 apisource/ 在 sys.path 里，以便 import _common
_PROVIDER_DIR = Path(__file__).resolve().parent
_APISOURCE = _PROVIDER_DIR.parent
if str(_APISOURCE) not in sys.path:
    sys.path.insert(0, str(_APISOURCE))

import _common  # noqa: E402
from _common import ProviderBundle, TASK_SLOTS, TASK_PARAMS  # noqa: E402


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PRICE_PATH = _PROVIDER_DIR / "price.md"
REGIONS_FILE = _PROVIDER_DIR / "regions.toml"
OUTPUT_DIR = _PROVIDER_DIR / "output"

# 内置区域→base_url 默认，用户可通过 regions.toml 覆盖
DEFAULT_REGION_URLS: Dict[str, str] = {
    "cn":        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "beijing":   "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "intl":      "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "sg":        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "global":    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "us":        "https://dashscope-us-east-1.aliyuncs.com/compatible-mode/v1",
    "hk":        "https://dashscope-hk.aliyuncs.com/compatible-mode/v1",
}

STREAMING_ONLY_KEYWORDS: Tuple[str, ...] = ("qvq-", "-thinking", "-reasoning")
REASONING_KEYWORDS: Tuple[str, ...] = ("-r1", "-thinking", "distill", "qvq", "qwq")


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class Region:
    """单个部署区域的元信息。"""

    key: str
    base_url: str
    provider_name: str


@dataclass
class Model:
    """同一个 model_code 在某个区域下的实例。"""

    code: str
    region: Region
    quota_remaining: int = 0
    quota_total: int = 0
    quota_valid: bool = False
    free_tier_only: bool = True
    price_in: float = 0.0
    price_out: float = 0.0
    category: str = "other"
    tier: str = "none"
    streaming_only: bool = False

    @property
    def has_free_quota(self) -> bool:
        return self.quota_valid and self.quota_remaining > 0

    @property
    def is_dated(self) -> bool:
        return bool(re.search(r"\d{4}-?\d{2}-?\d{2}", self.code))


# ---------------------------------------------------------------------------
# 区域加载
# ---------------------------------------------------------------------------

_RESPONSE_FILE_RE = re.compile(
    r"""
    response
    (?:
        _
        (?P<region>[a-zA-Z0-9-]+)
        (?:_[a-zA-Z0-9-]+)*
    )?
    \.json$
    """,
    re.VERBOSE,
)

_KNOWN_REGION_KEYS: frozenset[str] = frozenset(DEFAULT_REGION_URLS)


def discover_response_files(dir_: Path) -> List[Tuple[str, Path]]:
    """扫描 provider 目录下所有 ``response*.json``。"""

    results: List[Tuple[str, Path]] = []
    for p in sorted(dir_.iterdir()):
        if not p.is_file():
            continue
        m = _RESPONSE_FILE_RE.match(p.name)
        if not m:
            continue
        region_key = (m.group("region") or "cn").lower()
        if region_key not in _KNOWN_REGION_KEYS:
            first_segment = region_key.split("-")[0]
            if first_segment in _KNOWN_REGION_KEYS:
                region_key = first_segment
            else:
                print(f"提示: {p.name} 的 region 段 {region_key!r} 未识别，按 cn 处理。")
                region_key = "cn"
        results.append((region_key, p))
    return results


def load_region_config(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    return dict(doc.get("regions") or {})


def resolve_regions(response_files: Iterable[Tuple[str, Path]], overrides: Dict[str, Dict[str, str]]) -> Dict[str, Region]:
    regions: Dict[str, Region] = {}
    for region_key, _ in response_files:
        if region_key in regions:
            continue
        override = overrides.get(region_key) or {}
        base_url = override.get("base_url") or DEFAULT_REGION_URLS.get(region_key)
        if not base_url:
            raise RuntimeError(
                f"未知区域 {region_key!r}：请在 regions.toml 里给它指定 base_url，"
                f"或改用已知的区域名 ({sorted(DEFAULT_REGION_URLS)})。"
            )
        provider_name = "BaiLian" if region_key in ("cn", "beijing") else f"BaiLian-{region_key}"
        regions[region_key] = Region(key=region_key, base_url=base_url, provider_name=provider_name)
    return regions


# ---------------------------------------------------------------------------
# response.json 加载
# ---------------------------------------------------------------------------

def load_quotas(path: Path, region: Region) -> List[Model]:
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        quotas = data["data"]["DataV2"]["data"]["data"]["freeTierQuotas"]
    except (KeyError, TypeError) as e:
        raise RuntimeError(f"无法从 {path} 解析 freeTierQuotas: {e}") from e

    models: List[Model] = []
    for q in quotas:
        code = q["model"]
        remaining = int(q.get("quotaTotal", {}).get("parsedValue", 0) or 0)
        total = int(q.get("quotaInitTotal", {}).get("parsedValue", 0) or 0)
        status = q.get("quotaStatus", "")
        models.append(Model(
            code=code,
            region=region,
            quota_remaining=remaining,
            quota_total=total,
            quota_valid=(status == "VALID"),
            free_tier_only=bool(q.get("freeTierOnly", True)),
        ))
    return models


def append_embedding_defaults(models: List[Model], regions: Dict[str, Region]) -> None:
    """每个 region 兜底补 text-embedding-v4 / v3（阿里云 freeTierQuotas API 不返回）。"""

    defaults = [
        ("text-embedding-v4", 0.5, 0.0),
        ("text-embedding-v3", 0.7, 0.0),
    ]
    by_region_codes: Dict[str, set[str]] = {}
    for m in models:
        by_region_codes.setdefault(m.region.key, set()).add(m.code)

    for region in regions.values():
        present = by_region_codes.get(region.key, set())
        for code, p_in, p_out in defaults:
            if code in present:
                continue
            m = Model(
                code=code,
                region=region,
                quota_remaining=1_000_000,
                quota_total=1_000_000,
                quota_valid=True,
                free_tier_only=True,
            )
            m.price_in, m.price_out = p_in, p_out
            models.append(m)
            present.add(code)


# ---------------------------------------------------------------------------
# price.md 解析（中国内地最低档，best-effort）
# ---------------------------------------------------------------------------

_PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)元")
_CONTINUATION_RE = re.compile(r"^\s*\d+\s*K?\s*<\s*Token", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MODEL_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._/-]*$")


def parse_prices(path: Path) -> Dict[str, Tuple[float, float]]:
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    prices: Dict[str, Tuple[float, float]] = {}
    region = None
    for line in content.splitlines():
        if line.startswith("## 中国内地"):
            region = "cn"
            continue
        if line.startswith(("## 全球", "## 国际", "## 美国")):
            region = None
            continue
        if region != "cn" or not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if not cols:
            continue
        first = cols[0]
        if not first or first.startswith("---") or "模型名称" in first:
            continue
        if _CONTINUATION_RE.match(first):
            continue
        first_clean = _MD_LINK_RE.sub(r"\1", first)
        model_code = re.split(r"\s*>\s*", first_clean, maxsplit=1)[0].strip().replace("**", "")
        if not _MODEL_CODE_RE.match(model_code):
            continue
        tail = " | ".join(cols[1:])
        nums = [float(m.group(1)) for m in _PRICE_RE.finditer(tail)]
        if len(nums) < 2:
            continue
        prices.setdefault(model_code, (nums[0], nums[1]))
    return prices


# ---------------------------------------------------------------------------
# 分类 + 档位
# ---------------------------------------------------------------------------

def classify(code: str) -> Tuple[str, str, bool]:
    c = code.lower()
    streaming = any(k in c for k in STREAMING_ONLY_KEYWORDS)

    # 非 chat IO 的模型先隔离，避免走 /chat/completions 触发 400/404

    # 万相 wan 系列 + aitryon（虚拟试穿）：图像或视频生成
    if re.match(r"^wan[0-9]", c) or c.startswith("wan-") or c.startswith("wanx") or "aitryon" in c:
        if any(k in c for k in ("-i2v-", "-t2v-", "-v2v-", "-video", "video-", "-i2v", "-t2v")):
            return ("video-gen", "none", streaming)
        return ("image-gen", "none", streaming)

    # 通用图像生成 / 编辑
    if any(k in c for k in (
        "qwen-image", "-image-", "z-image", "tongyi-wanxiang",
        "-t2i-", "-i2i-", "image-gen", "imagegen",
    )):
        return ("image-gen", "none", streaming)

    # 通用视频生成
    if any(k in c for k in ("-video", "video-", "svd", "-i2v-", "-t2v-", "-v2v-")):
        return ("video-gen", "none", streaming)

    # 语音合成 / 识别
    if any(k in c for k in ("cosyvoice", "paraformer", "sensevoice", "-asr", "-tts", "speech-")):
        return ("audio-gen", "none", streaming)

    # 检索重排
    if any(k in c for k in ("-rerank", "rerank-")):
        return ("rerank", "none", streaming)

    # 翻译特化
    if "livetranslate" in c or "live-translate" in c:
        return ("translate", "none", streaming)

    # 超长上下文变体（-1m 后缀表示 1M token 上下文）
    if c.endswith("-1m") or "-instruct-1m" in c:
        return ("long-context", "none", streaming)

    if "embedding" in c:
        return ("embedding", "none", streaming)
    if "-vl-" in c or c.startswith("vl-") or c.endswith("-vl") or "qwen3-vl" in c or "qwen2.5-vl" in c or "qwen-vl" in c:
        return ("vlm", "none", streaming)
    if "qvq" in c:
        return ("vlm", "none", True)
    if "-ocr" in c:
        return ("ocr", "none", streaming)
    if "coder" in c:
        return ("coder", "none", streaming)
    if "-math" in c or c.startswith("math-") or "math-" in c:
        return ("math", "none", streaming)
    if "-mt-" in c or c.startswith("qwen-mt"):
        return ("mt", "none", streaming)
    if any(k in c for k in ("omni", "-audio", "realtime")):
        return ("audio", "none", streaming)
    if any(k in c for k in ("deep-research", "doc-turbo", "tongyi-", "intent-detect", "xiaomi-analysis")):
        return ("special", "none", streaming)
    if "-character" in c:
        return ("special", "none", streaming)

    if any(k in c for k in ("-max-preview", "3-max", "3.6-max", "3.5-max")):
        return ("chat", "extreme", streaming)
    if c.startswith("qwen-max") or c.startswith("qwen-max-"):
        return ("chat", "extreme", streaming)
    if "-397b-" in c or "235b-a22b" in c:
        return ("chat", "extreme", streaming)
    if "-plus" in c or c.endswith("plus"):
        return ("chat", "high", streaming)
    if any(k in c for k in ("122b-a10b", "-30b-a3b", "-30b", "-32b", "27b", "72b")):
        return ("chat", "mid", streaming)
    if any(k in c for k in ("flash", "turbo", "-35b-a3b", "-14b", "-7b", "-8b", "-4b", "-3b", "-1.7b", "-1.5b", "-0.6b", "-0.5b")):
        return ("chat", "low", streaming)

    if any(k in c for k in ("deepseek", "kimi", "glm", "minimax", "llama", "baichuan", "qwq")):
        if any(k in c for k in ("-r1", "v3", "k2", "-4.5", "-4.6", "-4.7", "-5", "-v4-pro")):
            return ("chat", "high", streaming)
        return ("chat", "mid", streaming)

    return ("other", "none", streaming)


def build_extra_params(code: str) -> Dict[str, Any]:
    """推断每个模型的 extra_params，避免调用 400。

    - MoE 系列（-a3b / a10b / a17b / a22b / a35b）默认开启 thinking，必须显式关闭。
    - qwen3.x-* 的 plus/flash 同样约定关闭 thinking，除非是显式 -thinking 变体。
    """

    c = code.lower()
    extra: Dict[str, Any] = {}

    moe_thinking_markers = ("-a3b", "-a10b", "-a17b", "-a22b", "-a35b-")
    if any(k in c for k in moe_thinking_markers):
        extra["enable_thinking"] = False
    if any(c.startswith(p) for p in ("qwen3.5-", "qwen3.6-", "qwen3-")):
        if "-thinking" not in c and "-instruct" not in c:
            extra.setdefault("enable_thinking", False)

    return extra


def enrich_models(models: List[Model], prices: Dict[str, Tuple[float, float]]) -> None:
    for m in models:
        cat, tier, streaming = classify(m.code)
        m.category = cat
        m.tier = tier
        m.streaming_only = streaming
        if m.code in prices and m.price_in == 0:
            m.price_in, m.price_out = prices[m.code]


# ---------------------------------------------------------------------------
# 全局唯一 name 生成（跨区域时加后缀）
# ---------------------------------------------------------------------------

def assign_names(models: List[Model]) -> Dict[int, str]:
    taken: set[str] = set()
    id_to_name: Dict[int, str] = {}

    def sort_key(m: Model) -> Tuple[int, int, str]:
        return (
            0 if m.region.key in ("cn", "beijing") else 1,
            1 if m.is_dated else 0,
            m.code,
        )

    for m in sorted(models, key=sort_key):
        base = re.sub(r"-?\d{4}-\d{2}-\d{2}$", "", m.code).replace("/", "-")
        candidates = []
        if m.region.key in ("cn", "beijing"):
            candidates.append(base)
        else:
            candidates.append(f"{base}-{m.region.key}")
        if m.is_dated:
            date_suffix = re.search(r"(\d{2})-?(\d{2})$", m.code)
            if date_suffix:
                candidates.append(f"{base}-{date_suffix.group(1)}{date_suffix.group(2)}")
        candidates.append(re.sub(r"[^A-Za-z0-9._-]", "-", m.code))
        candidates.append(f"{base}-{m.region.key}-{re.sub(r'[^A-Za-z0-9]', '', m.code)[-6:]}")
        for name in candidates:
            if name and name not in taken:
                taken.add(name)
                id_to_name[id(m)] = name
                break
    return id_to_name


# ---------------------------------------------------------------------------
# 档位映射（5 档）
# ---------------------------------------------------------------------------

def build_tier_mappings(
    models: List[Model],
    id_to_name: Dict[int, str],
) -> Dict[str, Dict[str, List[str]]]:

    def rank(m: Model) -> Tuple:
        c = m.code.lower()
        is_qwen = 0 if c.startswith(("qwen-", "qwen2", "qwen3")) else 1
        has_core = 0 if any(k in c for k in ("-plus", "-max", "-flash", "-turbo")) else 1
        is_cn = 0 if m.region.key in ("cn", "beijing") else 1
        has_date = 1 if m.is_dated else 0
        return (is_qwen, has_core, is_cn, has_date, c)

    def filter_chat(tier_level: Optional[str] = None, *, exclude_reasoning: bool = False) -> List[Model]:
        out: List[Model] = []
        for m in models:
            if m.category != "chat" or not m.has_free_quota or m.streaming_only:
                continue
            if tier_level and m.tier != tier_level:
                continue
            if exclude_reasoning and any(k in m.code.lower() for k in REASONING_KEYWORDS):
                continue
            out.append(m)
        out.sort(key=rank)
        return out

    def to_names(ms: List[Model], limit: Optional[int] = None) -> List[str]:
        names = [id_to_name[id(m)] for m in ms if id(m) in id_to_name]
        if limit is not None:
            names = names[:limit]
        return names

    def vl_free(*, include_streaming: bool = False, limit: int = 4) -> List[str]:
        filtered = [m for m in models if m.category == "vlm" and m.has_free_quota
                    and (include_streaming or not m.streaming_only)]

        def vl_rank(m: Model) -> Tuple:
            c = m.code.lower()
            pri = 3
            if "qwen-vl-max" in c:
                pri = 0
            elif "qwen-vl-plus" in c:
                pri = 1
            elif "qwen3-vl-plus" in c:
                pri = 2
            return (0 if c.startswith("qwen") else 1, pri, 1 if m.is_dated else 0, c)

        filtered.sort(key=vl_rank)
        return to_names(filtered, limit)

    low_chat = filter_chat("low", exclude_reasoning=True)
    mid_chat = filter_chat("mid", exclude_reasoning=True)
    high_chat = filter_chat("high", exclude_reasoning=True)
    extreme_chat = filter_chat("extreme", exclude_reasoning=True)
    all_chat_free = filter_chat(exclude_reasoning=True)

    tiers: Dict[str, Dict[str, List[str]]] = {
        "low": {
            "replyer": to_names(low_chat, 8),
            "planner": to_names(low_chat, 4) + to_names(mid_chat, 2),
            "utils":   to_names(low_chat, 8),
            "vlm":     vl_free(limit=2),
        },
        "mid": {
            "replyer": to_names(high_chat, 4) + to_names(mid_chat, 2),
            "planner": to_names(mid_chat, 4) + to_names(high_chat, 2),
            "utils":   to_names(low_chat, 6),
            "vlm":     vl_free(limit=3),
        },
        "high": {
            "replyer": to_names(high_chat, 6) + to_names(extreme_chat, 2),
            "planner": to_names(high_chat, 4) + to_names(mid_chat, 2),
            "utils":   to_names(low_chat, 4) + to_names(mid_chat, 1),
            "vlm":     vl_free(limit=3),
        },
        "extreme": {
            "replyer": to_names(extreme_chat, 6) + to_names(high_chat, 4),
            "planner": to_names(extreme_chat, 4) + to_names(high_chat, 3),
            "utils":   to_names(high_chat, 4),
            "vlm":     vl_free(limit=4),
        },
        "free": {
            "replyer": to_names([m for m in all_chat_free if m.tier in ("extreme", "high", "mid")], 24),
            "planner": to_names([m for m in all_chat_free if m.tier in ("extreme", "high", "mid")], 24),
            "utils":   to_names([m for m in all_chat_free if m.tier in ("low", "mid")], 16),
            "vlm":     vl_free(limit=16),
        },
    }

    for tier_name, mapping in tiers.items():
        for slot, lst in mapping.items():
            if not lst:
                fallback = to_names(all_chat_free, 1)
                if fallback:
                    mapping[slot] = fallback
    return tiers


# ---------------------------------------------------------------------------
# tomlkit 构造
# ---------------------------------------------------------------------------

def _default_temperature(category: str) -> float:
    return {
        "chat": 1.0, "vlm": 0.3, "embedding": 0.0, "ocr": 0.2,
        "math": 0.2, "coder": 0.3, "audio": 0.3, "mt": 0.2,
    }.get(category, 0.5)


def _find_embedding_name(models: List[Model], id_to_name: Dict[int, str]) -> str:
    for m in models:
        if m.code == "text-embedding-v4" and m.has_free_quota:
            return id_to_name.get(id(m), "")
    for m in models:
        if m.category == "embedding" and m.has_free_quota:
            return id_to_name.get(id(m), "")
    return ""


def build_models_aot(models: List[Model], id_to_name: Dict[int, str]):
    from tomlkit import aot, table

    free_models = [m for m in models if m.has_free_quota]
    free_models.sort(key=lambda m: (m.category, m.tier, m.region.key, m.code))

    arr = aot()
    for m in free_models:
        t = table()
        name = id_to_name.get(id(m))
        if not name:
            continue
        t["model_identifier"] = m.code
        t["name"] = name
        t["api_provider"] = m.region.provider_name
        t["price_in"] = m.price_in
        t["price_out"] = m.price_out
        t["force_stream_mode"] = m.streaming_only
        t["temperature"] = _default_temperature(m.category)
        extra_tbl = table()
        for k, v in build_extra_params(m.code).items():
            extra_tbl[k] = v
        t["extra_params"] = extra_tbl
        arr.append(t)
    return arr


def build_providers_aot(regions: Dict[str, Region], api_keys: Dict[str, str]):
    from tomlkit import aot, table

    arr = aot()
    for region in regions.values():
        t = table()
        t["name"] = region.provider_name
        t["base_url"] = region.base_url
        t["api_key"] = api_keys.get(region.key, "<API_KEY_PLACEHOLDER>")
        t["client_type"] = "openai"
        t["auth_type"] = "bearer"
        t["auth_header_name"] = "Authorization"
        t["auth_header_prefix"] = "Bearer"
        t["auth_query_name"] = "api_key"
        t["model_list_endpoint"] = "/models"
        t["reasoning_parse_mode"] = "auto"
        t["tool_argument_parse_mode"] = "auto"
        t["max_retry"] = 2
        t["timeout"] = 60
        t["retry_interval"] = 10
        t["default_headers"] = table()
        t["default_query"] = table()
        arr.append(t)
    return arr


# ---------------------------------------------------------------------------
# 控制台汇总
# ---------------------------------------------------------------------------

def print_summary(models: List[Model], regions: Dict[str, Region], tiers: Dict[str, Dict[str, List[str]]]) -> None:
    total = len(models)
    free = sum(1 for m in models if m.has_free_quota)
    priced = sum(1 for m in models if m.price_in > 0)
    print(f"\n概况: {len(regions)} 个区域，{total} 条模型条目，{free} 条有免费额度，{priced} 条解析到价格")
    for region in regions.values():
        r_total = sum(1 for m in models if m.region is region)
        r_free = sum(1 for m in models if m.region is region and m.has_free_quota)
        print(f"  [{region.key:8}] provider={region.provider_name:20} url={region.base_url}  条目={r_total} 免费={r_free}")
    print()
    for tier_name, mapping in tiers.items():
        sizes = {slot: len(lst) for slot, lst in mapping.items()}
        print(f"  tier={tier_name:8}  {sizes}")


# ---------------------------------------------------------------------------
# 归属判定
# ---------------------------------------------------------------------------

def _is_managed_provider_name(name: str) -> bool:
    return name == "BaiLian" or name.startswith("BaiLian-")


# ---------------------------------------------------------------------------
# Entry point: build
# ---------------------------------------------------------------------------

def _region_api_keys(regions: Dict[str, Region], existing: Dict[str, str], shared_key: Optional[str]) -> Dict[str, str]:
    keys: Dict[str, str] = {}
    for region in regions.values():
        existing_key = existing.get(region.provider_name, "")
        if existing_key:
            keys[region.key] = existing_key
        elif shared_key:
            keys[region.key] = shared_key
    return keys


def build(args, *, apisource_dir: Path) -> ProviderBundle:
    """apisource/manage.py 调用的入口。"""

    import tomlkit

    response_files = discover_response_files(_PROVIDER_DIR)
    if not response_files:
        raise RuntimeError(f"{_PROVIDER_DIR} 下找不到 response*.json")
    print(f"发现 {len(response_files)} 个区域的 response 文件:")
    for key, path in response_files:
        print(f"  [{key}] {path.name}")

    regions_file = Path(args.regions_file) if getattr(args, "regions_file", None) else REGIONS_FILE
    region_overrides = load_region_config(regions_file)
    regions = resolve_regions(response_files, region_overrides)

    all_models: List[Model] = []
    for region_key, path in response_files:
        region = regions[region_key]
        all_models.extend(load_quotas(path, region))
    append_embedding_defaults(all_models, regions)

    prices = parse_prices(PRICE_PATH)
    enrich_models(all_models, prices)
    id_to_name = assign_names(all_models)

    models_aot = build_models_aot(all_models, id_to_name)
    tiers = build_tier_mappings(all_models, id_to_name)

    print_summary(all_models, regions, tiers)

    # 把 models 清单和每档预览写到 aliyun/output/ 作为归档
    OUTPUT_DIR.mkdir(exist_ok=True)
    registry_doc = tomlkit.document()
    registry_doc["models"] = models_aot
    (OUTPUT_DIR / "models_registry.toml").write_text(tomlkit.dumps(registry_doc), encoding="utf-8")
    print(f"\n已写入 {OUTPUT_DIR / 'models_registry.toml'}")

    # api_key 解析
    existing_keys = _common.extract_existing_api_keys()
    region_keys_map = _region_api_keys(regions, existing_keys, args.api_key)
    for rk, cfg in region_overrides.items():
        if cfg.get("api_key"):
            region_keys_map[rk] = cfg["api_key"]

    providers_aot = build_providers_aot(
        regions,
        api_keys={rk: region_keys_map.get(rk, "<API_KEY_PLACEHOLDER>") for rk in regions},
    )

    tier = args.tier or "mid"  # 未指定时用 mid 占位
    tier_mapping = tiers.get(tier, {}) if args.tier else {}
    embedding_name = _find_embedding_name(all_models, id_to_name)

    return ProviderBundle(
        models_aot=models_aot,
        providers_aot=providers_aot,
        tier_mapping=dict(tier_mapping),
        embedding_name=embedding_name,
        tier=tier if args.tier else "none",
        is_managed_provider_name=_is_managed_provider_name,
    )
