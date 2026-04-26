"""插件 Manifest 版本兼容层。

用于在运行时把旧版本的 ``_manifest.json`` 透明升级到当前主程序支持的协议版本，
使老版本插件无需作者手动适配即可加载。用户在目标插件目录下看到的原始 manifest
文件保持不动，只在内存中完成转换。

典型用法：

    from src.plugin_runtime.manifest_compat import normalize_manifest, MigrationContext

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    context = MigrationContext(plugin_dir=manifest_path.parent)
    normalized = normalize_manifest(raw, context=context)
    for warning in context.warnings:
        logger.warning(warning)

    model = PluginManifest.model_validate(normalized)

扩展：后续需要支持 v2→v3 时，只需：

    1. 继承 ``VersionMigrator`` 实现 ``migrate``；
    2. 在模块 ``default_registry`` 上调用 ``register`` 或使用
       ``register_migrator`` 装饰器；
    3. 不需要改动任何调用方。
"""

from .base import MigrationContext, MigrationError, VersionMigrator
from .registry import MigratorRegistry, default_registry, register_migrator
# Side-effect imports: 注册内置 migrator
from . import v1_to_v2 as _v1_to_v2  # noqa: F401


def normalize_manifest(manifest, *, context=None):
    """把任意历史版本的 manifest 字典升级到当前最新协议版本。

    Args:
        manifest: 原始 manifest 字典（不会被修改，返回值是新对象）。
        context: 可选 ``MigrationContext``，用于收集 warnings 或向
            migrator 暴露插件目录。若为 ``None``，函数内部创建一个。

    Returns:
        dict: 规范化到最新版本的 manifest 字典副本。

    Raises:
        MigrationError: 无法找到将当前版本升级到目标版本的 migrator 链。
    """

    ctx = context if context is not None else MigrationContext()
    return default_registry.normalize(manifest, context=ctx)


__all__ = [
    "MigrationContext",
    "MigrationError",
    "MigratorRegistry",
    "VersionMigrator",
    "default_registry",
    "normalize_manifest",
    "register_migrator",
]
