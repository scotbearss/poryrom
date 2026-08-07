# Art pipeline

**What this page is for.** Getting pixel art into a pokeemerald-expansion fork at a quality that
reads as the same cast as the engine's own sprites — and, more often, deciding not to generate it at
all. The founding finding of this project's art work is that a generator **converts** a picture far
better than it **conjures** one from prose; the finding that superseded it is that at GBA overworld
scale you should not be generating either, because the engine already ships a professional's pixels
and a palette edit is lossless (record 75). Everything below is a consequence of one question: *what
resolution does this asset land at?* Read this before generating a sprite. See
[[walls-and-budgets]] for the palette and OAM ceilings the art has to live inside, and
[[maps-and-tilesets]] for tileset art, which is a different problem with a different tool.

---

## 1. The routing table — resolution picks the tool

| Target | First choice | Why |
|---|---|---|
| Overworld sprite, ~14-16 × 19-21 | **`kitbash_sprite.py`** — edit one the engine ships | a palette edit is lossless; every pixel stays where a professional put it |
| …with no suitable base | **`make_pixel.py`** (Retro Diffusion `*_low_res`) | generates from **16 px**; the only generator here that reaches GBA sprite scale |
| Species / battle art, 64×64 | **`make_reference.py`** (gpt-image-1) → PixelLab | proven by the Legs line; room for the detail both tools produce |
| Trainer pic, 64×64 | same | ditto |
| Any big art that must end up small | **`make_pixel.py --fix`** (K-Centroid) | the only downscaler that survives the trip |

This project got that routing wrong three times in a single round (record 75), and **each failure
passed the check the previous failure had installed**:

1. **31-35 px tall** — generated to the *frame* size. The frame is 16×32; the character inside it is
   ~14×21 with the top third empty. About **60 % too big for the cast**.
2. **21 px tall, 9 px wide, aspect 0.39** — height dead on and still wrong, because the cast is
   uniformly **14-16 wide in every direction, side views included**. A stick figure fits a 16×32 cell
   perfectly, so nothing in the pipeline objected.
3. **Right proportions, wrong resolution** — gpt-image-1 → PixelLab v3 produced genuinely good art at
   **52×87**. PixelLab's v3 reference mode **refuses to output below 32 px**. Reduced to 13×21 with
   LANCZOS/BOX/BILINEAR the face turned to mud: the eyes are *two pixels* in the original, and a 4×
   reduction destroys exactly the pixels doing the work.

**A generation pipeline has a resolution floor, and below it the art is good and unusable.** Ask what
resolution a pipeline actually lands on before adopting it for a new asset class, and expect the
pipeline to *split* — the same route is right for a 64×64 battle sprite and cannot reach a 14×21
walking one.

---

## 2. Kitbashing — the documented method, not a shortcut

The community teaches exactly one method at this scale: use an existing official sprite as a base
(record 75). It is the same rule as `new_map.py --dump-layout` (derive map data from a real layout,
never invent metatile ids), `make_card_panel.py` (replay the engine's own vertex maths), and
`check_dialogue.py` (score against the pin's own corpus) — see [[dialogue-voice]]. Art was the last
domain in this project to get it.

**And the base is usually already in the fork.** `reps` wanted a trainee in gym clothes; Emerald ships
`running_triathlete_m` — a runner in a vest and shorts, **16×20, aspect 0.80**, dead centre of the
measured band, nine frames, hand-placed. Three AI generations were spent trying to reach that quality
from prose while the answer sat in the tree (record 75).

`tools/kitbash_sprite.py`:

1. Loads an indexed (mode `P`) sheet from the fork.
2. `--report` prints per-index usage and row bands. **An index with zero uses is a free slot** — the
   triathlete had exactly one, index 14.
3. Optionally applies a **region remap** inside a row band, then a palette edit.
4. Writes the sheet plus a **CRLF JASC-PAL**, with every colour snapped to multiples of 8 (gbagfx
   truncates each channel to 5 bits, so the `.pal` on disk should say what the screen will show).

**The hazard, and its check.** Two regions can share a palette entry — the triathlete's headband and
vest are both indices 5/6, so whitening the vest whitens the headband. Splitting them needs a row
band, and **a band whose edge cuts through the region it should leave alone is the only way this
breaks**. The tool asserts on the **source** indices in the **gap** between the regions: measured
across all nine frames the headband is rows 12-20 and the vest rows 23-27, so rows **21-22** are empty
of both and the boundary goes there. With the boundary in empty space the exact row stops mattering
(record 75).

*The first draft of that check tested the **destination** indices outside the band and fired on a
correct edit, because a destination like "the hair colour" legitimately appears elsewhere on the body.
An assertion against a non-unique field is not weak, it is **wrong** (record 68).* See
[[verification-discipline]].

---

## 3. Measure the cast before you generate anything

### 3.1 Overworld people — the band

Across 20 of the engine's own overworld sprites: **width 14-16, height 18-21, aspect 0.67-0.89**,
content in rows ~10-30 of the 16×32 cell (record 75). `tools/make_player_sheet.py` measures this
**from the fork at build time and REFUSES a sheet outside the band**, naming which of width / height /
aspect failed; `--allow-offmodel` overrides and still reports. It correctly rejects the sprite that
shipped on the first attempt.

Also fixed by the engine and asserted rather than remembered: the player sheet is **nine frames**, and
**East does not exist** — `sAnim_FaceEast` / `sAnim_GoEast` are frames 2/7/8 h-flipped. Drawing East
separately is worse than wasted: it makes the character asymmetric in a way the engine never shows.

**"The right height" and "the right shape" are different claims.** Attempt 2 hit the height target dead
on and was still wrong on width and aspect. When you derive a target from a reference, derive the
**whole silhouette**, not the one dimension you happened to think of (record 75).

### 3.2 Battle sprites — area, and the shape of a *line*

Drawn bounding box of frame 1 of `anim_front.png`, all in the same 64×64 frame, index 0 being the
transparency key (record 70):

| species | box | area px² |
|---|---|---|
| torchic | 25 × 43 | 1,075 |
| bulbasaur | 35 × 33 | 1,155 |
| **moocalf** (ours, stage 1) | 43 × 56 | **2,408** |
| miltank | 54 × 47 | 2,538 |
| **squataur** (ours, stage 2) | 48 × 58 | **2,784** |
| **quadrabull** (ours, stage 3) | 52 × 59 | **3,068** |
| blaziken | 50 × 64 | 3,200 |
| tauros | 64 × 56 | 3,584 |
| aggron | 64 × 64 | 4,096 |

Over a random sample of **150** stock species: **median 2,208 · p90 3,776 · max 4,096.**

The finding is about the **line**, not the individual: `2,408 → 2,784 → 3,068` is **+27 % across three
stages**, where Torchic → Blaziken is `1,075 → 3,200`, **+198 %**. A baby already above the dex median
leaves the evolution nowhere to go and the line reads flat. Target for a redraw: stage 1 near
**1,200-1,500 px²**, stage 2 near **2,100-2,400**, stage 3 unchanged (record 70).

**Scale can be faked** — `gSpeciesInfo` carries `frontPicSize` / `frontPicYOffset`, and the pin has a
sprite visualiser (`DEBUG_POKEMON_SPRITE_VISUALIZER TRUE`, Select in the summary screen). Shrinking the
drawn pixels is the honest fix; moving the offset is not. **Re-measure after any change** rather than
eyeballing it.

---

## 4. The reference for one asset class is actively wrong for another

`make_reference.py --preset sheet` deliberately produces **angled** three-quarter views, which is the
battle-sprite convention and correct there. An overworld walking sprite is the opposite: **square-on,
symmetrical, arms down, neutral resting face** — its life comes from the walk cycle, not the pose. A
posed reference also measured **aspect 1.05** against the 0.67-0.89 band, because mid-stride puts the
arms out (record 75).

**Project a candidate reference into the target's own measured band before converting it.** One line of
arithmetic picks between three good-looking pictures.

**And walk the whole pipeline when the asset class is new.** The reference→convert step was established
for creature art and then simply not applied to the player character, for no reason beyond nobody
saying so out loud; three prose-driven generations came back "dinky" first (record 75). When a class
of asset is new, ask which steps of your existing pipeline were about the *old asset* and which were
about the *medium*.

---

## 5. Downscaling, alpha, and order of operations

**K-Centroid** (`make_pixel.py --fix`) is the durable find of record 75 and needs no API key: one tile
per output pixel, k-means the tile, keep the most prominent centroid. A hard black outline stays a hard
black outline instead of being averaged into its neighbours. Measured on the 52×87 → 13×21 case,
**LANCZOS loses the eyes and the outline entirely; K-Centroid keeps both.** `centroids` defaults to
**2** on the vendor's own advice — higher values introduce noise. Use it for *any* reduction of art
that has to end up as pixel art, species work included.

**Threshold alpha, never blend it.** The GBA has no partial transparency; a soft edge becomes a halo
the moment it is quantised.

**Quantise AFTER thresholding alpha, never before.** Compositing onto a transparency key and then
reducing colours lets the key win palette slots, and the sprite comes out **outlined in magenta**. This
is an ordering fault, not a filter choice (record 75).

---

## 6. Retro Diffusion, when you must generate at target scale

Purpose-trained for pixel art, so it produces grid-aligned pixels without blur. Its model is **not**
Stable Diffusion and its FAQ is explicit that SD/Midjourney habits return poor results (record 75):
**one descriptive sentence then a handful of tags** (not a tag soup, not a paragraph); **no
quality-stacking** ("best quality, masterpiece, ultra detailed") — it actively hurts; **describe the
subject only**, since `prompt_style` carries the pixel-art look; prefer industry terms ("contrast
lighting"); and expect word choice to move the *whole* image, not just its referent.

`POST https://api.retrodiffusion.ai/v1/inferences`, header `X-RD-Token: rdpk-…`. Body: `prompt`,
`prompt_style`, `width`, `height`, `num_images`, optional `seed`, `input_image` (raw base64, RGB, **no**
`data:` prefix), `strength` (0-1, default 0.75), `check_cost`. **`GET /v1/styles/selector` is the
authoritative live catalogue with per-style size limits** — read it rather than trusting any written
list, this one included. **`check_cost: true` prices a call for free; do that before any batch** — a
16×32 `rd_plus__low_res` measured **$0.024**. Key lives in `RETRODIFFUSION_API_KEY` in `~/.zshrc`, never
in a repo — see [[build-system]].

Styles that reach GBA scale (of 90 in the catalogue): `rd_plus__low_res`, `rd_fast__low_res`,
`rd_mini__low_res` (all 16-128), `rd_plus__topdown_item` (16-96), `rd_animation__four_angle_walking`
(**fixed 48×48**), `rd_animation__battle_sprites` (**fixed 64×64**). **The animation styles are
fixed-size — the same trap PixelLab set.** Check `min_width` / `max_width` before planning a round
around a style.

---

## 7. Getting the pixels into the ROM

Sprites go in as PNGs through the engine's own **`gbagfx`**, not through the parent toolkit's
`import_art.py`, which is the Butano path (record 64). The contract:

- **Indexed PNG, ≤16 colours, index 0 is the transparency key** (records 34, 35).
- **Front and back quantise together into ONE 16-colour table**; `shiny.pal` is the same slots
  recoloured; **icons quantise separately** against a chosen shared icon palette. Generated art will
  not naturally share a palette across the front/back pair — that is the thing most likely to bite
  (record 37).
- Battle sprites **64×64** front and back; trainer sprites 64×64; overworld sprites are small framed
  walk-sheets.
- **Delete co-located generated `.4bpp*` / `.gbapal*` / `.lz` after rewriting any PNG or PAL**, or
  `gbagfx` will not reconvert (record 37). `tools/new_species.py` never copies generated files for
  exactly this reason, and carries the donor's sprite-coordinate metadata (pic sizes, y-offsets,
  scales, icon palette index, anim ids) *with* the art, because art and its metadata drift apart
  otherwise.

**JASC-PAL is CRLF, and `patch` is not.** A `.pal` carried through a diff comes back LF-only —
moocalf's replayed palette was **190 bytes against the fork's 209**, and had shipped that way since the
first species landed. It was invisible because a second mechanism quietly copied the CRLF version back
over it; the redundancy that looked like duplication *was the repair*. `.pal` is now carried as a
binary asset only (record 65). See [[build-system]] for `export_hack.py`'s replay-and-byte-compare.

---

## 8. Failure modes — what each one actually looks like

🔇 marks a fault with no wrong number and no error anywhere — only a picture or a static check sees it.

| Fault | What you see | 🔇 |
|---|---|---|
| Generated to the frame size, not the content size | a character ~60 % larger than the cast beside it; every dimension legal | 🔇 |
| Right height, wrong width | a stick figure that fits its cell perfectly (record 75) | 🔇 |
| Reduced from above the resolution floor | a face that is mud; two-pixel eyes destroyed | to a human eye only |
| Quantised before alpha thresholding | the whole sprite outlined in magenta | no |
| Blended alpha instead of thresholded | a halo around every edge | no |
| Kitbash band edge cutting a region | the headband recolours with the vest | no, if the gap assertion runs |
| Stale generated `.4bpp` / `.gbapal` left in place | the **old** sprite in the ROM after a successful build (record 37) | 🔇 |
| Front and back quantised separately | front and back in visibly different colours | no |
| `.pal` carried through `diff`/`patch` | a palette 19 bytes short; the patch applies with zero rejects (record 65) | 🔇 |
| Sprite past the OBJ palette budget | drawn in full, right place, right animation, **someone else's colours** (record 74) | 🔇 |
| A silhouette guard measuring mode `P` via `convert("RGBA")` | it runs, prints, compares, and is wrong for every sprite (§9) | 🔇 |

---

## 9. The guard that measured the wrong thing

The silhouette check was written for the generate-and-downscale route. When that route was abandoned
the check stayed attached to it, so **the only pipeline it guarded was the one nobody used** and the
sprite that actually shipped went through no check at all. Wiring it into `kitbash_sprite.py` exposed a
second fault immediately (record 75):

**`.convert("RGBA")` on an indexed sheet destroys the measurement.** A GBA 4bpp sprite is mode `P` and
**palette index 0 *is* the transparent colour** — there is no alpha channel. Converting makes index 0
an opaque green, every pixel becomes content, and the measured box is the **16×32 cell** rather than
the character. It reported the shipped sprite as `w 16, h 32, aspect 0.50` — a number that is wrong for
*any* sprite, which is what makes it dangerous: the guard still ran, still printed, still compared
against the band, and still looked like it was working.

Fixed by reading index `!= 0` when the mode is `P`, and re-proved by sabotage: a synthetically narrowed
sheet is refused at `aspect 0.38`, and the real one passes at **16 × 21, aspect 0.76**.

Two rules out of it:

- **A guard rail attached to an abandoned code path is not a guard rail.** When a pipeline is replaced,
  walk its checks over to the replacement or delete them.
- **Transparency is a per-format question, not a universal one.** `convert("RGBA")` is the obvious call,
  it never errors, and it is wrong here.

---

## 10. Standing rules

- **One canonical brief per character or species, pasted verbatim into every generation.** A prompt
  describes one image; a brief pins the subject. Size intent belongs in the brief or the next
  regeneration loses it (record 70).
- **Send screenshots of every changed state before the user plays.** Art faults are the class a probe
  cannot see — there is no wrong *number* in a sprite wearing the wrong colours. See
  [[verification-discipline]].
- **Retro Diffusion for base sprites, PixelLab for rotation and animation** — the vendor's own
  head-to-head advice, and it matches what this project measured (record 75).

## Still open

- The `reps` trainer front pic is installed and built but **has never been seen on screen** — it shows
  only on the trainer card and no spec reaches there (record 75).
- The Moocalf / Squataur redraw at the corrected area targets is deferred and needs a PixelLab session
  (record 70).
