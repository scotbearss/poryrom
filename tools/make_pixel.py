#!/usr/bin/env python3
"""Retro Diffusion: pixel art generated AT the target resolution, plus the
K-Centroid downscaler that makes big art survive the trip down.

Added 2026-08-05 (doc 74), after slate item K spent three rounds discovering
that the tool it was using could not reach the target size. The split, measured:

  * PixelLab's v3 reference mode REFUSES an output below 32 px, and in practice
    returned 52x87 for a sprite that needed to be 16x21. Beautiful art, 4x too
    big, and reducing it with LANCZOS/BOX/BILINEAR turned the face to mud.
  * Retro Diffusion is purpose-trained for pixel art and its `*_low_res` styles
    generate from 16 px up -- i.e. natively at GBA sprite scale.

Their own head-to-head advice, and it matches what this project measured:
**Retro Diffusion for base sprites, PixelLab for rotation and animation.**

WHERE THIS SITS IN THE PIPELINE. It does NOT replace the two things that
actually produced the best result in doc 74:

  1. `kitbash_sprite.py` -- edit a sprite the engine already ships. Still the
     first thing to try for anything that resembles an existing NPC, because a
     palette edit is LOSSLESS and every pixel stays where a professional put it.
  2. `tools/make_reference.py` -- gpt-image-1 concept art. Still correct for
     anything with room to breathe (64x64 species art, trainer pics).

Use this when there is no suitable base sprite AND the target is small.

K-CENTROID (`--fix`), and it is the durable half of this file
-------------------------------------------------------------
Astropulse's downscaler, documented as outperforming every traditional method
for pixel art. It splits the image into one tile per output pixel, runs k-means
on each tile, and keeps the MOST PROMINENT centroid -- so a hard black outline
stays a hard black outline instead of being averaged into its neighbours.
Measured on doc 74's 52x87 -> 13x21 case it is not a close call: LANCZOS loses
the eyes and the outline entirely, K-Centroid keeps both.

`centroids` defaults to 2 on the vendor's own advice; higher values "introduce
more noise and artifacts". It needs no API key and no network -- it is 30 lines
of arithmetic, and it is the single most useful thing this round found.

PROMPTING (from the vendor's own FAQ -- their model is NOT Stable Diffusion and
"will return poor results" with SD/Midjourney habits)
------------------------------------------------------------------------------
  * ONE descriptive sentence, then a handful of tags. Not a tag soup, not a
    story, not a paragraph.
  * NO quality-stacking ("best quality, masterpiece, ultra detailed") -- it
    actively hurts.
  * Describe the SUBJECT only; the `prompt_style` carries the pixel-art look.
  * Prefer industry terms ("contrast lighting") over lay description.
  * Word choice shifts the whole image, not just its literal referent -- their
    example is "beach" (tropical, built-up) vs "shore" (forested, wild).
  * Match the resolution to the sprite size you actually want.

API
---
    POST https://api.retrodiffusion.ai/v1/inferences     header X-RD-Token: rdpk-...
    GET  https://api.retrodiffusion.ai/v1/styles/selector  (live style catalogue
                                                            with per-style size
                                                            limits -- authoritative)
Body: prompt, prompt_style, width, height, num_images, seed?, input_image?
(raw base64, RGB, NO data: prefix), strength? (0-1, default 0.75), check_cost?

`check_cost: true` prices a call for free. Do that before any batch.

Styles that reach GBA scale (verified against the live catalogue 2026-08-05):
    rd_plus__low_res        16-128   the good one for a small sprite
    rd_fast__low_res        16-128   cheaper, rougher
    rd_mini__low_res        16-128
    rd_animation__four_angle_walking   48x48 fixed -- a whole 4-direction walk
                                       cycle in one call, but only at 48 px
    rd_plus__topdown_item   16-96
Note the animation styles are FIXED-SIZE (48 or 64), which is the same trap
PixelLab set: check `min_width`/`max_width` in the catalogue before planning
around a style.

Key lives in RETRODIFFUSION_API_KEY (~/.zshrc), never in this repo.

Usage:
    python3 tools/make_pixel.py --styles
    python3 tools/make_pixel.py "a runner in a white vest" \
        --width 16 --height 32 --style rd_plus__low_res --out sprite.png
    python3 tools/make_pixel.py --fix big.png --out small.png \
        --width 16 --height 21
"""

import argparse
import base64
import io
import json
import os
import pathlib
import sys
import urllib.request

API = "https://api.retrodiffusion.ai/v1"


def fail(msg):
    print(f"make_pixel.py: {msg}", file=sys.stderr)
    sys.exit(2)


def token() -> str:
    t = os.environ.get("RETRODIFFUSION_API_KEY", "")
    if not t:
        fail("RETRODIFFUSION_API_KEY is not set. It lives in ~/.zshrc, like "
             "OPENAI_API_KEY -- never in this repo.")
    return t


def call(path: str, body=None):
    req = urllib.request.Request(
        f"{API}/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-RD-Token": token(), "Content-Type": "application/json"},
        method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        fail(f"HTTP {e.code}: {e.read().decode()[:400]}")


# --------------------------------------------------------------------------
# K-Centroid -- no key, no network
# --------------------------------------------------------------------------

def k_centroid(im, w: int, h: int, centroids: int = 2):
    """Astropulse's pixel-art downscale. One tile per output pixel; k-means the
    tile; keep the most prominent centroid. Preserves hard edges, which is the
    entire reason pixel art survives it and does not survive LANCZOS."""
    import numpy as np
    from PIL import Image
    rgb = im.convert("RGB")
    W, H = rgb.size
    out = Image.new("RGB", (w, h))
    op = out.load()
    a = np.asarray(rgb, dtype=np.float64)
    for y in range(h):
        for x in range(w):
            x0, x1 = int(x * W / w), max(int((x + 1) * W / w), int(x * W / w) + 1)
            y0, y1 = int(y * H / h), max(int((y + 1) * H / h), int(y * H / h) + 1)
            tile = a[y0:y1, x0:x1].reshape(-1, 3)
            if not len(tile):
                continue
            k = min(centroids, len(np.unique(tile, axis=0)))
            if k <= 1:
                op[x, y] = tuple(int(v) for v in tile.mean(axis=0))
                continue
            idx = np.argsort(tile.sum(axis=1))
            c = tile[[idx[0], idx[-1]]] if k == 2 else \
                tile[idx[np.linspace(0, len(idx) - 1, k).astype(int)]]
            lab = None
            for _ in range(12):
                d = ((tile[:, None, :] - c[None, :, :]) ** 2).sum(axis=2)
                lab = d.argmin(axis=1)
                nc = np.array([tile[lab == j].mean(axis=0) if (lab == j).any()
                               else c[j] for j in range(k)])
                if np.allclose(nc, c):
                    break
                c = nc
            op[x, y] = tuple(int(v) for v in c[np.bincount(lab, minlength=k).argmax()])
    return out


def fix(src: pathlib.Path, out: pathlib.Path, w: int, h: int, centroids: int):
    from PIL import Image
    im = Image.open(src).convert("RGBA")
    im = im.crop(im.getbbox())
    if not w or not h:
        fail("--fix needs --width and --height")
    col = k_centroid(im, w, h, centroids).convert("RGBA")
    # Alpha is thresholded, never blended: the GBA has no partial transparency,
    # and a soft edge becomes a halo the moment it is quantised.
    al = im.split()[3].resize((w, h), Image.BOX).load()
    p = col.load()
    for y in range(h):
        for x in range(w):
            c = p[x, y]
            p[x, y] = (c[0], c[1], c[2], 255 if al[x, y] >= 120 else 0)
    out.parent.mkdir(parents=True, exist_ok=True)
    col.save(out)
    print(f"  k-centroid: {im.size[0]}x{im.size[1]} -> {w}x{h} "
          f"(centroids={centroids}) -> {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("prompt", nargs="?")
    ap.add_argument("--style", default="rd_plus__low_res")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--input", type=pathlib.Path, help="img2img source")
    ap.add_argument("--strength", type=float, default=0.75)
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--styles", action="store_true",
                    help="print the live style catalogue, smallest first")
    ap.add_argument("--fix", type=pathlib.Path,
                    help="K-Centroid downscale a PNG. No API key needed.")
    ap.add_argument("--centroids", type=int, default=2)
    ap.add_argument("--cost", action="store_true",
                    help="price the call without spending anything")
    args = ap.parse_args()

    if args.fix:
        if not args.out:
            fail("--fix needs --out")
        fix(args.fix, args.out, args.width, args.height, args.centroids)
        return

    if args.styles:
        d = call("styles/selector")
        rows = sorted(d["styles"], key=lambda s: (s["min_width"], s["prompt_style"]))
        print(f"{len(rows)} styles (min-max width shown; check before planning "
              f"-- animation styles are FIXED size)")
        for s in rows:
            print(f"  {s['prompt_style']:44s} w{s['min_width']}-{s['max_width']:<5}"
                  f" h{s['min_height']}-{s['max_height']:<5} {s['name']}")
        return

    if not args.prompt:
        fail("give a prompt, or --styles / --fix")
    if not (args.width and args.height):
        fail("--width and --height are required: match the sprite size you want")
    if not args.out:
        fail("--out is required")

    body = {"prompt": args.prompt, "prompt_style": args.style,
            "width": args.width, "height": args.height,
            "num_images": args.n}
    if args.seed is not None:
        body["seed"] = args.seed
    if args.input:
        from PIL import Image
        im = Image.open(args.input).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "PNG")
        body["input_image"] = base64.b64encode(buf.getvalue()).decode()
        body["strength"] = args.strength
    if args.cost:
        body["check_cost"] = True
        print(json.dumps(call("inferences", body), indent=2))
        return

    d = call("inferences", body)
    imgs = d.get("base64_images") or ([d["base64_image"]] if "base64_image" in d else [])
    if not imgs:
        fail(f"no images in response: {json.dumps(d)[:400]}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(imgs):
        p = args.out if len(imgs) == 1 else \
            args.out.with_name(f"{args.out.stem}-{i+1}{args.out.suffix}")
        p.write_bytes(base64.b64decode(b))
        print(f"  saved {p}")
    if "credit_cost" in d:
        print(f"  cost {d['credit_cost']} credits, "
              f"{d.get('remaining_credits','?')} remaining")


if __name__ == "__main__":
    main()
