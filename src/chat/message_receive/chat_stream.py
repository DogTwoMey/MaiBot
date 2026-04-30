"""Backward-compat shim for pre-refactor plugins.

MaiBot 的聊天会话层重构后，``ChatStream`` 类被 ``BotChatSession`` 取代，
``get_chat_manager()`` 函数被替换为 ``chat_manager`` 模块级单例。

外部插件（如 A_memorix / prompt_injection_guard / impression_affection 等）
原来通过 ``from src.chat.message_receive.chat_stream import ...`` 引用这些符号。
本模块保留旧路径，把它们重定向到新位置——不修改插件源码也能继续工作。

请不要在新代码里依赖本模块：直接用 :mod:`src.chat.message_receive.chat_manager`。
"""

from __future__ import annotations

from src.chat.message_receive.chat_manager import (
    BotChatSession as ChatStream,
    ChatManager,
    chat_manager,
)


def get_chat_manager() -> ChatManager:
    """返回全局 ``chat_manager`` 单例（兼容旧调用）。"""

    return chat_manager


__all__ = ["ChatStream", "ChatManager", "chat_manager", "get_chat_manager"]
