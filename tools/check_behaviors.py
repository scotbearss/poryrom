#!/usr/bin/env python3
"""Metatile-behavior census: which of the 240 ids are actually free to reclaim.

Written for docs 77 §7.1 (slate item F, CLIMB). The premise of "add a new
metatile behavior" is that there is somewhere to put it, and at this pin there
is not: include/constants/metatile_behaviors.h defines 240 distinct ids over
the 240 slots below NUM_METATILE_BEHAVIORS, and the highest is 0xEF. A new
behavior is a RECLAIM, not an append -- so the only question that matters is
which abandoned slot is genuinely abandoned.

"Abandoned" is three questions, not one, and only the first is greppable:

  1. IS IT REFERENCED IN CODE? 77 ids are named MB_UNUSED_*, and nine of those
     are still tested by predicates in src/metatile_behavior.c. A name is not
     evidence; the reference is. (Doc 74's rule: ask who READS the field.)

  2. IS IT LIVE IN DATA? A behavior id is the low byte of a u16 in every
     tileset's metatile_attributes.bin -- BINARY FILES NO GREP WILL EVER HIT.
     An id with zero C references can still be painted on a metatile in a
     tileset we have never opened, and reclaiming it hands our new predicate a
     tile in somebody else's map. This is the check that cannot be done any
     other way, and it is the reason this tool exists.

  3. DOES IT CARRY LUGGAGE? sTileBitAttributes (src/metatile_behavior.c:9) is
     sparse-initialised by designator, so an id with no row reads 0 -- but
     MB_UNUSED_05 carries TILE_FLAG_HAS_ENCOUNTERS and MB_UNUSED_6F carries
     TILE_FLAG_SURFABLE. Reclaim one of those for a wall and the wall spawns
     wild Pokemon, or the player Surfs up it. Nothing errors and no screen
     shows a wrong number: it is the inherited-default shape again, and the
     fourth member of the class after an undrawn window frame, orange text and
     an unterminated player name.

Question 2 is answered in two tiers, because they mean different things:

  DECLARED -- the id appears in some tileset's attribute table, so a metatile
     carrying it EXISTS. This alone disqualifies a reclaim: the metatile does
     not stop existing because no map uses it today.
  PAINTED  -- that metatile is actually placed in some map's blockdata or in a
     border block. This is the severity, not the verdict.

THE DISCIPLINE, as in check_map.py: every engine constant judged against is
PARSED FROM THE HACK'S OWN SOURCE at run time -- the id ceiling and MB_INVALID
from the constants header, the behavior mask and the metatile-id mask from
include/global.fieldmap.h, the primary/secondary split from include/fieldmap.h.
The 2-byte attribute stride is DERIVED, not assumed: the tool asserts struct
Tileset still declares `const u16 *metatileAttributes` and that every tileset's
attribute file length matches its metatiles.bin at 16 bytes per metatile. A
changed engine fails loudly here rather than silently censusing the wrong
bytes.

USAGE
    python3 tools/check_behaviors.py
    python3 tools/check_behaviors.py --hack engine
    python3 tools/check_behaviors.py --explain MB_UNUSED_1D
    python3 tools/check_behaviors.py --json

Exit 0 = the census ran and at least one id is reclaimable. Exit 1 = it ran and
NOTHING is reclaimable (docs 77 P4 was wrong; the round changes shape). Exit
2 = cannot run, because an assumption this tool rests on no longer holds.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

import hx

TEXT_SUFFIXES = (".c", ".h", ".inc", ".s", ".json", ".txt")
SCAN_DIRS = ("src", "include", "data", "test", "tools")


# ---------------------------------------------------------------- C parsing

def _read(path: Path) -> str:
    if not path.is_file():
        sys.exit(f"cannot run: missing {path}")
    return path.read_text(errors="replace")


def parse_defines(text: str, names: list[str]) -> dict[str, int]:
    """Numeric #defines, resolving one level of reference to earlier names."""
    out: dict[str, int] = {}
    for name in names:
        m = re.search(rf"#define\s+{name}\b\s+(.+?)\s*(?://.*)?$", text, re.M)
        if not m:
            sys.exit(f"cannot run: #define {name} not found in engine source")
        expr = m.group(1).strip()
        for known, val in out.items():
            expr = re.sub(rf"\b{known}\b", str(val), expr)
        if not re.fullmatch(r"[0-9xXa-fA-F+*/() -]+", expr):
            sys.exit(f"cannot run: #define {name} = {expr!r} is not numeric")
        out[name] = int(eval(expr))  # arithmetic-only by the regex above
    return out


def parse_behavior_ids(header_text: str) -> dict[str, int]:
    """MB_* name -> numeric id, straight from the constants header."""
    out = {}
    for m in re.finditer(r"#define\s+(MB_\w+)\s+(0x[0-9A-Fa-f]+|\d+)", header_text):
        out[m.group(1)] = int(m.group(2), 0)
    if not out:
        sys.exit("cannot run: no MB_* constants found")
    return out


def _array_body(text: str, decl_pattern: str) -> tuple[str, int, int]:
    """Body of an initialised array, plus its span in `text`."""
    m = re.search(decl_pattern, text)
    if not m:
        sys.exit(f"cannot run: array matching {decl_pattern!r} not found")
    i = text.index("{", m.start())
    depth = 0
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[i : j + 1], m.start(), j + 1
    sys.exit(f"cannot run: unbalanced braces in array {decl_pattern!r}")


def parse_tile_bit_attributes(behavior_c: str) -> tuple[dict[str, str], str]:
    """MB_ name -> flag expression for every sTileBitAttributes designator row.

    Returns the rows and the source text with the array BLANKED -- replaced by
    the same number of newlines, so line numbers elsewhere in the file stay
    truthful -- so that a designator row is never miscounted as a live code
    reference. That distinction is the whole point: a row is luggage, a
    predicate is a user.
    """
    body, start, end = _array_body(
        behavior_c, r"sTileBitAttributes\s*\[[^\]]*\]\s*=\s*"
    )
    rows = {
        m.group(1): " ".join(m.group(2).split())
        for m in re.finditer(r"\[\s*(MB_\w+)\s*\]\s*=\s*([^,\n]+)", body)
    }
    blanked = "\n" * behavior_c[start:end].count("\n")
    return rows, behavior_c[:start] + blanked + behavior_c[end:]


# A predicate may test a RANGE rather than an equality, and a range names only
# its two endpoints -- so every id BETWEEN them is referenced by code that never
# mentions it. Missing that would make this tool commit the exact error it
# exists to prevent: handing back an id some predicate already accepts. All ten
# comparisons at this pin are well-formed two-sided ranges; anything this parser
# cannot pair is a hard stop, not a guess.
_COMPARE_RE = re.compile(r"[<>]=?\s*(MB_\w+)")
_RANGE_RE = re.compile(r">=\s*(MB_\w+)[^;{}]{0,160}?<=\s*(MB_\w+)", re.S)


def range_references(path_label: str, text: str, ids: dict[str, int]) -> dict[str, list[str]]:
    """MB_ name -> references earned by sitting INSIDE a tested range."""
    ranges = list(_RANGE_RE.finditer(text))
    compares = list(_COMPARE_RE.finditer(text))
    if len(compares) != 2 * len(ranges):
        paired = {m.start(1) for m in ranges} | {m.start(2) for m in ranges}
        for c in compares:
            if c.start(1) not in paired:
                line = text[: c.start()].count("\n") + 1
                sys.exit(
                    f"cannot run: {path_label}:{line} compares against "
                    f"{c.group(1)} outside a two-sided range. This tool can only "
                    f"expand paired ranges; an unpaired comparison would make it "
                    f"report ids as free that are not."
                )
    out: dict[str, list[str]] = {}
    for m in ranges:
        lo_name, hi_name = m.group(1), m.group(2)
        if lo_name not in ids or hi_name not in ids:
            continue
        lo, hi = sorted((ids[lo_name], ids[hi_name]))
        line = text[: m.start()].count("\n") + 1
        for name, value in ids.items():
            if lo <= value <= hi and name not in (lo_name, hi_name):
                out.setdefault(name, []).append(
                    f"{path_label}:{line} (inside range {lo_name}..{hi_name})"
                )
    return out


# ---------------------------------------------------------------- data reads

class Tilesets:
    """tileset label -> its metatile_attributes.bin, with the stride asserted."""

    def __init__(self, hack: Path):
        fieldmap_h = _read(hack / "include/global.fieldmap.h")
        if not re.search(r"const\s+u16\s*\*\s*metatileAttributes\s*;", fieldmap_h):
            sys.exit(
                "cannot run: struct Tileset no longer declares "
                "`const u16 *metatileAttributes` -- the 2-byte attribute stride "
                "this tool decodes is no longer derivable"
            )
        self.stride = 2

        headers = _read(hack / "src/data/tilesets/headers.h")
        incbins = _read(hack / "src/data/tilesets/metatiles.h")
        sym_to_path = {
            m.group(1): m.group(2)
            for m in re.finditer(
                r'const u16 (gMetatileAttributes_\w+)\[\] = INCBIN_U16\("([^"]+)"\)', incbins
            )
        }
        self.attr_path: dict[str, Path] = {}
        for m in re.finditer(
            r"const struct Tileset (gTileset_\w+)\s*=\s*\{(.*?)\};", headers, re.S
        ):
            am = re.search(r"\.metatileAttributes\s*=\s*(\w+)", m.group(2))
            if am and am.group(1) in sym_to_path:
                self.attr_path[m.group(1)] = hack / sym_to_path[am.group(1)]
        if not self.attr_path:
            sys.exit("cannot run: no tilesets resolved from headers.h")
        self._cache: dict[Path, bytes] = {}

        # The stride is a claim about these files, so check it against them.
        for label, path in sorted(self.attr_path.items()):
            metatiles = path.with_name("metatiles.bin")
            if not path.is_file() or not metatiles.is_file():
                continue
            n_attr = path.stat().st_size // self.stride
            n_meta = metatiles.stat().st_size // 16
            if n_attr != n_meta:
                sys.exit(
                    f"cannot run: {label} has {n_meta} metatiles but "
                    f"{n_attr} attribute entries -- the attribute format changed"
                )

    def attributes(self, label: str) -> bytes | None:
        path = self.attr_path.get(label)
        if path is None or not path.is_file():
            return None
        if path not in self._cache:
            self._cache[path] = path.read_bytes()
        return self._cache[path]

    def behaviors(self, label: str, mask: int) -> list[int]:
        """Behavior byte of every metatile this tileset declares, in order."""
        blob = self.attributes(label)
        if blob is None:
            return []
        n = len(blob) // self.stride
        return [
            struct.unpack_from("<H", blob, i * self.stride)[0] & mask for i in range(n)
        ]


def painted_behaviors(hack: Path, ts: Tilesets, consts: dict[str, int]):
    """behavior id -> set of layout ids that actually paint a tile carrying it.

    Walks every layout's blockdata AND its border, resolving each metatile id
    through that layout's own primary/secondary pair. The border counts: an
    oversize map renders as its border block edge to edge (doc 68 §3), so a
    border metatile's behavior is as real as any other.
    """
    layouts = json.loads(_read(hack / "data/layouts/layouts.json"))["layouts"]
    id_mask = consts["MAPGRID_METATILE_ID_MASK"]
    split = consts["NUM_METATILES_IN_PRIMARY"]
    beh_mask = consts["METATILE_ATTR_BEHAVIOR_MASK"]

    cache: dict[str, list[int]] = {}

    def behaviors_of(label: str) -> list[int]:
        if label not in cache:
            cache[label] = ts.behaviors(label, beh_mask)
        return cache[label]

    out: dict[int, set[str]] = {}
    unreadable: list[str] = []
    for lay in layouts:
        prim = behaviors_of(lay.get("primary_tileset", ""))
        sec = behaviors_of(lay.get("secondary_tileset", ""))
        for key in ("blockdata_filepath", "border_filepath"):
            rel = lay.get(key)
            if not rel:
                continue
            path = hack / rel
            if not path.is_file():
                unreadable.append(f"{lay['id']}:{key}")
                continue
            blob = path.read_bytes()
            for off in range(0, len(blob) - 1, 2):
                metatile = struct.unpack_from("<H", blob, off)[0] & id_mask
                if metatile < split:
                    table, idx = prim, metatile
                else:
                    table, idx = sec, metatile - split
                if idx < len(table):
                    out.setdefault(table[idx], set()).add(lay["id"])
    return out, unreadable


def code_references(hack: Path, ids: dict[str, int], skip: set[Path], patched: dict[Path, str]):
    """MB_ name -> sorted list of 'path:line' references across the tree.

    Counts both a name written out and a name covered by a tested range.
    """
    hits: dict[str, list[str]] = {}
    names = set(ids)
    pattern = re.compile(r"\bMB_\w+\b")
    for sub in SCAN_DIRS:
        root = hack / sub
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            if path in skip:
                continue
            text = patched.get(path)
            if text is None:
                try:
                    text = path.read_text(errors="replace")
                except OSError:
                    continue
            if "MB_" not in text:
                continue
            label = str(path.relative_to(hack))
            for lineno, line in enumerate(text.splitlines(), 1):
                for name in set(pattern.findall(line)):
                    if name in names:
                        hits.setdefault(name, []).append(f"{label}:{lineno}")
            for name, refs in range_references(label, text, ids).items():
                hits.setdefault(name, []).extend(refs)
    return hits


# ---------------------------------------------------------------- the census

def census(hack: Path):
    mb_header_path = hack / "include/constants/metatile_behaviors.h"
    mb_header = _read(mb_header_path)
    ids = parse_behavior_ids(mb_header)

    consts = parse_defines(mb_header, ["NUM_METATILE_BEHAVIORS"])
    consts |= parse_defines(
        _read(hack / "include/global.fieldmap.h"),
        ["METATILE_ATTR_BEHAVIOR_MASK", "MAPGRID_METATILE_ID_MASK"],
    )
    consts |= parse_defines(_read(hack / "include/fieldmap.h"), ["NUM_METATILES_IN_PRIMARY"])

    ceiling = consts["NUM_METATILE_BEHAVIORS"]
    sentinel = ids.get("MB_INVALID")
    real = {n: v for n, v in ids.items() if v < ceiling}

    behavior_c_path = hack / "src/metatile_behavior.c"
    tile_flags, behavior_c_minus_array = parse_tile_bit_attributes(_read(behavior_c_path))

    refs = code_references(
        hack,
        real,
        skip={mb_header_path},
        patched={behavior_c_path: behavior_c_minus_array},
    )

    ts = Tilesets(hack)
    declared: dict[int, set[str]] = {}
    for label in ts.attr_path:
        for beh in ts.behaviors(label, consts["METATILE_ATTR_BEHAVIOR_MASK"]):
            declared.setdefault(beh, set()).add(label)
    painted, unreadable = painted_behaviors(hack, ts, consts)

    by_id = {}
    for name, value in sorted(real.items(), key=lambda kv: kv[1]):
        by_id[value] = {
            "name": name,
            "id": value,
            "code_refs": sorted(refs.get(name, [])),
            "tile_flags": tile_flags.get(name),
            "declared_in": sorted(declared.get(value, ())),
            "painted_in": sorted(painted.get(value, ())),
        }
    free_slots = [i for i in range(ceiling) if i not in by_id]
    reclaimable = [
        e
        for e in by_id.values()
        if not e["code_refs"] and not e["declared_in"] and e["tile_flags"] is None
    ]
    return {
        "hack": str(hack),
        "ceiling": ceiling,
        "sentinel": sentinel,
        "defined": len(real),
        "constants": len(ids),
        "free_slots": free_slots,
        "named_unused": sum(1 for n in real if n.startswith("MB_UNUSED")),
        "with_tile_flags": sum(1 for e in by_id.values() if e["tile_flags"]),
        "referenced": sum(1 for e in by_id.values() if e["code_refs"]),
        "declared": sum(1 for e in by_id.values() if e["declared_in"]),
        "painted": sum(1 for e in by_id.values() if e["painted_in"]),
        "unreadable_layout_files": unreadable,
        "by_id": by_id,
        "reclaimable": reclaimable,
    }


# ---------------------------------------------------------------- reporting

def explain(result: dict, name: str) -> int:
    match = [e for e in result["by_id"].values() if e["name"] == name.upper()]
    if not match:
        print(f"no such behavior: {name}")
        return 2
    e = match[0]
    print(f"{e['name']}  = {e['id']:#04x}")
    print(f"  tile-flag row : {e['tile_flags'] or '(none -- reads 0)'}")
    print(f"  code refs     : {len(e['code_refs'])}")
    for r in e["code_refs"][:20]:
        print(f"      {r}")
    if len(e["code_refs"]) > 20:
        print(f"      ... and {len(e['code_refs']) - 20} more")
    print(f"  declared in   : {', '.join(e['declared_in']) or '(no tileset)'}")
    print(f"  painted in    : {len(e['painted_in'])} layout(s)")
    for lay in e["painted_in"][:10]:
        print(f"      {lay}")
    if len(e["painted_in"]) > 10:
        print(f"      ... and {len(e['painted_in']) - 10} more")
    verdict = (
        "RECLAIMABLE"
        if not e["code_refs"] and not e["declared_in"] and e["tile_flags"] is None
        else "IN USE -- do not reclaim"
    )
    print(f"  verdict       : {verdict}")
    return 0


def report(result: dict, limit: int) -> int:
    print(f"BEHAVIOR CENSUS -- {result['hack']}")
    print(
        f"  {result['defined']} ids defined below NUM_METATILE_BEHAVIORS "
        f"{result['ceiling']:#04x}"
        + (f", sentinel MB_INVALID {result['sentinel']:#04x}" if result["sentinel"] else "")
    )
    print(f"  free slots (never defined)      : {len(result['free_slots'])}")
    print(f"  named MB_UNUSED_*               : {result['named_unused']}")
    print(f"  referenced in C                 : {result['referenced']}")
    print(f"  carry an sTileBitAttributes row : {result['with_tile_flags']}")
    print(f"  declared in a tileset           : {result['declared']}")
    print(f"  painted in a layout or border   : {result['painted']}")
    if result["unreadable_layout_files"]:
        print(
            f"  ! unreadable layout files       : {len(result['unreadable_layout_files'])} "
            f"({', '.join(result['unreadable_layout_files'][:3])}...)"
        )
    print()

    rec = result["reclaimable"]
    print(f"RECLAIMABLE -- dead in code, dead in data, no inherited tile flags: {len(rec)}")
    for e in rec[:limit]:
        print(f"  {e['id']:#04x}  {e['name']}")
    if len(rec) > limit:
        print(f"  ... and {len(rec) - limit} more (--limit to see them)")

    trap = [
        e
        for e in result["by_id"].values()
        if not e["code_refs"] and (e["declared_in"] or e["tile_flags"])
    ]
    if trap:
        print()
        print(
            f"LOOKS FREE, IS NOT -- no C reference, but luggage or live data: {len(trap)}"
        )
        print("  (this is the set a grep would have handed you)")
        for e in trap[:limit]:
            why = []
            if e["tile_flags"]:
                why.append(f"flags {e['tile_flags']}")
            if e["painted_in"]:
                why.append(f"painted in {len(e['painted_in'])} layout(s)")
            elif e["declared_in"]:
                why.append(f"declared in {len(e['declared_in'])} tileset(s)")
            print(f"  {e['id']:#04x}  {e['name']:<36} {'; '.join(why)}")
        if len(trap) > limit:
            print(f"  ... and {len(trap) - limit} more")
    return 0 if rec else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hack", default=str(hx.default_hack()), help="hack root (a pokeemerald fork)")
    ap.add_argument("--explain", metavar="MB_NAME", help="full dossier on one behavior id")
    ap.add_argument("--json", action="store_true", help="machine-readable census")
    ap.add_argument("--limit", type=int, default=25, help="rows per list (default 25)")
    args = ap.parse_args()

    hack = Path(args.hack)
    if not hack.is_dir():
        sys.exit(f"cannot run: no such tree {hack}")
    result = census(hack)

    if args.json:
        print(json.dumps(result, indent=1, default=list))
        return 0 if result["reclaimable"] else 1
    if args.explain:
        return explain(result, args.explain)
    return report(result, args.limit)


if __name__ == "__main__":
    sys.exit(main())
