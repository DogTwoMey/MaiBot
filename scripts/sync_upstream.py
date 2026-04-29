"""Batch-sync all submodules from their `upstream` remote to `origin`.

For each submodule listed in .gitmodules:
  1. git fetch upstream
  2. show diff origin..upstream
  3. (with --apply) merge or rebase upstream/<default_branch>, then push origin

Main repo itself is also synced (the outer MaiBot repo) unless --skip-main.

Usage:
    python scripts/sync_upstream.py                         # dry-run: just show diffs
    python scripts/sync_upstream.py --apply                 # merge + push all
    python scripts/sync_upstream.py --apply --rebase        # rebase instead of merge
    python scripts/sync_upstream.py --only adapter          # single submodule
    python scripts/sync_upstream.py --apply --skip-main     # submodules only
"""

from __future__ import annotations

import argparse
import configparser
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    print(f"[sync] $ (cd {cwd.relative_to(REPO_ROOT) if cwd != REPO_ROOT else '.'}) {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check,
                          text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)


def has_remote(repo: Path, name: str) -> bool:
    r = subprocess.run(["git", "remote"], cwd=repo, capture_output=True, text=True)
    return name in r.stdout.split()


def default_branch(repo: Path, remote: str) -> str:
    # Try `git symbolic-ref refs/remotes/<remote>/HEAD`; fall back to main/master.
    r = subprocess.run(["git", "symbolic-ref", f"refs/remotes/{remote}/HEAD"],
                       cwd=repo, capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().rsplit("/", 1)[-1]
    for candidate in ("main", "master", "dev"):
        rr = subprocess.run(["git", "show-ref", "--verify", f"refs/remotes/{remote}/{candidate}"],
                            cwd=repo, capture_output=True, text=True)
        if rr.returncode == 0:
            return candidate
    raise SystemExit(f"[sync] cannot determine default branch of {remote} in {repo}")


def current_branch(repo: Path) -> str:
    r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                       cwd=repo, capture_output=True, text=True, check=True)
    return r.stdout.strip()


def workdir_clean(repo: Path) -> bool:
    r = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True)
    return not r.stdout.strip()


def list_submodules(root: Path) -> list[tuple[str, Path]]:
    gm = root / ".gitmodules"
    if not gm.exists():
        return []
    parser = configparser.ConfigParser()
    parser.read(gm, encoding="utf-8")
    out: list[tuple[str, Path]] = []
    for section in parser.sections():
        if not section.startswith("submodule "):
            continue
        path = parser.get(section, "path", fallback=None)
        if not path:
            continue
        name = Path(path).name
        out.append((name, (root / path).resolve()))
    return out


def sync_one(repo: Path, label: str, apply: bool, rebase: bool) -> bool:
    print(f"\n=== [{label}] {repo} ===")
    if not has_remote(repo, "upstream"):
        print(f"[sync] {label}: no 'upstream' remote configured — skip")
        return True

    run(["git", "fetch", "upstream"], cwd=repo)
    branch = default_branch(repo, "upstream")
    up_ref = f"upstream/{branch}"

    # Show what's missing on origin relative to upstream.
    diff = subprocess.run(
        ["git", "log", "--oneline", f"origin/{branch}..{up_ref}"],
        cwd=repo, capture_output=True, text=True,
    )
    pending = diff.stdout.strip()
    if not pending:
        print(f"[sync] {label}: origin/{branch} already up to date with {up_ref}")
        return True
    print(f"[sync] {label}: commits on {up_ref} not in origin/{branch}:")
    print(pending)

    if not apply:
        print(f"[sync] {label}: dry-run — not applying. Re-run with --apply to merge & push.")
        return True

    if not workdir_clean(repo):
        print(f"[sync] {label}: working tree dirty — aborting (commit/stash first)")
        return False
    cur = current_branch(repo)
    if cur != branch:
        print(f"[sync] {label}: current branch '{cur}' != '{branch}'. Checkout '{branch}' first.")
        return False

    if rebase:
        run(["git", "rebase", up_ref], cwd=repo)
    else:
        run(["git", "merge", "--no-edit", up_ref], cwd=repo)
    run(["git", "push", "origin", branch], cwd=repo)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync all (submodule) repos from upstream.")
    parser.add_argument("--apply", action="store_true",
                        help="Actually merge & push (default is dry-run).")
    parser.add_argument("--rebase", action="store_true",
                        help="Use rebase instead of merge when --apply.")
    parser.add_argument("--only", type=str, default=None,
                        help="Only operate on named submodule (skip main).")
    parser.add_argument("--skip-main", action="store_true",
                        help="Skip the outer MaiBot repo.")
    args = parser.parse_args()

    ok = True
    if not args.only and not args.skip_main:
        ok &= sync_one(REPO_ROOT, "main", args.apply, args.rebase)

    for name, path in list_submodules(REPO_ROOT):
        if args.only and name != args.only:
            continue
        if not path.exists() or not (path / ".git").exists():
            print(f"[sync] submodule {name} not initialized at {path} — run `git submodule update --init`")
            ok = False
            continue
        ok &= sync_one(path, name, args.apply, args.rebase)

    if not args.apply:
        print("\n[sync] dry-run complete. Use --apply to merge and push.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
