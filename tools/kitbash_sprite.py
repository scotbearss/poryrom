#!/usr/bin/env python3
"""Make a new overworld sprite by EDITING one the engine already ships.

This is what the community actually does, and this project had been ignoring it
for art while following the identical rule everywhere else. PokeCommunity's
overworld guide: *"your overworld doesn't have to be entirely from scratch --
you can look at existing overworld sprites and use them as a base to edit and
manipulate."* Lospec's Gen-3 tutorial is titled, in full, *"How to create an
overworld character sprite in Pokemon style USING OTHER SPRITES AS A BASE."*

It is the same rule as `new_map.py --dump-layout` (derive map data from a real
layout, never invent metatile ids), `make_card_panel.py` (replay the engine's
own vertex maths rather than redraw the shape), and `check_dialogue.py` (score
against the pin's own 4,362 conversations rather than against your ear). Doc 74
is where it was finally applied to sprites, after three AI generations came back
"dinky" against Game Freak's.

WHY IT BEATS GENERATING, AND IT IS NOT CLOSE. An Emerald overworld person is
14-16 px wide by 19-21 tall, and every one of those ~300 pixels was placed by a
professional. At that size there is no room for a generator to be approximately
right: the eyes are TWO PIXELS. A palette edit of an existing sprite is
**lossless** -- it changes the colour table and not one pixel position -- so the
result is, by construction, exactly as well drawn as the original.

WHAT THIS DOES

  1. Loads an indexed (mode "P") sprite sheet from the fork.
  2. Optionally REMAPS indices inside a row band, so a region that shares a
     palette entry with another region can be separated before recolouring.
     (The case that forced it: the running triathlete's headband and vest are
     both palette 5/6, so recolouring the vest white whitens the headband too.
     Remapping the head band's rows onto a free index breaks the tie.)
  3. Applies a palette edit and writes the sheet plus a CRLF JASC-PAL.

Every colour is snapped to multiples of 8, because gbagfx builds the .gbapal by
truncating each channel to 5 bits and the .pal on disk should say what the
screen will show.

FINDING A FREE INDEX. A GBA 4bpp sprite has 16 entries and most sheets do not
use all of them -- `--report` prints per-index usage across the whole sheet, and
an index with 0 uses is yours. The triathlete had exactly one (14).

Usage:
    python3 tools/kitbash_sprite.py --report <sheet.png>
    python3 tools/kitbash_sprite.py <spec.json>
"""

import argparse
import json
import pathlib
import sys
from collections import Counter

from PIL import Image

import hx  # noqa: E402
REPO_ROOT = hx.HARNESS_ROOT
N_COLORS = 16


def fail(msg):
    print(f"kitbash_sprite.py: {msg}", file=sys.stderr)
    sys.exit(2)


def snap(c):
    """GBA colour: 5 bits per channel. gbagfx truncates, so we truncate too."""
    return tuple((int(v) >> 3) << 3 for v in c)


def usage(im: Image.Image) -> Counter:
    px = im.load()
    return Counter(px[x, y] for y in range(im.height) for x in range(im.width))


def report(path: pathlib.Path) -> None:
    im = Image.open(path)
    if im.mode != "P":
        fail(f"{path} is mode {im.mode}, expected an indexed 'P' sheet")
    pal = im.getpalette()[: N_COLORS * 3]
    u = usage(im)
    print(f"{path}  {im.size[0]}x{im.size[1]}  ({im.size[0] // 16} frames of 16x32)")
    for i in range(N_COLORS):
        c = tuple(pal[i * 3:i * 3 + 3])
        n = u.get(i, 0)
        print(f"  idx {i:2d}  rgb {str(c):18s} {n:5d} px" + ("   <-- FREE" if n == 0 else ""))
    print("\nrows per index (frame 0), for picking a remap band:")
    px = im.load()
    for i in range(N_COLORS):
        rows = sorted({y for y in range(im.height) for x in range(16) if px[x, y] == i})
        if rows and i != 0:
            runs, start = [], rows[0]
            for a, b in zip(rows, rows[1:] + [None]):
                if b != (a + 1):
                    runs.append(f"{start}-{a}" if start != a else f"{a}")
                    start = b
            print(f"  idx {i:2d}  rows {', '.join(runs)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec", nargs="?", type=pathlib.Path)
    ap.add_argument("--report", type=pathlib.Path,
                    help="print per-index usage and row bands for a sheet")
    args = ap.parse_args()

    if args.report:
        report(args.report)
        return
    if not args.spec:
        fail("give a spec, or --report <sheet.png>")

    spec = json.loads(args.spec.read_text())
    base = pathlib.Path(spec["base"])
    if not base.is_absolute():
        base = (REPO_ROOT / base).resolve()
    if not base.exists():
        fail(f"base sprite not found: {base}")

    im = Image.open(base)
    if im.mode != "P":
        fail(f"{base} is mode {im.mode}, expected an indexed 'P' sheet")
    before = usage(im)
    px = im.load()

    # 1. PROVE THE BOUNDARY FIRST, on the untouched sheet.
    #
    # The risk in a band remap is that the band edge cuts through the region it
    # is supposed to leave alone. The check that catches it is on the SOURCE
    # indices, in the GAP between the two regions: if the colours being moved do
    # not appear anywhere in the gap, the boundary sits in empty space and can
    # be off by a row or two without consequence. (Checking the DESTINATION
    # indices outside the band is wrong and was this tool's first draft --
    # a destination index like "the hair colour" legitimately appears elsewhere
    # on the body, so that check fires on a correct edit. Same shape as doc 68's
    # rule that an inequality against a non-unique field is not weak, it is
    # wrong.) This is also the sprite version of doc 65's walk rule: put the
    # boundary where nothing is, and the exact number stops mattering.
    for r in spec.get("remap", []):
        src_idx = {int(k) for k in r["map"]}
        for g0, g1 in r.get("gap_rows", []):
            bad = [(x, y) for y in range(g0, g1 + 1) for x in range(im.width)
                   if px[x, y] in src_idx]
            if bad:
                fail(f"indices {sorted(src_idx)} appear {len(bad)} times in the "
                     f"gap rows {g0}-{g1}, so the two regions are NOT cleanly "
                     f"separated there. Run --report and pick a boundary that "
                     f"falls in empty space.")
            print(f"  boundary check: rows {g0}-{g1} are free of "
                  f"{sorted(src_idx)}  [gap confirmed]")

    # 2. region remaps, so two regions sharing an index can be told apart
    moved = 0
    for r in spec.get("remap", []):
        y0, y1 = r["rows"]
        src = {int(k): int(v) for k, v in r["map"].items()}
        for y in range(y0, y1 + 1):
            for x in range(im.width):
                if px[x, y] in src:
                    px[x, y] = src[px[x, y]]
                    moved += 1
        print(f"  remap rows {y0}-{y1}: {r['map']}  ({moved} px moved)")

    # 3. palette edit
    pal = im.getpalette()[:]
    for k, v in spec["palette"].items():
        i = int(k)
        c = snap(v)
        pal[i * 3:i * 3 + 3] = list(c)
        print(f"  idx {i:2d} -> rgb {c}")
    im.putpalette(pal)

    out = args.spec.parent / spec["out"]
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)

    # The silhouette guard runs on THIS path too, because this is the path that
    # shipped. It was written for the generate-and-downscale route and that
    # route was abandoned -- leaving the check attached only to the pipeline
    # nobody uses is how a guard rail quietly stops guarding anything. One
    # implementation, imported, never a second copy (the precedent here is
    # verify_hack.py importing boot_proof.py's resolver rather than
    # reimplementing it).
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from make_player_sheet import check_silhouette  # noqa: E402
    check_silhouette(Image.open(out), hx.ENGINE,
                     spec.get("allow_offmodel", False))
    after = usage(im)
    print(f"  sheet: {out}  ({im.size[0]}x{im.size[1]}, "
          f"{len(after)} of {N_COLORS} indices in use)")

    # 4. the JASC-PAL beside it. CRLF, because that is what JASC-PAL is and
    #    what every other palette in this tree uses -- doc 65 found `patch`
    #    silently flattening these to LF.
    if spec.get("palette_out"):
        pal_out = args.spec.parent / spec["palette_out"]
        lines = ["JASC-PAL", "0100", str(N_COLORS)]
        lines += [f"{pal[i*3]} {pal[i*3+1]} {pal[i*3+2]}" for i in range(N_COLORS)]
        pal_out.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
        print(f"  palette: {pal_out} (CRLF)")

    # 5. the claim this whole approach rests on, asserted rather than assumed
    src_px = Image.open(base).load()
    if spec.get("remap"):
        print("  (pixel-identity check skipped: this spec remaps indices)")
    else:
        diff = sum(1 for y in range(im.height) for x in range(im.width)
                   if px[x, y] != src_px[x, y])
        if diff:
            fail(f"{diff} pixel INDICES changed -- a pure recolour must move "
                 f"no pixels at all")
        print("  lossless: 0 pixel indices changed, only the colour table")


if __name__ == "__main__":
    main()
