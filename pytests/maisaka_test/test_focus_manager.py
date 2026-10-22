from types import SimpleNamespace

import pytest

from src.config.config import global_config
from src.maisaka.focus.manager import FocusModeManager, chat_manager


def test_focus_scope_requires_existing_session(monkeypatch):
    monkeypatch.setattr(chat_manager, "get_session_by_session_id", lambda _: None)
    with pytest.raises(ValueError, match="聊天流不存在"):
        FocusModeManager().get_focus_scope_key("missing")


def test_focus_default_group_uses_real_session(monkeypatch):
    monkeypatch.setattr(chat_manager, "get_session_by_session_id", lambda _: SimpleNamespace(is_group_session=True))
    monkeypatch.setattr(global_config.experimental, "focus_groups", [])
    assert FocusModeManager().get_focus_scope_key("existing-session") == "global"


def test_focus_private_chat_respects_configuration(monkeypatch):
    monkeypatch.setattr(global_config.experimental, "focus_mode", True)
    monkeypatch.setattr(global_config.experimental, "focus_on_private", False)
    manager = FocusModeManager()
    assert manager.is_enabled_for_chat(is_group_chat=True)
    assert not manager.is_enabled_for_chat(is_group_chat=False)
