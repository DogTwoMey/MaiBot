"""Backward-compat shim for pre-refactor plugins.

``src.common.data_models.database_data_model.DatabaseMessages`` 是旧路径；
重构后 MaiBot 的消息存取统一走 :class:`SessionMessage`
（定义在 :mod:`src.chat.message_receive.message`，即 ``find_messages`` 等仓储
函数的返回元素类型）。

这个 shim 把 ``DatabaseMessages`` 别名到 ``SessionMessage``，让 pre-1.0 的第三方
插件（如 HyperSharkawa_maibot-character-sketch-plugin）不改源码即可加载。

新代码请直接使用 :class:`SessionMessage`。
"""

from __future__ import annotations

from src.chat.message_receive.message import SessionMessage as DatabaseMessages

__all__ = ["DatabaseMessages"]
