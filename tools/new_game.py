#!/usr/bin/env python3
"""Scaffold a new game: its own repo, beside the harness, ready to build.

WHY A REPO PER GAME. The harness is one installed thing shared by every game;
a game is its own history, its own design doc, its own checks, its own backup.
Keeping them in one directory is what produced the coupling this whole migration
exists to undo -- and, concretely, what put 453 MB of Nintendo-derived working
copy inside a plugin that gets COPIED on install (doc 82 §5.3).

WHAT LANDS IN THE GAME REPO
    harness.json      the pins: harness version, engine ref + cache, image, game
    CLAUDE.md         short orientation for a session opening this repo
    README.md         how a PERSON sets this up on a machine that has nothing
    .claude/settings  declares the marketplace and enables the plugin
    design/           the living design doc, from the harness's templates
    verify/           this game's checks
    patches/          the only tracked copy of the game's code
    saves/            savestate sidecars (the states themselves stay out)
    hacks/            the working copy -- gitignored, rebuilt from patches/
    <game>.gba        the playable file, at the top, gitignored

WHAT STAYS IN THE HARNESS: the tools, the Lua, the docker build, the research,
and the fixture forks/specs that test the harness itself rather than any game.

    python3 tools/new_game.py <name> --title "GAME TITLE" [--dir ~/Documents/GitHub]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import hx

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def die(msg: str):
    sys.exit(f"new_game.py: {msg}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name", help="game name -> its own repo directory")
    ap.add_argument("--title", default=None,
                    help="cartridge title, <=12 chars (default: NAME upper)")
    ap.add_argument("--dir", default="~/Documents/GitHub",
                    help="where game repos live")
    ap.add_argument("--force", action="store_true",
                    help="write into an existing directory")
    args = ap.parse_args()

    if not NAME_RE.match(args.name):
        die(f"invalid name {args.name!r} -- use [a-z0-9][a-z0-9_-]*")
    title = (args.title or args.name.upper())[:12]
    root = Path(args.dir).expanduser() / args.name
    if root.exists() and not args.force:
        die(f"{root} already exists -- pass --force to write into it")

    for sub in ("design", "verify", "patches/assets", "saves", ".claude"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    # ---- the pin file: what makes every tool work from anywhere in here ------
    (root / "harness.json").write_text(json.dumps({
        "game": args.name,
        "title": title,
        "harness": {"plugin": "poryrom",
                    "version": _harness_version()},
        "engine": {"repo": "rh-hideout/pokeemerald-expansion",
                   "ref": hx.ENGINE_REF,
                   "cache": f"~/.poryrom/engines/{hx.ENGINE_REF_SLUG}"},
        "docker_image": hx.IMAGE,
    }, indent=1) + "\n")

    # ---- so opening this repo offers to install the harness -----------------
    (root / ".claude" / "settings.json").write_text(json.dumps({
        "extraKnownMarketplaces": {
            "poryrom": {"source": {"source": "github",
                                        "repo": "scotbearss/poryrom"}}},
        "enabledPlugins": {"poryrom@poryrom": True},
    }, indent=1) + "\n")

    gitignore = (hx.HARNESS_ROOT / ".gitignore")
    if gitignore.is_file():
        (root / ".gitignore").write_text(
            gitignore.read_text().rstrip("\n")
            + f"\n\n# The playable ROM lives at the top of this repo for reach,\n"
              f"# and is a build output like any other.\n{args.name}.gba\n")

    tpl = hx.TEMPLATES / "game-design"
    if tpl.is_dir() and not any((root / "design").iterdir()):
        for f in tpl.iterdir():
            if f.is_file():
                shutil.copy2(f, root / "design" / f.name)

    (root / "README.md").write_text(_readme(args.name, title))
    (root / "CLAUDE.md").write_text(_claude_md(args.name, title))

    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-b", "main", "-q", str(root)], check=False)

    print(f"==> {root}")
    print(f"    game   {args.name}")
    print(f"    title  {title}")
    print(f"    engine {hx.ENGINE_REF}  (cache: ~/.poryrom/engines/"
          f"{hx.ENGINE_REF_SLUG})")
    print(f"    image  {hx.IMAGE}")
    print()
    print("Next:")
    print(f"  cd {root}")
    print(f"  python3 <harness>/tools/new_hack.py {args.name}   # fork the engine")
    print(f"  # then build, verify, and copy the ROM here as {args.name}.gba")
    return 0


def _harness_version() -> str:
    man = hx.HARNESS_ROOT / ".claude-plugin" / "plugin.json"
    return json.loads(man.read_text())["version"] if man.is_file() else "unknown"


def _readme(name: str, title: str) -> str:
    return f"""# {name}

A Game Boy Advance game, built with **poryrom**.

## What this repo is

The **source of this game** — its design, its checks, and a patch that is the only
tracked copy of its code. It is not the game engine and it is not the tools; those
come from the poryrom harness, which is installed once and shared by every game.

**There is no commercial ROM anywhere in this.** The game is compiled from
`pokeemerald-expansion`, a public source project on GitHub. Nothing here was
extracted from a cartridge and nothing needs to be downloaded from anywhere shady.

## Setting this up on a machine that has nothing

1. **Install Docker Desktop** and start it. Everything compiles inside a container,
   so this is the only system-level thing you need.
2. **Install the harness plugin.** Opening this repo in Claude Code should offer to
   do it. It is a private repo, so you need access to it.
3. **Ask Claude to check the setup.** It runs a doctor that tells you exactly what
   is missing and the command to fix each thing — including cloning the engine,
   which is one command and about a gigabyte.
4. **Ask it to build the game.** When that finishes, `{name}.gba` appears at the top
   of this folder. That is the file you play.

You do not need to read any code to do any of this. Ask in plain English.

## Playing it

`{name}.gba` runs in any GBA emulator (mGBA is the usual choice) and on handhelds
that take a ROM file. The cartridge calls itself `{title}`.

## The one thing that will confuse you

`hacks/` holds the working copy of the game's code, and it is deliberately **not**
in version control — it is rebuilt from `patches/` whenever it is needed. So the
patch is precious and the working copy is disposable, which is the opposite of what
you would expect. That is why the tools refresh the patch after every good build.
"""


def _claude_md(name: str, title: str) -> str:
    return f"""# {name} — game repo

**The harness is the `poryrom` plugin.** Its skills carry the working rules;
do not restate them here. Start a session with the `session-start` skill.

## What this is

{name} — a GBA ROM hack built on pokeemerald-expansion, cartridge title `{title}`.

## Where things are

- `design/` — the living design doc. The identity block and mechanics live here.
- `verify/` — this game's checks, one JSON spec each.
- `patches/{name}.patch` — **the only tracked copy of this game's code.**
- `hacks/{name}/` — the working copy. Gitignored, rebuilt from the patch.
- `{name}.gba` — the playable ROM, refreshed after every verified build.
- `harness.json` — the pins. Every tool finds this by walking up from the cwd.

## Rules that are specific to this repo

- **Refresh the patch after every green build.** Until that runs, the change exists
  on exactly one disk.
- **Screenshots before playtests**, saved under `design/reports/assets/`.
- **Never commit a ROM, a savestate or a `.sav`** — the gitignore explains why in
  detail. Those bytes are Nintendo-derived or regenerable, usually both.

## Status

Scaffolded. Nothing built yet.
"""


if __name__ == "__main__":
    sys.exit(main())
