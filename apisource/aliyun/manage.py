#!/usr/bin/env python3
"""[已弃用] apisource/aliyun/manage.py 向后兼容 shim。

此入口已统一到 ``apisource/manage.py`` + ``--provider`` 参数。原命令::

    python apisource/aliyun/manage.py --tier free --apply

等价于新命令::

    python apisource/manage.py --provider aliyun --tier free --apply

此 shim 只做参数转接——收到老命令时自动补 ``--provider aliyun`` 并转发到新入口。
建议更新你的脚本 / 快捷方式。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_SHIM_DIR = Path(__file__).resolve().parent
_APISOURCE = _SHIM_DIR.parent
_NEW_ENTRY = _APISOURCE / "manage.py"


def _load_new_entry():
    if not _NEW_ENTRY.exists():
        raise FileNotFoundError(
            f"找不到新入口 {_NEW_ENTRY}。请检查 apisource/ 目录结构是否完整。"
        )
    spec = importlib.util.spec_from_file_location("_apisource_manage", _NEW_ENTRY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("[deprecated] apisource/aliyun/manage.py 已弃用，自动转发到 apisource/manage.py --provider aliyun ...")
    print()
    # 自动补 --provider aliyun（若用户未显式传）
    if "--provider" not in sys.argv:
        sys.argv.insert(1, "aliyun")
        sys.argv.insert(1, "--provider")
    mod = _load_new_entry()
    return mod.main()


if __name__ == "__main__":
    sys.exit(main())
