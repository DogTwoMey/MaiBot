from src.plugin_runtime.manifest_compat.base import MigrationContext
from src.plugin_runtime.manifest_compat.v1_to_v2 import V1ToV2Migrator


def test_v1_manifest_receives_legacy_adapter_snapshot_capability() -> None:
    context = MigrationContext()

    capabilities = V1ToV2Migrator._build_capabilities({}, context)

    assert capabilities == ["component.get_all_plugins"]


def test_v1_manifest_preserves_declared_capabilities_without_duplicates() -> None:
    context = MigrationContext()
    manifest = {"capabilities": ["send.text", "component.get_all_plugins"]}

    capabilities = V1ToV2Migrator._build_capabilities(manifest, context)

    assert capabilities == ["send.text", "component.get_all_plugins"]
