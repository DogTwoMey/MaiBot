"""迁移器注册表。

``MigratorRegistry`` 把多个 ``VersionMigrator`` 按 input→output 顺序串联起来，
从任意旧版本自动升级到当前最新协议版本。

典型用法：

    registry = MigratorRegistry()
    registry.register(V1ToV2Migrator())
    # 未来添加 V2ToV3Migrator 时，只需 register 一次；链条自动延伸
    normalized = registry.normalize(raw_manifest, context=ctx)
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from .base import MigrationContext, MigrationError, VersionMigrator


_M = TypeVar("_M", bound=VersionMigrator)


class MigratorRegistry:
    """管理从 v1、v2、…… 到最新版本的 migrator 链条。"""

    def __init__(self) -> None:
        # {input_version: migrator}
        self._migrators_by_input: Dict[int, VersionMigrator] = {}

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(self, migrator: VersionMigrator) -> None:
        """注册一个 migrator。

        Raises:
            ValueError: 同一 ``input_version`` 已存在注册项。
        """

        if migrator.input_version in self._migrators_by_input:
            existing = type(self._migrators_by_input[migrator.input_version]).__name__
            raise ValueError(
                f"已存在处理 v{migrator.input_version} 的 migrator: {existing}"
            )
        self._migrators_by_input[migrator.input_version] = migrator

    def unregister(self, input_version: int) -> None:
        """移除某个 migrator。主要用于测试。"""

        self._migrators_by_input.pop(input_version, None)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @property
    def latest_version(self) -> int:
        """当前链条最终会升级到的目标版本。"""

        if not self._migrators_by_input:
            # 没注册任何 migrator → 约定 v2 是当前最新
            return 2
        return max(m.output_version for m in self._migrators_by_input.values())

    def migrators(self) -> List[VersionMigrator]:
        """按 input_version 升序返回全部注册 migrator。"""

        return [self._migrators_by_input[k] for k in sorted(self._migrators_by_input)]

    # ------------------------------------------------------------------
    # 规范化
    # ------------------------------------------------------------------

    def normalize(
        self,
        manifest: Dict[str, Any],
        *,
        context: Optional[MigrationContext] = None,
    ) -> Dict[str, Any]:
        """把 manifest 升级到 :pyattr:`latest_version`。

        Args:
            manifest: 原始 manifest 字典（不被修改）。
            context: 迁移上下文；为 ``None`` 时会自动创建。

        Returns:
            dict: 深拷贝后升级到最新版本的字典。

        Raises:
            MigrationError: 如果从 ``manifest_version`` 到最新版本之间
                缺少必需的 migrator，无法组成完整链条。
        """

        ctx = context if context is not None else MigrationContext()

        # 已经是最新版本：直接深拷贝返回，避免调用方共享引用
        current_version = self._coerce_version(manifest.get("manifest_version"))
        target = self.latest_version
        if current_version >= target:
            return _deep_copy(manifest)

        working: Dict[str, Any] = _deep_copy(manifest)
        working["manifest_version"] = current_version  # 归一化类型

        while current_version < target:
            migrator = self._migrators_by_input.get(current_version)
            if migrator is None:
                raise MigrationError(
                    f"找不到把 manifest_version={current_version} 升级到 "
                    f"{current_version + 1} 的 migrator；请注册对应 migrator。"
                )
            working = migrator.migrate(working, ctx)
            new_version = int(working.get("manifest_version", migrator.output_version))
            if new_version != migrator.output_version:
                raise MigrationError(
                    f"{type(migrator).__name__} 产出的 manifest_version 应为 "
                    f"{migrator.output_version}，实际 {new_version}"
                )
            current_version = new_version

        return working

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_version(raw: Any) -> int:
        """尝试把 ``manifest_version`` 转为整型。不可转化则按 v1 处理。"""

        try:
            return int(raw)
        except (TypeError, ValueError):
            return 1


def _deep_copy(value: Any) -> Any:
    """仅针对 JSON 兼容类型做深拷贝（无递归对象或循环引用）。"""

    import copy
    return copy.deepcopy(value)


# ---------------------------------------------------------------------------
# 模块级单例 + 装饰器
# ---------------------------------------------------------------------------

default_registry = MigratorRegistry()


def register_migrator(cls: Type[_M]) -> Type[_M]:
    """装饰器：实例化 migrator 子类并注册到 :data:`default_registry`。

    用法::

        @register_migrator
        class MyMigrator(VersionMigrator):
            input_version = 3
            output_version = 4
            ...

    返回原类，以便 migrator 类仍能被显式引用。
    """

    default_registry.register(cls())
    return cls


__all__ = [
    "MigratorRegistry",
    "default_registry",
    "register_migrator",
]
