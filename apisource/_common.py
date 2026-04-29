"""apisource 共享工具：ProviderBundle + 合并式 apply。

本模块由 apisource/manage.py 以及各个 provider 模块共用。重点是
``apply_bundle_to_config``——它会把**当前 provider 管理范围内**的
[[models]]、[[api_providers]] 和 model_task_config.<slot> 条目 **增量合并** 到
config/model_config.toml，同时保留其它 provider 的条目与 api_key。

每个 provider 模块通过 ``build(args, *, apisource_dir) -> ProviderBundle``
声明自己要写入哪些条目，以及哪些 provider name 归属于它（通过
``is_managed_provider_name`` 谓词），便于 merge 时识别"本次归属 / 本次非归属"。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# 路径常量（与 PROJECT_ROOT 相关）
# ---------------------------------------------------------------------------

APISOURCE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APISOURCE_DIR.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "model_config.toml"
BACKUP_DIR = PROJECT_ROOT / "config" / "backup"


# ---------------------------------------------------------------------------
# 任务槽常量（全部 provider 共享）
# ---------------------------------------------------------------------------

TASK_SLOTS: Tuple[str, ...] = ("replyer", "planner", "utils", "vlm", "voice", "embedding")

TASK_PARAMS: Dict[str, Dict[str, Any]] = {
    "replyer":   {"max_tokens": 4096, "temperature": 1.0, "slow_threshold": 120},
    "planner":   {"max_tokens": 8000, "temperature": 0.7, "slow_threshold": 12},
    "utils":     {"max_tokens": 4096, "temperature": 0.5, "slow_threshold": 15},
    "vlm":       {"max_tokens": 512,  "temperature": 0.3, "slow_threshold": 15},
    "voice":     {"max_tokens": 1024, "temperature": 0.3, "slow_threshold": 12},
    "embedding": {"max_tokens": 1024, "temperature": 0.3, "slow_threshold": 5},
}


# ---------------------------------------------------------------------------
# Provider 契约
# ---------------------------------------------------------------------------

@dataclass
class ProviderBundle:
    """单次 provider build 的产出。

    Attributes:
        models_aot: 该 provider 本次希望写入 [[models]] 的 tomlkit aot。
        providers_aot: 该 provider 本次希望写入 [[api_providers]] 的 tomlkit aot。
        tier_mapping: ``{slot_name: [model_name, ...]}``；只包含本 provider 的模型。
            合并时会与 model_task_config 中"非本 provider 归属"的模型名合并，而不是覆盖。
        embedding_name: 本 provider 默认的 embedding 模型名；当 embedding 槽在当前
            config 里是空的时才会用到。没有可留空字符串。
        tier: tier 标签（"low"/"mid"/... 或 "template"/"none"），仅用于展示。
        is_managed_provider_name: 谓词 ``name -> bool``。本 provider 认为名字 ``name``
            归它管吗？例如 aliyun 归属 ``BaiLian`` 与 ``BaiLian-*``，
            deepseek 归属 ``DeepSeek``。合并时用来：
                - 判断一条 [[api_providers]] 是否属于本次；
                - 判断一条 [[models]] 的 ``api_provider`` 是否属于本次；
                - 判断一个 task slot 中的 model_list 项是否属于本次。
    """

    models_aot: Any
    providers_aot: Any
    tier_mapping: Dict[str, List[str]]
    embedding_name: str
    tier: str
    is_managed_provider_name: Callable[[str], bool]


# ---------------------------------------------------------------------------
# 基础 helper
# ---------------------------------------------------------------------------

def build_task_table(slot: str, model_names: List[str], *, selection_strategy: str = "random"):
    """构造单个 ``[model_task_config.<slot>]`` 表。"""

    from tomlkit import table

    t = table()
    t["model_list"] = list(model_names)
    params = TASK_PARAMS[slot]
    t["max_tokens"] = params["max_tokens"]
    t["temperature"] = params["temperature"]
    t["slow_threshold"] = params["slow_threshold"]
    t["selection_strategy"] = selection_strategy
    return t


def _backup_config() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"model_config.{stamp}.toml"
    shutil.copy2(CONFIG_PATH, backup)
    return backup


def extract_existing_api_keys() -> Dict[str, str]:
    """从现有 config/model_config.toml 里读出 ``{provider_name: api_key}``。"""

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


def _sanitize_task_names(desired: List[str], valid: Set[str]) -> Tuple[List[str], List[str]]:
    kept: List[str] = []
    dropped: List[str] = []
    for n in desired:
        if str(n) in valid:
            kept.append(str(n))
        else:
            dropped.append(str(n))
    return kept, dropped


# ---------------------------------------------------------------------------
# 合并 helper：把 bundle 的条目合并进 doc，保留其它 provider 条目
# ---------------------------------------------------------------------------

def _merge_api_providers(doc, new_providers_aot, is_managed: Callable[[str], bool]) -> None:
    """把 ``new_providers_aot`` 合并进 ``doc['api_providers']``。

    规则：
        - 现有 entry.name 不归本 provider 管 → 原样保留（保留 api_key）。
        - 现有 entry.name 归本 provider 管，且 new 里有同名 → 用 new 替换，
          并把现有 entry 的 api_key（非 placeholder）回填。
        - 现有 entry.name 归本 provider 管，但 new 里没有 → 视为已过时的归属条目，
          删除（例如 aliyun 以前有 us 区域，现在 response_us.json 已被删除）。
        - new 里出现但现有 doc 没有的 entry → 追加到末尾（api_key 仍会尝试回填）。
    """

    import tomlkit
    from tomlkit import aot

    existing = list(doc.get("api_providers") or [])
    existing_api_keys: Dict[str, str] = {}
    for entry in existing:
        n = str(entry.get("name", ""))
        k = str(entry.get("api_key", ""))
        if n and k and k != "<API_KEY_PLACEHOLDER>":
            existing_api_keys[n] = k

    new_by_name: Dict[str, Any] = {}
    new_order: List[str] = []
    for entry in new_providers_aot:
        n = str(entry.get("name", ""))
        if n and n not in new_by_name:
            new_by_name[n] = entry
            new_order.append(n)

    merged = aot()
    placed: Set[str] = set()
    for entry in existing:
        name = str(entry.get("name", ""))
        if is_managed(name):
            if name in new_by_name:
                new_entry = new_by_name[name]
                if name in existing_api_keys:
                    new_entry["api_key"] = existing_api_keys[name]
                merged.append(new_entry)
                placed.add(name)
            # else: 属于本 provider 但已从 bundle 中移除 → 丢弃
        else:
            # 非本 provider 归属 → 原样保留（含 api_key）
            merged.append(entry)

    for name in new_order:
        if name not in placed:
            new_entry = new_by_name[name]
            if name in existing_api_keys:
                new_entry["api_key"] = existing_api_keys[name]
            merged.append(new_entry)

    if "api_providers" in doc:
        del doc["api_providers"]
    doc["api_providers"] = merged


def _merge_models(doc, new_models_aot, is_managed_provider: Callable[[str], bool]) -> None:
    """把 ``new_models_aot`` 合并进 ``doc['models']``。

    规则：
        - 现有 entry.api_provider 不归本 provider 管 → 原样保留。
        - 现有 entry.api_provider 归本 provider 管：用 new 里同名条目替换；
          如果 new 没有同名 → 丢弃（过时条目）。
        - new 里出现但现有 doc 没有的 entry → 追加。
    """

    import tomlkit
    from tomlkit import aot

    existing = list(doc.get("models") or [])

    new_by_name: Dict[str, Any] = {}
    new_order: List[str] = []
    for entry in new_models_aot:
        n = str(entry.get("name", ""))
        if n and n not in new_by_name:
            new_by_name[n] = entry
            new_order.append(n)

    merged = aot()
    placed: Set[str] = set()
    for entry in existing:
        provider = str(entry.get("api_provider", ""))
        name = str(entry.get("name", ""))
        if is_managed_provider(provider):
            if name in new_by_name:
                merged.append(new_by_name[name])
                placed.add(name)
            # else: 过时的归属 model → 丢弃
        else:
            merged.append(entry)

    for name in new_order:
        if name not in placed:
            merged.append(new_by_name[name])

    if "models" in doc:
        del doc["models"]
    doc["models"] = merged


# ---------------------------------------------------------------------------
# 主 apply 入口
# ---------------------------------------------------------------------------

def apply_bundle_to_config(bundle: ProviderBundle, *, dry_run: bool) -> None:
    """把 ``bundle`` 合并进 ``config/model_config.toml``。

    合并规则简介（详见上方 helper）：
        - [[models]] / [[api_providers]]：按 ``is_managed_provider_name`` 识别归属，
          非本 provider 的条目保留不动。
        - model_task_config.<slot>.model_list：同一 slot 内保留"非本 provider
          归属"的 model_name，把 bundle.tier_mapping[slot] 的条目追加在后面（去重）。
        - api_key：从现有 config 的同名 provider 条目回填。
    """

    import tomlkit

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"找不到 {CONFIG_PATH}")

    current_text = CONFIG_PATH.read_text(encoding="utf-8")
    doc = tomlkit.loads(current_text)

    # 1) 合并 [[models]]
    _merge_models(doc, bundle.models_aot, bundle.is_managed_provider_name)

    # 2) 预计算 valid_names 和"本 run 归属的 model name"
    valid_names: Set[str] = set()
    managed_model_names: Set[str] = set()
    for entry in doc["models"]:
        n = str(entry.get("name", ""))
        if n:
            valid_names.add(n)
            if bundle.is_managed_provider_name(str(entry.get("api_provider", ""))):
                managed_model_names.add(n)

    # 3) model_task_config：按 slot 合并
    mtc = doc.get("model_task_config")
    if mtc is None:
        from tomlkit import table

        mtc = table()
        doc["model_task_config"] = mtc

    for slot in TASK_SLOTS:
        existing_list: List[str] = []
        if slot in mtc:
            raw = mtc[slot].get("model_list", [])
            existing_list = [str(x) for x in raw]

        # 保留"非本 provider"的 model 引用
        preserved = [n for n in existing_list if n not in managed_model_names]

        if slot in ("voice", "embedding"):
            # 语音 / embedding：本 provider 不主动提供，除非 bundle 明确写了
            bundle_slot = bundle.tier_mapping.get(slot, [])
            if bundle_slot:
                desired = bundle_slot
            elif slot == "embedding" and not preserved and bundle.embedding_name:
                desired = [bundle.embedding_name]
            else:
                desired = []
        else:
            desired = bundle.tier_mapping.get(slot, [])

        # 合并：现有非归属 + 新归属（去重 & 保序）
        seen: Set[str] = set()
        combined: List[str] = []
        for n in preserved + desired:
            if n and n not in seen:
                seen.add(n)
                combined.append(n)

        kept, dropped = _sanitize_task_names(combined, valid_names)
        if dropped:
            print(f"[apply] ⚠ {slot} 剔除失效引用: {dropped}")
        table_ = build_task_table(slot, kept)
        if slot in mtc:
            del mtc[slot]
        mtc[slot] = table_

    # 4) 合并 [[api_providers]]
    _merge_api_providers(doc, bundle.providers_aot, bundle.is_managed_provider_name)

    new_text = tomlkit.dumps(doc)

    if "<API_KEY_PLACEHOLDER>" in new_text:
        raise RuntimeError(
            "生成内容里仍有 <API_KEY_PLACEHOLDER>。"
            "请在 provider 配置里填写 api_key，或传 --api-key。"
        )

    # 汇报
    total_models = sum(1 for _ in doc["models"])
    managed_count = sum(
        1 for e in doc["models"]
        if bundle.is_managed_provider_name(str(e.get("api_provider", "")))
    )
    print(f"[apply] models 合并后 {total_models} 条（本次 provider 归属 {managed_count} 条）")
    for slot in TASK_SLOTS:
        mlist = list(doc["model_task_config"][slot].get("model_list", []))
        head = mlist[:8]
        suffix = "..." if len(mlist) > 8 else ""
        print(f"[apply] {slot:10} -> {len(mlist)} 候选: {head}{suffix}")

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
