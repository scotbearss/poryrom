#!/usr/bin/env python3
"""Static map contract-check for the Pokémon Thing mode.

The first tool of the content phase (docs 64 §7 / 47 §14.4). The field engine
has three pure-data failure modes that produce NO error, no assert, no log --
the map simply misbehaves and you stare at it wondering what you did wrong:

  1. MAP TOO BIG. InitMapLayoutData (src/fieldmap.c:97-114) copies the layout
     into its scratch buffer only if (width+15)*(height+14) <= 10240. If the
     product exceeds that, the `if` silently doesn't run and the player stands
     in a solid void of MAPGRID_UNDEFINED.
  2. TOO MANY OBJECTS IN THE SPAWN WINDOW. gObjectEvents has 16 live slots
     (player included; follower too if enabled). TrySpawnObjectEvents
     (src/event_object_movement.c:2463-2493) spawns templates inside a
     20x17-tile window around the player; GetAvailableObjectEventId returns
     the same TRUE for "no slot" as for "already loaded", so the 17th object
     in a window just doesn't appear.
  3. WARP ON THE WRONG METATILE. TryStartWarpEventScript / TryArrowWarp /
     TryDoorWarp (src/field_control_avatar.c) all require BOTH a warp event at
     the tile AND a metatile behavior in the warp-accepting set. A warp event
     on a plain tile exists, looks right, and does nothing.

All three are computable from map.json + layouts.json + the tileset attribute
bins WITHOUT building, which is what this tool does. Two more silent faults
ride along for free because they live in the same data:

  4. >64 OBJECT TEMPLATES. LoadObjEventTemplatesFromHeader (src/overworld.c:
     499-508) CpuCopy32s objectEventCount templates into a 64-slot SaveBlock1
     array with no bound -- a 65th template overwrites the flags array.
     That is save corruption, not a cosmetic bug.
  5. DANGLING WARP DESTINATION. A warp's dest_warp_id indexes the destination
     map's warp list with no bound check; past the end is garbage coordinates.
  6. AN OBJECT EVENT STANDING ON AN IMPASSABLE TILE. Nothing refuses it: the
     NPC spawns, animates and is talkable, embedded in whatever is drawn there.
     Doc 70 §1 -- doc 65's annex was stamped over RustboroCity's BOY_1, who
     stood inside the new building's wall for a day, through a playtest that
     reported zero findings and six specs. The placement search asked for a
     5x5 of plain ground and never asked WHO WAS STANDING ON IT. Terrain is
     what you are looking at, so it is what you check; the things standing on
     it are what you have to remember.

THE DISCIPLINE: every engine constant this tool judges against is PARSED FROM
THE HACK'S OWN SOURCE at run time -- the size ceiling and margins from
include/fieldmap.h, the slot counts from include/constants/global.h, the
warp-accepting behavior set by walking IsWarpMetatileBehavior +
IsArrowWarpMetatileBehavior in src/field_control_avatar.c through the
predicates in src/metatile_behavior.c to MB_* values in
include/constants/metatile_behaviors.h. Nothing here goes stale when the
engine pin moves, and the tool cannot drift from the arithmetic it checks
(the make_card_panel.py principle: derive from the original's own tables).

The one number NOT parsed: the spawn window's +-2 tile slack, which exists
only as literals inside TrySpawnObjectEvents. It is asserted against the
source text instead (see _spawn_window_dims), so a changed engine fails loudly
rather than silently checking the wrong window.

THE BASELINE DIFF, and why it exists: vanilla itself trips these checks 131
times -- script-triggered warps, dive warps, and arrival-only warp anchors
(some deliberately out of bounds) are all invisible to a static model, and
Nintendo shipped several >15-object spawn windows that flags keep from ever
co-occurring. The game works, so those are vanilla quirks, not faults. Instead
of modeling every trigger mechanism, findings that appear IDENTICALLY when the
same checks run over the pinned engine's own map data are suppressed by
default: what vanilla shipped is presumed intentional, and anything the hack
added or changed gets full scrutiny. --no-baseline shows everything. The
corollary to keep in mind when authoring: a deliberately script-only warp in
NEW content will FAIL here, because the tool cannot see scripts -- that FAIL
is the tool asking you to confirm the trigger exists, not always a bug.

USAGE
    python3 tools/check_map.py --hack hacks/reps          # all maps
    python3 tools/check_map.py --hack hacks/reps RustboroCity ...

Map arguments accept the directory name (RustboroCity) or the id
(MAP_RUSTBORO_CITY). Exit 0 = no findings, 1 = findings, 2 = cannot run.
FAIL means the engine will silently do the wrong thing; WARN means it can
under conditions the data alone cannot rule out (e.g. flag-gated objects that
could all be visible at once).
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

import hx


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
        expr = expr.replace("TRUE", "1").replace("FALSE", "0")
        if not re.fullmatch(r"[0-9xXa-fA-F+*/() -]+", expr):
            sys.exit(f"cannot run: #define {name} = {expr!r} is not numeric")
        out[name] = int(eval(expr))  # arithmetic-only by the regex above
    return out


def _function_body(text: str, name: str) -> str:
    m = re.search(rf"\b{name}\s*\([^)]*\)\s*\n?\{{", text)
    if not m:
        sys.exit(f"cannot run: function {name} not found in engine source")
    depth, i = 0, text.index("{", m.start())
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[i : j + 1]
    sys.exit(f"cannot run: unbalanced braces in {name}")


def warp_behavior_set(hack: Path) -> dict[int, str]:
    """value -> MB name for every behavior any warp-trigger path accepts.

    Walks the engine's own dispatch: IsWarpMetatileBehavior (the step-on and
    door paths both gate on it) plus IsArrowWarpMetatileBehavior, expanding
    each MetatileBehavior_Is* predicate to its MB_* constants, recursively for
    predicates that call predicates.
    """
    control = _read(hack / "src/field_control_avatar.c")
    behavior_c = _read(hack / "src/metatile_behavior.c")
    mb_header = _read(hack / "include/constants/metatile_behaviors.h")

    mb_values = {
        m.group(1): int(m.group(2), 0)
        for m in re.finditer(r"#define\s+(MB_\w+)\s+(0[xX][0-9a-fA-F]+|\d+)", mb_header)
    }

    predicates = set()
    for gate in ("IsWarpMetatileBehavior", "IsArrowWarpMetatileBehavior"):
        predicates |= set(re.findall(r"MetatileBehavior_Is\w+", _function_body(control, gate)))

    accepted: dict[int, str] = {}
    seen: set[str] = set()
    queue = sorted(predicates)
    while queue:
        pred = queue.pop()
        if pred in seen:
            continue
        seen.add(pred)
        body = _function_body(behavior_c, pred)
        for mb in re.findall(r"metatileBehavior\s*==\s*(MB_\w+)", body):
            if mb not in mb_values:
                sys.exit(f"cannot run: {pred} tests {mb}, absent from metatile_behaviors.h")
            accepted[mb_values[mb]] = mb
        queue += [p for p in re.findall(r"MetatileBehavior_Is\w+", body) if p != pred]
    if not accepted:
        sys.exit("cannot run: parsed an empty warp-behavior set")
    return accepted


def _spawn_window_dims(hack: Path, consts: dict[str, int]) -> tuple[int, int]:
    """Window size in tiles, with the source's literal slack asserted verbatim.

    TrySpawnObjectEvents: left = pos.x - 2, right = pos.x + MAP_OFFSET_W + 2,
    top = pos.y, bottom = pos.y + MAP_OFFSET_H + 2, all bounds inclusive.
    (Doc 64 rounds this to "20x18"; the verbatim source gives 20x17.)
    """
    body = _function_body(_read(hack / "src/event_object_movement.c"), "TrySpawnObjectEvents")
    expect = [
        r"left\s*=\s*gSaveBlock1Ptr->pos\.x\s*-\s*2",
        r"right\s*=\s*gSaveBlock1Ptr->pos\.x\s*\+\s*MAP_OFFSET_W\s*\+\s*2",
        r"top\s*=\s*gSaveBlock1Ptr->pos\.y",
        r"bottom\s*=\s*gSaveBlock1Ptr->pos\.y\s*\+\s*MAP_OFFSET_H\s*\+\s*2",
    ]
    for pat in expect:
        if not re.search(pat, body):
            sys.exit(
                "cannot run: TrySpawnObjectEvents no longer matches the window "
                f"this tool models (missing {pat!r}) -- re-derive the window"
            )
    return consts["MAP_OFFSET_W"] + 5, consts["MAP_OFFSET_H"] + 3  # inclusive spans


# ---------------------------------------------------------------- map data

class World:
    def __init__(self, hack: Path):
        self.hack = hack
        self.layouts = {
            lay["id"]: lay
            for lay in json.loads(_read(hack / "data/layouts/layouts.json"))["layouts"]
        }
        self.maps: dict[str, dict] = {}   # keyed by both id and dir name
        self.by_id: dict[str, dict] = {}
        for mj in sorted((hack / "data/maps").glob("*/map.json")):
            data = json.loads(mj.read_text())
            data["_dir"] = mj.parent.name
            self.maps[data["id"]] = data
            self.maps[mj.parent.name] = data
            self.by_id[data["id"]] = data

        # tileset label -> metatile_attributes.bin path, via the two data files
        headers = _read(hack / "src/data/tilesets/headers.h")
        incbins = _read(hack / "src/data/tilesets/metatiles.h")
        sym_to_path = {
            m.group(1): m.group(2)
            for m in re.finditer(r'const u16 (gMetatileAttributes_\w+)\[\] = INCBIN_U16\("([^"]+)"\)', incbins)
        }
        self.tileset_attrs: dict[str, Path] = {}
        for m in re.finditer(
            r"const struct Tileset (gTileset_\w+)\s*=\s*\{(.*?)\};", headers, re.S
        ):
            am = re.search(r"\.metatileAttributes\s*=\s*(\w+)", m.group(2))
            if am and am.group(1) in sym_to_path:
                self.tileset_attrs[m.group(1)] = hack / sym_to_path[am.group(1)]
        self._attr_cache: dict[Path, bytes] = {}

    def attributes(self, tileset_label: str) -> bytes | None:
        path = self.tileset_attrs.get(tileset_label)
        if path is None or not path.is_file():
            return None
        if path not in self._attr_cache:
            self._attr_cache[path] = path.read_bytes()
        return self._attr_cache[path]


# ---------------------------------------------------------------- checks

class Findings(list):
    def fail(self, map_name, check, msg):
        self.append(("FAIL", map_name, check, msg))

    def warn(self, map_name, check, msg):
        self.append(("WARN", map_name, check, msg))


def check_map(world: World, mapd: dict, consts, win_w, win_h, accepted, findings: Findings):
    name = mapd["_dir"]
    layout = world.layouts.get(mapd["layout"])
    if layout is None:
        findings.fail(name, "layout", f"layout {mapd['layout']} not in layouts.json")
        return
    w, h = layout["width"], layout["height"]

    # 1. size ceiling -- exceeded means InitMapLayoutData leaves a solid void
    product = (w + consts["MAP_OFFSET_W"]) * (h + consts["MAP_OFFSET_H"])
    if product > consts["MAX_MAP_DATA_SIZE"]:
        findings.fail(
            name, "map-size",
            f"({w}+{consts['MAP_OFFSET_W']})x({h}+{consts['MAP_OFFSET_H']}) = {product} "
            f"> {consts['MAX_MAP_DATA_SIZE']}: the layout is never copied, the map is a solid void",
        )

    # blockdata must exist and match w*h u16s, or the grid is garbage
    blockpath = world.hack / layout["blockdata_filepath"]
    blockdata = None
    if not blockpath.is_file():
        findings.fail(name, "blockdata", f"missing {layout['blockdata_filepath']}")
    else:
        blockdata = blockpath.read_bytes()
        if len(blockdata) != w * h * 2:
            findings.fail(
                name, "blockdata",
                f"{layout['blockdata_filepath']} is {len(blockdata)} B, layout says "
                f"{w}x{h} tiles = {w * h * 2} B",
            )
            blockdata = None

    objs = mapd.get("object_events", [])

    # 4. template ceiling -- the copy into SaveBlock1 is unbounded
    if len(objs) > consts["OBJECT_EVENT_TEMPLATES_COUNT"]:
        findings.fail(
            name, "template-count",
            f"{len(objs)} object_events > {consts['OBJECT_EVENT_TEMPLATES_COUNT']}: "
            "LoadObjEventTemplatesFromHeader overruns SaveBlock1 into the flags array",
        )

    # 2. spawn window: >budget objects in any window means some never appear
    budget = consts["OBJECT_EVENTS_COUNT"] - 1 - (1 if consts["OW_FOLLOWERS_ENABLED"] else 0)
    always = [(o["x"], o["y"]) for o in objs if str(o.get("flag", "0")) == "0"]
    total = [(o["x"], o["y"]) for o in objs]
    for label, pts, report in (("always-visible", always, findings.fail), ("flag-gated included", total, findings.warn)):
        count, at = _max_window(pts, win_w, win_h)
        if count > budget:
            report(
                name, "spawn-window",
                f"{count} {label} objects in one {win_w}x{win_h} spawn window "
                f"(top-left tile {at}), budget is {budget} "
                f"({consts['OBJECT_EVENTS_COUNT']} slots minus player"
                f"{' minus follower' if consts['OW_FOLLOWERS_ENABLED'] else ''}): "
                "the excess objects silently never spawn",
            )
            break  # the FAIL subsumes the WARN

    # 6. object events must stand somewhere standable
    if blockdata is not None:
        shift = consts["MAPGRID_COLLISION_SHIFT"]
        mask = consts["MAPGRID_COLLISION_MASK"] >> shift
        for i, o in enumerate(objs):
            x, y = o["x"], o["y"]
            if not (0 <= x < w and 0 <= y < h):
                findings.fail(
                    name, "object-bounds",
                    f"object {i} ({o.get('graphics_id', '?')}) at ({x},{y}) is outside "
                    f"the {w}x{h} layout",
                )
                continue
            collision = (struct.unpack_from("<H", blockdata, (y * w + x) * 2)[0] >> shift) & mask
            if collision:
                findings.fail(
                    name, "object-collision",
                    f"object {i} ({o.get('graphics_id', '?')}) at ({x},{y}) stands on a tile "
                    f"with collision {collision}: it spawns inside whatever is drawn there",
                )

    # 3 + 5. warps: behavior must be warp-accepting, destination must exist
    prim = world.attributes(layout["primary_tileset"])
    sec = world.attributes(layout["secondary_tileset"])
    for i, warp in enumerate(mapd.get("warp_events", [])):
        x, y = warp["x"], warp["y"]
        if not (0 <= x < w and 0 <= y < h):
            findings.fail(name, "warp-bounds", f"warp {i} at ({x},{y}) is outside the {w}x{h} layout")
            continue
        if blockdata is not None:
            metatile = struct.unpack_from("<H", blockdata, (y * w + x) * 2)[0] & 0x3FF
            if metatile < consts["NUM_METATILES_IN_PRIMARY"]:
                attrs, idx, which = prim, metatile, layout["primary_tileset"]
            else:
                attrs, idx, which = sec, metatile - consts["NUM_METATILES_IN_PRIMARY"], layout["secondary_tileset"]
            if attrs is None or idx * 2 + 2 > len(attrs):
                findings.fail(name, "warp-behavior",
                              f"warp {i} at ({x},{y}): cannot read metatile {metatile} attributes from {which}")
            else:
                behavior = struct.unpack_from("<H", attrs, idx * 2)[0] & consts["METATILE_ATTR_BEHAVIOR_MASK"]
                if behavior not in accepted:
                    findings.fail(
                        name, "warp-behavior",
                        f"warp {i} at ({x},{y}) sits on metatile {metatile} with behavior "
                        f"0x{behavior:02X}, which no warp path accepts: the warp exists, "
                        "the tile looks right, nothing happens",
                    )
        dest = warp.get("dest_map", "")
        if dest in ("MAP_DYNAMIC", "MAP_NONE", "MAP_UNDEFINED"):
            continue
        destd = world.by_id.get(dest)
        if destd is None:
            findings.fail(name, "warp-dest", f"warp {i} targets {dest}, which has no map.json")
            continue
        raw_id = str(warp.get("dest_warp_id", "0"))
        if not re.fullmatch(r"\d+", raw_id):
            findings.warn(name, "warp-dest", f"warp {i} has symbolic dest_warp_id {raw_id!r}, not checked")
            continue
        if int(raw_id) >= len(destd.get("warp_events", [])):
            findings.fail(
                name, "warp-dest",
                f"warp {i} targets {dest} warp {raw_id}, but that map has only "
                f"{len(destd.get('warp_events', []))} warps: arrival coordinates are garbage",
            )


def _max_window(points, win_w, win_h):
    """Max points in any win_w x win_h axis-aligned window (inclusive tiles)."""
    if not points:
        return 0, None
    best, best_at = 0, None
    lefts = sorted({x for x, _ in points})
    tops = sorted({y for _, y in points})
    for lx in lefts:
        for ty in tops:
            n = sum(1 for x, y in points if lx <= x < lx + win_w and ty <= y < ty + win_h)
            if n > best:
                best, best_at = n, (lx, ty)
    return best, best_at


# ---------------------------------------------------------------- entry

def _run_checks(world: World, targets, consts, win_w, win_h, accepted) -> Findings:
    findings = Findings()
    for mapd in targets:
        check_map(world, mapd, consts, win_w, win_h, accepted, findings)
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hack", default=str(hx.default_hack()), help="hack root (a pokeemerald fork)")
    ap.add_argument("--baseline", default=str(hx.ENGINE),
                    help="pinned engine clone; identical findings there are vanilla quirks, suppressed")
    ap.add_argument("--no-baseline", action="store_true",
                    help="report vanilla's own findings too, not just the hack's")
    ap.add_argument("maps", nargs="*", help="map dir names or MAP_* ids; default: all")
    args = ap.parse_args()
    hack = Path(args.hack)

    consts = parse_defines(_read(hack / "include/fieldmap.h"),
                           ["MAP_OFFSET", "MAP_OFFSET_W", "MAP_OFFSET_H",
                            "MAX_MAP_DATA_SIZE", "NUM_METATILES_IN_PRIMARY"])
    consts |= parse_defines(_read(hack / "include/constants/global.h"),
                            ["OBJECT_EVENTS_COUNT", "OBJECT_EVENT_TEMPLATES_COUNT"])
    consts |= parse_defines(_read(hack / "include/global.fieldmap.h"),
                            ["METATILE_ATTR_BEHAVIOR_MASK",
                             "MAPGRID_COLLISION_MASK", "MAPGRID_COLLISION_SHIFT"])
    consts |= parse_defines(_read(hack / "include/config/overworld.h"),
                            ["OW_FOLLOWERS_ENABLED"])
    accepted = warp_behavior_set(hack)
    win_w, win_h = _spawn_window_dims(hack, consts)

    world = World(hack)
    if args.maps:
        targets = []
        for m in args.maps:
            if m not in world.maps:
                sys.exit(f"cannot run: no map named {m}")
            targets.append(world.maps[m])
    else:
        targets = list(world.by_id.values())

    findings = _run_checks(world, targets, consts, win_w, win_h, accepted)

    suppressed = 0
    if not args.no_baseline:
        base = Path(args.baseline)
        if not (base / "data/maps").is_dir():
            sys.exit(f"cannot run: no baseline at {base} (use --no-baseline to skip suppression)")
        # Same rules (the hack's own constants and behavior set), vanilla's data:
        # a finding the pin also produces, byte for byte, is a shipped quirk.
        base_world = World(base)
        base_targets = [base_world.maps[m["_dir"]] for m in targets if m["_dir"] in base_world.maps]
        vanilla = {f for f in _run_checks(base_world, base_targets, consts, win_w, win_h, accepted)}
        kept = Findings()
        for f in findings:
            if f in vanilla:
                suppressed += 1
            else:
                kept.append(f)
        findings = kept

    for sev, map_name, check, msg in findings:
        print(f"{sev} {map_name} [{check}] {msg}")
    fails = sum(1 for f in findings if f[0] == "FAIL")
    warns = len(findings) - fails
    print(f"\nchecked {len(targets)} map(s) against {len(accepted)} warp behaviors, "
          f"window {win_w}x{win_h}, budget {consts['OBJECT_EVENTS_COUNT']}-slot: "
          f"{fails} FAIL, {warns} WARN"
          + (f" ({suppressed} vanilla quirk(s) suppressed by baseline)" if suppressed else ""))
    sys.exit(1 if fails or warns else 0)


if __name__ == "__main__":
    main()
