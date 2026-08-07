#!/usr/bin/env python3
"""Append-only new-map codegen for the Pokémon Thing mode.

The content phase's third tool, and the one doc 64 §10 item 3 needs: a new
city/room plus the door that reaches it. `check_map.py` JUDGES map data;
this tool WRITES it, so the two are a pair -- author here, then check there.

WHY A TOOL RATHER THAN PORYMAP. Porymap is a GUI, and this project's standing
rule is that chatting is the only manual step (root CLAUDE.md, the
nothing-by-hand principle). A map is six edits across five files plus two
binaries, and five of the six are the kind that fail SILENTLY when skipped:
a layout with no layouts.json row simply is not built, a map absent from
map_groups.json has no MAP_* constant, and a scripts.inc nobody `.include`s
links to nothing and takes the map's script pointers down with it.

WHAT IT EDITS, in order (all under --hack, a pokeemerald-expansion fork):

  1. data/layouts/<Name>/map.bin        the block grid, from an ASCII plan
     data/layouts/<Name>/border.bin     the 2x2 border block
  2. data/layouts/layouts.json          the layout row (append)
  3. data/maps/<Name>/map.json          header + object/warp/bg/coord events
  4. data/maps/<Name>/scripts.inc       the map's scripts (verbatim from spec)
  5. data/maps/map_groups.json          the map name, appended to ONE group
  6. data/event_scripts.s               .include of the scripts.inc above

  and, when the spec carries a "host_door" section, the way IN:

  7. data/layouts/<Host>/map.bin        a building stamped into the host map
  8. data/maps/<Host>/map.json          the warp event on the door tile

Everything mapjson generates -- header.inc, events.inc, connections.inc,
include/constants/map_groups.h, layouts.h -- is left to the build, exactly as
`reps.patch` already assumes (it excludes events.inc by name).

APPEND-ONLY, AND WHY IT MATTERS HERE. A map's identity is (group, num), and
num is its INDEX inside its group. SaveBlock1.location stores that pair, so
inserting a map mid-group teleports every existing save. Appending at the end
of one group renumbers nothing -- other groups are numbered independently.
The tool refuses any placement but the end.

DERIVE, DON'T GUESS -- `--dump-layout`. Metatile ids are meaningless outside
their tileset pair, and a wrong one is not an error, just a wall where you
wanted a floor. So the intended authoring loop is to dump an EXISTING layout
that already looks right, edit the ASCII plan it prints, and feed that back:

    python3 tools/new_map.py --hack <fork> \\
        --dump-layout LAYOUT_RUSTBORO_CITY_POKEMON_SCHOOL > plan.json

Every metatile in the result is one the engine itself ships with that exact
tileset pair. This is `make_card_panel.py`'s rule applied to map data: generate
the asset from the original's own tables rather than redrawing it.

ASSERTIONS. Every edit is asserted INDIVIDUALLY -- the 2026-07-30 lesson that
a script asserting only "the file changed" reports success when one of several
replacements silently fails to match. The binary writes are read back and
compared cell-by-cell; the host stamp additionally asserts that every byte
OUTSIDE the stamped rectangle is unchanged, because a paste with a wrong width
corrupts a row at a time and looks fine in a diffstat. The stamp also REFUSES a
site that covers any of the host map's object events -- doc 70 §1, where the
annex landed on RustboroCity's BOY_1 and left him standing in a wall through a
playtest and six specs. `--allow-covering-npcs` opens that gate out loud.

USAGE
    python3 tools/new_map.py --hack hacks/reps spec.json
    python3 tools/new_map.py --hack hacks/reps --dump-layout LAYOUT_X

Exit 0 on success (prints every file touched), 2 on any failed precondition or
assertion. Preconditions are all checked BEFORE the first write, and a map name
that already exists aborts there, so a re-run after a fix is safe.

SPEC (JSON):
{
  "name": "RustboroCity_TrainingAnnex",   // dir + symbol stem; MAP_/LAYOUT_ ids
                                          //   are derived unless given
  "group": "gMapGroup_IndoorRustboro",    // must already exist in map_groups.json
  "layout": {
    "primary_tileset": "gTileset_Building",
    "secondary_tileset": "gTileset_PokemonSchool",
    "border": [519, 519, 519, 519],       // 4 raw u16 blocks (2x2)
    "palette": {                          // one entry per char used in "plan"
      ".": [513, 0, 3],                   // [metatile, collision, elevation]
      "#": [520, 1, 0]
    },
    "plan": ["#####", ".....", "....."]   // rows; all rows the same length
  },
  "header": {                             // any map.json header field; these
    "music": "MUS_RUSTBORO",              //   six have no sensible default
    "region_map_section": "MAPSEC_RUSTBORO_CITY",
    "map_type": "MAP_TYPE_INDOOR"
  },
  "object_events": [ ... ],               // verbatim map.json event objects
  "warp_events":   [ ... ],
  "bg_events":     [ ... ],
  "coord_events":  [ ... ],
  "scripts": "<Name>_MapScripts::\\n\\t.byte 0\\n",   // or "scripts_file": path
  "host_door": {                          // optional: the way in
    "map": "RustboroCity",
    "stamp": {"from_x": 28, "from_y": 24, "w": 5, "h": 5,
              "from_layout": "LAYOUT_RUSTBORO_CITY"},  // defaults to host layout
    "at": [31, 33],                       // top-left where the stamp lands
    "door": [33, 37],                     // absolute tile the warp sits on
    "dest_warp_id": 0                     // warp index in THIS new map to
  }                                       //   arrive at
}
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

import hx

MARK = "new_map.py"

# include/global.fieldmap.h:7-11 -- the block word's three fields. Parsed from
# the fork at run time rather than hardcoded (check_map.py's discipline).
MASK_DEFAULTS = {
    "MAPGRID_METATILE_ID_MASK": 0x03FF,
    "MAPGRID_COLLISION_MASK": 0x0C00,
    "MAPGRID_ELEVATION_MASK": 0xF000,
    "MAPGRID_COLLISION_SHIFT": 10,
    "MAPGRID_ELEVATION_SHIFT": 12,
}


def die(msg: str):
    sys.exit(f"new_map.py: {msg}")


def read_masks(hack: Path) -> dict:
    """Parse the block-word field layout out of the fork's own header."""
    path = hack / "include/global.fieldmap.h"
    if not path.is_file():
        die(f"missing {path} -- is --hack a pokeemerald fork?")
    text = path.read_text()
    out = {}
    for name, fallback in MASK_DEFAULTS.items():
        m = re.search(rf"^#define\s+{name}\s+(0x[0-9A-Fa-f]+|\d+)", text, re.M)
        if not m:
            die(f"{name} not found in {path} -- the engine's block format moved")
        out[name] = int(m.group(1), 0)
        del fallback
    return out


def pack_block(masks: dict, metatile: int, collision: int, elevation: int) -> int:
    mt_mask = masks["MAPGRID_METATILE_ID_MASK"]
    co_mask = masks["MAPGRID_COLLISION_MASK"]
    el_mask = masks["MAPGRID_ELEVATION_MASK"]
    co_shift = masks["MAPGRID_COLLISION_SHIFT"]
    el_shift = masks["MAPGRID_ELEVATION_SHIFT"]
    if not 0 <= metatile <= mt_mask:
        die(f"metatile {metatile} out of range 0..{mt_mask}")
    if not 0 <= (collision << co_shift) <= co_mask or (collision << co_shift) & ~co_mask:
        die(f"collision {collision} does not fit {co_mask:#06x}")
    if (elevation << el_shift) & ~el_mask:
        die(f"elevation {elevation} does not fit {el_mask:#06x}")
    return metatile | (collision << co_shift) | (elevation << el_shift)


def unpack_block(masks: dict, word: int):
    return (
        word & masks["MAPGRID_METATILE_ID_MASK"],
        (word & masks["MAPGRID_COLLISION_MASK"]) >> masks["MAPGRID_COLLISION_SHIFT"],
        (word & masks["MAPGRID_ELEVATION_MASK"]) >> masks["MAPGRID_ELEVATION_SHIFT"],
    )


def read_bin(path: Path) -> list:
    data = path.read_bytes()
    if len(data) % 2:
        die(f"{path} has an odd byte count ({len(data)}) -- not a block grid")
    return list(struct.unpack(f"<{len(data)//2}H", data))


def write_bin(path: Path, words: list, what: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack(f"<{len(words)}H", *words))
    back = read_bin(path)
    if back != words:
        die(f"{what}: {path} read back different from what was written")
    print(f"  wrote   {path} ({what}, {len(words)} blocks)")


# ------------------------------------------------------------------ layouts

def load_layouts(hack: Path) -> dict:
    return json.loads((hack / "data/layouts/layouts.json").read_text())


def find_layout(hack: Path, layout_id: str) -> dict:
    for row in load_layouts(hack)["layouts"]:
        if row["id"] == layout_id:
            return row
    die(f"layout {layout_id} not found in data/layouts/layouts.json")


def dump_layout(hack: Path, layout_id: str):
    """Print an editable spec fragment derived from an existing layout.

    The whole point: every metatile printed is one the engine already uses with
    that exact tileset pair, so an edited copy cannot name a block that does not
    exist there. Chars are assigned in order of first appearance.
    """
    masks = read_masks(hack)
    row = find_layout(hack, layout_id)
    w, h = row["width"], row["height"]
    words = read_bin(hack / row["blockdata_filepath"])
    if len(words) != w * h:
        die(f"{layout_id}: {len(words)} blocks for a {w}x{h} layout")

    alphabet = ".#abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    seen, palette, plan = {}, {}, []
    for y in range(h):
        line = ""
        for x in range(w):
            word = words[y * w + x]
            if word not in seen:
                if len(seen) >= len(alphabet):
                    die(f"{layout_id} uses more than {len(alphabet)} distinct blocks")
                ch = alphabet[len(seen)]
                seen[word] = ch
                palette[ch] = list(unpack_block(masks, word))
            line += seen[word]
        plan.append(line)

    print(json.dumps({
        "_source": layout_id,
        "layout": {
            "primary_tileset": row["primary_tileset"],
            "secondary_tileset": row["secondary_tileset"],
            "border": read_bin(hack / row["border_filepath"]),
            "palette": palette,
            "plan": plan,
        },
    }, indent=2))


# --------------------------------------------------------------------- spec

def derive_ids(name: str) -> tuple:
    """RustboroCity_TrainingAnnex -> MAP_RUSTBORO_CITY_TRAINING_ANNEX."""
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name.replace("_", "_"))
    stem = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", stem)
    stem = re.sub(r"_+", "_", stem).upper()
    return f"MAP_{stem}", f"LAYOUT_{stem}"


HEADER_DEFAULTS = {
    "requires_flash": False,
    "weather": "WEATHER_NONE",
    "map_type": "MAP_TYPE_INDOOR",
    "allow_cycling": False,
    "allow_escaping": False,
    "allow_running": False,
    "show_map_name": False,
    "battle_scene": "MAP_BATTLE_SCENE_NORMAL",
    "connections": None,
}


def load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text())
    name = spec.get("name") or die("spec needs a name")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        die(f"name {name!r} must be a C-symbol-safe map dir name")
    map_id, layout_id = derive_ids(name)
    spec.setdefault("id", map_id)
    spec.setdefault("layout_id", layout_id)
    if not spec.get("group"):
        die("spec needs a group (a key of data/maps/map_groups.json)")

    lay = spec.get("layout") or die("spec needs a layout")
    for key in ("primary_tileset", "secondary_tileset", "palette", "plan"):
        if key not in lay:
            die(f"spec.layout needs {key}")
    plan = lay["plan"]
    if not plan or len({len(r) for r in plan}) != 1:
        die("spec.layout.plan must be a non-empty list of equal-length rows")
    unknown = {c for r in plan for c in r} - set(lay["palette"])
    if unknown:
        die(f"plan uses characters with no palette entry: {sorted(unknown)}")
    border = lay.setdefault("border", [0, 0, 0, 0])
    if len(border) != 4:
        die("spec.layout.border must be exactly 4 blocks (a 2x2 border)")

    if ("scripts" in spec) == ("scripts_file" in spec):
        die("spec needs exactly one of scripts / scripts_file")
    return spec


# ------------------------------------------------------------------- checks

def check_size_ceiling(hack: Path, w: int, h: int, allow_oversize: bool = False):
    """InitMapLayoutData's silent ceiling -- doc 47 §1.5, check_map.py §1.

    Checked HERE as well as in check_map.py on purpose: a map that trips it
    boots into a solid void with no error, and finding that out after a 75 s
    build is the expensive way to learn it.

    --allow-oversize downgrades the refusal to a warning, and exists for
    exactly one purpose: deliberately walking off the cliff to photograph the
    fall (doc 67 item C). Same shape as rom_pair.py's --allow-unmatched-sym --
    a guard rail you can open, that says out loud what you are giving up.
    """
    src = (hack / "include/fieldmap.h").read_text()
    m = re.search(r"#define\s+MAX_MAP_DATA_SIZE\s+(\d+)", src)
    ceiling = int(m.group(1)) if m else None
    mx = re.search(r"#define\s+MAP_OFFSET\s+(\d+)", src)
    if ceiling is None:
        # The pin spells it as a literal inside fieldmap.c instead.
        csrc = (hack / "src/fieldmap.c").read_text()
        m = re.search(r"<=\s*(\d{4,6})", csrc)
        if not m:
            die("cannot find the map-size ceiling in fieldmap.h or fieldmap.c")
        ceiling = int(m.group(1))
    margin_w, margin_h = 15, 14
    if mx:
        margin_w, margin_h = int(mx.group(1)) * 2 + 1, int(mx.group(1)) * 2
    need = (w + margin_w) * (h + margin_h)
    if need > ceiling:
        msg = (f"({w}+{margin_w})*({h}+{margin_h}) = {need} > {ceiling}: this map "
               f"would silently load as a solid void (doc 47 §1.5)")
        if not allow_oversize:
            die(msg)
        print(f"  OVERSIZE {msg}\n"
              f"           --allow-oversize given: writing it anyway. This map WILL "
              f"be a solid void\n"
              f"           the player cannot walk in. That is only ever what you want "
              f"in a fixture.")
        return
    print(f"  ok      size {w}x{h} -> {need} of {ceiling} layout words")


# -------------------------------------------------------------------- edits

def edit_json(path: Path, transform, what: str):
    old = path.read_text()
    doc = json.loads(old)
    new_doc = transform(doc)
    if new_doc is None:
        die(f"{what}: precondition failed in {path}")
    new = json.dumps(new_doc, indent=2) + "\n"
    if new == old:
        die(f"{what}: edit produced no change in {path}")
    path.write_text(new)
    print(f"  edited  {path} ({what})")


def edit_text(path: Path, transform, what: str):
    old = path.read_text()
    new = transform(old)
    if new is None:
        die(f"{what}: anchor not found in {path}")
    if new == old:
        die(f"{what}: edit produced no change in {path}")
    path.write_text(new)
    print(f"  edited  {path} ({what})")


def write_new_file(path: Path, text: str, what: str):
    if path.exists():
        die(f"{what}: {path} already exists -- refusing to clobber")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if path.read_text() != text:
        die(f"{what}: {path} read back different from what was written")
    print(f"  wrote   {path} ({what})")


# --------------------------------------------------------------------- main

def preflight(hack: Path, spec: dict):
    """Every refusal, before the first write."""
    layouts = load_layouts(hack)
    if any(r["id"] == spec["layout_id"] for r in layouts["layouts"]):
        die(f"{spec['layout_id']} already in layouts.json -- nothing to do")
    known_tilesets = {r["primary_tileset"] for r in layouts["layouts"]} | \
                     {r["secondary_tileset"] for r in layouts["layouts"]}
    for key in ("primary_tileset", "secondary_tileset"):
        if spec["layout"][key] not in known_tilesets:
            die(f"{spec['layout'][key]} is used by no existing layout -- typo?")

    groups = json.loads((hack / "data/maps/map_groups.json").read_text())
    if spec["group"] not in groups:
        die(f"group {spec['group']} not in map_groups.json")
    for gname in groups.get("group_order", []):
        if spec["name"] in groups.get(gname, []):
            die(f"{spec['name']} already in {gname} -- nothing to do")

    if (hack / "data/maps" / spec["name"]).exists():
        die(f"data/maps/{spec['name']} already exists -- refusing to clobber")
    if (hack / "data/layouts" / spec["name"]).exists():
        die(f"data/layouts/{spec['name']} already exists -- refusing to clobber")

    inc = f'\t.include "data/maps/{spec["name"]}/scripts.inc"\n'
    if inc in (hack / "data/event_scripts.s").read_text():
        die(f"{spec['name']}/scripts.inc already included in event_scripts.s")

    door = spec.get("host_door")
    if door:
        for key in ("map", "stamp", "at", "door"):
            if key not in door:
                die(f"host_door needs {key}")
        host_json = hack / "data/maps" / door["map"] / "map.json"
        if not host_json.is_file():
            die(f"host map {door['map']} has no map.json")
        n_warps = len(json.loads(host_json.read_text())["warp_events"])
        dest = door.get("dest_warp_id", 0)
        if not 0 <= dest < max(1, len(spec.get("warp_events", []))):
            die(f"host_door.dest_warp_id {dest} indexes past this map's "
                f"{len(spec.get('warp_events', []))} warps -- doc 47's dangling "
                f"destination, which the engine does not bounds-check")
        print(f"  ok      host {door['map']} has {n_warps} warps; the door "
              f"becomes warp {n_warps}")


def stamp_host(hack: Path, spec: dict, masks: dict, allow_covering_npcs: bool = False):
    """Paste a building into the host layout and append the door's warp."""
    door = spec["host_door"]
    host_layout_id = door.get("host_layout") or find_host_layout(hack, door["map"])
    host = find_layout(hack, host_layout_id)
    hw, hh = host["width"], host["height"]
    bin_path = hack / host["blockdata_filepath"]
    before = read_bin(bin_path)
    if len(before) != hw * hh:
        die(f"{host_layout_id}: {len(before)} blocks for {hw}x{hh}")

    st = door["stamp"]
    src_layout = find_layout(hack, st.get("from_layout", host_layout_id))
    src_w = src_layout["width"]
    src = read_bin(hack / src_layout["blockdata_filepath"])
    sw, sh = st["w"], st["h"]
    stamp = [src[(st["from_y"] + dy) * src_w + st["from_x"] + dx]
             for dy in range(sh) for dx in range(sw)]

    ax, ay = door["at"]
    if ax + sw > hw or ay + sh > hh:
        die(f"stamp {sw}x{sh} at ({ax},{ay}) runs off the {hw}x{hh} host map")

    # Who is standing there? Doc 70 §1: the annex's site was found by searching
    # for a 5x5 of plain GROUND, and the search never asked about occupants --
    # so RustboroCity's BOY_1 spent a day inside the new building's wall, past
    # a playtest and six specs. Terrain is what you are looking at; the things
    # standing on it are what you have to remember.
    covered = [
        o for o in json.loads(
            (hack / "data/maps" / door["map"] / "map.json").read_text()
        ).get("object_events", [])
        if ax <= o["x"] < ax + sw and ay <= o["y"] < ay + sh
    ]
    if covered:
        who = ", ".join(f"{o.get('graphics_id', '?')} at ({o['x']},{o['y']})" for o in covered)
        if not allow_covering_npcs:
            die(f"stamp {sw}x{sh} at ({ax},{ay}) covers {len(covered)} object event(s) "
                f"of {door['map']}: {who}.\n"
                f"           They would stand inside the building. Move them in that "
                f"map's map.json, or pick another site.\n"
                f"           --allow-covering-npcs stamps anyway.")
        print(f"  COVERED --allow-covering-npcs given: stamping over "
              f"{len(covered)} object event(s) of {door['map']}: {who}\n"
              f"           They WILL stand inside the building.")
    else:
        print(f"  ok      stamp site is clear of {door['map']}'s object events")

    after = list(before)
    for dy in range(sh):
        for dx in range(sw):
            after[(ay + dy) * hw + ax + dx] = stamp[dy * sw + dx]
    if after == before:
        die("host stamp changed nothing -- wrong coordinates?")

    # Individual host tiles the building needs around it -- a signpost beside
    # the door, a step, a hedge removed. Same derive-don't-guess rule as the
    # stamp: give a metatile the host's OWN tileset pair already uses.
    extra_tiles = {}
    for tx, ty, mt, co, el in door.get("tiles", []):
        if not (0 <= tx < hw and 0 <= ty < hh):
            die(f"host tile ({tx},{ty}) is off the {hw}x{hh} map")
        extra_tiles[(tx, ty)] = pack_block(masks, mt, co, el)
        after[ty * hw + tx] = extra_tiles[(tx, ty)]

    write_bin(bin_path, after, f"host stamp {sw}x{sh} at ({ax},{ay})"
              + (f" + {len(extra_tiles)} tile(s)" if extra_tiles else ""))

    # Assert the paste landed exactly, and NOTHING outside it moved. A paste
    # with a wrong width corrupts one row at a time and still looks plausible.
    back = read_bin(bin_path)
    for y in range(hh):
        for x in range(hw):
            i = y * hw + x
            inside = ax <= x < ax + sw and ay <= y < ay + sh
            if (x, y) in extra_tiles:
                want = extra_tiles[(x, y)]
            elif inside:
                want = stamp[(y - ay) * sw + (x - ax)]
            else:
                want = before[i]
            if back[i] != want:
                die(f"host stamp assertion failed at ({x},{y}): "
                    f"{back[i]:#06x} != {want:#06x}")
    untouched = hw * hh - sw * sh - len([t for t in extra_tiles
                                         if not (ax <= t[0] < ax + sw
                                                 and ay <= t[1] < ay + sh)])
    print(f"  ok      host stamp exact; {untouched} blocks outside unchanged")

    dx_, dy_ = door["door"]
    if not (ax <= dx_ < ax + sw and ay <= dy_ < ay + sh):
        die(f"door ({dx_},{dy_}) is outside the stamped building")
    mt, _, _ = unpack_block(masks, back[dy_ * hw + dx_])
    print(f"  note    door tile ({dx_},{dy_}) is metatile {mt:#05x} -- "
          f"check_map.py judges whether that behavior accepts a warp")

    host_json = hack / "data/maps" / door["map"] / "map.json"

    def add_warp(doc):
        doc["warp_events"].append({
            "x": dx_, "y": dy_, "elevation": 0,
            "dest_map": spec["id"],
            "dest_warp_id": str(door.get("dest_warp_id", 0)),
        })
        return doc

    n_before = len(json.loads(host_json.read_text())["warp_events"])
    edit_json(host_json, add_warp, f"warp {n_before} -> {spec['id']}")
    n_after = len(json.loads(host_json.read_text())["warp_events"])
    if n_after != n_before + 1:
        die(f"host warp append: {n_before} -> {n_after}, expected +1")

    # Anything else the door needs on the host map -- a sign beside it, an NPC
    # outside. Appended, never inserted: an object event's INDEX is its
    # SaveBlock1 flag slot, so inserting one shifts every later object's
    # persistent state (doc 47 §7.2).
    for kind in ("bg_events", "object_events", "coord_events"):
        extra = door.get(kind)
        if not extra:
            continue
        n0 = len(json.loads(host_json.read_text())[kind])
        edit_json(host_json, lambda d, k=kind, e=extra: {**d, k: d[k] + e},
                  f"append {len(extra)} to host {kind}")
        n1 = len(json.loads(host_json.read_text())[kind])
        if n1 != n0 + len(extra):
            die(f"host {kind} append: {n0} -> {n1}, expected +{len(extra)}")

    return n_before  # the host warp id the new map warps back to


def find_host_layout(hack: Path, host_map: str) -> str:
    return json.loads((hack / "data/maps" / host_map / "map.json").read_text())["layout"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hack", default=str(hx.default_hack()),
                    help="hack root (a pokeemerald fork)")
    ap.add_argument("--dump-layout", metavar="LAYOUT_ID",
                    help="print an editable spec fragment for an existing layout")
    ap.add_argument("--allow-oversize", action="store_true",
                    help="write a map that exceeds MAX_MAP_DATA_SIZE anyway. It will "
                         "load as a solid void; only a fixture ever wants this")
    ap.add_argument("--allow-covering-npcs", action="store_true",
                    help="stamp a building over the host map's object events anyway. "
                         "They will stand inside its walls (doc 70 §1)")
    ap.add_argument("spec", nargs="?", help="map spec JSON (see module docstring)")
    args = ap.parse_args()

    hack = Path(args.hack)
    if not (hack / "data/layouts/layouts.json").is_file():
        die(f"{hack} does not look like a pokeemerald fork")

    if args.dump_layout:
        dump_layout(hack, args.dump_layout)
        return
    if not args.spec:
        die("need a spec (or --dump-layout)")

    masks = read_masks(hack)
    spec = load_spec(Path(args.spec))
    lay = spec["layout"]
    w, h = len(lay["plan"][0]), len(lay["plan"])

    print(f"{spec['name']}  ({spec['id']}, {spec['layout_id']}, {w}x{h})")
    check_size_ceiling(hack, w, h, args.allow_oversize)
    preflight(hack, spec)

    # 1. the binaries
    words = [pack_block(masks, *lay["palette"][c]) for row in lay["plan"] for c in row]
    write_bin(hack / "data/layouts" / spec["name"] / "map.bin", words, "block grid")
    write_bin(hack / "data/layouts" / spec["name"] / "border.bin",
              list(lay["border"]), "border block")

    # 2. layouts.json
    row = {
        "id": spec["layout_id"],
        "name": f"{spec['name']}_Layout",
        "width": w, "height": h,
        "primary_tileset": lay["primary_tileset"],
        "secondary_tileset": lay["secondary_tileset"],
        "border_filepath": f"data/layouts/{spec['name']}/border.bin",
        "blockdata_filepath": f"data/layouts/{spec['name']}/map.bin",
    }
    n_before = len(load_layouts(hack)["layouts"])
    edit_json(hack / "data/layouts/layouts.json",
              lambda d: {**d, "layouts": d["layouts"] + [row]}, "layout row")
    layouts_after = load_layouts(hack)["layouts"]
    if len(layouts_after) != n_before + 1 or layouts_after[-1]["id"] != spec["layout_id"]:
        die(f"layouts.json append assertion failed ({n_before} -> {len(layouts_after)})")

    # 3./7./8. the host door first, so the new map's return warp can name it
    host_warp_id = (stamp_host(hack, spec, masks, args.allow_covering_npcs)
                if spec.get("host_door") else None)

    map_doc = {"id": spec["id"], "name": spec["name"], "layout": spec["layout_id"]}
    for key, val in {**HEADER_DEFAULTS, **spec.get("header", {})}.items():
        map_doc[key] = val
    for key in ("object_events", "warp_events", "coord_events", "bg_events"):
        map_doc[key] = spec.get(key, [])
    if host_warp_id is not None:
        for warp in map_doc["warp_events"]:
            if warp.get("dest_warp_id") == "HOST_DOOR":
                warp["dest_warp_id"] = str(host_warp_id)
        if not any(w.get("dest_map") == f"MAP_{spec['host_door']['map'].upper()}"
                   or w.get("dest_map", "").startswith("MAP_")
                   for w in map_doc["warp_events"]):
            die("host_door given but this map has no warp back out")
    write_new_file(hack / "data/maps" / spec["name"] / "map.json",
                   json.dumps(map_doc, indent=2) + "\n", "map header + events")

    # 4. scripts.inc
    scripts = (Path(spec["scripts_file"]).read_text() if "scripts_file" in spec
               else spec["scripts"])
    if f"{spec['name']}_MapScripts::" not in scripts:
        die(f"scripts must define {spec['name']}_MapScripts:: "
            f"(map.json's header points there)")
    write_new_file(hack / "data/maps" / spec["name"] / "scripts.inc",
                   scripts, "map scripts")

    # 5. map_groups.json
    def add_to_group(doc):
        doc[spec["group"]] = doc[spec["group"]] + [spec["name"]]
        return doc

    g_before = len(json.loads(
        (hack / "data/maps/map_groups.json").read_text())[spec["group"]])
    edit_json(hack / "data/maps/map_groups.json", add_to_group,
              f"append to {spec['group']}")
    g_after = json.loads((hack / "data/maps/map_groups.json").read_text())[spec["group"]]
    if len(g_after) != g_before + 1 or g_after[-1] != spec["name"]:
        die(f"map_groups.json append assertion failed "
            f"({g_before} -> {len(g_after)}, last {g_after[-1]!r})")

    # 6. event_scripts.s
    inc = f'\t.include "data/maps/{spec["name"]}/scripts.inc"\n'
    anchor = f'\t.include "data/maps/{g_after[-2]}/scripts.inc"\n'

    def add_include(text):
        if anchor not in text:
            return None
        return text.replace(anchor, anchor + inc, 1)

    edit_text(hack / "data/event_scripts.s", add_include,
              f"include {spec['name']}/scripts.inc")
    if (hack / "data/event_scripts.s").read_text().count(inc) != 1:
        die("event_scripts.s include assertion failed (expected exactly one)")

    print(f"\n{spec['name']}: done. Next:")
    print(f"  python3 tools/check_map.py --hack {hack} {spec['name']} "
          f"{spec.get('host_door', {}).get('map', '')}".rstrip())
    print(f"  build the fork, then verify the warp both ways.")
    print(f"  NOT done by this tool: the {MARK} spec is inert -- dialogue text, "
          f"specials and probes are separate, tracked source edits.")


if __name__ == "__main__":
    main()
