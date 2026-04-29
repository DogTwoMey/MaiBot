"""Build NapCatQQ from source and assemble the runtime shell directory.

Upstream (NapCatQQ) is a pnpm workspace monorepo. The runnable shell = contents
of `packages/napcat-shell/dist/` + `packages/napcat-shell-loader/` (launcher bat,
NapCatWinBoot native, loadNapCat.js, qqnt.json).

Usage:
    python scripts/build_napcat.py                # build + assemble
    python scripts/build_napcat.py --clean        # wipe output first (keeps config/)
    python scripts/build_napcat.py --no-install   # skip pnpm install
    python scripts/build_napcat.py --dev          # use build:shell:dev
    python scripts/build_napcat.py --source external/napcat-src --output runtime/napcat
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SOURCE = REPO_ROOT / "external" / "napcat-src"
DEFAULT_OUTPUT = REPO_ROOT / "runtime" / "napcat"

# Subdirs in runtime/napcat that represent user state and must not be wiped.
PRESERVE_DIRS = ("config", "cache", "logs", "plugins")


def which(cmd: str) -> str | None:
    return shutil.which(cmd) or shutil.which(cmd + ".cmd") or shutil.which(cmd + ".exe")


def run(cmd: list[str], cwd: Path) -> None:
    print(f"[build_napcat] $ {' '.join(cmd)}  (cwd={cwd})")
    result = subprocess.run(cmd, cwd=cwd, shell=False)
    if result.returncode != 0:
        raise SystemExit(f"[build_napcat] command failed ({result.returncode}): {' '.join(cmd)}")


def ensure_source(source: Path) -> None:
    if not source.exists() or not (source / "package.json").exists():
        raise SystemExit(
            f"[build_napcat] source not found at {source}. "
            f"Run: git submodule update --init --recursive"
        )


def ensure_toolchain() -> tuple[str, str]:
    node = which("node")
    if not node:
        raise SystemExit("[build_napcat] `node` not found in PATH. Install Node.js >= 18.")
    pnpm = which("pnpm")
    if not pnpm:
        raise SystemExit("[build_napcat] `pnpm` not found. Install via `npm i -g pnpm` or corepack.")
    return node, pnpm


def backup_preserved(output: Path, backup: Path) -> list[str]:
    moved: list[str] = []
    if not output.exists():
        return moved
    backup.mkdir(parents=True, exist_ok=True)
    for name in PRESERVE_DIRS:
        src = output / name
        if src.exists():
            dst = backup / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(src), str(dst))
            moved.append(name)
    return moved


def restore_preserved(backup: Path, output: Path, names: list[str]) -> None:
    for name in names:
        src = backup / name
        if not src.exists():
            continue
        dst = output / name
        if dst.exists():
            # merge: user state wins
            shutil.rmtree(dst)
        shutil.move(str(src), str(dst))
    try:
        backup.rmdir()
    except OSError:
        pass


def clean_output(output: Path) -> None:
    if not output.exists():
        return
    for child in output.iterdir():
        if child.name in PRESERVE_DIRS:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if target.exists() and item.name in PRESERVE_DIRS:
                # never clobber user state dirs
                continue
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def assemble(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    shell_dist = source / "packages" / "napcat-shell" / "dist"
    loader = source / "packages" / "napcat-shell-loader"
    if not shell_dist.exists():
        raise SystemExit(f"[build_napcat] build artifact missing: {shell_dist}")
    if not loader.exists():
        raise SystemExit(f"[build_napcat] loader package missing: {loader}")
    print(f"[build_napcat] copy {shell_dist} -> {output}")
    copy_tree(shell_dist, output)
    print(f"[build_napcat] copy {loader} -> {output}")
    copy_tree(loader, output)


def install_runtime_deps(output: Path) -> None:
    """Install node runtime dependencies into output/node_modules.

    napcat.mjs imports `express`, `ws`, etc. at runtime — those are declared in
    the dist's package.json but not bundled by vite. Without this step, running
    the launcher bat fails with `ERR_MODULE_NOT_FOUND: Cannot find package 'express'`.
    """
    pkg_json = output / "package.json"
    if not pkg_json.exists():
        raise SystemExit(f"[build_napcat] {pkg_json} missing — assemble step broken?")
    # Prefer npm (produces a flat, standalone node_modules); fall back to pnpm.
    npm = which("npm")
    if npm:
        print(f"[build_napcat] installing runtime deps via npm in {output}...")
        run([npm, "install", "--omit=dev", "--no-audit", "--no-fund"], cwd=output)
        return
    pnpm = which("pnpm")
    if pnpm:
        print(f"[build_napcat] installing runtime deps via pnpm (shamefully-hoist) in {output}...")
        run([pnpm, "install", "--prod", "--shamefully-hoist",
             "--ignore-workspace", "--config.node-linker=hoisted"], cwd=output)
        return
    raise SystemExit("[build_napcat] neither npm nor pnpm found to install runtime node_modules")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build NapCatQQ shell from source.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                        help=f"NapCatQQ source dir (default: {DEFAULT_SOURCE.relative_to(REPO_ROOT)})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Runtime output dir (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})")
    parser.add_argument("--clean", action="store_true",
                        help="Wipe output (except config/cache/logs/plugins) before copy.")
    parser.add_argument("--no-install", action="store_true", help="Skip `pnpm install` in the source tree.")
    parser.add_argument("--no-runtime-deps", action="store_true",
                        help="Skip npm install of runtime deps in the output dir.")
    parser.add_argument("--dev", action="store_true", help="Use build:shell:dev instead of build:shell.")
    parser.add_argument("--build-cmd", type=str, default=None,
                        help="Override build command, e.g. 'pnpm run build:shell:config'.")
    args = parser.parse_args()

    source: Path = args.source.resolve()
    output: Path = args.output.resolve()

    ensure_source(source)
    _, pnpm = ensure_toolchain()

    if not args.no_install:
        run([pnpm, "install"], cwd=source)

    if args.build_cmd:
        build_cmd = args.build_cmd.split()
    elif args.dev:
        build_cmd = [pnpm, "run", "build:shell:dev"]
    else:
        build_cmd = [pnpm, "run", "build:shell"]
    run(build_cmd, cwd=source)

    backup = output.parent / (output.name + ".preserved")
    moved = backup_preserved(output, backup)
    try:
        if args.clean:
            clean_output(output)
        assemble(source, output)
    finally:
        restore_preserved(backup, output, moved)

    if not args.no_runtime_deps:
        install_runtime_deps(output)

    print(f"[build_napcat] done. Runtime assembled at {output}")
    if moved:
        print(f"[build_napcat] preserved: {', '.join(moved)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
