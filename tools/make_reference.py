#!/usr/bin/env python3
"""Concept-reference image generation -- the intermediary before PixelLab.

The pipeline (user's call 2026-08-02, evidence base in docs/research/55):
PixelLab converts a PICTURE into a sprite far better than it conjures one from
prose, so the picture is perfected FIRST -- generated here with gpt-image-1 at
~$0.011 a try, reviewed in chat, iterated with --edit, and only the approved
image goes to PixelLab. Every prompt-engineering finding from doc 55 is baked
into the scaffolding so a plain description comes out conversion-ready:

  * die-cut-sticker / flat-vector / cel-shade style anchor -- the consensus
    keyword family for flat color, hard closed outlines, strong silhouette
  * color economy in the prompt (3-4 material groups, 2-3 shade steps,
    cool-shifted shadows) so 15-color quantization has something to keep
  * "neutral white balance, no warm cast" against the documented sepia drift
  * background: "transparent" API param (never prompt text) plus the
    anti-hole sentence against the white-interior punch-out bug
  * moderation: "low" -- the documented lever against false-positive
    rejections (and never name a console or franchise in your prompt; the
    pre-filter rejects trademarks deterministically)
  * edits run with input_fidelity: "high" and auto-append the verbatim
    preserve list, the official identity-drift countermeasure

PRESETS
  --preset creature   one creature, single view (default)
  --preset sheet      the IDENTITY ANCHOR: front view + back view in ONE
                      landscape image ("character model sheet" -- cross-view
                      consistency is far higher inside one generation than
                      across two). Generate this once per creature, keep it
                      forever, attach it to every later --edit. Design note:
                      the back view is what the player stares at all game --
                      give the creature a distinctive rear silhouette or back
                      marking, and remember front+back share ONE 15-color
                      palette on the GBA. Both views come out ANGLED (front
                      3/4 toward the viewer's bottom-left, back turned toward
                      the upper-right) -- the battle-sprite convention, doc 55
                      §5; baked in 2026-08-03 after Moocalf shipped square-on.
  --raw               no scaffold, prompt sent verbatim

USAGE
    tools/make_reference.py "small round orange salamander, determined" \
        --preset sheet --out design/reps/reports/assets/repling-sheet.png
    tools/make_reference.py "raise the left arm into a flex" \
        --edit repling-sheet.png --out repling-sheet-v2.png
    tools/make_reference.py ... --deliver
        also writes <out>-256.png: 256x256 Lanczos downscale, alpha kept --
        the exact artifact PixelLab's tools want (their stated contract:
        PNG, <=256px, flat colors, background removed, subject centered).

  --white       solid white background instead of transparent (use when the
                creature has large white/cream regions -- the transparent
                mode's hole-punch bug bites those)
  --quality     low|medium|high (default low; iterate low, finalize medium)
  --n           1-10 variants in one call (generation only)
  --size        1024x1024|1024x1536|1536x1024 (sheet preset defaults landscape)

Needs OPENAI_API_KEY in the environment (~/.zshrc). "Billing hard limit has
been reached" = platform credits ran dry. Rejected borderline prompts are
free and the IP classifier is probabilistic -- a plain retry is legitimate.
Exit 0 on success (prints paths), 2 on any failure.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

API = "https://api.openai.com/v1/images"

# Doc 55 §3: consensus style anchor. Order per OpenAI's own guide:
# scene -> subject -> key details -> constraints.
STYLE = (
    "die-cut sticker style flat vector art, restrained cel shading with hard-edged "
    "shade regions only, thick clean closed even-weight outlines, strong readable "
    "silhouette, limited palette of 3-4 material color groups with 2-3 shade steps "
    "each, shadows hue-shifted cooler rather than darkened, no gradients, no "
    "photoreal texture, no noise, neutral white balance, no warm cast, no text, "
    "no watermark. Retro creature-collector RPG concept art."
)

# Doc 55 §5: battle sprites are ANGLED, never dead-on -- fronts read at a 3/4
# turn facing the viewer's bottom-left (toward the player's mon), backs angle
# slightly toward the upper-right (toward the opponent). Baked here 2026-08-03
# after Moocalf shipped square-on and the user caught it against real sprites.
PRESETS = {
    "creature": (
        "A single {prompt}, full body, centered with clear margins, turned at a "
        "slight three-quarter angle facing the viewer's bottom-left. " + STYLE
    ),
    "sheet": (
        "Character model sheet of {prompt}: full-body FRONT view and full-body BACK "
        "view side by side, identical colors, markings, proportions and details in "
        "both views, neutral standing pose, both views centered with clear margins. "
        "The FRONT view is turned at a slight three-quarter angle facing the "
        "viewer's bottom-left, not straight-on. The BACK view is seen from behind "
        "and turned slightly toward the upper-right, showing a distinctive rear "
        "silhouette and back markings. " + STYLE
    ),
}

# Doc 55 §2: the community-verified counter to the transparent-background
# white-interior punch-out bug.
ANTI_HOLE = (
    " Ensure there is no transparency within the subject itself, "
    "just around the standalone subject."
)

# Doc 55 §4: the official drift countermeasure -- repeated VERBATIM on every
# edit, never paraphrased.
PRESERVE = (
    " Keep everything else exactly the same: do not change the creature's face, "
    "markings, colors, proportions, silhouette, outline style, or identity in any way."
)


def die(msg: str):
    sys.exit(f"make_reference.py: {msg}")


def call_api(args, prompt: str) -> dict:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        die("OPENAI_API_KEY is not set (it lives in ~/.zshrc; source it first)")
    background = "opaque" if args.white else "transparent"
    if args.edit:
        cmd = ["curl", "-s", f"{API}/edits",
               "-H", f"Authorization: Bearer {key}",
               "-F", "model=gpt-image-1",
               "-F", f"image=@{args.edit}",
               "-F", f"prompt={prompt}",
               "-F", f"size={args.size}",
               "-F", f"quality={args.quality}",
               "-F", f"background={background}",
               "-F", "input_fidelity=high"]
    else:
        body = json.dumps({"model": "gpt-image-1", "prompt": prompt,
                           "size": args.size, "quality": args.quality,
                           "background": background, "moderation": "low",
                           "n": args.n})
        cmd = ["curl", "-s", f"{API}/generations",
               "-H", f"Authorization: Bearer {key}",
               "-H", "Content-Type: application/json", "-d", body]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        die(f"curl failed: {out.stderr.strip()[:200]}")
    try:
        resp = json.loads(out.stdout)
    except json.JSONDecodeError:
        die(f"non-JSON API response: {out.stdout[:200]}")
    if "error" in resp:
        die(f"API error: {resp['error'].get('message', '?')[:300]}")
    return resp


def build_prompt(args) -> str:
    if args.raw:
        return args.prompt
    if args.edit:
        # Official edits guidance: describe the whole resulting image, state
        # the one change, then lock everything else (doc 55 §2, §4).
        return f"The same image with one change: {args.prompt}.{PRESERVE}"
    prompt = PRESETS[args.preset].format(prompt=args.prompt)
    if args.white:
        prompt += " Pure solid white background, a single uniform #FFFFFF field."
    else:
        prompt += ANTI_HOLE
    return prompt


def deliver(src: Path) -> Path:
    """256x256 PixelLab-ready artifact: Lanczos fit, PNG, alpha preserved."""
    from PIL import Image
    img = Image.open(src).convert("RGBA")
    img.thumbnail((256, 256), Image.LANCZOS)
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    canvas.paste(img, ((256 - img.width) // 2, (256 - img.height) // 2))
    out = src.with_name(src.stem + "-256.png")
    canvas.save(out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("prompt", help="the creature/change description -- genre words only, "
                                   "NEVER console or franchise names (deterministic filter)")
    ap.add_argument("--out", required=True, help="output PNG path")
    ap.add_argument("--preset", default="creature", choices=sorted(PRESETS),
                    help="creature = single view; sheet = front+back identity anchor")
    ap.add_argument("--edit", metavar="PNG",
                    help="iterate on an existing image (attach the ORIGINAL sheet, "
                         "not the latest revision -- it is the identity anchor)")
    ap.add_argument("--white", action="store_true",
                    help="solid white background instead of transparent")
    ap.add_argument("--quality", default="low", choices=["low", "medium", "high"])
    ap.add_argument("--n", type=int, default=1, help="variants per call (1-10, generation only)")
    ap.add_argument("--size", default=None,
                    choices=["1024x1024", "1024x1536", "1536x1024"])
    ap.add_argument("--raw", action="store_true", help="no scaffold, prompt sent verbatim")
    ap.add_argument("--deliver", action="store_true",
                    help="also write the 256px PixelLab-ready PNG beside --out")
    args = ap.parse_args()

    if args.size is None:
        args.size = "1536x1024" if (args.preset == "sheet" and not args.edit) else "1024x1024"
    if args.edit and not Path(args.edit).is_file():
        die(f"--edit image {args.edit} not found")
    if not 1 <= args.n <= 10:
        die("--n must be 1-10")

    resp = call_api(args, build_prompt(args))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, item in enumerate(resp["data"]):
        path = out if len(resp["data"]) == 1 else out.with_name(f"{out.stem}-{i + 1}{out.suffix}")
        path.write_bytes(base64.b64decode(item["b64_json"]))
        saved.append(path)
    usage = resp.get("usage", {})
    for path in saved:
        print(f"saved {path}")
        if args.deliver:
            print(f"saved {deliver(path)}  (PixelLab-ready)")
    print(f"({usage.get('total_tokens', '?')} tokens, quality={args.quality}, "
          f"{'edit+fidelity=high' if args.edit else 'generation'})")


if __name__ == "__main__":
    main()
