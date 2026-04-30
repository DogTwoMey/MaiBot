"""Backward-compat shim for pre-refactor plugins.

``src.config.api_ada_configs`` 是旧路径；重构后这些类都迁到
:mod:`src.config.model_configs`。第三方插件仍然按旧路径 import，本 shim
负责无缝转发。

请不要在新代码里依赖本模块，直接用 :mod:`src.config.model_configs`。
"""

from __future__ import annotations

from src.config.model_configs import APIProvider, ModelInfo, TaskConfig

__all__ = ["APIProvider", "ModelInfo", "TaskConfig"]
