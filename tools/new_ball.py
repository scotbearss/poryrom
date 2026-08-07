#!/usr/bin/env python3
"""New-Poké-Ball codegen for the Pokémon Thing mode.

The fourth content tool, after check_map.py, new_species.py and new_map.py
(doc 64 §7). It exists because adding a ball is the one content addition on
this engine that is NOT append-only, and the reason is a wall nothing in the
corpus had measured:

  A BALL'S ITEM ID MUST BE <= 63 AND CONTIGUOUS WITH THE OTHER BALLS.

  * `struct BoxPokemon` stores the ball a mon was caught in as `pokeball:6`
    (include/pokemon.h) -- 63 balls, hard.
  * `gBattleResults.catchAttempts[gLastUsedItem - FIRST_BALL]` indexes an
    array of POKEBALL_COUNT `u8`s by that difference, so a gap in the ball
    range is an out-of-bounds write during a catch, not a cosmetic problem.
  * `.secondaryId = ITEM_<X>_BALL - FIRST_BALL` in the item table says the
    same thing a second time.

  The last ball is ITEM_CHERISH_BALL = 27 and item 28 is ITEM_POTION, so the
  ONLY place a new ball can go is 28 -- and every item id from 28 up shifts by
  one. **That is save-visible**: SaveBlock1's bag pockets store raw `u16
  itemId` (include/global.h `struct ItemSlot`), so a save written before the
  shift reads every item one slot off afterwards, silently, with a valid
  checksum. Same family as doc 65's "a new map is APPENDED, never inserted",
  and worse, because here appending is not available.

  ADD BALLS BEFORE LONG-LIVED SAVES. The tool says so on every run.

Nothing outside include/constants/items.h needs to move: every other reference
in the tree -- item tables, map JSON, scripts, shop inventories -- names items
symbolically. That was checked, not assumed.

WHAT IT EDITS, in order (all under --hack, a pokeemerald-expansion fork):

  1. include/constants/items.h   the new ITEM_<ID> at LAST_BALL+1; every
                                 numeric item define at or above it shifted
                                 +1; LAST_BALL re-pointed; ITEMS_COUNT +1.
  2. include/pokeball.h          BALL_<ID> appended before POKEBALL_COUNT, so
                                 its index equals ITEM_<ID> - FIRST_BALL.
  3. src/pokeball.c              a GFX_TAG_ define.
  4. src/pokeball.c +            ONE ROW WHEREVER THE DONOR BALL HAS ONE. The
     src/battle_anim_throw.c     ball-indexed tables are scattered and not all
                                 are declared [POKEBALL_COUNT] -- two are
                                 implicitly sized, where a missing row does not
                                 zero-fill a slot, it SHORTENS the array. So
                                 this walks the donor's rows rather than a list
                                 of tables (a hand-written list missed 3 of 9),
                                 and a tree-wide sweep afterwards refuses if any
                                 file's donor-row count and new-row count
                                 disagree. Reusing a donor's particles is also
                                 the right answer on its own terms: a new ball
                                 does not need new particle graphics, and
                                 pretending otherwise is where the tile budget
                                 goes.
  5. src/pokeball.c              the cloned rows still name the donor's art, so
                                 the new ball's three rows are re-pointed at
                                 its own sprite, palette and tag -- each
                                 substitution asserted separately, since a
                                 silent miss is a ball drawn as the donor,
                                 which looks like a working feature.
  6. src/data/graphics/pokeballs.h   the throw-sprite INCBINs.
  7. src/data/graphics/items.h   the bag-icon INCBINs.
  8. include/graphics.h          extern declarations for all four.
  9. src/data/items.h            the [ITEM_<ID>] entry (pocket, battle usage,
                                 secondaryId, icon).
 10. the two ball SWITCHES       GetBallIdFromItemId's item->ball case, and
                                 LoadBallGfx's open-overlay case if the donor
                                 is listed there. A missing case in either does
                                 not crash, it falls to a default -- which is
                                 why they are easy to forget and invisible to a
                                 probe.
 11. graphics/                   balls/<file>.png, items/icons/<file>.png and
                                 items/icon_palettes/<file>.pal, each a DONOR
                                 asset with named palette entries replaced.

NOT TOUCHED, on purpose: gPokeballGraphics (follower-ball overworld sprites).
The pin itself has no row for BALL_POKE there -- 27 rows, and the stock Poké
Ball is not one of them -- so a new ball is exactly as covered as the vanilla
one, and adding a row means new overworld art for a table that is dead at
OW_FOLLOWERS_ENABLED FALSE.

Every edit is asserted individually -- the 2026-07-30 lesson that an edit
script asserting only "the file changed" reports success when one of several
replacements silently fails to match.

ART is a RECOLOUR of a donor ball, not new pixels, and the recolour is
authored from a dump rather than invented:

    python3 tools/new_ball.py --hack <fork> --dump-palette poke

prints the donor's throw-sprite palette and its icon .pal side by side with
usage counts, so the spec names indices that certainly exist. Same rule as
new_map.py --dump-layout and make_card_panel.py: generate the asset from the
original's own data. The throw sprite's palette lives in the PNG itself (the
build's `%.gbapal: %.png` rule); the icon's lives in a separate JASC .pal,
which is CRLF and must stay CRLF (doc 65: `patch` flattens it and the asset
copy is what puts it back).

USAGE
    python3 tools/new_ball.py --hack hacks/reps spec.json
    python3 tools/new_ball.py --hack hacks/reps --dump-palette poke

Exit 0 on success (prints every file touched), 2 on any failed precondition or
assertion. A ball whose id already exists aborts before the first write.

SPEC (JSON):
{
  "id": "REP_BALL",            // -> ITEM_REP_BALL, BALL_REP, GFX_TAG_REP_BALL
  "name": "Rep Ball",          // bag display name
  "price": 600,
  "description": ["A Ball that", "answers to the", "work you put in."],
  "file_stem": "rep",          // graphics/balls/<stem>.png
  "icon_stem": "rep_ball",     // graphics/items/icons/<stem>.png
  "throw_donor": "poke",       // graphics/balls/<donor>.png
  "icon_donor": "poke_ball",   // graphics/items/icons/<donor>.png + .pal
  "particle_donor": "BALL_POKE",   // whose particle anim/template/tag to reuse
  "throw_palette": {"1": "#0b4a20", ...},   // index -> #rrggbb, donor's rest kept
  "icon_palette":  {"7": "#2d5a39", ...}
}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MARK = "new_ball.py"  # stamped into every generated block


def die(msg: str):
    sys.exit(f"new_ball.py: {msg}")


def edit(path: Path, transform, what: str):
    """Apply transform(text) -> new text; assert it actually changed."""
    old = path.read_text()
    new = transform(old)
    if new is None:
        die(f"{what}: anchor not found in {path}")
    if new == old:
        die(f"{what}: edit produced no change in {path}")
    path.write_text(new)
    print(f"  edited  {path} ({what})")


def insert_after(text: str, anchor_re: str, insertion: str):
    """Insert after the single line matching anchor_re; None if not exactly one."""
    matches = list(re.finditer(anchor_re, text, re.M))
    if len(matches) != 1:
        return None
    end = matches[0].end()
    if end < len(text) and text[end] == "\n":
        end += 1
    return text[:end] + insertion + text[end:]


def parse_hex(value: str) -> tuple[int, int, int]:
    s = value.strip().lstrip("#")
    if len(s) != 6:
        die(f"colour {value!r} is not #rrggbb")
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        die(f"colour {value!r} is not #rrggbb")


# ------------------------------------------------------------ palette dumping

def read_jasc(path: Path) -> list[tuple[int, int, int]]:
    """Parse a JASC-PAL file into RGB triples. Tolerates CRLF or LF."""
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "JASC-PAL":
        die(f"{path} is not a JASC-PAL file")
    count = int(lines[2].strip())
    out = []
    for row in lines[3:3 + count]:
        r, g, b = (int(v) for v in row.split())
        out.append((r, g, b))
    return out


def write_jasc(path: Path, colours: list[tuple[int, int, int]]):
    """Write JASC-PAL with CRLF line endings -- the format's own convention,
    and the thing doc 65 caught `patch` silently flattening."""
    body = ["JASC-PAL", "0100", str(len(colours))]
    body += [f"{r} {g} {b}" for r, g, b in colours]
    path.write_bytes(("\r\n".join(body) + "\r\n").encode("ascii"))


def png_palette(path: Path) -> list[tuple[int, int, int]]:
    from PIL import Image
    im = Image.open(path)
    if im.mode != "P":
        die(f"{path} is not a paletted PNG (mode {im.mode})")
    raw = im.getpalette() or []
    return [tuple(raw[i * 3:i * 3 + 3]) for i in range(len(raw) // 3)]


def png_usage(path: Path) -> dict[int, int]:
    from PIL import Image
    counts: dict[int, int] = {}
    for px in Image.open(path).getdata():
        counts[px] = counts.get(px, 0) + 1
    return counts


def dump_palette(hack: Path, donor: str):
    """Print a donor ball's two palettes so a spec can name real indices."""
    throw = hack / "graphics/balls" / f"{donor}.png"
    if not throw.exists():
        die(f"no throw sprite at {throw}")
    icon_stem = donor if donor.endswith("_ball") else f"{donor}_ball"
    icon = hack / "graphics/items/icons" / f"{icon_stem}.png"
    icon_pal = hack / "graphics/items/icon_palettes" / f"{icon_stem}.pal"

    tp, tu = png_palette(throw), png_usage(throw)
    print(f"throw sprite  {throw}  (palette lives in the PNG)")
    for i, (r, g, b) in enumerate(tp[:16]):
        print(f"  {i:2d}  #{r:02x}{g:02x}{b:02x}   {tu.get(i, 0):5d} px")

    if icon_pal.exists():
        ip, iu = read_jasc(icon_pal), png_usage(icon)
        print(f"\nbag icon      {icon_pal}  (palette is a separate JASC .pal)")
        for i, (r, g, b) in enumerate(ip):
            print(f"  {i:2d}  #{r:02x}{g:02x}{b:02x}   {iu.get(i, 0):5d} px")
    else:
        print(f"\n(no icon palette at {icon_pal})")
    print("\nIndex 0 is the transparency key on both -- do not remap it.")


# ------------------------------------------------------------ spec handling

REQUIRED = ("id", "name", "file_stem", "icon_stem",
            "throw_donor", "icon_donor", "particle_donor")


def load_spec(path: Path) -> dict:
    try:
        spec = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        die(f"{path}: {e}")
    for key in REQUIRED:
        if not spec.get(key):
            die(f"{path}: missing required key {key!r}")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*_BALL", spec["id"]):
        die(f"id {spec['id']!r} must be UPPER_SNAKE and end in _BALL "
            "(it becomes ITEM_<id>)")
    desc = spec.get("description") or []
    if len(desc) > 3:
        die("description has more than 3 lines; the bag window fits 3")
    for line in desc:
        if len(line) > 18:
            die(f"description line {line!r} is {len(line)} chars; 18 is the "
                "practical width of the bag description window")
    return spec


def names(spec: dict) -> dict:
    """Every derived symbol, in one place."""
    item_id = spec["id"]                      # REP_BALL
    stem = item_id[:-len("_BALL")]            # REP
    camel = "".join(w.capitalize() for w in item_id.split("_"))   # RepBall
    return {
        "ITEM": f"ITEM_{item_id}",
        "BALL": f"BALL_{stem}",
        "TAG": f"GFX_TAG_{item_id}",
        "GfxCamel": "".join(w.capitalize() for w in stem.split("_")),  # Rep
        "IconCamel": camel,
    }


# --------------------------------------------------------------- 1. item ids

ITEM_DEFINE_RE = re.compile(r"^#define (ITEM_[A-Z0-9_]+) (\d+)$", re.M)


def shift_item_ids(hack: Path, n: dict, spec: dict) -> int:
    """Insert the ball at LAST_BALL+1 and shift every item id at or above it.

    Returns the new ball's item id. This is the dangerous edit in the tool:
    it rewrites ~800 defines, and getting it wrong is a game that builds.
    So it is bounded three ways -- only lines matching ITEM_DEFINE_RE, only
    between FIRST_BALL's define and ITEMS_COUNT, and the resulting id set must
    still be exactly the contiguous range it was before, one longer.
    """
    path = hack / "include/constants/items.h"
    text = path.read_text()
    if f"#define {n['ITEM']} " in text:
        die(f"{n['ITEM']} already exists in {path} -- nothing to do")

    # BOUND THE REWRITE. `ITEM_[A-Z0-9_]+ <number>` is NOT a safe pattern over
    # the whole file: below ITEMS_COUNT the same file defines ITEM_USE_MAIL 0,
    # ITEM_USE_PARTY_MENU_MOVES 5 and friends, which are use-type ids that
    # happen to share the prefix. Renumbering those would silently change what
    # every item in the game DOES. Found by the contiguity guard below on the
    # first run, which is the argument for having it.
    count_m = re.search(r"^#define ITEMS_COUNT (\d+)$", text, re.M)
    if not count_m:
        die(f"{path}: no numeric ITEMS_COUNT define")
    head, tail = text[:count_m.start()], text[count_m.start():]

    m = re.search(r"^#define LAST_BALL\s+(ITEM_[A-Z0-9_]+)$", head, re.M)
    if not m:
        die(f"{path}: no LAST_BALL define above ITEMS_COUNT")
    old_last = m.group(1)
    ids = {name: int(val) for name, val in ITEM_DEFINE_RE.findall(head)}
    if old_last not in ids:
        die(f"{path}: LAST_BALL names {old_last}, which has no numeric define")
    new_id = ids[old_last] + 1

    before = sorted(set(ids.values()))
    if len(before) != len(ids):
        die(f"{path}: two item names share one id above ITEMS_COUNT; refusing")
    if before != list(range(before[0], before[-1] + 1)):
        die(f"{path}: item ids are not contiguous before the edit; refusing "
            "to shift a range this tool does not understand")
    if int(count_m.group(1)) != before[-1] + 1:
        die(f"{path}: ITEMS_COUNT is {count_m.group(1)}, not max(item id) + 1 "
            f"({before[-1] + 1}); refusing")

    def bump(match):
        name, val = match.group(1), int(match.group(2))
        return f"#define {name} {val + 1}" if val >= new_id else match.group(0)

    shifted = ITEM_DEFINE_RE.sub(bump, head) + tail
    if shifted == text:
        die(f"{path}: no item id was shifted -- the ball would collide")

    # The new define goes where the shifted-away id used to be.
    # The comment goes on its OWN line: ITEM_DEFINE_RE anchors at end-of-line,
    # so a trailing `// new_ball.py` would make the new define invisible to
    # the tool's own contiguity assertion -- which is how this was caught.
    shifted = insert_after(
        shifted, rf"^#define {re.escape(old_last)} {ids[old_last]}$",
        f"// {MARK}\n#define {n['ITEM']} {new_id}\n")
    if shifted is None:
        die(f"{path}: could not place {n['ITEM']} after {old_last}")

    shifted = re.sub(r"^#define LAST_BALL\s+ITEM_[A-Z0-9_]+$",
                     f"#define LAST_BALL  {n['ITEM']}", shifted, count=1,
                     flags=re.M)
    shifted = re.sub(r"^#define ITEMS_COUNT \d+$",
                     f"#define ITEMS_COUNT {before[-1] + 2}", shifted,
                     count=1, flags=re.M)

    new_count_m = re.search(r"^#define ITEMS_COUNT \d+$", shifted, re.M)
    after_names = ITEM_DEFINE_RE.findall(shifted[:new_count_m.start()])
    after = sorted(int(v) for _, v in after_names)
    if len(after) != len(before) + 1:
        die(f"{path}: expected {len(before) + 1} ids after the insert, "
            f"got {len(after)} -- aborting before writing")
    if after != list(range(before[0], before[-1] + 2)):
        die(f"{path}: the shifted id set is not contiguous "
            f"({len(after)} ids, {after[0]}..{after[-1]}) -- aborting "
            "before writing")

    path.write_text(shifted)
    print(f"  edited  {path} ({n['ITEM']} = {new_id}; "
          f"{sum(1 for v in before if v >= new_id)} ids shifted +1)")
    return new_id, old_last


# --------------------------------------------------------- 2-8. the C tables

def add_ball_enum(hack: Path, n: dict):
    path = hack / "include/pokeball.h"
    edit(path, lambda t: insert_after(
        t, r"^    BALL_[A-Z0-9_]+,$(?=\n    POKEBALL_COUNT)",
        f"    {n['BALL']},   // {MARK}\n"),
        f"{n['BALL']} before POKEBALL_COUNT")


def add_gfx_tag(hack: Path, n: dict):
    path = hack / "src/pokeball.c"

    def add_tag(t):
        m = list(re.finditer(r"^#define GFX_TAG_[A-Z0-9_]+\s+(\d+)$", t, re.M))
        if not m:
            return None
        last = m[-1]
        return insert_after(t, re.escape(last.group(0)),
                            f"#define {n['TAG']} {int(last.group(1)) + 1}   "
                            f"// {MARK}\n")

    edit(path, add_tag, n["TAG"])


BALL_SOURCES = ("src/pokeball.c", "src/battle_anim_throw.c")


def _row_span(lines: list[str], i: int) -> int:
    """Index one past the row starting at lines[i], by brace depth."""
    depth = 0
    for j in range(i, len(lines)):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth <= 0 and lines[j].rstrip().endswith(","):
            return j + 1
    die(f"unterminated initializer row starting {lines[i]!r}")


def clone_donor_rows(hack: Path, n: dict, donor: str) -> int:
    """Give the new ball a row wherever the DONOR ball has one.

    Ball-indexed tables are scattered and not all of them are declared
    `[POKEBALL_COUNT]` -- two in battle_anim_throw.c are implicitly sized, so
    a missing row does not zero-fill, it shortens the array and every read at
    the new ball's index is out of bounds. Listing the tables by hand missed
    three of nine on the first attempt, which is why this walks the donor's
    rows instead: the new ball is defined wherever, and only wherever, the
    donor already is. Doc 68's rule -- to claim something is covered, account
    for every slot rather than checking the slots you remembered.

    NOT touched: gPokeballGraphics (follower-ball overworld sprites). The pin
    itself has no row for BALL_POKE there -- 27 rows, no POKE -- so a new ball
    is exactly as covered as the stock Poké Ball, and adding one would mean
    new overworld art for a table that is dead at OW_FOLLOWERS_ENABLED FALSE.
    """
    total = 0
    for rel in BALL_SOURCES:
        path = hack / rel
        lines = path.read_text().splitlines(keepends=True)
        out, cloned = [], 0
        i = 0
        start_re = re.compile(rf"^(\s*)\[{re.escape(donor)}\]\s*=")
        while i < len(lines):
            m = start_re.match(lines[i])
            if not m:
                out.append(lines[i])
                i += 1
                continue
            end = _row_span(lines, i)
            row = lines[i:end]
            out.extend(row)
            copy = list(row)
            copy[0] = copy[0].replace(f"[{donor}]", f"[{n['BALL']}]", 1)
            copy[-1] = copy[-1].rstrip("\n") + f"   // {MARK}, from {donor}\n"
            out.extend(copy)
            cloned += 1
            i = end
        if not cloned:
            die(f"{path}: no [{donor}] row found -- particle_donor wrong?")
        path.write_text("".join(out))
        print(f"  edited  {path} ({cloned} table rows cloned from {donor})")
        total += cloned
    return total


def retarget_gfx_rows(hack: Path, n: dict, spec: dict):
    """The cloned rows in pokeball.c still name the donor's art. Point the
    new ball's three rows at its own sprite, palette and tag -- each
    substitution asserted separately, since a silent miss here is a ball that
    is drawn as the donor and looks like a working feature."""
    path = hack / "src/pokeball.c"
    donor_camel = "".join(w.capitalize()
                          for w in spec["particle_donor"][len("BALL_"):]
                          .lower().split("_"))
    donor_tag = f"GFX_TAG_{spec['particle_donor'][len('BALL_'):]}_BALL"
    swaps = [(f"gBallGfx_{donor_camel}", f"gBallGfx_{n['GfxCamel']}"),
             (f"gBallPal_{donor_camel}", f"gBallPal_{n['GfxCamel']}"),
             (donor_tag, n["TAG"])]
    row_re = re.compile(rf"^(\s*)\[{re.escape(n['BALL'])}\]\s*=")

    text = path.read_text()
    lines = text.splitlines(keepends=True)
    for old, new in swaps:
        hits, i = 0, 0
        while i < len(lines):
            if row_re.match(lines[i]):
                end = _row_span(lines, i)
                for j in range(i, end):
                    if old in lines[j]:
                        lines[j] = lines[j].replace(old, new)
                        hits += 1
                i = end
            else:
                i += 1
        if not hits:
            die(f"{path}: no {n['BALL']} row references {old} -- the cloned "
                "rows do not look like the donor's")
        print(f"  edited  {path} ({old} -> {new} in {hits} line(s))")
    path.write_text("".join(lines))


def add_incbins(hack: Path, n: dict, spec: dict):
    gfx, pal = f"gBallGfx_{n['GfxCamel']}", f"gBallPal_{n['GfxCamel']}"
    icon, icon_pal = (f"gItemIcon_{n['IconCamel']}",
                      f"gItemIconPalette_{n['IconCamel']}")
    stem, istem = spec["file_stem"], spec["icon_stem"]

    edit(hack / "src/data/graphics/pokeballs.h", lambda t: t + (
        f'\nconst u32 {gfx}[] = INCBIN_U32("graphics/balls/{stem}.4bpp.lz");'
        f'   // {MARK}\n'
        f'const u32 {pal}[] = INCBIN_U32("graphics/balls/{stem}.gbapal.lz");\n'
    ), "throw-sprite INCBINs")

    edit(hack / "src/data/graphics/items.h", lambda t: t + (
        f'\nconst u32 {icon}[] = INCBIN_U32('
        f'"graphics/items/icons/{istem}.4bpp.lz");   // {MARK}\n'
        f'const u32 {icon_pal}[] = INCBIN_U32('
        f'"graphics/items/icon_palettes/{istem}.gbapal.lz");\n'
    ), "bag-icon INCBINs")

    externs = (f"\nextern const u32 {gfx}[];   // {MARK}\n"
               f"extern const u32 {pal}[];\n"
               f"extern const u32 {icon}[];\n"
               f"extern const u32 {icon_pal}[];\n\n")
    edit(hack / "include/graphics.h",
         lambda t: (t.replace("\n#endif //GUARD_GRAPHICS_H",
                              externs + "#endif //GUARD_GRAPHICS_H", 1)
                    if "\n#endif //GUARD_GRAPHICS_H" in t else None),
         "extern declarations")


def add_item_entry(hack: Path, n: dict, spec: dict, prev_last: str):
    path = hack / "src/data/items.h"
    desc = spec.get("description") or [spec["name"]]
    lines = "\n".join(f'            "{l}\\n"' for l in desc[:-1])
    lines = (lines + "\n" if lines else "") + f'            "{desc[-1]}"'
    entry = (
        f"    [{n['ITEM']}] =   // {MARK}\n"
        f"    {{\n"
        f'        .name = _("{spec["name"]}"),\n'
        f"        .price = {spec.get('price', 0)},\n"
        f"        .description = COMPOUND_STRING(\n{lines}),\n"
        f"        .pocket = POCKET_POKE_BALLS,\n"
        f"        .type = ITEM_USE_BAG_MENU,\n"
        f"        .battleUsage = EFFECT_ITEM_THROW_BALL,\n"
        f"        .secondaryId = {n['ITEM']} - FIRST_BALL,\n"
        f"        .iconPic = gItemIcon_{n['IconCamel']},\n"
        f"        .iconPalette = gItemIconPalette_{n['IconCamel']},\n"
        f"    }},\n")
    # Anchored on the entry of the ball that USED to be last, not on the
    # section comment that happens to follow it.
    anchor = (r"^    \[" + re.escape(prev_last) + r"\] =\n"
              r"(?:(?!\n    \},)[\s\S])*?\n    \},$")
    edit(path, lambda t: insert_after(t, anchor,
                                      "\n" + entry.rstrip("\n") + "\n"),
         f"{n['ITEM']} item entry")


def add_switch_cases(hack: Path, n: dict, spec: dict):
    """The two switches that are keyed on a ball rather than indexed by one.

    A missing case here does not crash -- it falls to a default -- which is
    exactly why they are easy to forget and impossible to see in a probe.
    """
    edit(hack / "src/battle_anim_throw.c", lambda t: insert_after(
        t, r"^    case ITEM_[A-Z0-9_]+:\n        return BALL_[A-Z0-9_]+;$"
           r"(?=\n    default:)",
        f"    case {n['ITEM']}:   // {MARK}\n        return {n['BALL']};\n"),
        "GetBallIdFromItemId case")

    # LoadBallGfx's switch decides which balls get the "open ball" overlay
    # drawn. Follow the donor: if the donor is listed, the clone must be too,
    # or the new ball opens without its lid.
    donor = spec["particle_donor"]
    path = hack / "src/pokeball.c"
    text = path.read_text()
    block = re.search(r"switch \(ballId\)\n    \{\n(.*?)\n    \}", text, re.S)
    if not block:
        die(f"{path}: could not find LoadBallGfx's switch (ballId)")
    donor_listed = re.search(
        rf"\bcase {re.escape(donor)}\b|\bcase BALL_\w+ \.\.\. BALL_\w+:",
        block.group(1)) is not None
    if not donor_listed:
        print(f"  skipped LoadBallGfx switch ({donor} is not listed there)")
        return
    edit(path, lambda t: insert_after(
        t, r"^    case BALL_[A-Z0-9_]+:$(?=\n        var = GetSpriteTileStartByTag)",
        f"    case {n['BALL']}:   // {MARK}, opens like {donor}\n"),
        "LoadBallGfx open-overlay case")


# ---------------------------------------------------------------- 9. graphics

def recolour_png(src: Path, dst: Path, swaps: dict):
    from PIL import Image
    im = Image.open(src)
    if im.mode != "P":
        die(f"{src} is not a paletted PNG (mode {im.mode})")
    pal = list(im.getpalette() or [])
    for key, colour in swaps.items():
        i = int(key)
        if i == 0:
            die("palette index 0 is the transparency key -- do not remap it")
        if (i + 1) * 3 > len(pal):
            die(f"{src} has no palette index {i}")
        pal[i * 3:i * 3 + 3] = list(parse_hex(colour))
    im.putpalette(pal)
    im.save(dst)
    print(f"  wrote   {dst} ({len(swaps)} palette entries recoloured)")


def add_graphics(hack: Path, spec: dict):
    balls = hack / "graphics/balls"
    icons = hack / "graphics/items/icons"
    ipals = hack / "graphics/items/icon_palettes"

    throw_src = balls / f"{spec['throw_donor']}.png"
    if not throw_src.exists():
        die(f"throw_donor: no {throw_src}")
    recolour_png(throw_src, balls / f"{spec['file_stem']}.png",
                 spec.get("throw_palette", {}))

    icon_src = icons / f"{spec['icon_donor']}.png"
    if not icon_src.exists():
        die(f"icon_donor: no {icon_src}")
    icon_swaps = spec.get("icon_palette", {})
    # The icon's real palette is the .pal; the PNG's embedded one is kept in
    # step so a preview of the PNG looks like the ball the game will draw.
    recolour_png(icon_src, icons / f"{spec['icon_stem']}.png", icon_swaps)

    pal_src = ipals / f"{spec['icon_donor']}.pal"
    if not pal_src.exists():
        die(f"icon_donor: no {pal_src}")
    colours = read_jasc(pal_src)
    for key, colour in icon_swaps.items():
        i = int(key)
        if i >= len(colours):
            die(f"{pal_src} has no index {i}")
        colours[i] = parse_hex(colour)
    dst = ipals / f"{spec['icon_stem']}.pal"
    write_jasc(dst, colours)
    print(f"  wrote   {dst} (JASC-PAL, CRLF)")


# ----------------------------------------------------- post-condition sweep

def check_every_table(hack: Path, n: dict, donor: str, expected_rows: int):
    """Assert the new ball is in EVERY table the donor is in, tree-wide.

    The tool only rewrites BALL_SOURCES; this sweep reads the whole tree, so
    a table that moves to a new file makes the next run fail loudly instead of
    shipping an out-of-bounds index. It counts rows rather than asking "is it
    mentioned somewhere", because a mention is not a slot.
    """
    donor_rows = new_rows = 0
    stray = []
    for path in sorted(hack.glob("src/**/*.[ch]")):
        text = path.read_text(errors="replace")
        d = len(re.findall(rf"^\s*\[{re.escape(donor)}\]\s*=", text, re.M))
        b = len(re.findall(rf"^\s*\[{re.escape(n['BALL'])}\]\s*=", text, re.M))
        donor_rows += d
        new_rows += b
        if d != b:
            stray.append(f"{path.relative_to(hack)}: {d} {donor} rows, "
                         f"{b} {n['BALL']} rows")
    if stray:
        die("the new ball is missing a row the donor has:\n    "
            + "\n    ".join(stray))
    if new_rows != expected_rows:
        die(f"cloned {expected_rows} rows but the tree now shows {new_rows} "
            f"{n['BALL']} rows -- refusing to call this done")
    print(f"  checked {new_rows} {n['BALL']} rows against {donor_rows} "
          f"{donor} rows, tree-wide")


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec", nargs="?", type=Path)
    ap.add_argument("--hack", required=True, type=Path,
                    help="a pokeemerald-expansion fork (hacks/<name>)")
    ap.add_argument("--dump-palette", metavar="DONOR",
                    help="print a donor ball's palettes and exit")
    args = ap.parse_args()

    hack = args.hack.resolve()
    if not (hack / "include/constants/items.h").exists():
        die(f"{hack} does not look like a pokeemerald fork")

    if args.dump_palette:
        dump_palette(hack, args.dump_palette)
        return
    if not args.spec:
        die("give a spec, or --dump-palette DONOR")

    spec = load_spec(args.spec)
    n = names(spec)
    print(f"{spec['name']} ({n['ITEM']}) into {hack}")

    item_id, prev_last = shift_item_ids(hack, n, spec)
    add_ball_enum(hack, n)
    add_gfx_tag(hack, n)
    rows = clone_donor_rows(hack, n, spec["particle_donor"])
    retarget_gfx_rows(hack, n, spec)
    add_incbins(hack, n, spec)
    add_item_entry(hack, n, spec, prev_last)
    add_switch_cases(hack, n, spec)
    add_graphics(hack, spec)
    check_every_table(hack, n, spec["particle_donor"], rows)

    print(f"\n{spec['name']} is {n['ITEM']} = {item_id}, {n['BALL']} = "
          f"{item_id - 1}.")
    print("WARNING: every item id from", item_id, "up shifted by one. Any save "
          "written before this build reads its bag one item off, silently, "
          "with a valid checksum. Start a new save.")
    print("Not done for you: the ball has no ACQUISITION path (mart stock, a "
          "gift script) and no catch-rate behaviour -- both are hack code.")


if __name__ == "__main__":
    main()
