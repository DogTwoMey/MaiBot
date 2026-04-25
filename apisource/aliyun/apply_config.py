#!/usr/bin/env python3
"""一键把某个档位的模型映射应用到 config/model_config.toml。

工作方式：
    1. 读取当前 `config/model_config.toml`
    2. 保留 [inner]、[[api_providers]]（含 api_key）、未识别的自定义段落
    3. 用 `output/models_registry.toml` 全量替换 [[models]] 数组
    4. 用 `tiers/<tier>.toml` 替换 6 个 [model_task_config.*] 段
    5. 写回 config/model_config.toml；先自动备份到 config/backup/

典型用法：
    python apply_config.py --tier mid
    python apply_config.py --tier high --refresh          # 先重跑 generate_model_config
    python apply_config.py --tier extreme --dry-run       # 只打印会做什么，不写

安全保证：
    - 永远先备份再写
    - 若生成产物里仍含 <API_KEY_PLACEHOLDER>，拒绝写入
    - 写入使用临时文件 + rename，失败不会破坏原文件
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent        # MaiBot repo 根
CONFIG_PATH = PROJECT_ROOT / "config" / "model_config.toml"
BACKUP_DIR = PROJECT_ROOT / "config" / "backup"
REGISTRY_PATH = SCRIPT_DIR / "output" / "models_registry.toml"
TIERS_DIR = SCRIPT_DIR / "tiers"
GENERATE_SCRIPT = SCRIPT_DIR / "generate_model_config.py"


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _ensure_tomlkit():
    try:
        import tomlkit  # noqa: F401
    except ImportError:
        print(
            "错误: 需要 tomlkit 来保留注释与格式。\n"
            "  pip install tomlkit\n"
            "（本项目 requirements 已包含，你也可以在项目 venv 里跑这个脚本。）"
        )
        sys.exit(1)


def _refresh_via_generator(tier: str | None) -> None:
    """调用 generate_model_config.py 刷新 registry + tier 预设。"""
    args = [sys.executable, str(GENERATE_SCRIPT)]
    if tier:
        args += ["--tier", tier]
    print(f"[refresh] 执行: {' '.join(args)}")
    r = subprocess.run(args, cwd=SCRIPT_DIR)
    if r.returncode != 0:
        print(f"错误: generator 退出码 {r.returncode}")
        sys.exit(r.returncode)


def _backup(config_path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"model_config.{stamp}.toml"
    shutil.copy2(config_path, backup)
    return backup


# ---------------------------------------------------------------------------
# 合并逻辑（基于 tomlkit 以保留注释）
# ---------------------------------------------------------------------------

TASK_SLOTS = ("replyer", "planner", "utils", "vlm", "voice", "embedding")

# 每个 task 槽的默认参数（若 tier 文件没指定则兜底）
_DEFAULT_TASK_PARAMS = {
    "replyer": {"max_tokens": 4096, "temperature": 1.0, "slow_threshold": 120},
    "planner": {"max_tokens": 8000, "temperature": 0.7, "slow_threshold": 12},
    "utils":   {"max_tokens": 4096, "temperature": 0.5, "slow_threshold": 15},
    "vlm":     {"max_tokens": 512,  "temperature": 0.3, "slow_threshold": 15},
    "voice":   {"max_tokens": 1024, "temperature": 0.3, "slow_threshold": 12},
    "embedding": {"max_tokens": 1024, "temperature": 0.3, "slow_threshold": 5},
}


def _load_registry_models() -> list[dict]:
    """读取 output/models_registry.toml，返回 [{code, name, price_in, ...}, ...]"""
    import tomlkit
    if not REGISTRY_PATH.exists():
        print(f"错误: 找不到 {REGISTRY_PATH}。请先运行 generate_model_config.py。")
        sys.exit(1)
    doc = tomlkit.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return list(doc.get("models", []))


def _load_tier(tier_name: str) -> dict[str, dict]:
    """返回 {task_name: {model_list, max_tokens, temperature, slow_threshold, ...}}。"""
    import tomlkit
    path = TIERS_DIR / f"{tier_name}.toml"
    if not path.exists():
        print(f"错误: 找不到 {path}。请先运行 generate_model_config.py 或带上 --refresh。")
        sys.exit(1)
    doc = tomlkit.loads(path.read_text(encoding="utf-8"))
    tier_table = doc.get("tier", {})
    return {slot: dict(tier_table.get(slot, {})) for slot in TASK_SLOTS}


def _find_embedding_name(registry_models: list[dict]) -> str:
    """从注册表里找一个合适的 embedding 模型名。"""
    for m in registry_models:
        if m.get("model_identifier", "") == "text-embedding-v4":
            return m["name"]
    for m in registry_models:
        if "embedding" in m.get("model_identifier", ""):
            return m["name"]
    return ""


def _build_models_array(registry_models: list[dict]):
    """构造 [[models]] 数组，每条带元信息注释。"""
    import tomlkit
    from tomlkit import aot, table, comment

    array = aot()
    for m in registry_models:
        t = table()
        # 依次写字段，顺序对 toml 无影响但对可读性有
        for key in ("model_identifier", "name", "api_provider", "price_in",
                    "price_out", "force_stream_mode", "temperature"):
            if key in m:
                t[key] = m[key]
        # 嵌套 extra_params
        if "extra_params" in m:
            extra = table()
            for ek, ev in m["extra_params"].items():
                extra[ek] = ev
            t["extra_params"] = extra
        else:
            t["extra_params"] = table()
        array.append(t)
    return array


def _build_task_table(slot: str, cfg: dict, fallback_list: list[str] | None = None):
    """构造单个 [model_task_config.<slot>] 表。"""
    from tomlkit import table
    t = table()
    model_list = list(cfg.get("model_list", []) or (fallback_list or []))
    t["model_list"] = model_list
    defaults = _DEFAULT_TASK_PARAMS[slot]
    t["max_tokens"] = int(cfg.get("max_tokens", defaults["max_tokens"]))
    t["temperature"] = float(cfg.get("temperature", defaults["temperature"]))
    t["slow_threshold"] = int(cfg.get("slow_threshold", defaults["slow_threshold"]))
    t["selection_strategy"] = str(cfg.get("selection_strategy", "random"))
    return t


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def apply_tier(tier_name: str, *, dry_run: bool) -> None:
    import tomlkit

    if not CONFIG_PATH.exists():
        print(f"错误: 找不到 {CONFIG_PATH}")
        sys.exit(1)

    # 1) 读当前 config（保留注释/顺序）
    current_text = CONFIG_PATH.read_text(encoding="utf-8")
    doc = tomlkit.loads(current_text)

    # 2) 读注册表 + tier
    registry_models = _load_registry_models()
    tier_cfg = _load_tier(tier_name)

    # 3) 安全检查：注册表与 tier 不能包含占位符（防误写）
    for m in registry_models:
        for v in m.values():
            if isinstance(v, str) and "API_KEY_PLACEHOLDER" in v:
                print("错误: registry 含占位符，拒绝写入")
                sys.exit(1)

    # 4) 替换 [[models]]
    new_models_aot = _build_models_array(registry_models)
    if "models" in doc:
        del doc["models"]
    doc["models"] = new_models_aot

    # 5) 替换 [model_task_config.*]
    # 确保 model_task_config 顶层存在
    mtc = doc.get("model_task_config")
    if mtc is None:
        from tomlkit import table as _tbl
        mtc = _tbl()
        doc["model_task_config"] = mtc

    embedding_name = _find_embedding_name(registry_models)
    embedding_fallback = [embedding_name] if embedding_name else []

    # 所有新 registry 里存在的模型 name
    valid_names: set[str] = {str(m.get("name", "")) for m in registry_models if m.get("name")}

    def _sanitize(names: list[str], fallback: list[str]) -> tuple[list[str], list[str]]:
        """过滤掉 registry 里不存在的模型名。返回 (保留的, 被剔除的)。"""
        kept, dropped = [], []
        for n in names:
            if str(n) in valid_names:
                kept.append(str(n))
            else:
                dropped.append(str(n))
        if not kept:
            kept = list(fallback)
        return kept, dropped

    for slot in TASK_SLOTS:
        # tier 文件只定义 replyer/planner/utils/vlm 四个槽；
        # voice 与 embedding 不在 tier 控制范围内：
        #   - 已有配置则原样保留（尊重用户手工设置），但要校验引用
        #   - 否则 embedding 写入默认；voice 写入空
        slot_cfg = tier_cfg.get(slot, {}) or {}
        if slot in ("voice", "embedding") and not slot_cfg.get("model_list"):
            if slot in mtc:
                # 保留用户已有配置，但校验 model_list 里每个引用
                existing_list = list(mtc[slot].get("model_list", []))
                fb = embedding_fallback if slot == "embedding" else []
                sanitized, dropped = _sanitize(existing_list, fb)
                if dropped:
                    print(f"[apply] ⚠ 保留 {slot} 时剔除失效引用: {dropped} -> 替换为 {sanitized}")
                # 就地更新 model_list（保留其它参数不变）
                mtc[slot]["model_list"] = sanitized
                continue
            # 没有现成配置：写入默认
            fallback = embedding_fallback if slot == "embedding" else []
            new_table = _build_task_table(slot, {}, fallback_list=fallback)
        else:
            # tier 定义的槽也校验一遍，防止手改 tier 文件引用不存在的 name
            desired = list(slot_cfg.get("model_list", []))
            sanitized, dropped = _sanitize(desired, [])
            if dropped:
                print(f"[apply] ⚠ tier={slot} 剔除失效引用: {dropped}")
            slot_cfg = {**slot_cfg, "model_list": sanitized}
            new_table = _build_task_table(slot, slot_cfg, fallback_list=None)
        if slot in mtc:
            del mtc[slot]
        mtc[slot] = new_table

    # 6) 生成新文本
    new_text = tomlkit.dumps(doc)

    # 7) 最终保护：防止 api_key 被意外替换
    import re
    current_key_match = re.search(r'api_key\s*=\s*"([^"]*)"', current_text)
    new_key_match = re.search(r'api_key\s*=\s*"([^"]*)"', new_text)
    if current_key_match and new_key_match:
        if current_key_match.group(1) != new_key_match.group(1):
            print("错误: 检测到 api_key 发生了变化，这很可能是 bug。已中止写入。")
            print(f"  current: {current_key_match.group(1)[:8]}...")
            print(f"  new:     {new_key_match.group(1)[:8]}...")
            sys.exit(1)
    if "<API_KEY_PLACEHOLDER>" in new_text:
        print("错误: 生成的配置里出现了 <API_KEY_PLACEHOLDER>，已中止写入。")
        sys.exit(1)

    # 8) 报告
    print(f"[apply] tier = {tier_name}")
    print(f"[apply] models: {len(registry_models)} 条 (将完整替换 [[models]] 数组)")
    for slot in TASK_SLOTS:
        mlist = list(doc["model_task_config"][slot].get("model_list", []))
        print(f"[apply] {slot:10} -> {len(mlist)} 个候选: {mlist}")

    if dry_run:
        print("\n[dry-run] 没有写入任何文件。")
        return

    # 9) 备份并写入
    backup_path = _backup(CONFIG_PATH)
    print(f"[apply] 已备份 -> {backup_path}")

    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".new")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    print(f"[apply] 已写入 {CONFIG_PATH}")
    print()
    print("下一步：重启 bot.py 让新配置生效。")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Apply an aliyun-tier preset to config/model_config.toml")
    parser.add_argument("--tier", choices=("low", "mid", "high", "extreme", "free"), help="应用的档位")
    parser.add_argument("--refresh", action="store_true",
                        help="应用前先重跑 generate_model_config.py（用最新 response.json / price.md 刷新 registry 与 tier 预设）")
    parser.add_argument("--regen-tiers", action="store_true",
                        help="刷新时覆盖已有的 tiers/*.toml（慎用：会抹掉你手改的档位预设）")
    parser.add_argument("--dry-run", action="store_true", help="打印变更但不写文件")
    args = parser.parse_args()

    _ensure_tomlkit()

    if args.refresh:
        gen_args = []
        if args.regen_tiers:
            gen_args.append("--regen-tiers")
        # 先刷新 registry + tier 预设
        print("[apply] 刷新 registry + tier 预设...")
        r = subprocess.run(
            [sys.executable, str(GENERATE_SCRIPT), *gen_args],
            cwd=SCRIPT_DIR,
        )
        if r.returncode != 0:
            print(f"错误: generator 退出码 {r.returncode}")
            return r.returncode

    if args.tier is None:
        print("提示: 没有指定 --tier；仅完成 refresh（如果带了 --refresh）。")
        return 0

    apply_tier(args.tier, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
