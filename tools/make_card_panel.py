#!/usr/bin/env python3
"""Generate the training card's background panel art (BG3) for the `reps` hack.

WHY THIS SCRIPT EXISTS
----------------------
`design/reps/reports/2026-07-30-pentagon-fidelity.md` established the
finding this whole file follows from: **in Emerald the condition pentagon is
mostly static ART, not code.** The frame, the maximum pentagon, its outline, the
five spokes and the five pastel vertex discs are all baked into ONE background
image (`graphics/pokeblock/use_screen/graph.4bpp`, 208 tiles). Only the *fill*
is computed, and even that is just a flat colour revealed through a
scanline-carved hardware window.

Slice 3.6 reused the machinery (`ConditionGraph_*`) and took it for the whole
feature. It is about a fifth of it, which is why our shape floated on a flat
field with no reference: you cannot tell 40% from 60% without a maximum drawn
behind it.

So this script draws the missing four fifths. It is the analogue of
`graph.4bpp` -- our own art, drawn by code rather than by an artist, because
this project's standing rule is that the only manual step is talking to Claude.

WHY IT READS THE ENGINE INSTEAD OF HARDCODING THE GEOMETRY
---------------------------------------------------------
The vertex positions are NOT "centre plus radius at 72-degree steps". The engine
computes them in `ConditionGraph_CalcPositions` (`src/menu_specialized.c`) from
a hand-authored length table and a Q8.8 sine table, with two off-by-one
adjustments that exist for no reason except that Game Freak wanted those pixels
there:

  * `sinIdx++` when the index lands on GRAPH_CUTE, and
  * `positions[posIdx].x++` for the lower half except one exact case.

A drawn maximum that disagreed with the computed shape by even a pixel would be
worse than no maximum at all -- the fill would poke out of its own frame. So the
tables are parsed out of the pin and the algorithm is replayed here verbatim.
Doc 59's lesson in a new costume: a derived number rots, so derive it again.

OUTPUT
------
A C header of `const` arrays (tiles, tilemap entries, palette) written into the
hack fork. `hacks/` is gitignored and disposable, so THIS FILE is the durable
artifact and the header is a build product -- same relationship as
`tools/make_song.py` to a `.s3m`.

Usage:
    python3 tools/make_card_panel.py \
        --engine engine \
        --out    hacks/reps/include/training_card_panel.h
    python3 tools/make_card_panel.py --preview /tmp/panel.png ...
"""

import argparse
import math
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# The panel's place on screen.
#
# Everything here is forced by the engine and cannot be negotiated. The graph's
# centre is CONDITION_GRAPH_CENTER_X = 155, and that is not a decoration: the
# scanline effect splits the shape at that x into WIN1 (left) and WIN0 (right),
# so moving the centre means rewriting the effect. The vertical band is likewise
# fixed at CONDITION_GRAPH_TOP_Y..BOTTOM_Y = 56..121.
#
# The panel therefore has to be laid out AROUND the shape rather than the other
# way round, and it is why the card's numbers live in a narrow left column: the
# pentagon owns screen x 120..190 and there is no version of this screen where
# it does not.
# --------------------------------------------------------------------------
# The panel must be CENTRED ON x = 155, the engine-fixed graph centre, not on
# any round tile number. At 13 tiles wide the only start column that does it is
# 13: screen x 104..207, centre 155.5. The first version started at column 12
# (centre 147.5) and the 7.5 px error was visible to the user on sight -- the
# MOBILITY disc sat 8 px from the panel's right edge while LEGS sat 23 from the
# left, and the disc's rightmost pixel actually overhung the plate.
PANEL_TILE_X = 13          # tile column the panel starts at -> screen x 104
PANEL_TILE_Y = 5           # tile row    the panel starts at -> screen y 40
PANEL_TILES_W = 13         # -> 104 px wide, screen x 104..207
PANEL_TILES_H = 12         # ->  96 px tall, screen y 40..135

PANEL_X = PANEL_TILE_X * 8
PANEL_Y = PANEL_TILE_Y * 8
PANEL_W = PANEL_TILES_W * 8
PANEL_H = PANEL_TILES_H * 8

CORNER_RADIUS = 6
DISC_RADIUS = 10

# Palette bank 4. Banks in use on this screen: 0 backdrop, 1 text, 2 healthbox
# (the exp bar), 3 the graph fill, 7 the window frame.
#
# Index 0 must stay unused by the art: on a background layer index 0 is
# TRANSPARENT, and every tile outside the panel is index 0 throughout, which is
# what lets one 32x32 tilemap hold a 13x12 panel and nothing else.
TRANSPARENT = 0
COLORS = {
    # The CARD's own white, painted into the panel's four rounded corners. The
    # hole punched in WIN_BODY is a rectangle and the plate is not, so without
    # this the corners showed the periwinkle backdrop -- four little bites of
    # exactly the colour this whole round exists to get rid of.
    "card":         (31, 31, 31),
    "panel":        (23, 27, 30),   # #BDDEF6, the original's pale blue plate
    "border_dark":  (11, 11, 13),
    "border_light": (20, 20, 23),
    "pent_fill":    (30, 31, 31),   # #F6FFFF, near-white -- the green lands ON this
    "pent_edge":    (16, 16, 18),   # #838394
    "pent_edge2":   (12, 12, 14),   # #626273
    "spoke":        (23, 22, 24),   # #BDB4C5
    "disc_orange":  (31, 19, 12),   # #FF9C62
    "disc_yellow":  (31, 30,  7),   # #FFF639
    "disc_green":   (14, 28, 14),   # #73E673
    "disc_pink":    (31, 21, 26),   # #FFACD5
    "disc_blue":    (16, 19, 31),   # #839CFF
}
# Fixed index order, because the C side indexes nothing by name and a reordering
# would silently recolour the screen.
PAL_ORDER = [
    "card", "panel", "border_dark", "border_light", "pent_fill", "pent_edge",
    "pent_edge2", "spoke", "disc_orange", "disc_yellow", "disc_green",
    "disc_pink", "disc_blue",
]
IDX = {name: i + 1 for i, name in enumerate(PAL_ORDER)}

# Disc colour per MENU SLOT, matching where the original puts each hue: top
# orange, then anticlockwise yellow, green, pink, blue. Slot order here is the
# card's own (top, upper-left, lower-left, lower-right, upper-right), which is
# the order ConditionGraph_CalcPositions writes because it DECREMENTS its index.
SLOT_DISC = ["disc_orange", "disc_yellow", "disc_green", "disc_pink", "disc_blue"]


# --------------------------------------------------------------------------
# Replaying the engine's own vertex maths.
# --------------------------------------------------------------------------
def parse_sine_table(trig_c: Path):
    """gSineTable, as Q8.8 ints, from src/trig.c.

    The file writes them as `Q_8_8(0.0234375)` with the exact decimal, so the
    values are read rather than recomputed -- a recomputed sin() would differ in
    the last bit here and there, and this table feeds an integer shift.
    """
    text = trig_c.read_text()
    body = text.split("const s16 gSineTable[] =", 1)[1]
    body = body.split("};", 1)[0]
    vals = [float(m) for m in re.findall(r"Q_8_8\(\s*(-?[\d.]+)\s*\)", body)]
    if len(vals) < 320:
        raise SystemExit(f"gSineTable: expected >=320 entries, parsed {len(vals)}")
    return [int(round(v * 256)) for v in vals]


def parse_line_lengths(menu_specialized_c: Path):
    """sConditionToLineLength[0..MAX_CONDITION]."""
    text = menu_specialized_c.read_text()
    body = text.split("sConditionToLineLength[MAX_CONDITION + 1] =", 1)[1]
    body = body.split("};", 1)[0]
    vals = [int(m) for m in re.findall(r"\b(\d+)\b", body)]
    if len(vals) != 256:
        raise SystemExit(f"sConditionToLineLength: expected 256 entries, parsed {len(vals)}")
    return vals


def calc_positions(conditions, sine, lengths, center_x, center_y, count=5):
    """A line-for-line replay of ConditionGraph_CalcPositions.

    Kept deliberately un-idiomatic -- the `posIdx` decrement, the `sinIdx++` at
    GRAPH_CUTE and the trailing `x++` are all reproduced in place so that a
    future reader can diff this against the C rather than trust a paraphrase.
    """
    GRAPH_COOL = 0
    GRAPH_CUTE = 1   # CONDITION_COUNT-ordered enum: COOL, CUTE, SMART, TOUGH, BEAUTY
    pos = [[0, 0] for _ in range(count)]

    it = iter(conditions)
    line_length = lengths[next(it)]
    pos[GRAPH_COOL][0] = center_x
    pos[GRAPH_COOL][1] = center_y - line_length

    sin_idx = 64
    pos_idx = GRAPH_COOL
    for _ in range(1, count):
        sin_idx = (sin_idx + 51) & 0xFF
        pos_idx -= 1
        if pos_idx < 0:
            pos_idx = count - 1
        if pos_idx == GRAPH_CUTE:
            sin_idx = (sin_idx + 1) & 0xFF

        line_length = lengths[next(it)]
        pos[pos_idx][0] = center_x + ((line_length * sine[64 + sin_idx]) >> 8)
        pos[pos_idx][1] = center_y - ((line_length * sine[sin_idx]) >> 8)

        if pos_idx <= GRAPH_CUTE and (line_length != 32 or pos_idx != GRAPH_CUTE):
            pos[pos_idx][0] += 1

    return pos


# The engine's OUTPUT array is not in menu-slot order, and this bit an earlier
# run of this script: it painted the upper-left disc blue when the original puts
# yellow there. `ConditionGraph_CalcPositions` consumes `conditions` FORWARDS
# while writing `positions` BACKWARDS from GRAPH_COOL, so input slot i lands at
# output index SLOT_TO_POS[i]. Everything downstream -- disc colours, the emitted
# vertex table, and therefore the label positions in C -- wants menu-slot order,
# so the reorder happens once, here, immediately after the replay.
SLOT_TO_POS = [0, 4, 3, 2, 1]   # top, upper-left, lower-left, lower-right, upper-right


# --------------------------------------------------------------------------
# A very small raster. No antialiasing anywhere: this is 4bpp GBA art and a
# blended edge pixel would just be a twelfth palette entry that reads as dirt.
# --------------------------------------------------------------------------
class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = [[TRANSPARENT] * w for _ in range(h)]

    def put(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = c

    def rounded_rect(self, x0, y0, x1, y1, r, fill, edge, edge2):
        """Filled rounded rectangle with a two-tone 2px border, as the original's
        plate has. Drawn by distance test rather than by arcs because a
        104x96 panel is 10k pixels and clarity beats cleverness at that size."""
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                d = self._corner_dist(x, y, x0, y0, x1, y1, r)
                if d is None:
                    continue
                if d > r:
                    continue
                if d > r - 1:
                    self.put(x, y, edge)
                elif d > r - 2:
                    self.put(x, y, edge2)
                else:
                    self.put(x, y, fill)

    def _corner_dist(self, x, y, x0, y0, x1, y1, r):
        """Distance from the rounded boundary, expressed as a radius so the same
        two comparisons handle both the straight edges and the corners."""
        cx0, cy0 = x0 + r, y0 + r
        cx1, cy1 = x1 - r, y1 - r
        dx = 0.0
        dy = 0.0
        if x < cx0:
            dx = cx0 - x
        elif x > cx1:
            dx = x - cx1
        if y < cy0:
            dy = cy0 - y
        elif y > cy1:
            dy = y - cy1
        if dx == 0 and dy == 0:
            # Interior: report the distance to the NEAREST straight edge, so the
            # border stripe continues along the flats.
            edge_d = min(x - x0, x1 - x, y - y0, y1 - y)
            return max(0.0, r - edge_d)
        return math.hypot(dx, dy)

    def polygon(self, pts, c):
        """Scanline fill, half-open on the right so two polygons sharing an edge
        never double-draw it."""
        if not pts:
            return
        ys = [p[1] for p in pts]
        for y in range(int(min(ys)), int(max(ys)) + 1):
            xs = []
            n = len(pts)
            for i in range(n):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % n]
                if y0 == y1:
                    continue
                if min(y0, y1) <= y < max(y0, y1):
                    xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                for x in range(int(math.floor(xs[i])), int(math.ceil(xs[i + 1]))):
                    self.put(x, y, c)

    def line(self, x0, y0, x1, y1, c):
        """Bresenham."""
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            self.put(x0, y0, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def polyline_thick(self, pts, c_outer, c_inner):
        """A 2px closed outline: the polygon's own edge in c_outer, and the same
        edge nudged one pixel toward the centroid in c_inner."""
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            self.line(int(x0), int(y0), int(x1), int(y1), c_outer)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            ix0, iy0 = self._toward(x0, y0, cx, cy)
            ix1, iy1 = self._toward(x1, y1, cx, cy)
            self.line(ix0, iy0, ix1, iy1, c_inner)

    @staticmethod
    def _toward(x, y, cx, cy):
        d = math.hypot(cx - x, cy - y) or 1.0
        return int(round(x + (cx - x) / d)), int(round(y + (cy - y) / d))

    def disc(self, cx, cy, r, c):
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    self.put(x, y, c)


# --------------------------------------------------------------------------
def build_panel(engine: Path):
    sine = parse_sine_table(engine / "src" / "trig.c")
    lengths = parse_line_lengths(engine / "src" / "menu_specialized.c")

    center_x, center_y = 155, (121 + 56) // 2 + 3   # CONDITION_GRAPH_CENTER_*
    raw = calc_positions([255] * 5, sine, lengths, center_x, center_y)
    verts = [raw[SLOT_TO_POS[i]] for i in range(5)]   # -> menu-slot order

    # Into panel-local pixel space.
    lx = lambda x: x - PANEL_X
    ly = lambda y: y - PANEL_Y
    local = [(lx(x), ly(y)) for x, y in verts]
    lcx, lcy = lx(center_x), ly(center_y)

    c = Canvas(PANEL_W, PANEL_H)
    # Opaque white everywhere first, so no pixel of this rectangle is ever
    # transparent: the whole panel rect is a hole in the body window.
    for y in range(PANEL_H):
        for x in range(PANEL_W):
            c.px[y][x] = IDX["card"]
    c.rounded_rect(0, 0, PANEL_W - 1, PANEL_H - 1, CORNER_RADIUS,
                   IDX["panel"], IDX["border_dark"], IDX["border_light"])

    # The MAXIMUM. This is the whole point of the layer: the fill is meaningless
    # without a drawn 100%.
    c.polygon(local, IDX["pent_fill"])

    # Spokes, so a lopsided shape reads as lopsided against something.
    for x, y in local:
        c.line(lcx, lcy, int(x), int(y), IDX["spoke"])

    # The discs sit ON the fill and UNDER the outline, as in the original: they
    # are the "you could be here" markers, and they are what the labels attach
    # to visually now that the labels are no longer floating at five radii.
    for i, (x, y) in enumerate(local):
        c.disc(int(x), int(y), DISC_RADIUS, IDX[SLOT_DISC[i]])

    c.polyline_thick(local, IDX["pent_edge"], IDX["pent_edge2"])

    return c, verts


def to_tiles(c: Canvas):
    """4bpp, GBA order: 8x8 tiles, row-major within a tile, two pixels per byte,
    LOW nybble first."""
    tiles = []
    for ty in range(PANEL_TILES_H):
        for tx in range(PANEL_TILES_W):
            words = []
            for row in range(8):
                v = 0
                for col in range(8):
                    p = c.px[ty * 8 + row][tx * 8 + col] & 0xF
                    v |= p << (col * 4)
                words.append(v & 0xFFFFFFFF)
            tiles.append(words)
    return tiles


def emit_header(path: Path, tiles, verts, argv):
    lines = []
    lines.append("// GENERATED by tools/make_card_panel.py -- DO NOT EDIT BY HAND.")
    lines.append("//")
    lines.append("// The training card's background panel: the pale plate, the MAXIMUM")
    lines.append("// pentagon, its outline, the five spokes and the five vertex discs. In")
    lines.append("// Emerald all of this is one static background image and only the fill is")
    lines.append("// computed (design/reps/reports/2026-07-30-pentagon-fidelity.md); this is our")
    lines.append("// equivalent of that image, drawn from the engine's OWN vertex maths so the")
    lines.append("// computed fill can never poke outside its own frame.")
    lines.append("//")
    lines.append("// Regenerate with:")
    lines.append("//   %s" % " ".join(argv))
    lines.append("")
    lines.append("#ifndef GUARD_TRAINING_CARD_PANEL_H")
    lines.append("#define GUARD_TRAINING_CARD_PANEL_H")
    lines.append("")
    lines.append("#define CARD_PANEL_TILE_X   %d" % PANEL_TILE_X)
    lines.append("#define CARD_PANEL_TILE_Y   %d" % PANEL_TILE_Y)
    lines.append("#define CARD_PANEL_TILES_W  %d" % PANEL_TILES_W)
    lines.append("#define CARD_PANEL_TILES_H  %d" % PANEL_TILES_H)
    lines.append("#define CARD_PANEL_NUM_TILES %d" % len(tiles))
    lines.append("")
    lines.append("// Screen positions of the MAXIMUM pentagon's vertices, in menu-slot order")
    lines.append("// (top, then anticlockwise). Replayed from ConditionGraph_CalcPositions with")
    lines.append("// every condition at MAX_CONDITION, so the labels below can be hung off the")
    lines.append("// same numbers the art was drawn from instead of a second set that drifts.")
    for i, (x, y) in enumerate(verts):
        lines.append("//   slot %d: (%3d, %3d)" % (i, x, y))
    lines.append("static const u8 sCardPanel_VertexX[5] = { %s };"
                 % ", ".join(str(x) for x, _ in verts))
    lines.append("static const u8 sCardPanel_VertexY[5] = { %s };"
                 % ", ".join(str(y) for _, y in verts))
    lines.append("")

    pal = ["RGB(%d, %d, %d)" % COLORS[n] for n in PAL_ORDER]
    lines.append("// Palette bank CARD_PANEL_PALETTE. Index 0 is left BLACK and unused: on a")
    lines.append("// background layer it is transparent, which is what lets the 32x32 tilemap")
    lines.append("// carry a 13x12 panel and nothing else.")
    lines.append("static const u16 sCardPanel_Pal[16] =")
    lines.append("{")
    lines.append("    RGB_BLACK,")
    for name, entry in zip(PAL_ORDER, pal):
        lines.append("    %s,%s// %s" % (entry, " " * max(1, 22 - len(entry)), name))
    for _ in range(16 - 1 - len(pal)):
        lines.append("    RGB_BLACK,")
    lines.append("};")
    lines.append("")
    lines.append("static const u32 sCardPanel_Tiles[CARD_PANEL_NUM_TILES * 8] =")
    lines.append("{")
    for i, words in enumerate(tiles):
        lines.append("    " + " ".join("0x%08X," % w for w in words) + "  // tile %d" % i)
    lines.append("};")
    lines.append("")
    lines.append("#endif // GUARD_TRAINING_CARD_PANEL_H")
    path.write_text("\n".join(lines) + "\n")


def emit_preview(path: Path, c: Canvas, scale=3):
    """A PNG of exactly what the ROM will show, so the art can be looked at
    without a build. Five of the six bugs in the 2026-07-30 session were found by
    looking at a picture and none by a probe -- a preview is the cheapest step in
    this loop, so the generator owes one."""
    try:
        from PIL import Image
    except ImportError:
        print("preview skipped: Pillow not installed", file=sys.stderr)
        return
    rgb = {0: (0, 0, 0)}
    for name, i in IDX.items():
        r, g, b = COLORS[name]
        rgb[i] = (r * 255 // 31, g * 255 // 31, b * 255 // 31)
    img = Image.new("RGB", (PANEL_W, PANEL_H))
    img.putdata([rgb[c.px[y][x]] for y in range(PANEL_H) for x in range(PANEL_W)])
    img.resize((PANEL_W * scale, PANEL_H * scale), Image.NEAREST).save(path)
    print("preview -> %s" % path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", required=True, type=Path,
                    help="the pinned pokeemerald-expansion clone (read-only; the tables come from here)")
    ap.add_argument("--out", type=Path, help="C header to write")
    ap.add_argument("--preview", type=Path, help="also write a PNG of the panel")
    args = ap.parse_args()

    canvas, verts = build_panel(args.engine)
    tiles = to_tiles(canvas)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        emit_header(args.out, tiles, verts, sys.argv)
        print("panel -> %s  (%d tiles, %d bytes of gfx)"
              % (args.out, len(tiles), len(tiles) * 32))
    if args.preview:
        emit_preview(args.preview, canvas)


if __name__ == "__main__":
    main()
