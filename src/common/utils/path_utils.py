"""
项目路径相关工具。

DB 里的 `full_path` 字段统一按以下约定存取，避免跨机器/换目录时全部失效：

- 写入前调用 ``to_stored_path``：若路径落在 ``PROJECT_ROOT`` 之内，存项目相对路径（POSIX 分隔符）；否则存绝对路径（兼容外部资源）。
- 读取后调用 ``resolve_stored_path``：统一得到可用于文件系统操作的绝对 ``Path``。

旧数据（绝对路径）仍能被 ``resolve_stored_path`` 正确解析，所以无需立刻迁移也能继续运行。
"""

from pathlib import Path

# 向上四级到达项目根：src/common/utils/path_utils.py -> src/common/utils -> src/common -> src -> <root>
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]


def to_stored_path(path: str | Path) -> str:
    """把绝对路径规范化为可写入 DB 的字符串。

    Args:
        path: 绝对或相对的文件路径。

    Returns:
        POSIX 风格的相对路径（若该路径位于项目根之内），否则返回原始绝对路径字符串。
    """
    p = Path(path)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    else:
        p = p.resolve()
    try:
        rel = p.relative_to(PROJECT_ROOT)
        return rel.as_posix()
    except ValueError:
        return str(p)


def resolve_stored_path(value: str | Path | None) -> Path:
    """把 DB 中取出的路径字符串还原成绝对 ``Path``。

    Args:
        value: DB 字段值，可能是绝对路径或项目相对路径，允许 ``None``/空字符串。

    Returns:
        绝对 ``Path``。对于空值返回一个不存在的占位路径（调用方应照常处理“找不到文件”的分支）。
    """
    if not value:
        return PROJECT_ROOT / "__missing__"
    p = Path(value)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()
