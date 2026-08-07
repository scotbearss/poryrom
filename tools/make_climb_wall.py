#!/usr/bin/env python3
"""The climbing wall: derived tileset art + a taller annex, for docs 77 slate item F.

Two halves, both idempotent, both asserting the END STATE rather than "did this
change" (doc 73's rule -- a change assertion dies the second time you run it):

  1. THE ART, DERIVED NOT DRAWN. A climbing wall is the room's own wall with
     holds on it. This reads the existing wall metatile out of the fork, checks
     it really is the two-tile vertical-panel repeat it is supposed to be, and
     stamps holds onto copies of those exact tiles in colours ALREADY IN THAT
     TILESET'S PALETTE. Nothing is invented: no new tile art, no new palette
     entry, no palette edit at all. Doc 75's rule -- when a generator keeps
     under-delivering, ask whether the artifact can be DERIVED -- and the same
     rule new_map.py --dump-layout applies to map data and check_dialogue.py
     applies to prose. It is also the only rule that WORKS here: doc 75 measured
     the generators' resolution floor at 32 px and a metatile is 16.

  2. THE ROOM. The annex is 12x11 with three rows of wall at the top and nothing
     above them, so a climb had nowhere to arrive. This grows it upward by six
     rows -- an upper floor with its own back wall -- and turns one column of the
     lower room's back wall into the climbable strip. The map's `num` does not
     change, so nothing save-visible moves (doc 65's append-only rule is about
     map numbers, not layout dimensions).

WHAT IS DERIVED FROM THE FORK RATHER THAN HARDCODED: MB_CLIMBABLE_WALL's value,
NUM_TILES_IN_PRIMARY, NUM_METATILES_IN_PRIMARY, the block-word field masks, the
map-size ceiling, the source wall metatile's tile composition and palette, and
the tile count in graphics_file_rules.mk. If any of them moves, this refuses.

USAGE
    python3 tools/make_climb_wall.py --hack hacks/reps
    python3 tools/make_climb_wall.py --check     # verify, write nothing

Exit 0 = the fork is in the wanted end state. 1 = --check found it is not.
2 = cannot run.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

import hx

sys.path.insert(0, str(Path(__file__).resolve().parent))

import new_map  # noqa: E402  (pack_block / read_masks / write_bin / the ceiling check)

try:
    from PIL import Image
except ImportError:
    sys.exit("cannot run: needs Pillow (pip install pillow)")


LAYOUT_ID = "LAYOUT_RUSTBORO_CITY_TRAINING_ANNEX"
LAYOUT_DIR = "data/layouts/RustboroCity_TrainingAnnex"
TILESET_DIR = "data/tilesets/secondary/pokemon_school"
TILESET_RULE = "$(TILESETGFXDIR)/secondary/pokemon_school/tiles.4bpp"

# The room's plain wall. Asserted, not trusted: see check_source_wall().
SOURCE_WALL_METATILE = 528
NEW_TILE_COUNT = 8          # two metatiles' worth
NEW_METATILE_COUNT = 2

# Hold positions per new tile, as (x, y, palette_index) in an 8x8 cell. The three
# colours are indices that already exist in this tileset's palette 6 -- green,
# orange and pale blue -- so the wall needs no palette edit and cannot disturb
# anything else drawn with it.
HOLD_GREEN, HOLD_ORANGE, HOLD_BLUE = 8, 6, 13
HOLDS = [
    [(2, 1, HOLD_GREEN), (5, 5, HOLD_ORANGE)],
    [(1, 3, HOLD_BLUE)],
    [(4, 2, HOLD_ORANGE)],
    [(2, 6, HOLD_GREEN), (5, 1, HOLD_BLUE)],
    [(5, 2, HOLD_BLUE)],
    [(2, 4, HOLD_GREEN), (5, 6, HOLD_ORANGE)],
    [(1, 1, HOLD_ORANGE), (4, 5, HOLD_GREEN)],
    [(3, 3, HOLD_BLUE)],
]


def die(msg: str):
    sys.exit(f"cannot run: {msg}")


def read_define(path: Path, name: str) -> int:
    if not path.is_file():
        die(f"missing {path}")
    m = re.search(rf"^#define\s+{name}\s+(0x[0-9A-Fa-f]+|\d+)", path.read_text(), re.M)
    if not m:
        die(f"#define {name} not found in {path}")
    return int(m.group(1), 0)


# ------------------------------------------------------------------ the art

def entry(tile_id: int, palette: int) -> int:
    return (tile_id & 0x3FF) | ((palette & 0xF) << 12)


def check_source_wall(hack: Path, tile_split: int, meta_split: int):
    """Read the wall metatile and prove it is the shape this tool assumes.

    Returns (palette, [the four bottom-layer secondary tile indices], top layer).
    """
    blob = (hack / TILESET_DIR / "metatiles.bin").read_bytes()
    idx = SOURCE_WALL_METATILE - meta_split
    if (idx + 1) * 16 > len(blob):
        die(f"metatile {SOURCE_WALL_METATILE} is past the end of the tileset")
    ent = struct.unpack_from("<8H", blob, idx * 16)
    bottom, top = ent[:4], ent[4:]

    pals = {(e >> 12) & 0xF for e in bottom}
    if len(pals) != 1:
        die(f"metatile {SOURCE_WALL_METATILE} mixes palettes {sorted(pals)} -- "
            "this tool stamps holds in one palette and cannot span two")
    palette = pals.pop()
    if any(e & 0x0C00 for e in bottom):
        die(f"metatile {SOURCE_WALL_METATILE} uses flipped tiles -- a stamped hold "
            "would be mirrored and the derivation would not be lossless")
    ids = [e & 0x3FF for e in bottom]
    if any(t < tile_split for t in ids):
        die(f"metatile {SOURCE_WALL_METATILE} draws from the PRIMARY tileset "
            f"({ids}); this tool appends to the secondary and cannot copy those")
    if not (ids[0] == ids[2] and ids[1] == ids[3]):
        die(f"metatile {SOURCE_WALL_METATILE} is not the vertical two-tile repeat "
            f"this tool derives from (tiles {ids})")
    return palette, [t - tile_split for t in ids], top


def highest_referenced_tile(hack: Path, tile_split: int, skip_from: int) -> int:
    """The highest SECONDARY tile index any existing metatile draws from.

    THIS IS NOT THE SAME AS THE DECLARED TILE COUNT, and assuming it was cost
    this round a build: gTileset_PokemonSchool's build rule ships 278 tiles, and
    its window metatiles (529, 530, 537, 538) reference tiles 279, 280 and 281.
    Those are blank in tiles.png and truncated away by -num_tiles, so in the
    shipped game they are whatever the previously-loaded tileset left in VRAM.

    Append art at the declared count and it lands *underneath four metatiles
    that are already in use*: the annex's windows come back drawn as climbing
    wall, in the right place, correctly tiled, looking entirely deliberate.
    Another plausible artifact, and no probe has a wrong number to find.

    So the first free tile is derived from what is REFERENCED, never from what
    is declared. `skip_from` excludes our own metatiles on a re-run.
    """
    blob = (hack / TILESET_DIR / "metatiles.bin").read_bytes()
    highest = -1
    for i in range(len(blob) // 16):
        if i + tile_split >= skip_from:
            break
        for e in struct.unpack_from("<8H", blob, i * 16):
            t = e & 0x3FF
            if t >= tile_split:
                highest = max(highest, t - tile_split)
    return highest


def assert_no_collision(hack: Path, tile_split: int, first: int, count: int, upto: int):
    """Nothing that already existed may draw from the tiles we just claimed."""
    blob = (hack / TILESET_DIR / "metatiles.bin").read_bytes()
    claimed = set(range(first, first + count))
    for i in range(len(blob) // 16):
        if i + tile_split >= upto:
            break
        for e in struct.unpack_from("<8H", blob, i * 16):
            t = e & 0x3FF
            if t >= tile_split and (t - tile_split) in claimed:
                die(f"metatile {i + tile_split} already draws from secondary tile "
                    f"{t - tile_split}, which this tool is about to overwrite")


def png_cells(img: Image.Image) -> int:
    return (img.width // 8) * (img.height // 8)


def grow_png(img: Image.Image, need_cells: int) -> Image.Image:
    """Add whole rows of blank cells until the sheet holds `need_cells`."""
    cols = img.width // 8
    rows_needed = (need_cells + cols - 1) // cols
    if rows_needed * 8 <= img.height:
        return img
    bigger = Image.new("P", (img.width, rows_needed * 8), 0)
    bigger.putpalette(img.getpalette())
    bigger.paste(img, (0, 0))
    return bigger


def read_cell(img, cell):
    cols = img.width // 8
    ox, oy = (cell % cols) * 8, (cell // cols) * 8
    return [img.getpixel((ox + x, oy + y)) for y in range(8) for x in range(8)]


def write_cell(img, cell, px):
    cols = img.width // 8
    ox, oy = (cell % cols) * 8, (cell // cols) * 8
    for y in range(8):
        for x in range(8):
            img.putpixel((ox + x, oy + y), px[y * 8 + x])


def stamp(px: list, holds) -> list:
    """A hold is a 2x2 block. Small on purpose: the cast is 14 px wide."""
    out = list(px)
    for hx, hy, color in holds:
        for dy in range(2):
            for dx in range(2):
                x, y = hx + dx, hy + dy
                if 0 <= x < 8 and 0 <= y < 8:
                    out[y * 8 + x] = color
    return out


def build_art(hack: Path, base_tiles, current_count: int, check: bool) -> bool:
    """Append the stamped tiles to tiles.png. Returns True if already correct."""
    png = hack / TILESET_DIR / "tiles.png"
    img = Image.open(png)
    if img.mode != "P":
        die(f"{png} is {img.mode}, not indexed -- gbagfx needs an indexed PNG")
    need = current_count + NEW_TILE_COUNT
    if png_cells(img) < need:
        if check:
            return False
        img = grow_png(img, need)

    wanted = []
    for i in range(NEW_TILE_COUNT):
        src = base_tiles[i % len(base_tiles)]
        wanted.append(stamp(read_cell(img, src), HOLDS[i]))

    already = all(read_cell(img, current_count + i) == wanted[i]
                  for i in range(NEW_TILE_COUNT))
    if already or check:
        return already
    for i, px in enumerate(wanted):
        write_cell(img, current_count + i, px)
    img.save(png)
    back = Image.open(png)
    for i in range(NEW_TILE_COUNT):
        if read_cell(back, current_count + i) != wanted[i]:
            die(f"tiles.png cell {current_count + i} read back different")
    print(f"  wrote   {png} (cells {current_count}..{current_count + NEW_TILE_COUNT - 1})")
    return False


def build_metatiles(hack: Path, palette, base_tiles, top, first_tile,
                    behavior: int, tile_split: int, check: bool) -> bool:
    meta = hack / TILESET_DIR / "metatiles.bin"
    attr = hack / TILESET_DIR / "metatile_attributes.bin"
    mblob, ablob = meta.read_bytes(), attr.read_bytes()
    have = len(mblob) // 16
    if len(ablob) // 2 != have:
        die(f"{have} metatiles but {len(ablob)//2} attribute entries")

    rows, attrs = [], []
    for m in range(NEW_METATILE_COUNT):
        ids = [first_tile + tile_split + m * 4 + q for q in range(4)]
        rows.append(struct.pack("<8H", *[entry(t, palette) for t in ids], *top))
        # Behavior in the low byte; everything above it copied from the wall this
        # is derived from, so the layer type cannot drift from its source.
        attrs.append(struct.pack("<H", behavior))

    want_meta = mblob + b"".join(rows)
    want_attr = ablob + b"".join(attrs)
    if mblob[-NEW_METATILE_COUNT * 16:] == b"".join(rows) and \
       ablob[-NEW_METATILE_COUNT * 2:] == b"".join(attrs):
        return True
    if check:
        return False
    meta.write_bytes(want_meta)
    attr.write_bytes(want_attr)
    print(f"  wrote   {meta} + attributes ({NEW_METATILE_COUNT} metatiles, "
          f"ids {have + tile_split}..{have + tile_split + NEW_METATILE_COUNT - 1})")
    return False


NUM_TILES_ANCHOR = (
    re.escape(TILESET_RULE)
    + r":\s*%\.4bpp:\s*%\.png\n\t\$\(GFX\) \$< \$@ -num_tiles (\d+)"
)


def read_num_tiles(hack: Path) -> int:
    """How many tiles gbagfx is told to emit. NOT how many the PNG holds, and
    NOT how many the metatiles reference -- see highest_referenced_tile()."""
    m = re.search(NUM_TILES_ANCHOR, (hack / "graphics_file_rules.mk").read_text())
    if not m:
        die("the pokemon_school tiles.4bpp rule is not where this tool expects it "
            "in graphics_file_rules.mk")
    return int(m.group(1))


def bump_tile_count(hack: Path, new: int, check: bool) -> bool:
    path = hack / "graphics_file_rules.mk"
    text = path.read_text()
    m = re.search(NUM_TILES_ANCHOR, text)
    have = int(m.group(1))
    if have == new:
        return True
    if check:
        return False
    text = text[:m.start(1)] + str(new) + text[m.end(1):]
    path.write_text(text)
    if read_num_tiles(hack) != new:
        die("the -num_tiles edit did not land -- refusing to leave the tree half-done")
    print(f"  wrote   {path} (-num_tiles {have} -> {new})")
    return False


# ------------------------------------------------------------------ the room

def build_room(hack: Path, masks, climb_ids, check: bool) -> bool:
    """Grow the annex upward and cut the climbable strip into its back wall.

    The upper level is built from the room's OWN wall and floor blocks, read out
    of the existing map rather than named -- so it matches whatever the room is
    made of, and a later retheme of the annex carries up here for free.
    """
    layouts_path = hack / "data/layouts/layouts.json"
    layouts = json.loads(layouts_path.read_text())
    lay = next((l for l in layouts["layouts"] if l["id"] == LAYOUT_ID), None)
    if lay is None:
        die(f"{LAYOUT_ID} not in layouts.json")
    w, h = lay["width"], lay["height"]
    grid = new_map.read_bin(hack / LAYOUT_DIR / "map.bin")
    if len(grid) != w * h:
        die(f"{LAYOUT_ID} is {w}x{h} but its map.bin holds {len(grid)} blocks")

    if h == BASE_HEIGHT + UPPER_ROWS:
        return True     # already grown; nothing to do
    if h != BASE_HEIGHT:
        die(f"{LAYOUT_ID} is {w}x{h}; this tool grows the {w}x{BASE_HEIGHT} room "
            "and does not know what to do with any other shape")
    if check:
        return False

    def row(y):
        return grid[y * w:(y + 1) * w]

    # The room's own parts, taken from the rows they already occupy.
    cap_row = row(0)            # ceiling cap
    wall_row = row(1)           # back wall proper
    band_row = row(2)           # the walkable strip at the wall's foot
    edge_row = row(3)           # floor edge
    floor_blk = row(5)[2]       # a plain floor block, away from the furniture

    plain_wall = wall_row[0]    # column 0 is wall with no window in it
    plain_band = band_row[0]
    plain_cap = cap_row[1]

    upper = (
        [plain_cap] * w
        + [plain_wall] * w
        + [plain_band] * w
        + [edge_row[1]] * w
        + [floor_blk] * w
        + [floor_blk] * w
    )
    if len(upper) != UPPER_ROWS * w:
        die("internal: upper level built the wrong number of rows")

    new_grid = upper + grid

    # Cut the strip: the cap row and the wall row of the LOWER room's back wall,
    # which are now rows UPPER_ROWS+0 and UPPER_ROWS+1.
    for i, y in enumerate((UPPER_ROWS + 0, UPPER_ROWS + 1)):
        new_grid[y * w + CLIMB_COLUMN] = new_map.pack_block(
            masks, climb_ids[i], CLIMB_COLLISION, CLIMB_ELEVATION)

    new_map.check_size_ceiling(hack, w, BASE_HEIGHT + UPPER_ROWS)
    new_map.write_bin(hack / LAYOUT_DIR / "map.bin", new_grid, "annex, grown upward")

    lay["height"] = BASE_HEIGHT + UPPER_ROWS
    layouts_path.write_text(json.dumps(layouts, indent=2) + "\n")
    check_lay = next(l for l in json.loads(layouts_path.read_text())["layouts"]
                     if l["id"] == LAYOUT_ID)
    if check_lay["height"] != BASE_HEIGHT + UPPER_ROWS:
        die("layouts.json height did not land")
    print(f"  wrote   {layouts_path} ({LAYOUT_ID} height {h} -> "
          f"{BASE_HEIGHT + UPPER_ROWS})")

    shift_events(hack)
    return False


def shift_events(hack: Path):
    """Move every event down by the rows inserted above it.

    Growing a map at the TOP moves everything already in it, and map.json's
    coordinates do not know that. Nothing errors if this is skipped: the coach
    stands six tiles north of where she was (inside the new wall), the door warp
    sits on a tile with no door behavior and simply does nothing, and the
    blackboard sign is unreachable. check_map.py catches two of those three,
    which is the argument for running it before the build rather than after.
    """
    path = hack / "data/maps/RustboroCity_TrainingAnnex/map.json"
    data = json.loads(path.read_text())
    moved = 0
    for key in ("object_events", "warp_events", "coord_events", "bg_events"):
        for ev in data.get(key) or []:
            if "y" in ev:
                ev["y"] += UPPER_ROWS
                moved += 1
    path.write_text(json.dumps(data, indent=2) + "\n")
    back = json.loads(path.read_text())
    for key in ("object_events", "warp_events", "coord_events", "bg_events"):
        for a, b in zip(back.get(key) or [], data.get(key) or []):
            if a.get("y") != b.get("y"):
                die("map.json event shift did not land")
    print(f"  wrote   {path} ({moved} events moved down {UPPER_ROWS} rows)")


BASE_METATILES = 58     # what gTileset_PokemonSchool ships
BASE_HEIGHT = 11
UPPER_ROWS = 6
# COLUMN 0, AND THE REASON IS A HARNESS RULE RATHER THAN A VISUAL ONE.
# Doc 65: in a scripted input timeline every leg of a walk should end AGAINST
# something -- a move that has to stop in open space is a frame count that will
# drift. With the strip at column 1 the route needed a one-tile Right, and it
# overshot to column 2 on the first run: the player then faced ordinary wall,
# every climb probe read zero, and it looked exactly like a dead feature.
# Against the map edge, `Left until you stop` lands on the strip exactly, and
# `Up` then stops against the wall itself. Two legs, no frame counts.
CLIMB_COLUMN = 0
CLIMB_COLLISION = 1     # walking into it bumps; the field move is the only way up
CLIMB_ELEVATION = 3


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hack", default=str(hx.default_hack()))
    ap.add_argument("--check", action="store_true",
                    help="report whether the fork is already in the end state; write nothing")
    args = ap.parse_args()
    hack = Path(args.hack)
    if not hack.is_dir():
        die(f"no such tree {hack}")

    behavior = read_define(hack / "include/constants/metatile_behaviors.h",
                           "MB_CLIMBABLE_WALL")
    tile_split = read_define(hack / "include/fieldmap.h", "NUM_TILES_IN_PRIMARY")
    meta_split = read_define(hack / "include/fieldmap.h", "NUM_METATILES_IN_PRIMARY")
    masks = new_map.read_masks(hack)

    palette, base_tiles, top = check_source_wall(hack, tile_split, meta_split)

    # Our own metatiles are appended, so on a re-run they are the tail. Everything
    # before them is "what already existed" for both the collision check and the
    # first-free-tile search.
    have_meta = len(((hack / TILESET_DIR / "metatiles.bin").read_bytes())) // 16
    first_meta = have_meta - NEW_METATILE_COUNT if have_meta > BASE_METATILES else have_meta
    if first_meta != BASE_METATILES:
        die(f"{TILESET_DIR} holds {have_meta} metatiles; this tool expects "
            f"{BASE_METATILES} or {BASE_METATILES + NEW_METATILE_COUNT}")
    climb_ids = [first_meta + meta_split + i for i in range(NEW_METATILE_COUNT)]
    upto = first_meta + meta_split

    referenced = highest_referenced_tile(hack, tile_split, upto)
    declared = read_num_tiles(hack)
    base_count = max(declared, referenced + 1)
    # On a re-run `declared` already includes our tiles; back them out.
    if declared >= referenced + 1 + NEW_TILE_COUNT:
        base_count = declared - NEW_TILE_COUNT
    assert_no_collision(hack, tile_split, base_count, NEW_TILE_COUNT, upto)

    print(f"climbing wall -> {hack}")
    print(f"  behavior MB_CLIMBABLE_WALL = {behavior:#04x}")
    print(f"  derived from metatile {SOURCE_WALL_METATILE} "
          f"(palette {palette}, tiles {base_tiles})")
    print(f"  tiles declared {declared}, highest referenced {referenced} "
          f"-> new art at {base_count}..{base_count + NEW_TILE_COUNT - 1}")
    print(f"  metatiles {climb_ids}, column {CLIMB_COLUMN}")

    states = [
        build_art(hack, base_tiles, base_count, args.check),
        build_metatiles(hack, palette, base_tiles, top, base_count, behavior,
                        tile_split, args.check),
        bump_tile_count(hack, base_count + NEW_TILE_COUNT, args.check),
        build_room(hack, masks, climb_ids, args.check),
    ]
    if args.check:
        ok = all(states)
        print("  end state: " + ("present" if ok else "NOT present"))
        return 0 if ok else 1
    print("  done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
