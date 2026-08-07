#!/usr/bin/env python3
"""Generate the big countdown digits (BG3) for the `reps` hack's running set.

WHY THIS SCRIPT EXISTS
----------------------
Slice 4's Soul is "a set runs itself from across the room". During a 60-second
wall sit the player is on the floor with the console beside them, and until this
slice the seconds remaining were `LEFT: 47 SEC` in FONT_NORMAL body text in the
top-left corner of a mostly empty window -- roughly 8 px tall, at the far end of
a room, while you are shaking. The number has to be big or the feature does not
work, and no amount of audio substitutes for being able to glance at it.

WHY IT DERIVES THE GLYPHS FROM THE PIN INSTEAD OF DRAWING THEM
--------------------------------------------------------------
This project's standing art rule (locked 2026-07-31, after the pentagon round)
is GENERATE, never hand-draw -- and where the original has something to derive
from, derive from it rather than inventing a parallel version that drifts.

Emerald does ship a set of big countdown numerals: the Berry Blender's
`graphics/berry_blender/countdown_numbers.png`, 32x32 each, chunky and outlined.
They are the right idiom and they are unusable here, because the Berry Blender
only ever counts 3, 2, 1 -- there is no 0, and no 4 through 9. Extrapolating the
missing seven by hand would be exactly the hand-drawing the rule forbids, and
they would sit next to three authentic glyphs advertising the difference.

So the glyphs come from the pin's OWN font sheet instead:
`graphics/fonts/latin_normal.png`, the FONT_NORMAL glyph atlas, at character
codes 0xA1..0xAA (charmap.txt's '0'..'9'). Those are the letterforms already on
every other line of this screen. We take the foreground stroke, drop the font's
own 1 px drop-shadow, scale 2x, and re-outline in the Berry Blender's heavier
style. The result is the game's own digit, at four times the area, wearing the
game's own countdown treatment. Nothing about the shape is invented here.

WHAT IT COSTS (measured, against scope.md sec. Slice 4's budget)
----------------------------------------------------------------
Ten glyphs at 2x3 tiles = 60 tiles, against a ceiling of 60 for digits and 180
for the slice. One BG palette bank of the 10 free. Zero EWRAM -- the arrays are
`const`, so they land in ROM, which is at 77%.

OUTPUT
------
A C header of `const` arrays written into the hack fork. `hacks/` is gitignored
and disposable, so THIS FILE is the durable artifact and the header is a build
product -- the same relationship `make_card_panel.py` has to its panel. DO NOT
hand-edit the header; regenerate it.

Usage:
    python3 tools/make_countdown_digits.py \
        --engine engine \
        --out    hacks/reps/include/training_countdown_gfx.h
    python3 tools/make_countdown_digits.py --engine ... --preview /tmp/d.png
"""

import argparse
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Geometry, and it was MEASURED rather than picked.
#
# FONT_NORMAL's digits trim to 5x9 px of actual ink (all ten of them; '1' is
# 3 wide). So the cell size falls out of the scale factor rather than being a
# taste decision:
#
#   2x -> 10x18 ink, 13x21 with outline and shadow -> 2x3 tiles ->  60 tiles
#   3x -> 15x27 ink, 18x30 with outline and shadow -> 3x4 tiles -> 120 tiles
#
# 3x, because the whole point of the slice is reading the number from the floor
# and 27 px of digit beats 18 for 60 more tiles out of a budget with ~340 free
# (scope.md sec. Slice 4 caps this slice at 180 on charbase 0). 3x also makes
# the stroke 3 px wide instead of 2, which is most of why it stops looking like
# scaled body text and starts looking like a timer.
#
# 4x would be 20x36 ink in a 4x5-tile cell = 200 tiles, over the slice's stated
# ceiling, and two digits would be 64 px wide inside a 208 px window -- it would
# own the screen rather than sit on it.
# --------------------------------------------------------------------------
SCALE = 3
DIGIT_W_TILES = 3
DIGIT_H_TILES = 4
DIGIT_W = DIGIT_W_TILES * 8          # 24
DIGIT_H = DIGIT_H_TILES * 8          # 32
DIGIT_COUNT = 10

# Where the digits live in the font atlas. charmap.txt maps '0' to 0xA1 and the
# atlas is a 16-column grid of 16x16 cells indexed by character code, so '0' is
# row 10, column 1. Asserted at runtime below rather than trusted: a font sheet
# that moved would otherwise emit ten plausible-looking wrong glyphs.
FONT_SHEET = "graphics/fonts/latin_normal.png"
FONT_CELL = 16
FONT_COLS = 16
CHAR_ZERO = 0xA1

# The font atlas's own palette indices. 0 is the transparent field, 1 is the
# stroke, 2 is the font's built-in drop shadow. We keep 1 and deliberately
# DISCARD 2 -- a 1 px shadow scaled 2x becomes a 2 px smear, and we are drawing
# a heavier outline of our own anyway.
FONT_INK = 1

# Our output palette.
#
# EACH CELL IS AN OPAQUE PLATE, NOT A TRANSPARENT FIELD, and that is a fix
# rather than a preference. BG_PANEL sits at priority 3, BEHIND the body window,
# so the digits are seen through a rectangle of PIXEL_FILL(0) punched in it --
# and whatever the digit tiles leave transparent shows the SCREEN BACKDROP,
# RGB(17,18,31). That periwinkle is the exact colour the pentagon round named as
# "the single biggest cause of weird colors"; the first build of this screen put
# a hard-edged box of it in the middle of a white card.
#
# So the cells carry their own plate, in the card panel's own pale blue, and the
# digits are dark ON it. Matching the body window's white instead was the other
# candidate and is worse: an almost-but-not-quite match reads as a rendering
# bug, where a plate that is deliberately a different colour reads as a plate --
# and this one is the same plate the training card already uses.
#
# Index 0 stays transparent and unused. Every other cell of BG3's 32x32 tilemap
# is entry 0 and must disappear.
PAL_TRANSPARENT = 0
PAL_PLATE = 1
PAL_FILL = 2
PAL_HILIGHT = 3

COLORS = {
    PAL_PLATE:   (23, 27, 30),   # #BDDEF6, the training card panel's pale blue
    PAL_FILL:    (11, 11, 13),   # deep slate, the card's own border_dark
    PAL_HILIGHT: (31, 31, 31),   # white, offset down-right -- engraves the glyph
}


def load_font_digits(engine: Path):
    """Pull '0'..'9' out of the pin's FONT_NORMAL atlas as boolean ink masks."""
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Pillow is required: pip3 install pillow")

    sheet_path = engine / FONT_SHEET
    if not sheet_path.exists():
        sys.exit("font atlas not found: %s" % sheet_path)

    sheet = Image.open(sheet_path)
    if sheet.mode != "P":
        sys.exit("expected an indexed (P-mode) font atlas, got %s" % sheet.mode)

    masks = []
    for i in range(DIGIT_COUNT):
        code = CHAR_ZERO + i
        row, col = divmod(code, FONT_COLS)
        cell = sheet.crop((col * FONT_CELL, row * FONT_CELL,
                           col * FONT_CELL + FONT_CELL, row * FONT_CELL + FONT_CELL))
        px = cell.load()
        mask = [[px[x, y] == FONT_INK for x in range(FONT_CELL)]
                for y in range(FONT_CELL)]
        if not any(any(r) for r in mask):
            sys.exit("glyph for '%d' (code 0x%02X) is empty -- the atlas layout "
                     "moved; re-derive CHAR_ZERO from charmap.txt" % (i, code))
        masks.append(mask)
    return masks


def trim(mask):
    """Crop a glyph mask to its ink bounding box."""
    rows = [y for y, r in enumerate(mask) if any(r)]
    cols = [x for x in range(len(mask[0])) if any(r[x] for r in mask)]
    return [[mask[y][x] for x in cols] for y in rows]


def scale(mask, n=SCALE):
    out = []
    for row in mask:
        wide = [v for v in row for _ in range(n)]
        for _ in range(n):
            out.append(list(wide))
    return out


def render_glyph(mask):
    """Scale, engrave, and centre on an opaque plate DIGIT_W x DIGIT_H."""
    g = scale(trim(mask))
    gh, gw = len(g), len(g[0])

    # +1 on each axis for the highlight offset; the plate needs no margin
    # because it fills the cell.
    need_w, need_h = gw + 1, gh + 1
    if need_w > DIGIT_W or need_h > DIGIT_H:
        sys.exit("glyph does not fit: needs %dx%d, cell is %dx%d"
                 % (need_w, need_h, DIGIT_W, DIGIT_H))

    cell = [[PAL_PLATE] * DIGIT_W for _ in range(DIGIT_H)]
    ox = (DIGIT_W - gw) // 2
    oy = (DIGIT_H - gh) // 2

    def inside(x, y):
        return 0 <= x < DIGIT_W and 0 <= y < DIGIT_H

    # Highlight first, offset down-right by one, then the dark glyph on top of
    # it. What is left showing is a one-pixel white edge along the bottom-right
    # of every stroke, which is how the engine's own UI plates catch the light.
    for y in range(gh):
        for x in range(gw):
            if g[y][x] and inside(ox + x + 1, oy + y + 1):
                cell[oy + y + 1][ox + x + 1] = PAL_HILIGHT

    for y in range(gh):
        for x in range(gw):
            if g[y][x] and inside(ox + x, oy + y):
                cell[oy + y][ox + x] = PAL_FILL

    return cell


def to_tiles(cells):
    """4bpp, GBA order: 8x8 tiles, row-major within a tile, two pixels per byte,
    LOW nybble first. Digit-major, then row-major within the digit, so tile
    index = digit * DIGIT_TILES + ty * DIGIT_W_TILES + tx."""
    tiles = []
    for cell in cells:
        for ty in range(DIGIT_H_TILES):
            for tx in range(DIGIT_W_TILES):
                words = []
                for row in range(8):
                    v = 0
                    for col in range(8):
                        p = cell[ty * 8 + row][tx * 8 + col] & 0xF
                        v |= p << (col * 4)
                    words.append(v & 0xFFFFFFFF)
                tiles.append(words)
    return tiles


def emit_header(path: Path, tiles, argv):
    lines = []
    lines.append("// GENERATED by tools/make_countdown_digits.py -- DO NOT EDIT BY HAND.")
    lines.append("//")
    lines.append("// The big seconds-remaining digits for STATE_RUNNING_SET. Slice 4's Soul is")
    lines.append("// that a set runs itself from across the room, and until this the number was")
    lines.append("// FONT_NORMAL body text about 8 px tall.")
    lines.append("//")
    lines.append("// The letterforms are the PIN'S OWN: FONT_NORMAL's glyph atlas at character")
    lines.append("// codes 0xA1..0xAA (5x9 px of ink each), scaled %dx with the font's 1 px drop" % SCALE)
    lines.append("// shadow discarded and a heavier outline applied in the Berry Blender")
    lines.append("// countdown's style. Emerald's actual countdown numerals were the first")
    lines.append("// choice and only ship 1, 2 and 3, which is no use for a 60-second timer.")
    lines.append("//")
    lines.append("// Regenerate with:")
    lines.append("//   %s" % " ".join(argv))
    lines.append("")
    lines.append("#ifndef GUARD_TRAINING_COUNTDOWN_GFX_H")
    lines.append("#define GUARD_TRAINING_COUNTDOWN_GFX_H")
    lines.append("")
    lines.append("#define CD_DIGIT_W_TILES   %d" % DIGIT_W_TILES)
    lines.append("#define CD_DIGIT_H_TILES   %d" % DIGIT_H_TILES)
    lines.append("#define CD_DIGIT_TILES     (CD_DIGIT_W_TILES * CD_DIGIT_H_TILES)")
    lines.append("#define CD_DIGIT_COUNT     %d" % DIGIT_COUNT)
    lines.append("#define CD_NUM_TILES       %d" % len(tiles))
    lines.append("")
    lines.append("// tile index of digit d's tile (tx, ty), relative to the base tile the")
    lines.append("// screen loads these at.")
    lines.append("#define CD_TILE(d, tx, ty) \\")
    lines.append("    ((d) * CD_DIGIT_TILES + (ty) * CD_DIGIT_W_TILES + (tx))")
    lines.append("")
    lines.append("// Palette bank CD_PALETTE. Index 0 is transparent and MUST stay so: BG3's")
    lines.append("// tilemap is 32x32 = 1024 cells and two digits occupy %d of them."
                 % (2 * DIGIT_W_TILES * DIGIT_H_TILES))
    lines.append("static const u16 sCountdownDigits_Pal[16] =")
    lines.append("{")
    lines.append("    RGB_BLACK,                 // 0 transparent (unused: the cells are opaque)")
    for idx, label in ((PAL_PLATE, "plate"), (PAL_FILL, "fill"), (PAL_HILIGHT, "highlight")):
        r, g, b = COLORS[idx]
        entry = "RGB(%d, %d, %d)" % (r, g, b)
        lines.append("    %s,%s// %d %s" % (entry, " " * max(1, 27 - len(entry)), idx, label))
    for _ in range(16 - 4):
        lines.append("    RGB_BLACK,")
    lines.append("};")
    lines.append("")
    lines.append("static const u32 sCountdownDigits_Tiles[CD_NUM_TILES * 8] =")
    lines.append("{")
    for i, words in enumerate(tiles):
        d, rem = divmod(i, DIGIT_W_TILES * DIGIT_H_TILES)
        ty, tx = divmod(rem, DIGIT_W_TILES)
        lines.append("    " + " ".join("0x%08X," % w for w in words)
                     + "  // '%d' tile (%d,%d)" % (d, tx, ty))
    lines.append("};")
    lines.append("")
    lines.append("#endif // GUARD_TRAINING_COUNTDOWN_GFX_H")
    path.write_text("\n".join(lines) + "\n")
    print("header -> %s  (%d tiles)" % (path, len(tiles)))


def emit_preview(path: Path, cells, scale=4):
    """A PNG of exactly what the ROM will show. Five bugs on 2026-07-30 were
    found by looking at a picture and none by a probe; a preview is the cheapest
    verification step this project has."""
    try:
        from PIL import Image
    except ImportError:
        print("preview skipped: Pillow not installed", file=sys.stderr)
        return

    # The body window's white, because that is what surrounds the plate on
    # screen -- a preview on any other field would misrepresent the one
    # relationship worth checking.
    bg = (255, 255, 255)
    rgb = {PAL_TRANSPARENT: bg}
    for idx, (r, g, b) in COLORS.items():
        rgb[idx] = (r * 255 // 31, g * 255 // 31, b * 255 // 31)

    img = Image.new("RGB", (DIGIT_W * DIGIT_COUNT, DIGIT_H), bg)
    px = img.load()
    for d, cell in enumerate(cells):
        for y in range(DIGIT_H):
            for x in range(DIGIT_W):
                px[d * DIGIT_W + x, y] = rgb[cell[y][x]]
    img.resize((img.width * scale, img.height * scale), Image.NEAREST).save(path)
    print("preview -> %s" % path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", required=True, type=Path,
                    help="the pinned read-only pokeemerald-expansion clone")
    ap.add_argument("--out", type=Path, help="C header to write")
    ap.add_argument("--preview", type=Path, help="also write a PNG of the digits")
    args = ap.parse_args()

    masks = load_font_digits(args.engine)
    cells = [render_glyph(m) for m in masks]
    tiles = to_tiles(cells)

    if len(tiles) != DIGIT_COUNT * DIGIT_W_TILES * DIGIT_H_TILES:
        sys.exit("internal: tile count %d is not %d glyphs x %d tiles"
                 % (len(tiles), DIGIT_COUNT, DIGIT_W_TILES * DIGIT_H_TILES))

    if args.out:
        emit_header(args.out, tiles, ["python3", "tools/make_countdown_digits.py",
                                      "--engine", str(args.engine), "--out", str(args.out)])
    if args.preview:
        emit_preview(args.preview, cells)
    if not args.out and not args.preview:
        ap.error("nothing to do: pass --out and/or --preview")


if __name__ == "__main__":
    main()
