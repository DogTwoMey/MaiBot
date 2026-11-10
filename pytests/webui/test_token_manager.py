import json

from src.host.authentication import HostCredentials


def test_configured_password_survives_host_restart(tmp_path):
    path = tmp_path / "webui.json"
    first = HostCredentials(path)
    first.update("FixedPassword!123")
    first.complete_setup()
    second = HostCredentials(path)
    assert second.verify("FixedPassword!123")
    assert second.setup_status() == {
        "is_first_setup": False, "token_source": "configured", "requires_custom_token": False,
    }


def test_legacy_temporary_password_rotates_without_losing_setup_state(tmp_path):
    path = tmp_path / "webui.json"
    path.write_text(json.dumps({"access_token": "b" * 64, "first_setup_completed": True}))
    first = HostCredentials(path)
    second = HostCredentials(path)
    assert first.token != "b" * 64
    assert second.token != first.token
    assert second.token_source == "temporary"
    assert not second.setup_status()["is_first_setup"]
