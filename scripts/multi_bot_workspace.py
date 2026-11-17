# ruff: noqa: E402
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Tuple
from uuid import uuid4

import argparse
import asyncio
import json
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "runtime/multi-bot-source"
WORKSPACE = ROOT / "runtime/multi-bot-workspace"
sys.path.insert(0, str(SOURCE))

import tomlkit

from src.common.process_lease import ProcessLease, instance_lock_path
from src.config.shared_models import merge_catalog, missing_references
from src.host.config_migration import plan_host_settings
from src.host.config_transaction import commit_config_files, recover_config_transaction, write_private
from src.host.control import control_request
from src.host.model_migration import plan_model_catalog
from src.host.registry import BotRecord, Registry
from src.host.retention_migration import plan_retention


# region Lifecycle
@contextmanager
def stopped_workspace(workspace: Path) -> Iterator[List[BotRecord]]:
    with ExitStack() as locks:
        locks.enter_context(ProcessLease(workspace / "host/run.lock"))
        bots = Registry(workspace).list_bots()
        for bot in bots:
            locks.enter_context(ProcessLease(instance_lock_path(bot.directory)))
        locks.enter_context(ProcessLease(workspace / "host/model-config.lock"))
        recover_config_transaction(workspace / "host")
        yield bots


def stop_workspace(workspace: Path) -> None:
    try:
        with stopped_workspace(workspace):
            print("Host and workers are stopped.")
            return
    except RuntimeError:
        asyncio.run(control_request(workspace, "shutdown"))
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            with stopped_workspace(workspace):
                print("Host and workers stopped gracefully.")
                return
        except RuntimeError:
            time.sleep(0.5)
    raise TimeoutError("Host or worker lease is still held after 90 seconds")
# endregion


# region Configuration transfer
def plan_sync(workspace: Path, bots: List[BotRecord], names: List[str], originals: Path) -> Tuple[Dict[Path, str], Dict[Path, bytes]]:
    unknown = set(names) - {bot.name for bot in bots}
    if unknown:
        raise ValueError(f"Unknown bots: {sorted(unknown)}")
    host_path = workspace / "host/config.toml"
    catalog_path = workspace / "host/model_catalog.toml"
    paths = [host_path, catalog_path]
    for bot in bots:
        paths.extend(bot.directory / "config" / name for name in ("bot_config.toml", "model_config.toml"))
    documents = {path: tomlkit.parse(path.read_bytes().decode("utf-8")) for path in paths}
    copies, inputs = {}, {}
    for bot in bots:
        if bot.name not in names:
            continue
        original = originals / bot.name
        if not original.is_dir():
            raise ValueError(f"Config source directory does not exist: {original}")
        pairs = [(original / "config" / name, bot.directory / "config" / name)
                 for name in ("bot_config.toml", "model_config.toml")]
        for source in (original / "data/custom_prompts").rglob("*"):
            if source.is_file():
                pairs.append((source, bot.directory / source.relative_to(original)))
        for source in (original / "plugins").glob("*/config.toml"):
            plugin = bot.directory / "plugins" / source.parent.name
            if not plugin.is_dir():
                raise ValueError(f"Plugin code must be installed before copying its config: {plugin}")
            pairs.append((source, plugin / "config.toml"))
        for source in (original / "src/plugins/built_in").glob("*/config.toml"):
            pairs.append((source, bot.directory / "config/builtin_plugins" / source.parent.name / "config.toml"))
        for source, target in pairs:
            content = source.read_bytes()
            inputs[source] = content
            text = content.decode("utf-8")
            if target in documents:
                documents[target] = tomlkit.parse(text.lstrip("\ufeff"))
            else:
                if target.suffix == ".toml":
                    tomlkit.parse(text.lstrip("\ufeff"))
                copies[target] = text
    local_bots = {path: doc for path, doc in documents.items() if path.name == "bot_config.toml"}
    plan_host_settings(host_path, documents[host_path], local_bots)
    plan_retention(documents[host_path], local_bots)
    plan_model_catalog(documents[catalog_path], bots, documents)
    for bot in bots:
        errors = missing_references(merge_catalog(documents[bot.directory / "config/model_config.toml"], documents[catalog_path]))
        if errors:
            raise ValueError(f"Missing model references for {bot.name}: {sorted(errors)}")
    copies.update({path: tomlkit.dumps(doc) for path, doc in documents.items()})
    changes = {path: text for path, text in copies.items()
               if not path.exists() or path.read_bytes() != text.encode("utf-8")}
    return changes, inputs


def save_changes(workspace: Path, changes: Dict[Path, str]) -> Path | None:
    if not changes:
        return None
    backup = workspace / "host/backups" / ("config-sync-" + uuid4().hex)
    manifest = {}
    for path in changes:
        if not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError(f"Config target escapes workspace: {path}")
        relative = path.relative_to(workspace).as_posix()
        manifest[relative] = path.read_bytes().decode("utf-8") if path.exists() else None
    write_private(backup / "originals.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    commit_config_files(workspace / "host", changes)
    for path, text in changes.items():
        if path.read_bytes() != text.encode("utf-8"):
            raise RuntimeError(f"Read-back mismatch: {path}; backup: {backup}")
    return backup


def sync_config(workspace: Path, names: List[str], apply: bool, originals: Path) -> None:
    with stopped_workspace(workspace) as bots:
        changes, inputs = plan_sync(workspace, bots, names, originals.resolve(strict=True))
        if any(source.read_bytes() != content for source, content in inputs.items()):
            raise RuntimeError("Source changed during planning; retry after saving all config edits")
        backup = save_changes(workspace, changes) if apply else None
        print(json.dumps({"apply": apply, "bots": names, "changed_files": len(changes),
                          "backup": str(backup) if backup else None}, ensure_ascii=False))


def restore_config(workspace: Path, backup: Path) -> None:
    with stopped_workspace(workspace) as bots:
        backup = backup.resolve()
        if not backup.is_relative_to(workspace / "host/backups"):
            raise ValueError("Backup must be inside this workspace's host/backups directory")
        manifest = json.loads((backup / "originals.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not all(isinstance(key, str) for key in manifest):
            raise ValueError("Backup manifest must map relative paths to original contents")
        allowed = [workspace / "host/config.toml", workspace / "host/model_catalog.toml"]
        allowed.extend(bot.directory / "config" / name for bot in bots for name in ("bot_config.toml", "model_config.toml"))
        prompt_roots = [bot.directory / "data/custom_prompts" for bot in bots]
        plugin_roots = [bot.directory / folder for bot in bots for folder in ("plugins", "config/builtin_plugins")]
        changes = {}
        for relative, original in manifest.items():
            path = (workspace / relative).resolve()
            is_prompt = any(path.is_relative_to(root) for root in prompt_roots)
            is_plugin_config = path.name == "config.toml" and path.parent.parent in plugin_roots
            if path not in allowed and not is_prompt and not is_plugin_config:
                raise ValueError(f"Backup target is outside config directories: {path}")
            if original is not None and not isinstance(original, str):
                raise ValueError("Invalid backup content")
            changes[str(path)] = original
        current = {str(Path(path).relative_to(workspace)): Path(path).read_bytes().decode("utf-8")
                   if Path(path).exists() else None for path in changes}
        reverse = workspace / "host/backups" / ("config-sync-" + uuid4().hex)
        write_private(reverse / "originals.json", json.dumps(current, ensure_ascii=False, indent=2))
        write_private(workspace / "host/model-config-transaction.json", json.dumps(changes, ensure_ascii=False))
        recover_config_transaction(workspace / "host")
        print(json.dumps({"restored_files": len(changes), "backup": str(reverse)}))
# endregion


# region Command line
def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stop")
    sync = commands.add_parser("sync-config")
    sync.add_argument("--bot", action="append", choices=("MaiBot", "MaiBot2"))
    sync.add_argument("--apply", action="store_true")
    sync.add_argument("--originals", type=Path, required=True)
    restore = commands.add_parser("restore-config")
    restore.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "stop":
        stop_workspace(WORKSPACE)
    elif args.command == "sync-config":
        sync_config(WORKSPACE, args.bot or ["MaiBot2"], args.apply, args.originals)
    else:
        restore_config(WORKSPACE, args.backup)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, TimeoutError) as error:
        print(f"[multi-bot] {error}", file=sys.stderr)
        raise SystemExit(1) from None
# endregion
