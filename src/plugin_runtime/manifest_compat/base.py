"""版本迁移器的抽象基类与上下文。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional


class MigrationError(RuntimeError):
    """迁移过程出现不可恢复错误时抛出。"""


@dataclass
class MigrationContext:
    """迁移过程中供 migrator 使用的上下文。

    Attributes:
        plugin_dir: 当前 manifest 所在的插件目录，可选。migrator 可以据此
            读取 locale 文件、附加资源等，从而产出更准确的 v2 字段。
        warnings: migrator 对 **非致命** 差异（例如字段重命名、默认值填充）
            的提醒。调用方可以把这些 warning 打到日志里给插件作者或用户看。
        extras: 自由扩展的信息袋。未来若有 migrator 需要传递额外的上下文
            而又不希望频繁修改 ``MigrationContext`` 签名，可以塞进 ``extras``。
    """

    plugin_dir: Optional[Path] = None
    warnings: List[str] = field(default_factory=list)
    extras: Dict[str, Any] = field(default_factory=dict)

    def warn(self, message: str) -> None:
        """记录一条非致命提示。"""
        self.warnings.append(message)


class VersionMigrator(ABC):
    """把 ``input_version`` 结构的 manifest 转换为 ``output_version`` 结构。

    子类实现步骤：

        1. 在子类设置类属性 ``input_version`` 与 ``output_version``；
        2. 实现 :meth:`migrate`，**不得** 修改传入的 ``manifest``，
           应返回一个新的字典；
        3. 通过 :func:`register_migrator` 装饰器或
           ``default_registry.register(Migrator())`` 注册到默认链。
    """

    input_version: ClassVar[int]
    output_version: ClassVar[int]

    def applies_to(self, manifest: Dict[str, Any]) -> bool:
        """默认按 ``manifest_version`` 字段匹配。"""

        return int(manifest.get("manifest_version", 0)) == self.input_version

    @abstractmethod
    def migrate(self, manifest: Dict[str, Any], context: MigrationContext) -> Dict[str, Any]:
        """把 manifest 转换为下一版本的字典结构。

        子类实现必须满足：

        - 返回的字典 ``manifest_version`` 字段必须等于 ``self.output_version``；
        - 不修改传入的 ``manifest`` 对象；
        - 对无法转换的字段使用合理默认值，并通过 ``context.warn`` 记录。
        """

    # ------------------------------------------------------------------
    # 运行期便利方法
    # ------------------------------------------------------------------

    def __init_subclass__(cls, **kwargs: Any) -> None:  # noqa: D401
        super().__init_subclass__(**kwargs)
        # 强制子类显式声明版本号，避免误注册
        for attr in ("input_version", "output_version"):
            if not isinstance(getattr(cls, attr, None), int):
                raise TypeError(
                    f"{cls.__name__} 必须声明整型类属性 {attr}"
                )
        if cls.output_version <= cls.input_version:
            raise TypeError(
                f"{cls.__name__}: output_version ({cls.output_version}) "
                f"必须大于 input_version ({cls.input_version})"
            )


__all__ = [
    "MigrationContext",
    "MigrationError",
    "VersionMigrator",
]
