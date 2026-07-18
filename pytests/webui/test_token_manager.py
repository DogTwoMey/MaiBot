from pathlib import Path

import json

from src.webui.core.security import TOKEN_SOURCE_TEMPORARY, TokenManager


def _write_webui_config(config_path: Path, access_token: str, *, include_token_source: bool = True) -> None:
    config = {
        "access_token": access_token,
        "created_at": "2026-06-29T00:00:00",
        "updated_at": "2026-06-29T00:00:00",
        "first_setup_completed": True,
        "setup_completed_at": "2026-06-29T00:00:00",
    }
    if include_token_source:
        config["token_source"] = TOKEN_SOURCE_TEMPORARY
    config_path.write_text(json.dumps(config), encoding="utf-8")


def test_temporary_token_persists_across_token_manager_reinitialization(tmp_path: Path) -> None:
    config_path = tmp_path / "webui.json"
    existing_token = "a" * 64
    _write_webui_config(config_path, existing_token)

    first_manager = TokenManager(config_path)
    second_manager = TokenManager(config_path)

    assert first_manager.get_token() == existing_token
    assert second_manager.get_token() == existing_token
    assert second_manager.get_token_source() == TOKEN_SOURCE_TEMPORARY
    assert second_manager.should_show_startup_token()


def test_legacy_hex_token_is_marked_temporary_without_rotation(tmp_path: Path) -> None:
    config_path = tmp_path / "webui.json"
    existing_token = "b" * 64
    _write_webui_config(config_path, existing_token, include_token_source=False)

    manager = TokenManager(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert manager.get_token() == existing_token
    assert config["access_token"] == existing_token
    assert config["token_source"] == TOKEN_SOURCE_TEMPORARY
