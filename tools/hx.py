"""hx -- the one place that answers "where is everything".

WHY THIS EXISTS. The 2026-08-06 coupling audit's headline finding was that this
harness had *no shared paths module*: twelve tools each computed
`Path(__file__).resolve().parents[2]` -- the old *toolkit* root -- and then
re-appended the literal string "pokemon", and seven more baked
"pokemon/hacks/reps" into an argparse default. That is one fact (where things
live) written down nineteen times, which is the same defect this project has
recorded in three other domains: a constant written twice is a second copy of
the data. Extraction made it load-bearing, because every one of those paths was
wrong the moment the directory moved.

THE TWO ROOTS, AND WHY THEY ARE DIFFERENT.

  HARNESS_ROOT -- where the *tools* live. Derived from this file's own location,
      so it is correct whether the harness is a git checkout or a read-only
      plugin cache copy. Never assume it is writable.

  WORKSPACE -- where the *game* lives: its forks, specs, saves, patches. Found
      by walking up from the current directory looking for `harness.json`,
      exactly the way git finds `.git`. Falls back to HARNESS_ROOT when there is
      no config anywhere above -- which is the state during the migration, and
      which reproduces the pre-split layout exactly.

Keeping them apart is the whole point. A plugin installed once must serve many
game repos, and the tools must never write into their own installation.

harness.json (in a game repo's root) looks like:

    {"game": "reps",
     "harness": {"plugin": "rombench", "version": "1.0.0"},
     "engine": {"ref": "expansion/1.9.4", "commit": "2e656274",
                "cache": "~/.rombench/engines/expansion-1.9.4"},
     "docker_image": "rombench-build:1"}

Every field is optional; the defaults below reproduce the layout this harness
had before it moved, so nothing changes until a game repo asks it to.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_NAME = "harness.json"

# Where the tools are. tools/hx.py -> parents[1] is the harness root.
HARNESS_ROOT = Path(__file__).resolve().parents[1]

# The image the verification harness runs in. The Dockerfile that builds it is
# docker/Dockerfile IN THIS REPO, and it is not a stock mGBA: it carries the
# video-buffer fix, the mCoreAutoloadSave gate and the mAVStream audio tap that
# three separate rounds of this project had to add. See PROVENANCE.md.
DEFAULT_IMAGE = "rombench-build:1"

# The engine pin. A game repo overrides this in harness.json; the value here is
# what `reps` was built against and what every doc from 34 up cites.
DEFAULT_ENGINE_REF = "expansion/1.9.4"


def find_workspace(start: Path | str | None = None) -> Path:
    """The game repo we are working in: nearest ancestor holding harness.json.

    Falls back to HARNESS_ROOT so that a harness with no game repo around it
    behaves exactly as it did before the split.
    """
    here = Path(start).resolve() if start else Path.cwd().resolve()
    for cand in (here, *here.parents):
        if (cand / CONFIG_NAME).is_file():
            return cand
    return HARNESS_ROOT


def load_config(workspace: Path | None = None) -> dict:
    ws = workspace or find_workspace()
    cfg = ws / CONFIG_NAME
    if not cfg.is_file():
        return {}
    try:
        return json.loads(cfg.read_text())
    except json.JSONDecodeError as exc:            # a broken config must be loud
        raise SystemExit(f"{cfg}: not valid JSON -- {exc}") from exc


WORKSPACE = find_workspace()
CONFIG = load_config(WORKSPACE)

# "expansion/1.9.4" -> "expansion-1.9.4", so the ref can name a directory.
ENGINE_REF_SLUG = (CONFIG.get("engine") or {}).get(
    "ref", DEFAULT_ENGINE_REF).replace("/", "-")


DEFAULT_CACHE_ROOT = Path(os.path.expanduser("~/.rombench/engines"))


def _engine_path() -> Path:
    """The pinned pokeemerald-expansion clone.

    Order: an explicit cache in harness.json, then the workspace's own engine/,
    then the shared default cache. The cache must be a real git CLONE, not an
    unpacked tarball -- new_hack.py forks via `git archive` and reads
    `git describe`/`rev-parse` to record a fork's provenance.

    THE HARNESS ITSELF IS NOT A CANDIDATE, deliberately (2026-08-06, doc 82
    §5.3). Installing this plugin COPIES its directory into a cache, so an
    engine clone sitting inside the harness gets copied too -- the first local
    install came to 1.0 GB, of which 946 MB was a pinned engine and a hack fork.
    Both are Nintendo-derived, which makes that a policy problem and not merely
    a size one: nothing distributable may contain them. Keeping the engine in a
    shared cache OUTSIDE any repo fixes the size, the copy and the fence at
    once, and means twelve game repos share one clone instead of carrying one
    each.
    """
    cache = (CONFIG.get("engine") or {}).get("cache")
    if cache:
        return Path(os.path.expanduser(cache)).resolve()
    if (WORKSPACE / "engine").exists():
        return WORKSPACE / "engine"
    return DEFAULT_CACHE_ROOT / ENGINE_REF_SLUG


ENGINE = _engine_path()
ENGINE_REF = (CONFIG.get("engine") or {}).get("ref", DEFAULT_ENGINE_REF)
IMAGE = CONFIG.get("docker_image", DEFAULT_IMAGE)
GAME = CONFIG.get("game")

# Harness-side (read-only in a plugin install).
HARNESS = HARNESS_ROOT / "harness"          # the Lua the emulator runs
TOOLS = HARNESS_ROOT / "tools"
TEMPLATES = HARNESS_ROOT / "templates"

# Workspace-side (written to).
HACKS = WORKSPACE / "hacks"
SPEC_DIR = WORKSPACE / "verify"
SAVES = WORKSPACE / "saves"
PATCHES = WORKSPACE / "patches"
STUDIO = WORKSPACE / "studio"


def default_hack(name: str | None = None) -> Path:
    """The fork a tool should act on when the operator names none.

    `GAME` when a game repo declares one -- so `reps` stops being hardcoded in
    six tools that have no business knowing the name of one particular game.
    """
    return HACKS / (name or GAME or "reps")


def describe() -> str:
    """One-line orientation, for a tool's --help or a doctor check."""
    return (f"harness={HARNESS_ROOT}\nworkspace={WORKSPACE}\n"
            f"engine={ENGINE} ({ENGINE_REF})\nimage={IMAGE}\ngame={GAME or '(none declared)'}")


if __name__ == "__main__":
    print(describe())
