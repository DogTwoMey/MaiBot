#!/usr/bin/env python3
"""生成 MaiBot model_config.toml 的工具。

数据源：
    response.json  — 阿里云百炼控制台 freeTierQuotas XHR 响应
    price.md       — 阿里云百炼官方价格文档

产物（写入 apisource/aliyun/output/ 与 apisource/aliyun/tiers/）：
    output/models_registry.toml     — 全部模型声明（含价格、免费额度注释）
    output/model_config.<tier>.toml — 应用某档位后的完整模型配置预览
    tiers/low.toml, mid.toml, high.toml, extreme.toml
                                    — 四档任务分配预设（可手动编辑）

典型用法：
    python generate_model_config.py                    # 首次初始化 / 刷新一切
    python generate_model_config.py --tier mid         # 生成 mid 档位的完整配置预览
    python generate_model_config.py --only-free        # 仅在 registry 里列出仍有免费额度的模型

说明：
    - 本脚本不会读取也不会写入 config/model_config.toml；
      请自行将 output/model_config.<tier>.toml 里的片段合并到正式配置中。
    - tier 预设默认覆盖 4 个任务：replyer / planner / utils / vlm。
      voice / embedding 不分档，由脚本固定选择（voice 为空；embedding 取 text-embedding-v4）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
RESPONSE_PATH = SCRIPT_DIR / "response.json"
PRICE_PATH = SCRIPT_DIR / "price.md"
TIERS_DIR = SCRIPT_DIR / "tiers"
OUTPUT_DIR = SCRIPT_DIR / "output"


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class Model:
    code: str                       # 原始 model_identifier
    quota_remaining: int = 0        # 免费额度剩余 token
    quota_total: int = 0            # 免费额度总量
    quota_valid: bool = False       # quotaStatus == VALID 且剩余 > 0
    free_tier_only: bool = True     # 控制台里"用完即停"开关
    price_in: float = 0.0           # 元/M token；0 表示未能解析到
    price_out: float = 0.0
    category: str = "other"         # chat / vlm / embedding / coder / math / ocr / mt / audio / special / other
    tier: str = "none"              # extreme / high / mid / low （仅 chat 用）
    streaming_only: bool = False    # qvq-* 等仅支持流式的模型

    @property
    def short_name(self) -> str:
        """给 model_config.toml 里的 name 字段起个短别名。去掉日期后缀。"""
        # 去掉末尾的日期片段 -YYYY-MM-DD 或 -YYYYMMDD
        alias = re.sub(r"-?\d{4}-\d{2}-\d{2}$", "", self.code)
        # 替换路径前缀（MiniMax/xxx）
        alias = alias.replace("/", "-")
        return alias

    @property
    def has_free_quota(self) -> bool:
        return self.quota_valid and self.quota_remaining > 0


# ---------------------------------------------------------------------------
# 加载 response.json
# ---------------------------------------------------------------------------

def load_quotas(path: Path) -> list[Model]:
    data = json.loads(path.read_text(encoding="utf-8"))
    quotas = data["data"]["DataV2"]["data"]["data"]["freeTierQuotas"]
    models: list[Model] = []
    for q in quotas:
        code = q["model"]
        remaining = int(q.get("quotaTotal", {}).get("parsedValue", 0) or 0)
        total = int(q.get("quotaInitTotal", {}).get("parsedValue", 0) or 0)
        status = q.get("quotaStatus", "")
        m = Model(
            code=code,
            quota_remaining=remaining,
            quota_total=total,
            quota_valid=(status == "VALID"),
            free_tier_only=bool(q.get("freeTierOnly", True)),
        )
        models.append(m)

    # 内置补充：freeTierQuotas API 不返回 embedding 模型，手动补入常用项
    # 免费额度不在此接口中呈现，默认标记为 valid（实际是否有免费额度以百炼账号为准）
    embedding_defaults = [
        ("text-embedding-v4", 0.5, 0.0),
        ("text-embedding-v3", 0.7, 0.0),
    ]
    existing_codes = {m.code for m in models}
    for code, p_in, p_out in embedding_defaults:
        if code in existing_codes:
            continue
        m = Model(
            code=code,
            quota_remaining=1_000_000,
            quota_total=1_000_000,
            quota_valid=True,
            free_tier_only=True,
        )
        # 临时塞价格（正常 flow 在 enrich_models 里写入 price；这里保底）
        m.price_in = p_in
        m.price_out = p_out
        models.append(m)

    return models


# ---------------------------------------------------------------------------
# 解析 price.md（best-effort）
# ---------------------------------------------------------------------------

_PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)元")
_CONTINUATION_RE = re.compile(r"^\s*\d+\s*K?\s*<\s*Token", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MODEL_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._/-]*$")


def parse_prices(path: Path) -> dict[str, tuple[float, float]]:
    """解析 price.md，返回 {model_code: (price_in, price_out)}。

    仅处理"中国内地"段的价格表，取**最低一档**价格（最常用于短上下文）。
    """
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    prices: dict[str, tuple[float, float]] = {}
    region = None

    for raw_line in content.splitlines():
        line = raw_line.rstrip()

        # 区域切换：只取 "中国内地"
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
        # 跳过表头、分隔线、阶梯延续行
        if not first or first.startswith("---") or first.startswith("**") or "模型名称" in first:
            continue
        if _CONTINUATION_RE.match(first):
            continue

        # 去 markdown 链接
        first_clean = _MD_LINK_RE.sub(r"\1", first)
        # 取 > 前面（折扣/注记信息）
        model_code = re.split(r"\s*>\s*", first_clean, maxsplit=1)[0].strip()
        # 去掉 **...**
        model_code = model_code.replace("**", "").strip()
        if not _MODEL_CODE_RE.match(model_code):
            continue

        # 后续列里找 "N元"
        tail_text = " | ".join(cols[1:])
        nums = [float(m.group(1)) for m in _PRICE_RE.finditer(tail_text)]
        if len(nums) < 2:
            continue

        p_in, p_out = nums[0], nums[1]
        # 多个同名条目（不同地区或不同档位）只保留第一次（= 最低档位 / 中国内地）
        prices.setdefault(model_code, (p_in, p_out))

    return prices


# ---------------------------------------------------------------------------
# 分类 + 档位判定
# ---------------------------------------------------------------------------

_STREAMING_ONLY_KEYWORDS = ("qvq-", "-thinking", "-reasoning")


def classify(code: str) -> tuple[str, str, bool]:
    """返回 (category, tier, streaming_only)。tier 仅对 chat 有意义。"""
    c = code.lower()
    streaming = any(k in c for k in _STREAMING_ONLY_KEYWORDS)

    # 非 chat 类别优先判
    if "embedding" in c:
        return ("embedding", "none", streaming)
    if "-vl-" in c or c.startswith("vl-") or c.endswith("-vl") or "qwen3-vl" in c or "qwen2.5-vl" in c or "qwen-vl" in c:
        return ("vlm", "none", streaming)
    if "qvq" in c:
        # qvq 是 VL+推理，归 vlm；必须流式
        return ("vlm", "none", True)
    if "-ocr" in c:
        return ("ocr", "none", streaming)
    if "coder" in c:
        return ("coder", "none", streaming)
    if "-math" in c or c.startswith("math-") or "math-" in c:
        return ("math", "none", streaming)
    if "-mt-" in c or c.startswith("qwen-mt"):
        return ("mt", "none", streaming)
    if any(k in c for k in ("omni", "paraformer", "sensevoice", "-audio", "-tts", "-asr", "realtime")):
        return ("audio", "none", streaming)
    if any(k in c for k in ("deep-research", "doc-turbo", "tongyi-", "intent-detect", "xiaomi-analysis")):
        return ("special", "none", streaming)
    if "-character" in c:
        return ("special", "none", streaming)  # 角色扮演变体

    # chat 的档位判定
    # extreme：旗舰 / max-preview / 235b / 397b / 极大模型
    if any(k in c for k in ("-max-preview", "3-max", "3.6-max", "3.5-max")):
        return ("chat", "extreme", streaming)
    if c.startswith("qwen-max") or c == "qwen-max" or c.startswith("qwen-max-"):
        return ("chat", "extreme", streaming)
    if "-397b-" in c or "235b-a22b" in c:
        return ("chat", "extreme", streaming)

    # high：plus 系列 / 3.6-plus / 3.5-plus
    if "-plus" in c or c.endswith("plus"):
        return ("chat", "high", streaming)

    # mid：中型 MoE 与 27b/30b/32b 稠密模型
    if any(k in c for k in ("122b-a10b", "-30b-a3b", "-30b", "-32b", "27b", "72b")):
        return ("chat", "mid", streaming)

    # low：flash / turbo / 小模型
    if any(k in c for k in ("flash", "turbo", "-35b-a3b", "-14b", "-7b", "-8b", "-4b", "-3b", "-1.7b", "-1.5b", "-0.6b", "-0.5b")):
        return ("chat", "low", streaming)

    # 第三方：按名字直觉归类
    if any(k in c for k in ("deepseek", "kimi", "glm", "minimax", "llama", "baichuan", "qwq")):
        # 简化：带 r1 / v3 / k2 / 4.5+ 的常见是 high/mid，其它当 mid
        if any(k in c for k in ("-r1", "v3", "k2", "-4.5", "-4.6", "-4.7", "-5", "-v4-pro")):
            return ("chat", "high", streaming)
        return ("chat", "mid", streaming)

    return ("other", "none", streaming)


# ---------------------------------------------------------------------------
# 应用价格与分类到 Model 列表
# ---------------------------------------------------------------------------

def enrich_models(models: list[Model], prices: dict[str, tuple[float, float]]) -> None:
    for m in models:
        cat, tier, streaming = classify(m.code)
        m.category = cat
        m.tier = tier
        m.streaming_only = streaming
        if m.code in prices:
            p_in, p_out = prices[m.code]
            m.price_in = p_in
            m.price_out = p_out


# ---------------------------------------------------------------------------
# 生成 [[models]] 声明区块
# ---------------------------------------------------------------------------

def _unique_name(model: Model, taken: set[str]) -> str:
    """给模型起一个唯一的 name，避免冲突。"""
    base = model.short_name
    if base not in taken:
        return base
    # 同基名重名：附加日期后缀的精简形式
    m = re.search(r"-(\d{4})-?(\d{2})-?(\d{2})$", model.code)
    if m:
        alias = f"{base}-{m.group(2)}{m.group(3)}"
        if alias not in taken:
            return alias
    # 最后兜底用原 code 去掉非字母数字字符
    alias = re.sub(r"[^A-Za-z0-9._-]", "-", model.code)
    return alias


def _format_model_block(model: Model, name: str) -> str:
    comment_bits = []
    if model.has_free_quota:
        comment_bits.append(f"免费剩余 {model.quota_remaining:,}/{model.quota_total:,}")
    elif model.quota_total:
        comment_bits.append(f"免费额度已耗尽（总量 {model.quota_total:,}）")
    if model.streaming_only:
        comment_bits.append("仅支持流式")
    header = f"# {model.code}"
    if comment_bits:
        header += "  # " + "；".join(comment_bits)

    lines = [
        header,
        "[[models]]",
        f'model_identifier = "{model.code}"',
        f'name = "{name}"',
        'api_provider = "BaiLian"',
        f"price_in = {model.price_in}",
        f"price_out = {model.price_out}",
        f'force_stream_mode = {"true" if model.streaming_only else "false"}',
        f"temperature = {_default_temperature(model.category)}",
        "[models.extra_params]",
    ]
    return "\n".join(lines)


def _default_temperature(category: str) -> float:
    return {
        "chat": 1.0,
        "vlm": 0.3,
        "embedding": 0.0,
        "ocr": 0.2,
        "math": 0.2,
        "coder": 0.3,
        "audio": 0.3,
        "mt": 0.2,
    }.get(category, 0.5)


def build_registry_toml(models: list[Model], only_free: bool) -> tuple[str, dict[str, Model]]:
    """返回 (toml 文本, {name -> model})。"""
    # 过滤
    chosen = [m for m in models if m.has_free_quota] if only_free else list(models)
    # 排序：先按 category，再按 tier 粗排，再按 code
    tier_order = {"extreme": 0, "high": 1, "mid": 2, "low": 3, "none": 4}
    chosen.sort(key=lambda m: (m.category, tier_order.get(m.tier, 99), m.code))

    taken: set[str] = set()
    name_to_model: dict[str, Model] = {}
    blocks: list[str] = []
    current_group = ""
    for m in chosen:
        group = m.category if m.category != "chat" else f"chat-{m.tier}"
        if group != current_group:
            blocks.append(f"\n# ============================================================\n# {group}\n# ============================================================")
            current_group = group
        name = _unique_name(m, taken)
        taken.add(name)
        name_to_model[name] = m
        blocks.append(_format_model_block(m, name))

    header = "\n".join(
        [
            "# models_registry.toml",
            f"# 由 generate_model_config.py 生成于 {datetime.now().isoformat(timespec='seconds')}",
            f"# 源: response.json ({len(models)} 条) + price.md",
            f"# 过滤: {'仅免费额度未耗尽' if only_free else '全部'}",
            "# 单位: price_in / price_out 的单位为 元/M token（最低一档）",
            "",
        ]
    )
    return header + "\n\n".join(blocks) + "\n", name_to_model


# ---------------------------------------------------------------------------
# 档位预设
# ---------------------------------------------------------------------------

TASK_SLOTS = ("replyer", "planner", "utils", "vlm")


def _pick(models: list[Model], **filters) -> list[str]:
    """从模型列表里按条件筛选出 name 列表。filters: category/tier/streaming_only/has_free/limit"""
    result = []
    for m in models:
        if "category" in filters and m.category != filters["category"]:
            continue
        if "tier" in filters and m.tier != filters["tier"]:
            continue
        if "has_free" in filters and m.has_free_quota != filters["has_free"]:
            continue
        if "streaming_only" in filters and m.streaming_only != filters["streaming_only"]:
            continue
        if "exclude_codes" in filters and any(k in m.code for k in filters["exclude_codes"]):
            continue
        result.append(m)
    limit = filters.get("limit")
    if limit is not None:
        result = result[:limit]
    return result


def build_tier_configs(
    name_to_model: dict[str, Model],
) -> dict[str, dict[str, list[str]]]:
    """生成四档预设的 task → model_names 映射。"""
    models = list(name_to_model.values())
    # 倒排索引
    by_name = {n: m for n, m in name_to_model.items()}

    def _rank(m: Model) -> tuple:
        """排序：Qwen 系优先，然后按"稳定版"> snapshot，再按 code 字典序。"""
        c = m.code.lower()
        is_qwen = 0 if c.startswith(("qwen-", "qwen2", "qwen3")) else 1
        # 稳定版(无日期后缀)优先
        has_date = 1 if re.search(r"\d{4}-?\d{2}-?\d{2}", c) else 0
        # plus/max 优先于其它变体
        has_core = 0 if any(k in c for k in ("-plus", "-max", "-flash", "-turbo")) else 1
        return (is_qwen, has_core, has_date, c)

    _REASONING_KEYWORDS = ("-r1", "-thinking", "distill", "qvq", "qwq")

    # Model → name 反查表（一个 model 对应唯一 name）
    model_to_name = {id(m): n for n, m in by_name.items()}

    def chat(tier_level: str, *, max_count: int = 8, exclude_reasoning: bool = False) -> list[str]:
        filtered = [
            m for m in models
            if m.category == "chat"
            and m.tier == tier_level
            and m.has_free_quota
            and not m.streaming_only
        ]
        if exclude_reasoning:
            filtered = [m for m in filtered if not any(k in m.code.lower() for k in _REASONING_KEYWORDS)]
        filtered.sort(key=_rank)
        # 保留排序后的顺序
        return [model_to_name[id(m)] for m in filtered if id(m) in model_to_name][:max_count]

    def vl_pick(prefer_streaming: bool = False, max_count: int = 3) -> list[str]:
        filtered = [
            m for m in models
            if m.category == "vlm"
            and m.has_free_quota
            and (m.streaming_only == prefer_streaming if prefer_streaming else not m.streaming_only)
        ]
        def rank(m: Model) -> tuple:
            c = m.code.lower()
            is_qwen = 0 if c.startswith("qwen") else 1
            # qwen-vl-plus > qwen-vl-max > qwen3-vl-plus 之类的偏好
            pri = 3
            if "-max" in c and "qwen-vl-max" in c:
                pri = 0
            elif "-plus" in c and "qwen-vl" in c:
                pri = 1
            elif "qwen3-vl-plus" in c:
                pri = 2
            has_date = 1 if re.search(r"\d{4}-?\d{2}-?\d{2}", c) else 0
            return (is_qwen, pri, has_date, c)
        filtered.sort(key=rank)
        return [model_to_name[id(m)] for m in filtered if id(m) in model_to_name][:max_count]

    tiers: dict[str, dict[str, list[str]]] = {}

    # low：最便宜；utils 不用 reasoning
    tiers["low"] = {
        "replyer": chat("low", max_count=6),
        "planner": chat("low", max_count=4) + chat("mid", max_count=2),
        "utils": chat("low", max_count=6, exclude_reasoning=True),
        "vlm": vl_pick(prefer_streaming=False, max_count=2),
    }

    # mid：日常平衡，replyer 以 Qwen plus 打底
    tiers["mid"] = {
        "replyer": chat("high", max_count=4) + chat("mid", max_count=2),
        "planner": chat("mid", max_count=4) + chat("high", max_count=2),
        "utils": chat("low", max_count=4, exclude_reasoning=True),
        "vlm": vl_pick(prefer_streaming=False, max_count=2),
    }

    # high：回复质量优先
    tiers["high"] = {
        "replyer": chat("high", max_count=6) + chat("extreme", max_count=1),
        "planner": chat("high", max_count=4) + chat("mid", max_count=2),
        "utils": chat("low", max_count=3, exclude_reasoning=True) + chat("mid", max_count=1, exclude_reasoning=True),
        "vlm": vl_pick(prefer_streaming=False, max_count=2),
    }

    # extreme：不计成本；utils 也用 high 但排除推理
    tiers["extreme"] = {
        "replyer": chat("extreme", max_count=5) + chat("high", max_count=3),
        "planner": chat("extreme", max_count=3) + chat("high", max_count=2),
        "utils": chat("high", max_count=4, exclude_reasoning=True),
        "vlm": vl_pick(prefer_streaming=False, max_count=3),
    }

    # free：优先榨完所有仍有免费额度的模型。
    # 不限 tier，同档位内 qwen 系优先，紧接着第三方（DeepSeek / Kimi / GLM / MiniMax 等免费池）。
    # max_count 放宽，让 random 策略把流量摊到所有独立配额池。
    def all_free_chat(exclude_reasoning: bool = False) -> list[Model]:
        result = []
        for lvl in ("high", "extreme", "mid", "low"):
            for m in models:
                if (m.category == "chat" and m.tier == lvl
                        and m.has_free_quota and not m.streaming_only):
                    if exclude_reasoning and any(k in m.code.lower() for k in _REASONING_KEYWORDS):
                        continue
                    result.append(m)
        return result

    def _ordered_names(filtered: list[Model]) -> list[str]:
        filtered.sort(key=_rank)
        return [model_to_name[id(m)] for m in filtered if id(m) in model_to_name]

    # replyer：所有 high + extreme + mid 的免费模型（非推理）
    replyer_free = _ordered_names([m for m in all_free_chat(exclude_reasoning=True)
                                   if m.tier in ("extreme", "high", "mid")])[:16]
    # planner：可以包含推理模型，让 Planner 拥有更强工具使用能力
    planner_free = _ordered_names([m for m in all_free_chat(exclude_reasoning=False)
                                   if m.tier in ("extreme", "high", "mid")])[:16]
    # utils：all low + mid 的非推理
    utils_free = _ordered_names([m for m in all_free_chat(exclude_reasoning=True)
                                 if m.tier in ("low", "mid")])[:12]
    # vlm：所有非流式 VL 免费池（尽量多 snapshot）
    vlm_free = vl_pick(prefer_streaming=False, max_count=8)

    tiers["free"] = {
        "replyer": replyer_free or chat("high") or chat("mid") or chat("low"),
        "planner": planner_free or chat("mid") or chat("high"),
        "utils":   utils_free   or chat("low") or chat("mid"),
        "vlm":     vlm_free     or vl_pick(prefer_streaming=False, max_count=1),
    }

    # 兜底
    for tier_name, mapping in tiers.items():
        for slot, lst in mapping.items():
            if not lst:
                fallback = chat("low") or chat("mid") or chat("high")
                mapping[slot] = fallback[:1]
    return tiers


def format_tier_toml(tier_name: str, mapping: dict[str, list[str]]) -> str:
    lines = [
        f"# tiers/{tier_name}.toml",
        f"# 档位: {tier_name}",
        "# 说明: 把每个任务槽的 model_list 映射到 [[models]] 里的 name。",
        "# 你可以手动编辑这份文件调整选择。",
        "",
    ]
    task_params = {
        "replyer": ("4096", "1.0", "120"),
        "planner": ("8000", "0.7", "12"),
        "utils": ("4096", "0.5", "15"),
        "vlm": ("512", "0.3", "15"),
    }
    for task, names in mapping.items():
        max_t, temp, slow = task_params[task]
        lines.append(f"[tier.{task}]")
        arr = ",\n".join(f'    "{n}"' for n in names) if names else ""
        if arr:
            lines.append(f"model_list = [\n{arr},\n]")
        else:
            lines.append("model_list = []")
        lines.append(f"max_tokens = {max_t}")
        lines.append(f"temperature = {temp}")
        lines.append(f"slow_threshold = {slow}")
        lines.append('selection_strategy = "random"')
        lines.append("")
    return "\n".join(lines)


def load_tier_toml(path: Path) -> dict[str, dict]:
    """读回一个 tier toml，返回每个 task 的配置 dict。"""
    import tomllib
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    return doc.get("tier", {})


# ---------------------------------------------------------------------------
# 合成完整的 model_config.<tier>.toml
# ---------------------------------------------------------------------------

def format_task_block(task_name: str, cfg: dict) -> str:
    model_list = cfg.get("model_list", [])
    max_tokens = cfg.get("max_tokens", 4096)
    temperature = cfg.get("temperature", 0.5)
    slow_threshold = cfg.get("slow_threshold", 15)
    strategy = cfg.get("selection_strategy", "random")
    lines = [f"[model_task_config.{task_name}]"]
    if model_list:
        arr = ",\n".join(f'    "{n}"' for n in model_list)
        lines.append(f"model_list = [\n{arr},\n]")
    else:
        lines.append("model_list = []")
    lines.append(f"max_tokens = {max_tokens}")
    lines.append(f"temperature = {temperature}")
    lines.append(f"slow_threshold = {slow_threshold}")
    lines.append(f'selection_strategy = "{strategy}"')
    return "\n".join(lines)


def _embedding_model_name(name_to_model: dict[str, Model]) -> str:
    for n, m in name_to_model.items():
        if "text-embedding-v4" in m.code:
            return n
    for n, m in name_to_model.items():
        if m.category == "embedding" and m.has_free_quota:
            return n
    return ""


def build_full_config(
    tier_name: str,
    registry_text: str,
    tier_mapping: dict[str, dict],
    name_to_model: dict[str, Model],
) -> str:
    embedding_name = _embedding_model_name(name_to_model)
    task_blocks = [format_task_block(t, tier_mapping.get(t, {})) for t in TASK_SLOTS]
    task_blocks.append(
        format_task_block(
            "voice",
            {"model_list": [], "max_tokens": 1024, "temperature": 0.3, "slow_threshold": 12, "selection_strategy": "random"},
        )
    )
    task_blocks.append(
        format_task_block(
            "embedding",
            {"model_list": [embedding_name] if embedding_name else [], "max_tokens": 1024, "temperature": 0.3, "slow_threshold": 5, "selection_strategy": "random"},
        )
    )

    provider = """
# =============================================================
# API Provider
# =============================================================

[[api_providers]]
name = "BaiLian"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key = "<API_KEY_PLACEHOLDER>"   # 请替换为你的真实 key
client_type = "openai"
auth_type = "bearer"
auth_header_name = "Authorization"
auth_header_prefix = "Bearer"
auth_query_name = "api_key"
model_list_endpoint = "/models"
reasoning_parse_mode = "auto"
tool_argument_parse_mode = "auto"
max_retry = 2
timeout = 60
retry_interval = 10

[api_providers.default_headers]

[api_providers.default_query]
"""

    head = f'[inner]\nversion = "1.14.1"\n\n# 档位: {tier_name}\n# 生成时间: {datetime.now().isoformat(timespec="seconds")}\n\n'
    return head + registry_text + "\n\n# =============================================================\n# 任务 → 模型映射\n# =============================================================\n\n" + "\n\n".join(task_blocks) + "\n" + provider


# ---------------------------------------------------------------------------
# 命令分发
# ---------------------------------------------------------------------------

def cmd_build(only_free: bool, regen_tiers: bool = False) -> None:
    models = load_quotas(RESPONSE_PATH)
    prices = parse_prices(PRICE_PATH)
    enrich_models(models, prices)

    registry, name_to_model = build_registry_toml(models, only_free=only_free)
    OUTPUT_DIR.mkdir(exist_ok=True)
    registry_path = OUTPUT_DIR / "models_registry.toml"
    registry_path.write_text(registry, encoding="utf-8")
    print(f"[build] 已写入 {registry_path}  ({len(name_to_model)} 条)")

    # 生成四档预设
    tiers = build_tier_configs(name_to_model)
    TIERS_DIR.mkdir(exist_ok=True)
    for tier_name, mapping in tiers.items():
        path = TIERS_DIR / f"{tier_name}.toml"
        if path.exists() and not regen_tiers:
            print(f"[build] 保留已有 {path}（加 --regen-tiers 可覆盖）")
            continue
        path.write_text(format_tier_toml(tier_name, mapping), encoding="utf-8")
        print(f"[build] 已写入 {path}")

    # 统计
    total = len(models)
    free = sum(1 for m in models if m.has_free_quota)
    with_price = sum(1 for m in models if m.price_in > 0)
    print()
    print(f"概况: 总计 {total} 条模型，{free} 条仍有免费额度，{with_price} 条解析到中国内地价格")


def cmd_tier(tier_name: str) -> None:
    tier_path = TIERS_DIR / f"{tier_name}.toml"
    if not tier_path.exists():
        print(f"错误: 未找到档位文件 {tier_path}。请先运行 `python generate_model_config.py` 初始化。")
        sys.exit(1)

    models = load_quotas(RESPONSE_PATH)
    prices = parse_prices(PRICE_PATH)
    enrich_models(models, prices)
    registry, name_to_model = build_registry_toml(models, only_free=False)
    tier_mapping = load_tier_toml(tier_path)

    full = build_full_config(tier_name, registry, tier_mapping, name_to_model)
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"model_config.{tier_name}.toml"
    out_path.write_text(full, encoding="utf-8")
    print(f"[tier={tier_name}] 已生成 {out_path}")
    print(f"任务映射预览 ({tier_path.name}):")
    for task, cfg in tier_mapping.items():
        mlist = cfg.get("model_list", [])
        print(f"  {task:10} -> {mlist}")
    print()
    print("下一步：diff 该文件与 config/model_config.toml，挑需要的片段合并。")
    print("注意：api_key 字段是占位符 <API_KEY_PLACEHOLDER>，合并时保留你原来的 key。")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate MaiBot model_config.toml from aliyun quota + price data.")
    parser.add_argument("--tier", choices=("low", "mid", "high", "extreme", "free"), help="生成指定档位的完整配置")
    parser.add_argument("--only-free", action="store_true", help="registry 仅包含仍有免费额度的模型")
    parser.add_argument("--regen-tiers", action="store_true", help="强制覆盖 tiers/*.toml（默认会保留已有手工编辑）")
    args = parser.parse_args()

    if not RESPONSE_PATH.exists():
        print(f"错误: 缺少 {RESPONSE_PATH}")
        return 1

    if args.tier:
        # 先确保 build 过（registry + tier 预设存在）
        if not (TIERS_DIR / f"{args.tier}.toml").exists() or args.regen_tiers:
            print(f"首次运行或 --regen-tiers：先初始化 registry 与档位预设...")
            cmd_build(only_free=False, regen_tiers=args.regen_tiers)
        cmd_tier(args.tier)
    else:
        cmd_build(only_free=args.only_free, regen_tiers=args.regen_tiers)

    return 0


if __name__ == "__main__":
    sys.exit(main())
