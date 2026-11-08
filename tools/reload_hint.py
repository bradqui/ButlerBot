#!/usr/bin/env python3
"""
What to run in Discord after pulling new code: which of our cogs to unload, load or reload, new pip packages to
install, and whether slash commands need syncing.

Run it on the server, in the folder that holds data/, right after `git pull`:

    python3 tools/reload_hint.py             # what changed in the last pull (git's ORIG_HEAD)
    python3 tools/reload_hint.py 82dbef3     # what changed since a commit

It only reads git; it never touches the bot. Standard library only.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COGS = "data/cogs/CogManager/cogs/"
SHARED = COGS + "_shared/"
SLASH_MARKERS = ("app_commands", "ContextMenu", "slash_command")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def resolves(ref: str) -> bool:
    try:
        git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        return True
    except subprocess.CalledProcessError:
        return False


def cogs_at(ref: str) -> set:
    """Our cog packages at `ref`: folders under the cogs path that have an __init__.py."""
    names = git("ls-tree", "-r", "--name-only", ref, "--", COGS).splitlines()
    return {path[len(COGS):].split("/")[0] for path in names
            if path.startswith(COGS) and path.endswith("/__init__.py") and path.count("/") == len(COGS.split("/"))}


def requirements(ref: str, cog: str) -> set:
    try:
        info = json.loads(git("show", f"{ref}:{COGS}{cog}/info.json"))
    except (subprocess.CalledProcessError, ValueError):
        return set()
    return {str(r) for r in info.get("requirements") or []}


def touches_slash(diff: str) -> bool:
    """Whether a diff adds or removes slash-command code (so `[p]slash sync` is needed)."""
    for line in diff.splitlines():
        if line.startswith(("+++", "---")) or not line.startswith(("+", "-")):
            continue
        if any(marker in line for marker in SLASH_MARKERS):
            return True
    return False


def plan(since: str) -> list:
    """The steps to run, in order, as (command, why) pairs."""
    changed = [p for p in git("diff", "--name-only", since, "HEAD").splitlines() if p]
    before, after = cogs_at(since), cogs_at("HEAD")
    removed, added = sorted(before - after), sorted(after - before)
    touched = {p[len(COGS):].split("/")[0] for p in changed if p.startswith(COGS) and not p.startswith(SHARED)}
    reload = sorted((after & before) if any(p.startswith(SHARED) for p in changed) else (touched & before & after))
    steps = []
    for cog in removed:
        steps.append((f"!unload {cog}", "this cog was removed; unload it before loading anything new"))
    packages = sorted({pkg for cog in after for pkg in requirements("HEAD", cog) - requirements(since, cog)})
    for pkg in packages:
        steps.append((f"!pipinstall {pkg}", "a new requirement"))
    if added:
        steps.append((f"!load {' '.join(added)}", "new cogs"))
    if reload:
        why = "the shared style module changed" if any(p.startswith(SHARED) for p in changed) else "their code changed"
        steps.append((f"!reload {' '.join(reload)}", why))
    slash_diff = git("diff", since, "HEAD", "--", COGS) if (touched or added or removed) else ""
    if touches_slash(slash_diff):
        steps.append(("!slash sync", "slash commands or context menus changed"))
    return steps


def main(argv: list) -> int:
    since = argv[1] if len(argv) > 1 else "ORIG_HEAD"
    if not resolves(since):
        if len(argv) > 1:
            print(f"Can't find {since!r} in this repository.")
            return 1
        since = "HEAD~1"
        print("No ORIG_HEAD (nothing was pulled yet?), so this compares with the previous commit.\n")
    changed = [p for p in git("diff", "--name-only", since, "HEAD").splitlines() if p]
    head = git("log", "-1", "--format=%h %s").strip()
    print(f"Changes from {git('rev-parse', '--short', since).strip()} to {head}: {len(changed)} files.\n")
    steps = plan(since)
    if not steps:
        print("Nothing to run in Discord: no cog code changed.")
    else:
        print("Run these in Discord, in this order:")
        for i, (command, why) in enumerate(steps, 1):
            print(f"  {i}. {command}    ({why})")
    if any(p.startswith("docs/") for p in changed):
        print("\nThe handbook site (docs/) updates on its own a few minutes after the push.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
