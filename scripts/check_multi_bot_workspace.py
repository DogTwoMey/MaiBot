from pathlib import Path
from tempfile import TemporaryDirectory

import json
import shutil

import multi_bot_workspace as workspace


def check():
    with TemporaryDirectory(prefix="multi-bot-check-", dir=workspace.ROOT / "runtime") as directory:
        root = Path(directory)
        (root / "host").mkdir()
        for name in ("config.toml", "model_catalog.toml"):
            shutil.copy2(workspace.WORKSPACE / "host" / name, root / "host" / name)
        registry = workspace.Registry(root)
        registry.create()
        originals = root / "imports"
        for bot in workspace.Registry(workspace.WORKSPACE).list_bots():
            target = root / "bots" / bot.bot_id
            (target / "config").mkdir(parents=True)
            source = originals / bot.name
            (source / "config").mkdir(parents=True)
            for name in ("bot_config.toml", "model_config.toml"):
                shutil.copy2(bot.directory / "config" / name, target / "config" / name)
                shutil.copy2(bot.directory / "config" / name, source / "config" / name)
            for plugin in (bot.directory / "plugins").glob("*/config.toml"):
                (target / "plugins" / plugin.parent.name).mkdir(parents=True)
                destination = source / "plugins" / plugin.parent.name / "config.toml"
                destination.parent.mkdir(parents=True)
                shutil.copy2(plugin, destination)
            registry.add_bot(bot.name, target, owned=True, initialization="initialized", bot_id=bot.bot_id)
        try:
            with workspace.ProcessLease(root / "host/run.lock"):
                with workspace.stopped_workspace(root):
                    raise AssertionError("Held Host lease was accepted")
        except RuntimeError:
            pass
        with workspace.stopped_workspace(root) as bots:
            selected, _ = workspace.plan_sync(root, bots, ["MaiBot2"], originals)
            other = next(bot.directory for bot in bots if bot.name == "MaiBot")
            assert not any(path.is_relative_to(other) for path in selected)
            changes, sources = workspace.plan_sync(root, bots, ["MaiBot", "MaiBot2"], originals)
            before = {path: path.read_bytes() if path.exists() else None for path in changes}
            backup = workspace.save_changes(root, changes)
            assert backup is not None
            assert all(path.read_bytes() == text.encode("utf-8") for path, text in changes.items())
            again, _ = workspace.plan_sync(root, bots, ["MaiBot", "MaiBot2"], originals)
            assert not again, list(again)
            assert all(path.read_bytes() == content for path, content in sources.items())
        workspace.restore_config(root, backup)
        assert all((path.read_bytes() if path.exists() else None) == content for path, content in before.items())
        invalid = root / "host/backups/config-sync-invalid"
        invalid.mkdir()
        (invalid / "originals.json").write_text(json.dumps({"../../outside.toml": "bad"}), encoding="utf-8")
        try:
            workspace.restore_config(root, invalid)
            raise AssertionError("Out-of-workspace restore was accepted")
        except ValueError:
            pass
        print("PASS: running-host guard, bot scope, config sync, idempotence, source preservation, backup restore, restore boundary")


if __name__ == "__main__":
    check()
