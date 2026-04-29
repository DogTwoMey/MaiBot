"""Post-clone bootstrap for MaiBot unified workspace.

After `git clone --recurse-submodules` (or a plain clone), run this once to:
  1. Ensure submodules are initialized & fetched.
  2. Add the `upstream` remote to each submodule (only if missing).
  3. Run `uv sync` in the main repo and in each Python submodule (adapter).
  4. Copy launcher.toml.example -> launcher.toml if missing.

Usage (first-time clone may not yet have a .venv; uv creates it on demand):
    uv run python scripts/bootstrap.py
    uv run python scripts/bootstrap.py --build-napcat   # also build NapCat shell

Idempotent: safe to re-run.
"""

from __future__ import annotations

import argparse
import configparser
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# submodule path -> upstream URL (kept here because `.gitmodules` only stores origin)
UPSTREAMS: dict[str, str] = {
    "external/adapter":     "git@github.com:Mai-with-u/MaiBot-Napcat-Adapter.git",
    "external/napcat-src":  "git@github.com:NapNeko/NapCatQQ.git",
}

# submodules that are Python projects and need `uv sync`
PYTHON_SUBMODULES = ("external/adapter",)


def run(cmd: list[str], cwd: Path, check: bool = True) -> int:
    print(f"[bootstrap] $ (cd {cwd.relative_to(REPO_ROOT) if cwd != REPO_ROOT else '.'}) {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check).returncode


def has_remote(repo: Path, name: str) -> bool:
    r = subprocess.run(["git", "remote"], cwd=repo, capture_output=True, text=True)
    return name in r.stdout.split()


def submodule_paths() -> list[str]:
    gm = REPO_ROOT / ".gitmodules"
    if not gm.exists():
        return []
    cp = configparser.ConfigParser()
    cp.read(gm, encoding="utf-8")
    return [cp.get(s, "path") for s in cp.sections() if s.startswith("submodule ") and cp.has_option(s, "path")]


def step_submodule_init() -> None:
    print("\n==> [1/4] git submodule update --init --recursive")
    run(["git", "submodule", "update", "--init", "--recursive"], cwd=REPO_ROOT)


def step_upstream_remotes() -> None:
    print("\n==> [2/4] configure upstream remotes on submodules")
    for rel in submodule_paths():
        sub = REPO_ROOT / rel
        if not (sub / ".git").exists():
            print(f"[bootstrap] skip {rel} (not initialized)")
            continue
        upstream_url = UPSTREAMS.get(rel)
        if not upstream_url:
            print(f"[bootstrap] {rel}: no upstream mapping defined — skip")
            continue
        if has_remote(sub, "upstream"):
            print(f"[bootstrap] {rel}: upstream already present — skip")
            continue
        run(["git", "remote", "add", "upstream", upstream_url], cwd=sub)
        run(["git", "fetch", "upstream"], cwd=sub, check=False)


def step_uv_sync() -> None:
    print("\n==> [3/4] uv sync (main + python submodules)")
    uv = shutil.which("uv") or shutil.which("uv.exe")
    if not uv:
        raise SystemExit("[bootstrap] `uv` not found in PATH. Install uv first: https://docs.astral.sh/uv/")
    run([uv, "sync"], cwd=REPO_ROOT)
    for rel in PYTHON_SUBMODULES:
        sub = REPO_ROOT / rel
        if not (sub / "pyproject.toml").exists():
            print(f"[bootstrap] {rel}: no pyproject.toml — skip uv sync")
            continue
        run([uv, "sync"], cwd=sub)


def step_launcher_toml() -> None:
    print("\n==> [4/4] initialize scripts/launcher.toml")
    example = REPO_ROOT / "scripts" / "launcher.toml.example"
    target = REPO_ROOT / "scripts" / "launcher.toml"
    if target.exists():
        print(f"[bootstrap] {target.relative_to(REPO_ROOT)} already exists — skip")
        return
    if not example.exists():
        print(f"[bootstrap] WARN: {example} missing — skip")
        return
    shutil.copyfile(example, target)
    print(f"[bootstrap] created {target.relative_to(REPO_ROOT)} from template")


def step_build_napcat() -> None:
    print("\n==> [extra] build NapCat shell")
    uv = shutil.which("uv") or shutil.which("uv.exe")
    if not uv:
        raise SystemExit("[bootstrap] uv missing for build step")
    run([uv, "run", "python", "scripts/build_napcat.py"], cwd=REPO_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-clone setup for MaiBot unified workspace.")
    parser.add_argument("--build-napcat", action="store_true",
                        help="Also run build_napcat.py to assemble runtime/napcat/ (requires node+pnpm)")
    parser.add_argument("--skip-sync", action="store_true", help="Skip uv sync steps")
    args = parser.parse_args()

    step_submodule_init()
    step_upstream_remotes()
    if not args.skip_sync:
        step_uv_sync()
    step_launcher_toml()
    if args.build_napcat:
        step_build_napcat()

    print("\n[bootstrap] done. Next: edit scripts/launcher.toml, then:")
    print("    uv run python scripts/launcher.py start")
    return 0


if __name__ == "__main__":
    sys.exit(main())
