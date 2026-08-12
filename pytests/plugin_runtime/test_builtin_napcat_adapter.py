from pathlib import Path

from src.plugin_runtime.integration import PluginRuntimeManager


def test_napcat_adapter_is_distributed_as_builtin_plugin() -> None:
    builtin_root = Path("src/plugins/built_in").resolve()

    adapter_plugin_ids = PluginRuntimeManager._discover_plugin_ids_by_type([builtin_root], "adapter")

    assert "maibot-team.napcat-adapter" in adapter_plugin_ids
