#!/usr/bin/env python3
"""阿里云百炼模型 → MaiBot model_config.toml 一体化工具。

特性：
    - 支持多区域：扫描 ``apisource/aliyun/response*.json``，每个文件代表一个区域
      （单文件 ``response.json`` 视为区域 ``cn``；多文件形如
      ``response_cn.json`` / ``response_intl.json`` / ``response_us.json`` 等，
      区域名从文件名推断）。
    - 自动把"仍有免费额度"的模型全部注册到 MaiBot，必要时按区域生成多个
      ``[[api_providers]]`` 条目，并用 name 后缀区分同模型跨区域的 snapshot。
    - 内置 5 档预设（low / mid / high / extreme / free），free 档把**所有
      免费配额模型**平铺到每个任务槽以最大化额度利用。
    - 支持 ``--apply`` 直接改写 ``config/model_config.toml``，保留
      ``[[api_providers]]`` 里的 ``api_key``。

典型用法：
    # 只构建，不改配置（预览）
    python manage.py

    # 构建 + 应用 free 档（把所有免费模型塞进任务槽）
    python manage.py --tier free --apply

    # 构建 + 应用 mid 档（日常平衡）
    python manage.py --tier mid --apply

    # 指定区域→base_url 的映射
    python manage.py --tier free --regions-file regions.toml --apply

    # 仅 dry-run，不写文件
    python manage.py --tier free --dry-run

数据源目录默认为脚本所在目录：
    apisource/aliyun/response*.json     免费额度数据（可多个区域）
    apisource/aliyun/price.md           官方价目文档
    apisource/aliyun/regions.toml       可选：区域配置（base_url 等）
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "model_config.toml"
BACKUP_DIR = PROJECT_ROOT / "config" / "backup"
PRICE_PATH = SCRIPT_DIR / "price.md"
REGIONS_FILE = SCRIPT_DIR / "regions.toml"
OUTPUT_DIR = SCRIPT_DIR / "output"

# 内置区域→base_url 默认。用户可通过 regions.toml 覆盖。
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

TASK_SLOTS = ("replyer", "planner", "utils", "vlm", "voice", "embedding")
TASK_PARAMS: Dict[str, Dict[str, Any]] = {
    "replyer":   {"max_tokens": 4096, "temperature": 1.0, "slow_threshold": 120},
    "planner":   {"max_tokens": 8000, "temperature": 0.7, "slow_threshold": 12},
    "utils":     {"max_tokens": 4096, "temperature": 0.5, "slow_threshold": 15},
    "vlm":       {"max_tokens": 512,  "temperature": 0.3, "slow_threshold": 15},
    "voice":     {"max_tokens": 1024, "temperature": 0.3, "slow_threshold": 12},
    "embedding": {"max_tokens": 1024, "temperature": 0.3, "slow_threshold": 5},
}

STREAMING_ONLY_KEYWORDS: Tuple[str, ...] = ("qvq-", "-thinking", "-reasoning")
REASONING_KEYWORDS: Tuple[str, ...] = ("-r1", "-thinking", "distill", "qvq", "qwq")


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class Region:
    """单个部署区域的元信息。"""

    key: str                       # cn / intl / us ...
    base_url: str
    provider_name: str             # [[api_providers]].name


@dataclass
class Model:
    """同一个 model_code 在某个区域下的实例。"""

    code: str                      # 原始 model_identifier
    region: Region
    quota_remaining: int = 0
    quota_total: int = 0
    quota_valid: bool = False
    free_tier_only: bool = True
    price_in: float = 0.0
    price_out: float = 0.0
    category: str = "other"        # chat / vlm / embedding / coder / math / ocr / mt / audio / special / other
    tier: str = "none"             # extreme / high / mid / low
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
        _                    # 下划线分隔
        (?P<region>[a-zA-Z0-9-]+)   # 第一段：区域（cn / intl / us / hk ...）
        (?:_[a-zA-Z0-9-]+)*  # 后续可有 _tab 标签（_llm / _vl / _omni / _voice / _embed 等）
    )?
    \.json$
    """,
    re.VERBOSE,
)


_KNOWN_REGION_KEYS: frozenset[str] = frozenset(DEFAULT_REGION_URLS)


def discover_response_files(dir_: Path) -> List[Tuple[str, Path]]:
    """扫描脚本目录下所有 response*.json，返回 [(region_key, path)]。

    支持的文件命名：

    - ``response.json``                → cn
    - ``response_<region>.json``       → <region>
    - ``response_<region>_<tab>.json`` → <region>（同区域多类别 tab）

    当 region 段不在已知映射里时，默认归到 ``cn``，并打印提示。
    """

    results: List[Tuple[str, Path]] = []
    for p in sorted(dir_.iterdir()):
        if not p.is_file():
            continue
        m = _RESPONSE_FILE_RE.match(p.name)
        if not m:
            continue
        region_key = (m.group("region") or "cn").lower()
        if region_key not in _KNOWN_REGION_KEYS:
            # 未知区域名：极可能是"原本想写 cn_llm/cn_vl 这种 tab 后缀，但解析到了 cn_llm 当 region"
            # 回退策略：取首段作为 region key
            first_segment = region_key.split("-")[0]
            if first_segment in _KNOWN_REGION_KEYS:
                region_key = first_segment
            else:
                # 文件名里第一段也不是已知 region，默认归 cn
                print(f"提示: {p.name} 的 region 段 {region_key!r} 未识别，按 cn 处理。")
                region_key = "cn"
        results.append((region_key, p))
    return results


def load_region_config(path: Path) -> Dict[str, Dict[str, str]]:
    """读取 regions.toml。结构::

        [regions.cn]
        base_url = "https://..."

    返回 ``{region_key: {base_url: ...}}``。
    """

    if not path.exists():
        return {}
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    return dict(doc.get("regions") or {})


def resolve_regions(response_files: Iterable[Tuple[str, Path]], overrides: Dict[str, Dict[str, str]]) -> Dict[str, Region]:
    """为每个出现的区域确定 base_url。"""

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
# 单个 region 的 response.json 加载
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
    """按每个 region 一次地补充 embedding 模型兜底条目（阿里云 freeTierQuotas API 不返回）。

    若 region 的 response 文件已经包含同名 embedding 模型则跳过。
    """

    defaults = [
        ("text-embedding-v4", 0.5, 0.0),
        ("text-embedding-v3", 0.7, 0.0),
    ]
    # 收集每个 region 已出现过的模型 code
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
# price.md 解析（best-effort，取中国内地最低档）
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

    # 先把"非 chat 输入输出"的模型全部隔离——这些走的不是 /chat/completions 的 content
    # schema，强行塞进 replyer/planner/utils 只会得到 400/404 参数错误。

    # 万相 wan 系列：wan2.1 / wan2.2 / wan2.5 … —— 图像或视频生成，走专用端点
    # 同时捕获 aitryon (虚拟试穿，本质也是图像生成)
    if re.match(r"^wan[0-9]", c) or c.startswith("wan-") or c.startswith("wanx") or "aitryon" in c:
        # 模态细分：i2v / t2v / v2v 是视频，其它（含 t2i / i2i / 无显式标识）归图像
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

    # 语音合成 / 识别独立端点
    if any(k in c for k in ("cosyvoice", "paraformer", "sensevoice", "-asr", "-tts", "speech-")):
        return ("audio-gen", "none", streaming)

    # 检索重排
    if any(k in c for k in ("-rerank", "rerank-")):
        return ("rerank", "none", streaming)

    # 翻译特化（livetranslate / 翻译专用模型）—— 走 chat 但不适合回复主链
    if "livetranslate" in c or "live-translate" in c:
        return ("translate", "none", streaming)

    # 超长上下文变体（-1m 后缀表示 1M token 上下文）：响应慢，不适合 utils
    # 归类为 "long-context" 排除出常规任务列表
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
    """为某个模型推断合适的 extra_params，避免调用时触发 400。

    主要处理：
    - qwen3-*-a3b / a10b / a17b / a22b 等 MoE 默认开启 thinking，
      非流式调用必须 enable_thinking=false。
    - qwen3.x-* 部分模型同样强制要求显式关闭 thinking。
    """

    c = code.lower()
    extra: Dict[str, Any] = {}

    # MoE thinking-默认开启 的模型：强制关闭 thinking 以走非流式 chat
    moe_thinking_markers = ("-a3b", "-a10b", "-a17b", "-a22b", "-a35b-")
    if any(k in c for k in moe_thinking_markers):
        extra["enable_thinking"] = False
    # qwen3.x 系列 plus/flash 也遵循该约定
    if any(c.startswith(p) for p in ("qwen3.5-", "qwen3.6-", "qwen3-")):
        # 显式 thinking 变体单独处理（它们应该走流式，外层 streaming_only 会拦）
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
# 唯一 name 生成（跨区域时加后缀）
# ---------------------------------------------------------------------------

def assign_names(models: List[Model]) -> Dict[int, str]:
    """给每个 Model 分配一个全局唯一的 name。按 id() 作为 key 返回。"""

    taken: set[str] = set()
    id_to_name: Dict[int, str] = {}
    # 先按 "中国内地优先 + 无日期 snapshot 优先" 排序，让主要模型占用无后缀的 name
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
            # 额外尝试带日期的别名
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
# 任务档位
# ---------------------------------------------------------------------------

def build_tier_mappings(
    models: List[Model],
    id_to_name: Dict[int, str],
) -> Dict[str, Dict[str, List[str]]]:
    """生成 5 档任务预设，只选择有免费额度的模型。"""

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

    # free：所有有免费额度的非推理 chat，按 rank 组合
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
            # 任务槽里直接平铺"所有免费额度的模型"
            "replyer": to_names([m for m in all_chat_free if m.tier in ("extreme", "high", "mid")], 24),
            "planner": to_names([m for m in all_chat_free if m.tier in ("extreme", "high", "mid")], 24),
            "utils":   to_names([m for m in all_chat_free if m.tier in ("low", "mid")], 16),
            "vlm":     vl_free(limit=16),
        },
    }

    # 兜底：空列表 → 填任意
    for tier_name, mapping in tiers.items():
        for slot, lst in mapping.items():
            if not lst:
                fallback = to_names(all_chat_free, 1)
                if fallback:
                    mapping[slot] = fallback
    return tiers


# ---------------------------------------------------------------------------
# TOML 构造（tomlkit）
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
    """构造 [[models]] 数组（tomlkit aot）。只包含有免费额度的模型。"""

    import tomlkit
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
        # 头部注释（tomlkit 写入 aot 元素的注释较繁琐，暂略）
        arr.append(t)
    return arr


def build_task_table(slot: str, model_names: List[str], *, selection_strategy: str = "random"):
    from tomlkit import table
    t = table()
    t["model_list"] = list(model_names)
    params = TASK_PARAMS[slot]
    t["max_tokens"] = params["max_tokens"]
    t["temperature"] = params["temperature"]
    t["slow_threshold"] = params["slow_threshold"]
    t["selection_strategy"] = selection_strategy
    return t


def build_providers_aot(regions: Dict[str, Region], api_keys: Dict[str, str]):
    """构造 [[api_providers]] 数组。保留 api_key 的占位符（后续由 apply 阶段合并）。"""

    import tomlkit
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
# 合并到 config/model_config.toml
# ---------------------------------------------------------------------------

def _backup_config() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"model_config.{stamp}.toml"
    shutil.copy2(CONFIG_PATH, backup)
    return backup


def _extract_existing_api_keys() -> Dict[str, str]:
    """从现有 config/model_config.toml 里读出已有的 {provider_name: api_key}。

    provider_name 是 [[api_providers]].name 字段，用来跨区域映射。本脚本约定：
    - BaiLian (无后缀)        → region=cn
    - BaiLian-<region_key>    → 对应区域
    """

    if not CONFIG_PATH.exists():
        return {}
    import tomlkit
    doc = tomlkit.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    result: Dict[str, str] = {}
    for entry in doc.get("api_providers", []) or []:
        name = str(entry.get("name", ""))
        key = str(entry.get("api_key", ""))
        if name and key and key != "<API_KEY_PLACEHOLDER>":
            result[name] = key
    return result


def _region_api_keys(regions: Dict[str, Region], existing: Dict[str, str], shared_key: Optional[str]) -> Dict[str, str]:
    """按 region_key 解析 api_key。"""

    keys: Dict[str, str] = {}
    for region in regions.values():
        existing_key = existing.get(region.provider_name, "")
        if existing_key:
            keys[region.key] = existing_key
        elif shared_key:
            keys[region.key] = shared_key
    return keys


def _sanitize_task_names(desired: List[str], valid: set[str]) -> Tuple[List[str], List[str]]:
    kept, dropped = [], []
    for n in desired:
        if str(n) in valid:
            kept.append(str(n))
        else:
            dropped.append(str(n))
    return kept, dropped


def apply_to_config(
    tier_mapping: Dict[str, List[str]],
    models_aot,
    providers_aot,
    *,
    dry_run: bool,
    embedding_name: str,
) -> None:
    """就地改写 config/model_config.toml：替换 [[models]]、[model_task_config.*]、[[api_providers]]。"""

    import tomlkit

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"找不到 {CONFIG_PATH}")

    current_text = CONFIG_PATH.read_text(encoding="utf-8")
    doc = tomlkit.loads(current_text)

    # 替换 [[models]]
    if "models" in doc:
        del doc["models"]
    doc["models"] = models_aot

    # model_task_config
    valid_names = {str(entry.get("name")) for entry in models_aot if entry.get("name")}
    mtc = doc.get("model_task_config")
    if mtc is None:
        from tomlkit import table
        mtc = table()
        doc["model_task_config"] = mtc

    for slot in TASK_SLOTS:
        if slot in ("voice", "embedding"):
            existing_list = [] if slot not in mtc else list(mtc[slot].get("model_list", []))
            if slot == "embedding" and not existing_list:
                existing_list = [embedding_name] if embedding_name else []
            kept, dropped = _sanitize_task_names(existing_list, valid_names)
            if dropped:
                print(f"[apply] ⚠ {slot} 剔除失效引用: {dropped} -> {kept}")
            table_ = build_task_table(slot, kept)
        else:
            desired = tier_mapping.get(slot, [])
            kept, dropped = _sanitize_task_names(desired, valid_names)
            if dropped:
                print(f"[apply] ⚠ tier slot {slot} 剔除失效引用: {dropped}")
            table_ = build_task_table(slot, kept)
        if slot in mtc:
            del mtc[slot]
        mtc[slot] = table_

    # [[api_providers]]
    if "api_providers" in doc:
        del doc["api_providers"]
    doc["api_providers"] = providers_aot

    new_text = tomlkit.dumps(doc)

    # 安全检查：占位符不能泄漏
    if "<API_KEY_PLACEHOLDER>" in new_text:
        raise RuntimeError(
            "生成的内容里仍有 <API_KEY_PLACEHOLDER>。"
            "请在 regions.toml 里给对应区域写入 api_key，或传 --api-key 作为全局值。"
        )

    # 报告
    print(f"[apply] models: {sum(1 for _ in models_aot)} 条")
    for slot in TASK_SLOTS:
        mlist = list(doc["model_task_config"][slot].get("model_list", []))
        print(f"[apply] {slot:10} -> {len(mlist)} 候选: {mlist[:8]}{'...' if len(mlist) > 8 else ''}")

    if dry_run:
        print("\n[dry-run] 不写入任何文件。")
        return

    backup = _backup_config()
    print(f"[apply] 已备份 -> {backup}")
    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".new")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    print(f"[apply] 已写入 {CONFIG_PATH}")
    print("\n下一步：重启 bot.py 让新配置生效。")


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
# CLI
# ---------------------------------------------------------------------------

def _ensure_tomlkit() -> None:
    try:
        import tomlkit  # noqa: F401
    except ImportError:
        print("错误: 需要 tomlkit。请用项目 venv 跑：\n  .venv\\Scripts\\python.exe apisource\\aliyun\\manage.py")
        sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="阿里云百炼模型 → MaiBot config 一体化工具。")
    parser.add_argument(
        "--tier",
        choices=("low", "mid", "high", "extreme", "free"),
        help="要应用的档位（不指定只构建产物到 output/）",
    )
    parser.add_argument("--apply", action="store_true", help="写入 config/model_config.toml（默认只产物到 output/）")
    parser.add_argument("--dry-run", action="store_true", help="--apply 时打印变更但不写文件")
    parser.add_argument("--regions-file", default=str(REGIONS_FILE), help="区域配置 TOML（默认 regions.toml）")
    parser.add_argument("--api-key", default=None, help="未在 regions.toml 声明时使用的全局 api_key")
    args = parser.parse_args()

    _ensure_tomlkit()

    response_files = discover_response_files(SCRIPT_DIR)
    if not response_files:
        print(f"错误: {SCRIPT_DIR} 下找不到 response*.json")
        return 1
    print(f"发现 {len(response_files)} 个区域的 response 文件:")
    for key, path in response_files:
        print(f"  [{key}] {path.name}")

    region_overrides = load_region_config(Path(args.regions_file))
    regions = resolve_regions(response_files, region_overrides)

    # 聚合所有模型（一个区域可能有多个文件：llm/vl/omni/voice/embed tab）
    all_models: List[Model] = []
    for region_key, path in response_files:
        region = regions[region_key]
        all_models.extend(load_quotas(path, region))
    append_embedding_defaults(all_models, regions)

    prices = parse_prices(PRICE_PATH)
    enrich_models(all_models, prices)
    id_to_name = assign_names(all_models)

    # 构造产物（即使 --apply 也需要）
    import tomlkit
    models_aot = build_models_aot(all_models, id_to_name)
    tiers = build_tier_mappings(all_models, id_to_name)

    print_summary(all_models, regions, tiers)

    # 无论是否 apply，都把产物写到 output/
    OUTPUT_DIR.mkdir(exist_ok=True)
    registry_doc = tomlkit.document()
    registry_doc["models"] = models_aot
    (OUTPUT_DIR / "models_registry.toml").write_text(tomlkit.dumps(registry_doc), encoding="utf-8")
    print(f"\n已写入 {OUTPUT_DIR / 'models_registry.toml'}")

    if not args.tier:
        print("未指定 --tier；仅完成产物构建。")
        return 0

    # API keys 解析
    existing_keys = _extract_existing_api_keys()
    region_keys_map = _region_api_keys(regions, existing_keys, args.api_key)
    # regions_file 显式写的 api_key 覆盖一切
    for rk, cfg in region_overrides.items():
        if cfg.get("api_key"):
            region_keys_map[rk] = cfg["api_key"]

    providers_aot = build_providers_aot(
        regions,
        api_keys={rk: region_keys_map.get(rk, "<API_KEY_PLACEHOLDER>") for rk in regions},
    )

    embedding_name = _find_embedding_name(all_models, id_to_name)

    if args.apply or args.dry_run:
        apply_to_config(
            tier_mapping=tiers[args.tier],
            models_aot=models_aot,
            providers_aot=providers_aot,
            dry_run=args.dry_run,
            embedding_name=embedding_name,
        )
    else:
        # 仅生成完整 toml 到 output/ 供检阅
        doc = tomlkit.document()
        doc["inner"] = tomlkit.table()
        doc["inner"]["version"] = "1.14.1"
        doc["models"] = models_aot
        doc["model_task_config"] = tomlkit.table()
        for slot in TASK_SLOTS:
            if slot in ("voice", "embedding"):
                names = [embedding_name] if (slot == "embedding" and embedding_name) else []
            else:
                names = tiers[args.tier].get(slot, [])
            doc["model_task_config"][slot] = build_task_table(slot, names)
        doc["api_providers"] = providers_aot
        out_path = OUTPUT_DIR / f"model_config.{args.tier}.toml"
        out_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
        print(f"\n已生成预览 {out_path}（没有写入正式 config）。")
        print("加 --apply 把它合并到 config/model_config.toml。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
