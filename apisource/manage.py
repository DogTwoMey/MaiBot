#!/usr/bin/env python3
"""apisource 多 provider 管理入口。

通过 ``--provider <name>`` 把请求分派给 ``apisource/<name>/provider.py``。
目前支持：
    - all       → **推荐** 一次性配置全部 provider（DeepSeek + Aliyun + DZMM）
    - aliyun    → 阿里云百炼（多模态：VLM / Voice / Embedding）
    - deepseek  → DeepSeek 官方（对话：replyer / planner / utils）
    - dzmm      → 大嘴猫猫（补充 replyer）

典型用法::

    # 推荐：统一配置所有 provider 到 high 档
    python apisource/manage.py --provider all --tier high --apply

    # 预览 high 档改动
    python apisource/manage.py --provider all --tier high --apply --dry-run

    # 单独配置某个 provider
    python apisource/manage.py --provider deepseek --tier high --apply

档位说明（--provider all）：
    low   → DeepSeek flash + Aliyun low + DZMM replyer
    mid   → DeepSeek flash-think + Aliyun low + DZMM replyer
    high  → DeepSeek pro-nonthink + Aliyun high + DZMM replyer
    ultra → DeepSeek pro-think + Aliyun high + DZMM replyer

    多模态档位映射：low/mid 用 Aliyun low，high/ultra 用 Aliyun high。

合并语义（重要）：
    - ``[[api_providers]]`` / ``[[models]]``：按 provider 归属合并，**不覆盖**其它
      provider 的条目。
    - ``model_task_config``（各功能位 replyer/planner/utils/...）：**独占替换**。
    - 使用 ``--provider all`` 时，所有槽位由复合 bundle 统一写入，
      replyer 包含 DeepSeek + DZMM 模型，多模态槽位由 Aliyun 覆盖。
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import sys
from pathlib import Path
from typing import List


SCRIPT_DIR = Path(__file__).resolve().parent

# 让 provider 模块可以 ``import _common``
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import _common  # noqa: E402
from _common import ProviderBundle  # noqa: E402


# 多模态档位映射：主 tier → Aliyun 用的 tier
_MULTIMODAL_TIER_MAP = {
    "low": "low",
    "mid": "low",
    "high": "high",
    "ultra": "high",
}


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


def _build_composite_bundle(args, providers: List[str]) -> ProviderBundle:
    """加载所有 provider 并构建复合 bundle。

    - DeepSeek：使用请求的 tier，负责 replyer / planner / utils
    - Aliyun：根据 _MULTIMODAL_TIER_MAP 映射 tier，负责 vlm / voice / embedding
    - DZMM：所有档位均追加 replyer 候选
    """
    from tomlkit import aot

    tier = args.tier
    all_models = aot()
    all_providers = aot()
    combined_mapping = {slot: [] for slot in _common.TASK_SLOTS}
    managed_predicates = []
    embedding_name = ""

    for pname in providers:
        provider_args = copy.copy(args)
        if pname == "aliyun":
            provider_args.tier = _MULTIMODAL_TIER_MAP.get(tier, tier)
        print(f"\n--- {pname} (tier={provider_args.tier}) ---")
        module = _load_provider_module(pname)
        bundle = module.build(provider_args, apisource_dir=SCRIPT_DIR)

        for m in bundle.models_aot:
            all_models.append(m)
        for p in bundle.providers_aot:
            all_providers.append(p)

        # 合并 tier_mapping：各 provider 的模型追加到对应槽位
        for slot, models in bundle.tier_mapping.items():
            combined_mapping[slot].extend(models)

        managed_predicates.append(bundle.is_managed_provider_name)
        if bundle.embedding_name:
            embedding_name = bundle.embedding_name

    def is_managed(name: str) -> bool:
        return any(pred(name) for pred in managed_predicates)

    # 去重（保留顺序）
    for slot in combined_mapping:
        seen = set()
        deduped = []
        for n in combined_mapping[slot]:
            if n not in seen:
                seen.add(n)
                deduped.append(n)
        combined_mapping[slot] = deduped

    print(f"\n=== 复合 bundle（tier={tier}）===")
    for slot, lst in combined_mapping.items():
        if lst:
            print(f"  {slot:10} -> {lst}")

    return ProviderBundle(
        models_aot=all_models,
        providers_aot=all_providers,
        tier_mapping=combined_mapping,
        embedding_name=embedding_name,
        tier=tier,
        is_managed_provider_name=is_managed,
    )


def main() -> int:
    providers = _discover_providers()
    if not providers:
        print(f"错误: {SCRIPT_DIR} 下没有找到任何 provider 子目录 (需包含 provider.py)")
        return 1

    provider_choices = ["all"] + providers

    parser = argparse.ArgumentParser(
        description="apisource 多 provider 管理入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=provider_choices,
        help=f"服务提供商: {provider_choices}（推荐 all）",
    )
    parser.add_argument(
        "--tier",
        choices=("low", "mid", "high", "ultra", "free"),
        help="档位预设（low/mid/high/ultra）",
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
    parser.add_argument(
        "--regions-file",
        default=None,
        help="[aliyun] 区域覆盖配置；默认 apisource/aliyun/regions.toml",
    )
    args = parser.parse_args()

    if args.provider == "all" and not args.tier:
        parser.error("--provider all 必须指定 --tier（low/mid/high/ultra）")

    if args.provider == "all" and args.tier == "free":
        parser.error("--provider all 不支持 free 档位；free 仅适用于单个 provider")

    _ensure_tomlkit()

    if args.provider == "all":
        print(f"== 统一配置（tier={args.tier}）==")
        bundle = _build_composite_bundle(args, providers)
    else:
        print(f"== provider: {args.provider} ==")
        module = _load_provider_module(args.provider)
        bundle = module.build(args, apisource_dir=SCRIPT_DIR)

    if args.apply or args.dry_run:
        _common.apply_bundle_to_config(bundle, dry_run=args.dry_run)
    else:
        print("未传 --apply / --dry-run；只运行了 provider.build。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
