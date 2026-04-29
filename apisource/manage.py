#!/usr/bin/env python3
"""apisource 多 provider 管理入口。

通过 ``--provider <name>`` 把请求分派给 ``apisource/<name>/provider.py``。
目前支持：
    - aliyun    → 阿里云百炼（分 5 档：low / mid / high / extreme / free）
    - deepseek  → DeepSeek 官方（基于模板，配 v4-flash / v4-pro 等）

典型用法::

    # 把 aliyun 的 free 档合并进 config/model_config.toml
    python apisource/manage.py --provider aliyun --tier free --apply

    # 预览改动（dry-run）
    python apisource/manage.py --provider aliyun --tier mid --apply --dry-run

    # 把 DeepSeek 模型加入配置，用同一个 api-key
    python apisource/manage.py --provider deepseek --apply --api-key sk-xxxx

    # 只生成 provider 自己的产物到 provider 目录下的 output/
    python apisource/manage.py --provider aliyun --tier free

合并语义（重要）：
    - ``[[api_providers]]`` / ``[[models]]``：按 provider 归属合并，**不覆盖**其它
      provider 的条目。执行 ``--provider deepseek`` 不会删掉 Aliyun/OpenAI 等条目
      （含 api_key）。
    - ``model_task_config``（各功能位 replyer/planner/utils/...）：**独占替换**。
      本 provider 覆盖的 slot 的 model_list 会被完全替换为本 provider 的模型，
      绝不与其它 provider 混用 —— 确保切 provider 后该功能位只调本次指定的模型。
    - Provider 不覆盖的 slot（如 DeepSeek 不涉及 voice/embedding/vlm）：保留原配置
      不动，换 chat provider 不会误伤已配好的其它功能。
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import List


SCRIPT_DIR = Path(__file__).resolve().parent

# 让 provider 模块可以 ``import _common``
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import _common  # noqa: E402


def _discover_providers() -> List[str]:
    """扫描 apisource/ 下含 provider.py 的子目录。"""

    found: List[str] = []
    for p in sorted(SCRIPT_DIR.iterdir()):
        if p.is_dir() and (p / "provider.py").exists():
            found.append(p.name)
    return found


def _load_provider_module(name: str):
    provider_file = SCRIPT_DIR / name / "provider.py"
    if not provider_file.exists():
        raise FileNotFoundError(f"找不到 provider: {provider_file}")
    spec = importlib.util.spec_from_file_location(f"_apisource_{name}_provider", provider_file)
    assert spec and spec.loader, f"无法加载 {provider_file}"
    module = importlib.util.module_from_spec(spec)
    # 必须先注册到 sys.modules，否则模块内 @dataclass 无法通过 cls.__module__ 反查
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ensure_tomlkit() -> None:
    try:
        import tomlkit  # noqa: F401
    except ImportError:
        print(
            "错误: 需要 tomlkit。请用项目 venv 跑：\n"
            "  .venv\\Scripts\\python.exe apisource\\manage.py --provider <name>"
        )
        sys.exit(1)


def main() -> int:
    providers = _discover_providers()
    if not providers:
        print(f"错误: {SCRIPT_DIR} 下没有找到任何 provider 子目录 (需包含 provider.py)")
        return 1

    parser = argparse.ArgumentParser(
        description="apisource 多 provider 管理入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=providers,
        help=f"服务提供商: {providers}",
    )
    parser.add_argument(
        "--tier",
        choices=("low", "mid", "high", "extreme", "free"),
        help="档位预设（具体含义 provider 自定义；不传时走 provider 默认）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="把 provider 产出**合并**进 config/model_config.toml（保留其它 provider 条目）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="配合 --apply：打印变更但不落盘",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="provider 自身未提供 api_key 时使用的兜底值",
    )
    # provider-specific extras（透传给 provider.build）
    parser.add_argument(
        "--regions-file",
        default=None,
        help="[aliyun] 区域覆盖配置；默认 apisource/aliyun/regions.toml",
    )
    args = parser.parse_args()

    _ensure_tomlkit()

    print(f"== provider: {args.provider} ==")
    module = _load_provider_module(args.provider)
    bundle = module.build(args, apisource_dir=SCRIPT_DIR)

    if args.apply or args.dry_run:
        _common.apply_bundle_to_config(bundle, dry_run=args.dry_run)
    else:
        print("未传 --apply / --dry-run；只运行了 provider.build（如 provider 写了 output/ 产物，请去对应目录查看）。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
