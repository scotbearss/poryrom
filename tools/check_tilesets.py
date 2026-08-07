#!/usr/bin/env python3
"""Static tileset contract-check: does a metatile draw from a tile that SHIPS?

Written for docs 77 §7.1b, after that round lost a build cycle to the answer
being "no". `gTileset_PokemonSchool`'s build rule emits **278** tiles, and four
of its metatiles -- the annex's own windows -- reference tiles **279, 280 and
281**. Those cells are blank in tiles.png and `-num_tiles` truncates them away,
so on hardware those VRAM slots hold whatever the previously-loaded tileset
left behind.

WHY THAT MATTERS TO ANYONE ADDING ART. The natural place to append a new tile is
"one past the declared count", and in a tileset like that one it lands
*underneath metatiles already in use*. Doc 77 did exactly this and the annex came
back with its windows drawn as climbing wall: right place, right tiling, right
palette, entirely deliberate-looking. It is the plausible-artifact class again --
there is no wrong number anywhere for a probe to find, and no error at build
time, because `-Wnum_tiles` warns about a PNG that is too BIG and says nothing
about metatiles that reach too FAR.

So: a declared count is a claim about what a tileset SHIPS. The question you
need answered before appending is what it REFERENCES. This tool answers it for
every tileset in the tree, without building.

WHAT IT CHECKS

  1. OVER-REFERENCE (secondary half). A metatile draws from tile index >=
     NUM_TILES_IN_PRIMARY, i.e. from its own tileset's tiles -- and that index
     is past `-num_tiles`. This is the one that bites an append.
  2. OVER-REFERENCE (primary half). A metatile draws from a primary tile past
     the declared count of a primary it is actually PAIRED with in
     layouts.json. Pairing matters: the same secondary can sit on two different
     primaries, and only the pairings that exist can be judged.
  3. COUNT MISMATCH. metatiles.bin and metatile_attributes.bin disagree about
     how many metatiles there are, which makes every behavior read past the
     shorter one garbage.
  4. A PRIMARY drawing from the secondary range at all, which nothing pairs it
     with and so cannot be resolved.

FAIL vs WARN, and why this tool does NOT simply suppress vanilla like
check_map.py does. A violation the pinned engine has too is upstream's, not
something this hack broke -- but unlike a script-only warp it is not
*intentional*, and it is exactly the information you want before appending to
that tileset. So it is reported as WARN with the pin named, and only violations
this tree ADDED are FAIL. --no-baseline makes everything FAIL.

THE DISCIPLINE, as in check_map.py and check_behaviors.py: every engine constant
is PARSED FROM THE TREE'S OWN SOURCE at run time -- the primary/secondary split
from include/fieldmap.h, the tile-id mask from include/global.fieldmap.h, the
per-tileset counts from graphics_file_rules.mk, the pairings from layouts.json.

USAGE
    python3 tools/check_tilesets.py
    python3 tools/check_tilesets.py --hack engine --no-baseline
    python3 tools/check_tilesets.py --json

Exit 0 = no findings this tree introduced. 1 = findings. 2 = cannot run.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

import hx


def die(msg: str):
    sys.exit(f"cannot run: {msg}")


def read_define(path: Path, name: str) -> int:
    if not path.is_file():
        die(f"missing {path}")
    m = re.search(rf"^#define\s+{name}\s+(0x[0-9A-Fa-f]+|\d+)", path.read_text(), re.M)
    if not m:
        die(f"#define {name} not found in {path}")
    return int(m.group(1), 0)


def parse_num_tiles(hack: Path) -> dict[str, int]:
    """tileset directory (relative to data/tilesets) -> declared tile count.

    The rules name paths, not gTileset_* labels, so the key is the path tail --
    which is also what the .4bpp lives under.
    """
    path = hack / "graphics_file_rules.mk"
    if not path.is_file():
        die(f"missing {path}")
    out = {}
    for m in re.finditer(
        r"\$\(TILESETGFXDIR\)/(\S+?)/([\w]*tiles)\.4bpp:.*?\n\t\$\(GFX\)[^\n]*?-num_tiles (\d+)",
        path.read_text(), re.S,
    ):
        if m.group(2) == "tiles":       # skip unused_tiles.4bpp variants
            out[m.group(1)] = int(m.group(3))
    if not out:
        die("no -num_tiles rules found; graphics_file_rules.mk's shape changed")
    return out


def parse_tilesets(hack: Path) -> dict[str, str]:
    """gTileset_* label -> directory under data/tilesets, via the INCBIN paths."""
    headers = (hack / "src/data/tilesets/headers.h").read_text()
    incbins = (hack / "src/data/tilesets/metatiles.h").read_text()
    sym_to_dir = {}
    for m in re.finditer(r'const u16 (gMetatiles_\w+)\[\] = INCBIN_U16\("data/tilesets/([^"]+)/metatiles\.bin"\)', incbins):
        sym_to_dir[m.group(1)] = m.group(2)
    out = {}
    for m in re.finditer(r"const struct Tileset (gTileset_\w+)\s*=\s*\{(.*?)\};", headers, re.S):
        mm = re.search(r"\.metatiles\s*=\s*(\w+)", m.group(2))
        if mm and mm.group(1) in sym_to_dir:
            out[m.group(1)] = sym_to_dir[mm.group(1)]
    if not out:
        die("no tilesets resolved from headers.h / metatiles.h")
    return out


def pairings(hack: Path) -> dict[str, set[str]]:
    """secondary label -> the set of primary labels it is actually used with."""
    layouts = json.loads((hack / "data/layouts/layouts.json").read_text())["layouts"]
    out: dict[str, set[str]] = {}
    for lay in layouts:
        sec, prim = lay.get("secondary_tileset"), lay.get("primary_tileset")
        if sec and prim:
            out.setdefault(sec, set()).add(prim)
    return out


def scan(hack: Path):
    split = read_define(hack / "include/fieldmap.h", "NUM_TILES_IN_PRIMARY")
    id_mask = 0x3FF
    counts = parse_num_tiles(hack)
    tilesets = parse_tilesets(hack)
    pairs = pairings(hack)

    findings = []
    for label, subdir in sorted(tilesets.items()):
        base = hack / "data/tilesets" / subdir
        meta_p, attr_p = base / "metatiles.bin", base / "metatile_attributes.bin"
        if not meta_p.is_file():
            continue
        meta = meta_p.read_bytes()
        n_meta = len(meta) // 16
        if attr_p.is_file() and len(attr_p.read_bytes()) // 2 != n_meta:
            findings.append(("count-mismatch", label,
                             f"{n_meta} metatiles but {len(attr_p.read_bytes()) // 2} "
                             f"attribute entries"))

        own = counts.get(subdir)
        # highest referenced index on each side, and who references it
        worst_sec, worst_prim = (-1, None), (-1, None)
        for i in range(n_meta):
            for e in struct.unpack_from("<8H", meta, i * 16):
                t = e & id_mask
                if t >= split:
                    if t - split > worst_sec[0]:
                        worst_sec = (t - split, i + split)
                elif t > worst_prim[0]:
                    worst_prim = (t, i)

        is_primary = subdir.startswith("primary/")
        if is_primary and worst_sec[0] >= 0:
            findings.append(("primary-uses-secondary", label,
                             f"metatile {worst_sec[1]} draws from secondary tile "
                             f"{worst_sec[0]}, which no pairing can resolve"))
        if not is_primary and own is not None and worst_sec[0] >= own:
            findings.append(("over-reference", label,
                             f"ships {own} tiles (-num_tiles) but metatile {worst_sec[1]} "
                             f"draws from its tile {worst_sec[0]} -- appending art at "
                             f"{own} lands underneath a metatile already in use"))
        if not is_primary and worst_prim[0] >= 0:
            for prim_label in sorted(pairs.get(label, ())):
                prim_dir = tilesets.get(prim_label)
                prim_count = counts.get(prim_dir) if prim_dir else None
                if prim_count is not None and worst_prim[0] >= prim_count:
                    findings.append(("over-reference-primary", label,
                                     f"metatile {worst_prim[1] + split} draws from primary tile "
                                     f"{worst_prim[0]}, but its pair {prim_label} ships "
                                     f"{prim_count}"))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hack", default=str(hx.default_hack()))
    ap.add_argument("--baseline", default=str(hx.ENGINE),
                    help="pinned engine clone; identical findings there are upstream's, "
                         "reported as WARN rather than FAIL")
    ap.add_argument("--no-baseline", action="store_true",
                    help="treat every finding as this tree's")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    hack = Path(args.hack)
    if not hack.is_dir():
        die(f"no such tree {hack}")
    found = scan(hack)

    base = set()
    baseline = Path(args.baseline)
    if not args.no_baseline and baseline.is_dir() and baseline.resolve() != hack.resolve():
        base = {(k, label) for k, label, _ in scan(baseline)}

    rows = [("WARN" if (k, label) in base else "FAIL", k, label, msg)
            for k, label, msg in found]
    if args.json:
        print(json.dumps([{"level": a, "check": b, "tileset": c, "detail": d}
                          for a, b, c, d in rows], indent=1))
    else:
        for level, check, label, msg in sorted(rows):
            print(f"{level}  {check:<24} {label}: {msg}")
        fails = sum(1 for r in rows if r[0] == "FAIL")
        warns = len(rows) - fails
        print(f"\nchecked {len(parse_tilesets(hack))} tilesets: {fails} FAIL, {warns} WARN"
              + ("" if args.no_baseline else " (WARN = present in the pin too, upstream's)"))
    return 1 if any(r[0] == "FAIL" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
