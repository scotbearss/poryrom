#!/usr/bin/env python3
"""Render a background layer out of the pinned engine's raw assets, as a PNG.

WHY THIS EXISTS. `reps` slice 3.6 reused the engine's contest-condition graph and
got it visually wrong, and the thing that diagnosed it was decoding what the
ORIGINAL screen is actually made of (design/reps/reports/
2026-07-30-pentagon-fidelity.md). The headline of that review was that the
pentagon is mostly static ART -- frame, spokes, vertex discs and labels are one
208-tile background image, and only the fill is computed. Prose could not have
carried that; a picture did.

So this is the recipe, tracked, the way tools/make_savestate.py is the
recipe for save states. Re-run it after each visual fix and diff the result
against a fresh screenshot -- that turns a one-off comparison into a repeatable
check, which is the whole point.

`engine/` is gitignored and Nintendo-derived, so this script reads it and
never copies from it. What it emits is a render for looking at, in a PRIVATE
workshop repo, not an asset that goes anywhere near a product (CLAUDE.md
-- nothing in this folder can ever ship, renders least of all).

Usage:

    python3 tools/render_reference.py \\
        --tiles graphics/pokeblock/use_screen/graph.4bpp \\
        --map   graphics/pokeblock/use_screen/graph.bin \\
        --pal   graphics/pokeblock/use_screen/graph.gbapal \\
        --width 32 --pal-base 2 --tile-base 640 \\
        --out   /tmp/graph.png --scale 2

Paths are relative to engine/ unless absolute. Needs Pillow.
"""

import argparse
import struct
import sys
from pathlib import Path

import hx  # noqa: E402
REPO_ROOT = hx.HARNESS_ROOT
ENGINE = hx.ENGINE

TILE_BYTES = 32          # 8x8 pixels, 4 bits each
PAL_ENTRIES = 16


def resolve(p):
    path = Path(p)
    return path if path.is_absolute() else ENGINE / path


def read_palettes(path):
    """A .gbapal is a flat run of BGR555 u16s: 16 colours per bank, N banks.

    Index 0 of every bank is TRANSPARENT on a background, not black -- callers
    that composite must honour that or every render comes out with a black
    rectangle where the screen should show through.
    """
    raw = resolve(path).read_bytes()
    banks = []
    for base in range(0, len(raw), PAL_ENTRIES * 2):
        chunk = raw[base:base + PAL_ENTRIES * 2]
        if len(chunk) < PAL_ENTRIES * 2:
            break
        bank = []
        for i in range(PAL_ENTRIES):
            v = struct.unpack_from("<H", chunk, i * 2)[0]
            # BGR555 -> RGB888. The <<3 | >>2 form fills the low bits so white
            # comes out 255 rather than 248; a plain <<3 makes every render
            # slightly dark and it is the classic way these decodes go wrong.
            r, g, b = v & 31, (v >> 5) & 31, (v >> 10) & 31
            bank.append(((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)))
        banks.append(bank)
    return banks


def read_tiles(path):
    raw = resolve(path).read_bytes()
    tiles = []
    for base in range(0, len(raw) - TILE_BYTES + 1, TILE_BYTES):
        px = [[0] * 8 for _ in range(8)]
        for row in range(8):
            for pair in range(4):
                byte = raw[base + row * 4 + pair]
                px[row][pair * 2] = byte & 0xF          # low nibble is the LEFT pixel
                px[row][pair * 2 + 1] = byte >> 4
        tiles.append(px)
    return tiles


def render(tiles, mapping, banks, width_tiles, pal_base=0, tile_base=0):
    from PIL import Image

    entries = len(mapping) // 2
    height_tiles = max(1, entries // width_tiles)
    img = Image.new("RGBA", (width_tiles * 8, height_tiles * 8), (0, 0, 0, 0))
    px = img.load()

    for i in range(min(entries, width_tiles * height_tiles)):
        entry = struct.unpack_from("<H", mapping, i * 2)[0]
        # Tile ids in a tilemap are absolute within the CHAR BLOCK, and an
        # asset is loaded at some offset inside it (use_pokeblock.c's BG3
        # template carries `.baseTile = 0x100`, and graph.bin's ids start at
        # 640). Subtract where this .4bpp was loaded to. Get it wrong and every
        # id lands past the end of the tile list and the render is BLANK --
        # which is exactly how this script failed first time.
        tile_id = (entry & 0x3FF) - tile_base
        hflip = bool(entry & 0x400)
        vflip = bool(entry & 0x800)
        # The tilemap's palette field is an ABSOLUTE BG palette bank (0..15),
        # but a .gbapal usually holds only the one or two banks that asset gets
        # loaded into -- so the raw number indexes off the end. --pal-base says
        # which BG bank the file's first bank is loaded to; out-of-range after
        # that means the tile uses a palette this file does not contain, and
        # clamping is the honest fallback (the render will be wrong THERE and
        # right everywhere else, which is more useful than refusing to draw).
        want = ((entry >> 12) & 0xF) - pal_base
        bank = banks[want] if 0 <= want < len(banks) else banks[0]
        if not (0 <= tile_id < len(tiles)):
            continue
        tile = tiles[tile_id]
        tx, ty = (i % width_tiles) * 8, (i // width_tiles) * 8
        for y in range(8):
            sy = 7 - y if vflip else y
            for x in range(8):
                sx = 7 - x if hflip else x
                idx = tile[sy][sx]
                # Index 0 is transparent, NOT bank[0]. See read_palettes().
                px[tx + x, ty + y] = (0, 0, 0, 0) if idx == 0 else (*bank[idx], 255)
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tiles", required=True, help="uncompressed .4bpp, relative to engine/")
    ap.add_argument("--map", required=True, help="uncompressed .bin tilemap")
    ap.add_argument("--pal", required=True, help=".gbapal")
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=32, help="tilemap width in tiles (default 32)")
    ap.add_argument("--pal-base", type=int, default=0,
                    help="which BG palette bank this .gbapal is loaded into "
                         "(the tilemap stores absolute bank numbers)")
    ap.add_argument("--tile-base", type=int, default=0,
                    help="tile index this .4bpp is loaded at (graph.bin uses 640)")
    ap.add_argument("--scale", type=int, default=1)
    args = ap.parse_args()

    for label, p in (("tiles", args.tiles), ("map", args.map), ("pal", args.pal)):
        if not resolve(p).exists():
            sys.exit(f"error: {label} not found: {resolve(p)}\n"
                     f"       engine/ is gitignored -- clone the pin first "
                     f"(see CLAUDE.md).")

    tiles = read_tiles(args.tiles)
    mapping = resolve(args.map).read_bytes()
    banks = read_palettes(args.pal)
    if not banks:
        sys.exit("error: palette file held no complete 16-colour bank")

    img = render(tiles, mapping, banks, args.width, args.pal_base, args.tile_base)
    if args.scale > 1:
        from PIL import Image
        img = img.resize((img.width * args.scale, img.height * args.scale), Image.NEAREST)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"{out}  {img.width}x{img.height}  "
          f"{len(tiles)} tiles, {len(banks)} palette bank(s)")


if __name__ == "__main__":
    main()
