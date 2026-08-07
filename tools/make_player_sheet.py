#!/usr/bin/env python3
"""Assemble a pokeemerald PLAYER OVERWORLD SHEET from generated art.

Doc 67 slate item K. The player's walking graphic is a 144x32 PNG holding NINE
16x32 frames, and the order is not documentation, it is
`sAnimTable_Standard` in src/data/object_events/object_event_anims.h:

    0  stand South      3  walk South A     4  walk South B
    1  stand North      5  walk North A     6  walk North B
    2  stand West       7  walk West  A     8  walk West  B

EAST DOES NOT EXIST. sAnim_FaceEast is frame 2 with `.hFlip = TRUE`, and
sAnim_GoEast is frames 7/2/8/2 all h-flipped. So a player sheet needs THREE
directions of art, not four -- and a fourth generated direction is not merely
wasted, it is a trap: drawing East separately makes the character asymmetric
in a way the engine will never show, and whatever you put there is ignored.
This tool reads the anim table out of the fork and refuses if that layout has
changed, rather than trusting the paragraph above.

The walk is TWO frames per direction alternating with the standing frame
(A, stand, B, stand), so a 4-frame generated cycle contributes its two step
EXTREMES and the generator's own in-between frames are dropped.

ALIGNMENT IS THE WHOLE JOB, and it is the part that cannot be eyeballed.
Every source frame is a loose sprite on a larger canvas with its own bounding
box; pasting them by canvas centre makes the character slide around under its
own feet. This aligns on a GROUND LINE -- the bottom of the content -- shared
by every frame in the sheet, and horizontally on the standing frame's centre,
so the walk cycle bobs vertically (as it should) without drifting sideways.

A frame taller than 32px after that alignment loses pixels off the TOP, which
on a person is the head. That is reported per frame and refused unless
--allow-clip, because a two-pixel haircut is exactly the kind of fault that
renders perfectly and is only ever caught by looking (doc 62's class).

PALETTE. The GBA gives a 4bpp sprite ONE 16-colour palette, and every frame of
every direction shares it. This derives a single palette across all nine frames
at once via tools/gba_quantize.py --shared, which is the same argument
game/palette-proof/ proved at import time: quantising frames independently
gives each one its own idea of "skin", and the character changes colour as it
turns. Index 0 is transparent by GBA rule.

Usage:
    python3 tools/make_player_sheet.py <spec.json>
    python3 tools/make_player_sheet.py <spec.json> --preview out.png
"""

import argparse
import json
import pathlib
import re
import sys

from PIL import Image

import hx  # noqa: E402
REPO_ROOT = hx.HARNESS_ROOT

FRAME_W, FRAME_H = 16, 32
N_FRAMES = 9
# frame index -> (direction, role) exactly as sAnimTable_Standard uses them
LAYOUT = [
    ("south", "stand"), ("north", "stand"), ("west", "stand"),
    ("south", "a"), ("south", "b"),
    ("north", "a"), ("north", "b"),
    ("west", "a"), ("west", "b"),
]
DIRECTIONS = ("south", "north", "west")


def fail(msg):
    print(f"make_player_sheet.py: {msg}", file=sys.stderr)
    sys.exit(2)


def check_anim_layout(engine: pathlib.Path) -> None:
    """Prove the nine-frame order against the fork instead of remembering it.

    Doc 66: a tool that hardcodes what a shipping table says is a second copy
    of the data, and the copy is where the two drift. This cannot read the
    table as data (it is C), so it asserts the exact frame indices instead --
    which fails loudly if a future pin reorders them.
    """
    path = engine / "src/data/object_events/object_event_anims.h"
    if not path.exists():
        fail(f"{path} not found -- is --engine pointing at a pokeemerald tree?")
    text = path.read_text()
    want = {
        "sAnim_FaceSouth": [0], "sAnim_FaceNorth": [1], "sAnim_FaceWest": [2],
        "sAnim_GoSouth": [3, 0, 4, 0],
        "sAnim_GoNorth": [5, 1, 6, 1],
        "sAnim_GoWest": [7, 2, 8, 2],
    }
    for name, frames in want.items():
        m = re.search(r'static const union AnimCmd ' + name +
                      r'\[\] =\s*\{(.*?)\n\};', text, re.S)
        if not m:
            fail(f"{name} not found in the fork's anim table")
        got = [int(x) for x in re.findall(r'ANIMCMD_FRAME\((\d+),', m.group(1))]
        if got != frames:
            fail(f"{name} uses frames {got}, this tool assumes {frames}. "
                 f"The nine-frame player sheet layout has changed at this pin; "
                 f"fix LAYOUT before generating art against it.")
    if ".hFlip = TRUE" not in text:
        fail("no hFlip in the anim table -- East may no longer be a mirror of "
             "West, in which case a player needs four directions, not three")
    print("  anim layout: 9 frames, East is West h-flipped  [checked against the fork]")


# Whose silhouette the player has to sit next to. Read from the fork at run
# time rather than hardcoded, for the same reason check_dialogue.py scores
# against the pin's own 4,362 conversations: derive the rule from the thing you
# are imitating, not from your eye.
CAST = [
    "people/brendan/walking.png", "people/may/walking.png",
    "people/boy_1.png", "people/boy_2.png", "people/boy_3.png",
    "people/girl_1.png", "people/girl_2.png", "people/girl_3.png",
    "people/man_1.png", "people/man_2.png", "people/woman_1.png",
    "people/woman_2.png", "people/old_man.png", "people/old_woman.png",
    "people/fat_man.png", "people/youngster.png", "people/lass.png",
    "people/expert_m.png", "people/expert_f.png", "people/rich_boy.png",
]


def measure_cast(engine: pathlib.Path):
    """Width, height and ASPECT of every overworld person the engine ships.

    THE ASPECT IS THE POINT. A generated sprite can hit the height target dead
    on and still be wrong, because 'the right height' and 'the right shape' are
    different claims -- and the first version of this tool checked only that the
    art FIT the cell, which a stick figure does comfortably. What a person sees
    when the character walks past an NPC is the silhouette, so that is what has
    to be measured.
    """
    base = engine / "graphics/object_events/pics"
    rows = []
    for rel in CAST:
        p = base / rel
        if not p.exists():
            continue
        im = Image.open(p)
        px = im.load()
        xs, ys = [], []
        for y in range(min(FRAME_H, im.height)):
            for x in range(FRAME_W):
                if px[x, y] != 0:
                    xs.append(x)
                    ys.append(y)
        if xs:
            rows.append((rel, max(xs) - min(xs) + 1, max(ys) - min(ys) + 1))
    if len(rows) < 5:
        fail(f"only found {len(rows)} cast sprites under {base} -- cannot "
             f"derive a silhouette band to check against")
    return rows


def check_silhouette(sheet: Image.Image, engine: pathlib.Path,
                     allow: bool) -> None:
    rows = measure_cast(engine)
    ws = sorted(r[1] for r in rows)
    hs = sorted(r[2] for r in rows)
    ars = sorted(r[1] / r[2] for r in rows)
    lo, hi = ars[0], ars[-1]

    # TRANSPARENCY IS NOT ALPHA ON AN INDEXED SHEET. A GBA 4bpp sprite is mode
    # "P" and palette index 0 IS the transparent colour -- .convert("RGBA")
    # makes it an opaque green and every pixel becomes content, so the measured
    # box is the 16x32 CELL and the aspect reads 0.50 for any sprite whatsoever.
    # That is a plausible wrong number, which is the class this project keeps
    # getting caught by: the guard still prints, still compares, still looks
    # like it is working, and is measuring the wrong thing.
    if sheet.mode == "P":
        raw = sheet.load()
        def opaque(px_, py_):
            return raw[px_, py_] != 0
    else:
        rgba = sheet.convert("RGBA").load()
        def opaque(px_, py_):
            return rgba[px_, py_][3] >= 128

    xs, ys = [], []
    for i in range(N_FRAMES):
        for y in range(FRAME_H):
            for x in range(FRAME_W):
                if opaque(i * FRAME_W + x, y):
                    xs.append(x)
                    ys.append(y)
    w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    ar = w / h

    print(f"  cast ({len(rows)} sprites): w {ws[0]}-{ws[-1]}, h {hs[0]}-{hs[-1]}, "
          f"aspect {lo:.2f}-{hi:.2f}")
    print(f"  ours:  w {w}, h {h}, aspect {ar:.2f}")

    if lo <= ar <= hi and ws[0] <= w <= ws[-1] and hs[0] <= h <= hs[-1]:
        print("  silhouette: inside the cast's band")
        return
    why = []
    if not (ws[0] <= w <= ws[-1]):
        why.append(f"width {w} outside {ws[0]}-{ws[-1]}")
    if not (hs[0] <= h <= hs[-1]):
        why.append(f"height {h} outside {hs[0]}-{hs[-1]}")
    if not (lo <= ar <= hi):
        why.append(f"ASPECT {ar:.2f} outside {lo:.2f}-{hi:.2f} -- "
                   f"{'too narrow/tall' if ar < lo else 'too wide/short'} "
                   f"for this cast")
    msg = ("this character does not share the cast's silhouette:\n    "
           + "\n    ".join(why)
           + "\n  Emerald's overworld people are CHIBI -- big head, short limbs, "
             "wide body. Realistic proportions read as a stick figure beside "
             "them even at exactly the right height.")
    if allow:
        print(f"  WARNING: {msg}")
    else:
        fail(msg + "\n  Re-generate, or pass --allow-offmodel if this is "
                   "deliberate.")


def content_box(im: Image.Image):
    bb = im.convert("RGBA").getbbox()
    if bb is None:
        fail("a source frame is entirely transparent")
    return bb


def place(src: Image.Image, ground: int, centre_x: int, allow_clip: bool,
          label: str) -> tuple[Image.Image, int]:
    """Paste one source frame into a 16x32 cell.

    `ground` is the y of the shared ground line measured from the BOTTOM of the
    cell; `centre_x` is the source x that should land in the middle of the cell.
    Returns the cell and how many rows were clipped off the top.
    """
    bb = content_box(src)
    # Where the content must move to: its bottom lands on the shared ground
    # line, its horizontal centre on the cell's centre.
    dy = (FRAME_H - ground) - bb[3]
    dx = FRAME_W // 2 - centre_x
    # Composite through a padded canvas so a negative offset cannot wrap.
    pad = Image.new("RGBA", (src.width + 2 * FRAME_W, src.height + 2 * FRAME_H),
                    (0, 0, 0, 0))
    pad.alpha_composite(src, (FRAME_W, FRAME_H))
    cell = pad.crop((FRAME_W - dx, FRAME_H - dy,
                     FRAME_W - dx + FRAME_W, FRAME_H - dy + FRAME_H))
    # What actually fell outside the cell, measured from the moved bounding box
    # rather than predicted from the sizes.
    lost_top = max(0, -(bb[1] + dy))
    lost_side = max(0, -(bb[0] + dx)) + max(0, (bb[2] + dx) - FRAME_W)
    if (lost_top or lost_side) and not allow_clip:
        fail(f"{label}: {lost_top}px clipped off the top and {lost_side}px off "
             f"the sides fitting a {bb[2]-bb[0]}x{bb[3]-bb[1]} sprite into "
             f"{FRAME_W}x{FRAME_H}. Re-generate smaller art, or pass "
             f"--allow-clip if you have LOOKED at the result and it is fine.")
    return cell, lost_top + lost_side


N_COLORS = 16          # index 0 is transparent, 15 usable -- the GBA 4bpp rule


def quantize(sheets: list[tuple[Image.Image, pathlib.Path]],
             pal_out: pathlib.Path) -> None:
    """Write every indexed PNG and the single JASC-PAL they all share.

    TAKES A LIST BECAUSE THE WALK AND RUN SHEETS ARE ONE PALETTE, NOT TWO.
    `gObjectEventPic_BrendanNormalRunning` INCBINs walking.4bpp and running.4bpp
    back to back into a single 18-frame graphic with one paletteTag, so
    quantising them separately gives the player one set of colours standing and
    a subtly different set running. They are stacked into one image, quantised
    once, and split back out.

    ONE palette for all nine frames is not a nicety: a 4bpp sprite gets a
    single 16-colour bank, and every frame of every direction is drawn from it.
    Quantising frames independently gives each its own idea of "skin" and the
    character changes colour as it turns -- which is what game/palette-proof/
    established at import time on the toolkit side.

    Channels are snapped to multiples of 8 because gbagfx builds the .gbapal by
    truncating each channel to 5 bits. Without the snap the .pal on disk and the
    colour on screen disagree by up to 7, and the .pal is what a human opens to
    check the palette.

    The .pal is written CRLF, which is what JASC-PAL is and what every other
    palette in this tree uses -- doc 65 found `patch` silently flattening these
    to LF and an asset copy quietly repairing it afterwards.
    """
    KEY = (255, 0, 255)
    W = max(s.width for s, _ in sheets)
    offs, total = [], 0
    for s, _ in sheets:
        offs.append(total)
        total += s.height
    stack = Image.new("RGBA", (W, total), (0, 0, 0, 0))
    for (s, _), oy in zip(sheets, offs):
        stack.alpha_composite(s.convert("RGBA"), (0, oy))

    # Composite onto a key colour so quantisation never invents a colour out of
    # the alpha edge, then rebuild transparency from the source alpha.
    flat = Image.new("RGB", stack.size, KEY)
    flat.paste(stack, (0, 0), stack)
    q = flat.quantize(colors=N_COLORS - 1, method=Image.MEDIANCUT, dither=Image.NONE)

    pal = q.getpalette()[: (N_COLORS - 1) * 3]
    colors = [tuple((pal[i * 3 + c] >> 3) << 3 for c in range(3))
              for i in range(N_COLORS - 1)]

    src = q.load()
    alpha = stack.split()[3].load()
    used = set()
    for (sheet, png_out), oy in zip(sheets, offs):
        out = Image.new("P", sheet.size)
        op = out.load()
        for y in range(sheet.height):
            for x in range(sheet.width):
                # index 0 is the transparent slot; every real colour shifts up one
                v = 0 if alpha[x, oy + y] < 128 else src[x, oy + y] + 1
                op[x, y] = v
                used.add(v)
        full = list(KEY) + [c for rgb in colors for c in rgb]
        full += [0] * (768 - len(full))
        out.putpalette(full)
        png_out.parent.mkdir(parents=True, exist_ok=True)
        out.save(png_out)
        print(f"  indexed: {png_out}")

    if len(used) > N_COLORS:
        fail(f"{len(used)} palette indices in use, the GBA allows {N_COLORS}")

    lines = ["JASC-PAL", "0100", str(N_COLORS), f"{KEY[0]} {KEY[1]} {KEY[2]}"]
    lines += [f"{r} {g} {b}" for r, g, b in colors]
    pal_out.parent.mkdir(parents=True, exist_ok=True)
    pal_out.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
    print(f"  palette: {pal_out}  ({len(used)} of {N_COLORS} indices used, "
          f"shared across {len(sheets)} sheets, CRLF)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec", type=pathlib.Path, nargs="?")
    # A single arbitrary asset through the SAME quantiser. The trainer front
    # pic is 64x64 and has its own palette tag, so it cannot ride in the sheet
    # spec's shared bank -- but it needs identical treatment otherwise
    # (16 colours, index 0 transparent, channels snapped to gbagfx's 5 bits, a
    # CRLF JASC-PAL beside it), and a second near-copy of that is how the two
    # drift.
    ap.add_argument("--image", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--pal", type=pathlib.Path)
    ap.add_argument("--engine", type=pathlib.Path,
                    default=hx.ENGINE)
    ap.add_argument("--allow-clip", action="store_true")
    ap.add_argument("--allow-offmodel", action="store_true",
                    help="build anyway when the silhouette is outside the "
                         "cast's measured band (it will still be reported)")
    ap.add_argument("--preview", type=pathlib.Path)
    args = ap.parse_args()

    if args.image:
        if not (args.out and args.pal):
            fail("--image needs --out and --pal")
        quantize([(Image.open(args.image).convert("RGBA"), args.out.resolve())],
                 args.pal.resolve())
        return
    if not args.spec:
        fail("give a sheet spec, or --image/--out/--pal for a single asset")

    spec = json.loads(args.spec.read_text())
    src_dir = (args.spec.parent / spec["source_dir"]).resolve()

    check_anim_layout(args.engine.resolve())

    # THE GROUND LINE AND THE HORIZONTAL CENTRE ARE SHARED ACROSS EVERY SHEET,
    # not computed per sheet. The walk and run sheets are the same character:
    # centring each on its own frames would make him jump sideways the moment
    # you pressed B.
    ground = spec.get("ground", 1)
    anchor = {}
    for d in DIRECTIONS:
        p = src_dir / spec["sheets"][0]["frames"][d]["stand"]
        bb = content_box(Image.open(p).convert("RGBA"))
        anchor[d] = (bb[0] + bb[2]) // 2

    built = []
    for sh in spec["sheets"]:
        out = (args.spec.parent / sh["out"]).resolve()
        sheet = Image.new("RGBA", (FRAME_W * N_FRAMES, FRAME_H), (0, 0, 0, 0))
        lost_total = 0
        for i, (d, role) in enumerate(LAYOUT):
            p = src_dir / sh["frames"][d][role]
            if not p.exists():
                fail(f"missing source frame {p}")
            cell, lost = place(Image.open(p).convert("RGBA"), ground, anchor[d],
                               args.allow_clip,
                               f"{sh['out']} frame {i} ({d} {role})")
            lost_total += lost
            sheet.alpha_composite(cell, (i * FRAME_W, 0))
        print(f"  sheet: {out.name}  ({sheet.width}x{sheet.height}, "
              f"{N_FRAMES} frames, {lost_total}px clipped)")
        built.append((sheet, out))

    # Checked on the FIRST sheet only: walk and run are the same character, and
    # a run frame legitimately leans and stretches.
    check_silhouette(built[0][0], args.engine.resolve(), args.allow_offmodel)

    pal_out = (args.spec.parent / spec["palette_out"]).resolve()
    quantize(built, pal_out)

    if args.preview:
        S = 6
        W, H = built[0][0].width, FRAME_H * len(built)
        pv = Image.new("RGBA", (W * S, H * S), (40, 40, 48, 255))
        for i, (s, _) in enumerate(built):
            pv.alpha_composite(s.resize((W * S, FRAME_H * S), Image.NEAREST),
                               (0, i * FRAME_H * S))
        pv.save(args.preview)
        print(f"  preview: {args.preview}")

    print("\nNext: copy the sheet and its .pal into the fork, side by side --\n"
          "  graphics/object_events/pics/people/brendan/walking.png\n"
          "  graphics/object_events/palettes/brendan.pal\n"
          "and REMEMBER THE RUNNING SHEET: gObjectEventPic_BrendanNormalRunning\n"
          "INCBINs walking.4bpp AND running.4bpp back to back, both drawn from\n"
          "this one palette. Replace walking and not running and the run frames\n"
          "are still Brendan -- wearing the new character's colours.")


if __name__ == "__main__":
    main()
