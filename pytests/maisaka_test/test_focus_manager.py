from src.config.config import global_config
from src.maisaka.focus.manager import FOCUS_GLOBAL_SCOPE_KEY, focus_mode_manager


def _clear_focus_state() -> None:
    focus_mode_manager._focused_session_ids_by_scope.clear()
    focus_mode_manager._next_focus_blocked_session_id_by_scope.clear()
    focus_mode_manager._last_cycle_at_by_session_id.clear()
    focus_mode_manager._last_read_at_by_session_id.clear()


def test_force_enter_focus_overrides_next_entry_block(monkeypatch) -> None:
    monkeypatch.setattr(global_config.experimental, "focus_mode", True)
    monkeypatch.setattr(global_config.experimental, "focus_on_private", False)
    monkeypatch.setattr(global_config.experimental, "focus_chat_whitelist", [])
    monkeypatch.setattr(global_config.experimental, "focus_groups", [])
    _clear_focus_state()

    focus_mode_manager._next_focus_blocked_session_id_by_scope[FOCUS_GLOBAL_SCOPE_KEY] = "qq_group_1"

    assert focus_mode_manager.try_enter_focus("qq_group_1", is_group_chat=True) is False
    assert focus_mode_manager.force_enter_focus("qq_group_1", is_group_chat=True) is True
    assert focus_mode_manager.can_decide("qq_group_1", is_group_chat=True) is True
    assert focus_mode_manager._next_focus_blocked_session_id_by_scope == {}

    _clear_focus_state()
