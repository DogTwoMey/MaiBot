#!/usr/bin/env python3
"""一次性把 ``[[models]]`` 缺失的三个新字段补齐。

MaiBot 在 2026 的一次 schema 升级里给每个模型加了 ``cache`` / ``cache_price_in`` /
``visual`` 三个字段（含默认值）。老 config 里没有写这三项时，每次启动都会被品鉴器
当成"新增配置项"打到日志里——387 个模型 × 3 个字段 = 日志被上千条同样的 info 灌爆。

另有 ``max_tokens: int | None``，因为 TOML 无法表达 null、迁移器又不会把 None 写回
文件，所以无法在配置里"补齐"它；那条路已经在 ``src/config/config_base.py`` 里
通过"default=None 的字段不算缺失"修掉了。

本脚本做的事（只改新增字段，绝不动已存在的值）：
    - 遍历 ``config/model_config.toml`` 里所有 ``[[models]]``
    - 给缺失 ``cache`` 的补 ``false``
    - 给缺失 ``cache_price_in`` 的补 ``0.0``
    - 给缺失 ``visual`` 的补 ``false``（如果原 name/model_identifier 明显是 VLM/多模态
      模型则补 ``true``，启发式匹配 ``-vl-`` / ``qwen3-vl`` / ``qwen2.5-vl`` /
      ``qvq`` / ``qwen-vl`` / ``vlm`` / ``-image-`` / ``-omni`` 等关键字）

执行前会在 ``config/backup/`` 里留一份备份。典型用法：

    .venv\\Scripts\\python.exe scripts\\backfill_model_fields.py
"""

from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "model_config.toml"
BACKUP_DIR = PROJECT_ROOT / "config" / "backup"


_VLM_HINTS = (
    "-vl-", "-vl", "vl-", "qwen-vl", "qwen2.5-vl", "qwen2-vl", "qwen3-vl",
    "qvq", "vlm", "-omni", "-audio", "-image", "vision", "claude-3",
)


def _guess_visual(model_identifier: str, name: str) -> bool:
    candidate = f"{model_identifier or ''}|{name or ''}".lower()
    return any(hint in candidate for hint in _VLM_HINTS)


def _backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = BACKUP_DIR / f"model_config.{stamp}.pre-backfill.toml"
    shutil.copy2(CONFIG_PATH, dst)
    return dst


def main() -> int:
    try:
        import tomlkit
    except ImportError:
        print("错误: 需要 tomlkit，请在 venv 里跑 pip install tomlkit")
        return 1

    if not CONFIG_PATH.exists():
        print(f"错误: 找不到 {CONFIG_PATH}")
        return 1

    doc = tomlkit.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    models = doc.get("models") or []

    total = len(models)
    added_cache = 0
    added_cache_price_in = 0
    added_visual = 0

    for entry in models:
        if "cache" not in entry:
            entry["cache"] = False
            added_cache += 1
        if "cache_price_in" not in entry:
            entry["cache_price_in"] = 0.0
            added_cache_price_in += 1
        if "visual" not in entry:
            entry["visual"] = _guess_visual(
                str(entry.get("model_identifier", "")),
                str(entry.get("name", "")),
            )
            added_visual += 1

    print(f"共扫描 [[models]] 条目 {total} 个")
    print(f"补齐 cache:          {added_cache}")
    print(f"补齐 cache_price_in: {added_cache_price_in}")
    print(f"补齐 visual:         {added_visual}")

    touched = added_cache + added_cache_price_in + added_visual
    if touched == 0:
        print("没有缺失字段，无需写回。")
        return 0

    backup = _backup()
    print(f"已备份原文件到 {backup}")

    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".new")
    tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    print(f"已写入 {CONFIG_PATH}")
    print("下一次启动应不再出现『配置文件中新增配置项: cache/cache_price_in/visual』日志。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
