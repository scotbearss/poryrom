#!/usr/bin/env python3
"""Append-only new-species codegen for the Pokémon Thing mode.

The second content tool (docs 64 §7, 37 §1). Doc 37 calls species addition
"the single clearest codegen target" in this mode: on the expansion base it is
~8 files in a FIXED order, every one an append or a single tracked rewrite,
and comma-and-bracket-error-prone by hand. This tool takes an inert JSON spec
(house pattern: make_song.py) and performs every edit, asserting each one
individually -- the 2026-07-30 lesson that an edit script asserting only "the
file changed" reports success when one replacement silently fails to match.

WHAT IT EDITS, in order (all under --hack, a pokeemerald-expansion fork):

  1. include/constants/species.h        SPECIES_<ID> appended before
                                        SPECIES_EGG; the EGG define is rewritten
                                        to (SPECIES_<ID> + 1) so NUM_SPECIES
                                        follows automatically.
  2. include/constants/pokedex.h        NATIONAL_DEX_<ID> appended to the enum;
                                        NATIONAL_DEX_COUNT re-pointed at it via
                                        an #undef/#define block at header end
                                        (macro expansion is lazy, so every use
                                        site sees the final definition).
  3. include/constants/cries.h          CRY_<ID> before CRY_COUNT.
  4. sound/cry_tables.inc               `cry`/`cry_reverse` rows appended to
                                        both tables, matching enum order.
  5. sound/direct_sound_data.inc        Cry_<Name>:: .incbin at end of file,
                                        plus the sample copied into
                                        sound/direct_sound_samples/cries/.
  6. src/data/graphics/pokemon.h        the INCBIN block (front/back/palettes/
                                        icon/footprint). PNG + JASC .pal
                                        sources are copied into
                                        graphics/<name>/; the build's
                                        pattern rules generate .4bpp.lz etc.
                                        Generated files are never copied (doc
                                        37: stale .4bpp*/.lz block reconversion).
  7. src/data/pokemon_graphics/front_pic_anims.h
                                        sAnim_<Name>_1 + SINGLE_ANIMATION.
  8. src/data/level_up_learnsets/custom.h   (created on first use,
                                        #include wired into src/pokemon.c)
  9. src/data/species_info/custom_families.h  the gSpeciesInfo entry
                                        (created on first use, #include wired
                                        into species_info.h). Entries are
                                        UNGATED -- no P_FAMILY_* flag needed.
 10. src/data/pokedex_orders.h  alphabetical (sorted insert by name);
                                        weight/height lists get an append at
                                        the end, deliberately unsorted -- doing
                                        it right means parsing every species'
                                        weight, and a wrong sort position is
                                        cosmetic. Flagged in the output.

ART AND CRY are placeholders by design in this tool: --art-from / --cry-from
name an existing species whose sources are copied (personal, non-distributed
mode -- see CLAUDE.md). The sprite-coordinate metadata (pic sizes,
y-offsets, scales, icon palette index, anim ids) is parsed out of the donor's
own gSpeciesInfo entry and carried WITH the art, because art and its metadata
drift apart otherwise (the pentagon lesson: reusing a look means reusing the
asset, and the numbers are part of the asset). Real art later just replaces
the files and those fields.

KNOWN LIMITS, on purpose:
  * The new species joins the NATIONAL dex only, not the Hoenn dex -- it shows
    in the in-game dex once the player has the national mode.
  * SPECIES_EGG shifts up by one. An egg sitting in an EXISTING save file will
    hatch into the new species. reps has no eggs; still: add species BEFORE
    long-lived saves when possible.
  * Teachable/egg-move learnsets point at the engine's empty sNone* tables --
    TM compatibility is a later, deliberate edit (doc 37 §1).

USAGE
    python3 tools/new_species.py --hack hacks/reps spec.json

Exit 0 on success (prints every file touched), 2 on any failed precondition
or assertion -- in which case files already written stay written; rerunning
after a fix is safe because every step is idempotency-guarded by the species
name, and a duplicate name aborts before the first write.

SPEC (JSON; only "name" and "stats" required):
{
  "name": "Repling",              // display + symbol stem, <=10 chars
  "category": "Wall Sit",         // dex category, <=12 chars
  "description": "Line one.\\nLine two.",       // dex text, <=4 lines
  "stats": {"hp":40,"attack":45,"defense":35,
            "speed":70,"sp_attack":65,"sp_defense":55},
  "types": ["FIGHTING"],          // 1 or 2, TYPE_ names sans prefix
  "abilities": ["GUTS"],          // 1-3, ABILITY_ names sans prefix
  "catch_rate": 45, "exp_yield": 62,
  "ev_yield": {"attack": 1},      // stat keys as in "stats"
  "gender_ratio": 50.0,           // percent female, or "GENDERLESS"
  "egg_cycles": 20, "growth_rate": "MEDIUM_SLOW",
  "egg_groups": ["FIELD"], "body_color": "RED",
  "height": 5, "weight": 50,      // decimeters, hectograms
  "level_up_learnset": [[1, "POUND"], [7, "BULK_UP"]],
  "evolution": {"method": "EVO_LEVEL", "param": 16, "target": "SPECIES_X"},
  "art_from": "treecko",          // graphics/<dir> donor
  "cry_from": "treecko"           // cries/<name>.bin donor
}
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import hx

MARK = "new_species.py"  # stamped into every generated block


def die(msg: str):
    sys.exit(f"new_species.py: {msg}")


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


def insert_before(text: str, anchor_re: str, insertion: str):
    """Insert before the single line matching anchor_re; None if not exactly one."""
    matches = list(re.finditer(anchor_re, text, re.M))
    if len(matches) != 1:
        return None
    i = matches[0].start()
    return text[:i] + insertion + text[i:]


# ------------------------------------------------------------ spec handling

STAT_FIELDS = {  # spec key -> (gSpeciesInfo field, EV-yield field)
    "hp": ("baseHP", "evYield_HP"),
    "attack": ("baseAttack", "evYield_Attack"),
    "defense": ("baseDefense", "evYield_Defense"),
    "speed": ("baseSpeed", "evYield_Speed"),
    "sp_attack": ("baseSpAttack", "evYield_SpAttack"),
    "sp_defense": ("baseSpDefense", "evYield_SpDefense"),
}

DEFAULTS = {
    "category": "Unknown", "description": "A newly discovered species.",
    "types": ["NORMAL"], "abilities": ["NONE"],
    "catch_rate": 45, "exp_yield": 60, "ev_yield": {},
    "gender_ratio": 50.0, "egg_cycles": 20, "growth_rate": "MEDIUM_FAST",
    "egg_groups": ["FIELD"], "body_color": "GRAY",
    "height": 10, "weight": 100,
    "level_up_learnset": [[1, "POUND"]],
    "art_from": "treecko", "cry_from": "treecko",
}


def load_spec(path: Path) -> dict:
    spec = {**DEFAULTS, **json.loads(path.read_text())}
    name = spec.get("name") or die("spec needs a name")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", name):
        die(f"name {name!r} must be alphanumeric (symbol stem and dir name)")
    if len(name) > 10:
        die(f"name {name!r} exceeds the 10-char species-name budget")
    if "stats" not in spec or set(spec["stats"]) != set(STAT_FIELDS):
        die(f"spec.stats must have exactly {sorted(STAT_FIELDS)}")
    if not 1 <= len(spec["types"]) <= 2 or not 1 <= len(spec["abilities"]) <= 3:
        die("types must be 1-2 entries, abilities 1-3")
    for lvl, mv in spec["level_up_learnset"]:
        if not (1 <= int(lvl) <= 100 and re.fullmatch(r"[A-Z0-9_]+", mv)):
            die(f"bad learnset row [{lvl}, {mv!r}]")
    spec["Name"] = name[0].upper() + name[1:]
    spec["ID"] = name.upper()
    spec["dir"] = name.lower()
    return spec


def donor_metadata(hack: Path, donor_id: str) -> dict:
    """Parse pic/scale/anim metadata out of the donor's gSpeciesInfo entry."""
    fields = ["frontPicSize", "frontPicYOffset", "backPicSize", "backPicYOffset",
              "pokemonScale", "pokemonOffset", "trainerScale", "trainerOffset",
              "iconPalIndex", "frontAnimId", "backAnimId"]
    info_dir = hack / "src/data/species_info"
    candidates = sorted(info_dir.glob("gen_*_families.h"))
    # custom species (our own earlier output) are valid donors too
    if (info_dir / "custom_families.h").exists():
        candidates.append(info_dir / "custom_families.h")
    for family in candidates:
        text = family.read_text()
        # allow a trailing comment between '=' and '{' -- our own generated
        # entries carry '// new_species.py' there
        m = re.search(rf"\[SPECIES_{donor_id}\]\s*=\s*(?://[^\n]*\n\s*)?\{{", text)
        if not m:
            continue
        block = text[m.end(): text.index("\n    },", m.end())]
        out = {}
        for f in fields:
            fm = re.search(rf"\.{f}\s*=\s*(.+),\s*$", block, re.M)
            if not fm:
                die(f"donor SPECIES_{donor_id}: field .{f} not found -- pick another donor")
            out[f] = fm.group(1).strip()
        return out
    die(f"donor SPECIES_{donor_id} not found in any gen_*_families.h or custom_families.h")


# ------------------------------------------------------------ the edits

def add_species_constant(hack: Path, ID: str):
    def tf(text):
        egg = re.search(r"#define SPECIES_EGG \(SPECIES_(\w+) \+ 1\)", text)
        if not egg:
            return None
        prev = egg.group(1)
        prevdef = re.search(rf"#define SPECIES_{prev}\s+(\d+)", text)
        if not prevdef:
            return None
        n = int(prevdef.group(1)) + 1
        text = text.replace(egg.group(0), f"#define SPECIES_EGG (SPECIES_{ID} + 1)")
        return insert_before(
            text, r"^#define SPECIES_EGG \(",
            f"#define SPECIES_{ID}{' ' * max(1, 48 - len('#define SPECIES_' + ID))}{n} // {MARK}\n")
    edit(hack / "include/constants/species.h", tf, f"SPECIES_{ID} + EGG shift")


def add_dex_constant(hack: Path, ID: str):
    path = hack / "include/constants/pokedex.h"

    def tf(text):
        entries = list(re.finditer(r"^    NATIONAL_DEX_(\w+),$", text, re.M))
        if not entries:
            return None
        last = entries[-1]
        text = text[:last.end()] + f"\n    NATIONAL_DEX_{ID}, // {MARK}" + text[last.end():]
        block = (f"\n// {MARK}: custom species extend the national dex. Macro expansion is\n"
                 f"// lazy, so every use of NATIONAL_DEX_COUNT sees this final definition.\n"
                 f"#undef NATIONAL_DEX_COUNT\n"
                 f"#define NATIONAL_DEX_COUNT NATIONAL_DEX_{ID}\n")
        guard = re.search(r"^#endif // GUARD_CONSTANTS_POKEDEX_H", text, re.M)
        if not guard:
            return None
        return text[:guard.start()] + block + "\n" + text[guard.start():]
    edit(path, tf, f"NATIONAL_DEX_{ID} + COUNT redefine")


def add_cry(hack: Path, spec: dict):
    ID, Name, low = spec["ID"], spec["Name"], spec["dir"]
    edit(hack / "include/constants/cries.h",
         lambda t: insert_before(t, r"^    CRY_COUNT,", f"    CRY_{ID}, // {MARK}\n"),
         f"CRY_{ID}")

    def table_tf(directive):
        def tf(text):
            rows = list(re.finditer(rf"^\t{directive} Cry_\w+$", text, re.M))
            if not rows:
                return None
            pos = rows[-1].end()
            nxt = text.find("\n", pos) + 1
            # If the last row sits inside a family gate, land after its .endif.
            endif = re.match(r"\.endif @ P_FAMILY_\w+\n", text[nxt:])
            if endif:
                nxt += endif.end()
                return text[:nxt] + f"\t{directive} Cry_{Name}\n" + text[nxt:]
            return text[:pos] + f"\n\t{directive} Cry_{Name}" + text[pos:]
        return tf
    edit(hack / "sound/cry_tables.inc", table_tf("cry"), f"cry Cry_{Name}")
    edit(hack / "sound/cry_tables.inc", table_tf("cry_reverse"), f"cry_reverse Cry_{Name}")

    src = hack / f"sound/direct_sound_samples/cries/{spec['cry_from'].lower()}.bin"
    if not src.is_file():
        die(f"cry donor sample {src} missing")
    dst = hack / f"sound/direct_sound_samples/cries/{low}.bin"
    shutil.copyfile(src, dst)
    print(f"  copied  {dst} (from {spec['cry_from']})")

    def sound_tf(text):
        return text.rstrip("\n") + (f"\n\n\t.align 2 @ {MARK}\nCry_{Name}::\n"
                                    f"\t.incbin \"sound/direct_sound_samples/cries/{low}.bin\"\n")
    edit(hack / "sound/direct_sound_data.inc", sound_tf, f"Cry_{Name} incbin")


def add_art(hack: Path, spec: dict):
    donor = hack / "graphics/pokemon" / spec["art_from"].lower()
    dest = hack / "graphics/pokemon" / spec["dir"]
    if not donor.is_dir():
        die(f"art donor dir {donor} missing")
    if dest.exists():
        die(f"{dest} already exists")
    dest.mkdir(parents=True)
    needed = ["anim_front.png", "back.png", "icon.png", "footprint.png",
              "normal.pal", "shiny.pal"]
    for f in needed:
        if not (donor / f).is_file():
            die(f"art donor lacks {f} -- pick a donor with complete sources")
        shutil.copyfile(donor / f, dest / f)  # sources only; build regenerates the rest
    print(f"  copied  {dest}/ ({len(needed)} source files from {spec['art_from']})")

    Name, low = spec["Name"], spec["dir"]
    block = f"""
// {MARK}: {Name} (ungated -- custom species have no P_FAMILY flag)
const u32 gMonFrontPic_{Name}[] = INCBIN_U32("graphics/{low}/anim_front.4bpp.lz");
const u32 gMonPalette_{Name}[] = INCBIN_U32("graphics/{low}/normal.gbapal.lz");
const u32 gMonBackPic_{Name}[] = INCBIN_U32("graphics/{low}/back.4bpp.lz");
const u32 gMonShinyPalette_{Name}[] = INCBIN_U32("graphics/{low}/shiny.gbapal.lz");
const u8 gMonIcon_{Name}[] = INCBIN_U8("graphics/{low}/icon.4bpp");
#if P_FOOTPRINTS
const u8 gMonFootprint_{Name}[] = INCBIN_U8("graphics/{low}/footprint.1bpp");
#endif
"""
    edit(hack / "src/data/graphics/pokemon.h",
         lambda t: t.rstrip("\n") + "\n" + block, f"gMonFrontPic_{Name} block")

    anim = f"""
// {MARK}: {Name}
static const union AnimCmd sAnim_{Name}_1[] =
{{
    ANIMCMD_FRAME(0, 1),
    ANIMCMD_END,
}};
SINGLE_ANIMATION({Name});
"""
    edit(hack / "src/data/pokemon_graphics/front_pic_anims.h",
         lambda t: t.rstrip("\n") + "\n" + anim, f"sAnims_{Name}")


def add_learnset(hack: Path, spec: dict):
    custom = hack / "src/data/level_up_learnsets/custom.h"
    if not custom.exists():
        custom.write_text(f"// Custom species learnsets ({MARK}). Append-only.\n")
        edit(hack / "src/pokemon.c",
             lambda t: insert_before(
                 t, r"^#include \"data/teachable_learnsets\.h\"",
                 f"#include \"data/level_up_learnsets/custom.h\" // {MARK}\n"),
             "custom learnset include")
    rows = "\n".join(f"    LEVEL_UP_MOVE({int(lvl):2}, MOVE_{mv})," for lvl, mv in spec["level_up_learnset"])
    with custom.open("a") as f:
        f.write(f"\nstatic const struct LevelUpMove s{spec['Name']}LevelUpLearnset[] = {{\n"
                f"{rows}\n    LEVEL_UP_END\n}};\n")
    print(f"  edited  {custom} (s{spec['Name']}LevelUpLearnset)")


def species_entry(spec: dict, meta: dict) -> str:
    s, Name, ID = spec, spec["Name"], spec["ID"]
    stats = s["stats"]
    ev = "".join(f"        .{STAT_FIELDS[k][1]} = {v},\n" for k, v in s["ev_yield"].items() if v)
    types = ", ".join("TYPE_" + t for t in s["types"])
    abilities = ", ".join("ABILITY_" + a for a in (s["abilities"] + ["NONE"] * 3)[:3])
    eggs = ", ".join("EGG_GROUP_" + g for g in s["egg_groups"])
    gr = s["gender_ratio"]
    gender = ("MON_GENDERLESS" if gr == "GENDERLESS"
              else "MON_MALE" if gr in (0, "MALE_ONLY")
              else "MON_FEMALE" if gr in (100, "FEMALE_ONLY")
              else f"PERCENT_FEMALE({gr})")
    desc = s["description"].split("\n")
    if len(desc) > 4 or any(len(line) > 42 for line in desc):
        die("description: max 4 lines of 42 chars (the dex text window)")
    desc_c = "\n".join(f'            "{line}{"" if i == len(desc) - 1 else chr(92) + "n"}"'
                       for i, line in enumerate(desc))
    evo = ""
    if "evolution" in s:
        e = s["evolution"]
        evo = f"        .evolutions = EVOLUTION({{{e['method']}, {e['param']}, {e['target']}}}),\n"
    return f"""
    [SPECIES_{ID}] = // {MARK}
    {{
        .baseHP        = {stats['hp']},
        .baseAttack    = {stats['attack']},
        .baseDefense   = {stats['defense']},
        .baseSpeed     = {stats['speed']},
        .baseSpAttack  = {stats['sp_attack']},
        .baseSpDefense = {stats['sp_defense']},
        .types = MON_TYPES({types}),
        .catchRate = {s['catch_rate']},
        .expYield = {s['exp_yield']},
{ev}        .genderRatio = {gender},
        .eggCycles = {s['egg_cycles']},
        .friendship = STANDARD_FRIENDSHIP,
        .growthRate = GROWTH_{s['growth_rate']},
        .eggGroups = MON_EGG_GROUPS({eggs}),
        .abilities = {{ {abilities} }},
        .bodyColor = BODY_COLOR_{s['body_color']},
        .speciesName = _("{s['name']}"),
        .cryId = CRY_{ID},
        .natDexNum = NATIONAL_DEX_{ID},
        .categoryName = _("{s['category']}"),
        .height = {s['height']},
        .weight = {s['weight']},
        .description = COMPOUND_STRING(
{desc_c}),
        .pokemonScale = {meta['pokemonScale']},
        .pokemonOffset = {meta['pokemonOffset']},
        .trainerScale = {meta['trainerScale']},
        .trainerOffset = {meta['trainerOffset']},
        .frontPic = gMonFrontPic_{Name},
        .frontPicSize = {meta['frontPicSize']},
        .frontPicYOffset = {meta['frontPicYOffset']},
        .frontAnimFrames = sAnims_{Name},
        .frontAnimId = {meta['frontAnimId']},
        .backPic = gMonBackPic_{Name},
        .backPicSize = {meta['backPicSize']},
        .backPicYOffset = {meta['backPicYOffset']},
        .backAnimId = {meta['backAnimId']},
        .palette = gMonPalette_{Name},
        .shinyPalette = gMonShinyPalette_{Name},
        .iconSprite = gMonIcon_{Name},
        .iconPalIndex = {meta['iconPalIndex']},
        FOOTPRINT({Name})
        .levelUpLearnset = s{Name}LevelUpLearnset,
        .teachableLearnset = sNoneTeachableLearnset,
        .eggMoveLearnset = sNoneEggMoveLearnset,
{evo}    }},
"""


def add_species_info(hack: Path, spec: dict, meta: dict):
    custom = hack / "src/data/species_info/custom_families.h"
    if not custom.exists():
        custom.write_text(f"// Custom species ({MARK}). Append-only, ungated.\n")
        edit(hack / "src/data/species_info.h",
             lambda t: insert_before(
                 t, r"^\n    \[SPECIES_EGG\] =",
                 f"    #include \"species_info/custom_families.h\" // {MARK}\n"),
             "custom_families include")
    with custom.open("a") as f:
        f.write(species_entry(spec, meta))
    print(f"  edited  {custom} (SPECIES_{spec['ID']} entry)")


def add_dex_orders(hack: Path, ID: str):
    path = hack / "src/data/pokedex_orders.h"

    def alpha_tf(text):
        m = re.search(r"const u16 gPokedexOrder_Alphabetical\[\] =\n\{\n(.*?)\n\};", text, re.S)
        if not m:
            return None
        rows = m.group(1).split("\n")
        names = [(i, nm.group(1)) for i, r in enumerate(rows)
                 if (nm := re.search(r"NATIONAL_DEX_(\w+),", r))]
        at = next((i for i, n in names if n > ID), len(rows))
        rows.insert(at, f"    NATIONAL_DEX_{ID}, // {MARK}")
        return text[:m.start(1)] + "\n".join(rows) + text[m.end(1):]
    edit(path, alpha_tf, f"alphabetical order ({ID})")

    for which in ("Weight", "Height"):
        def tail_tf(text, which=which):
            m = re.search(rf"const u16 gPokedexOrder_{which}\[\] =\n\{{\n(.*?)\n\}};", text, re.S)
            if not m:
                return None
            appended = (m.group(1) + f"\n    NATIONAL_DEX_{ID}, // {MARK}: appended, not "
                        f"{which.lower()}-sorted -- cosmetic in the dex's sort-by-{which.lower()} view")
            return text[:m.start(1)] + appended + text[m.end(1):]
        edit(path, tail_tf, f"{which.lower()} order ({ID})")



# ------------------------------------------------------- drawn-content measure

def measure_front_pic(hack: Path, name: str) -> tuple[int, int, int]:
    """Bounding box of frame 1 of a species' front sprite, in drawn pixels.

    Doc 70 §2: the user reported a sprite as too big; measured against 150
    stock species it sat BELOW the engine's own equivalent, and the real fault
    was the FIRST stage of the line being oversized, so the line grows 27%
    where Torchic -> Blaziken grows 198%. **A silhouette claim is cheap to
    check and expensive to guess**, and the guess was wrong twice over -- wrong
    species, wrong direction.

    Index 0 is the transparency key on these sheets, and frame 1 is the first
    64x64 cell. Returns (w, h, area).
    """
    png = hack / "graphics/pokemon" / name / "anim_front.png"
    if not png.is_file():
        die(f"no front sprite at {png}")
    try:
        from PIL import Image
    except ImportError:
        die("--measure needs Pillow (pip install Pillow)")
    im = Image.open(png)
    if im.mode != "P":
        die(f"{png} is {im.mode}, not indexed -- these sheets are always P")
    frame = im.crop((0, 0, 64, 64))
    px = frame.load()
    xs, ys = [], []
    for y in range(64):
        for x in range(64):
            if px[x, y] != 0:          # 0 is the transparency key
                xs.append(x)
                ys.append(y)
    if not xs:
        return (0, 0, 0)
    w = max(xs) - min(xs) + 1
    h = max(ys) - min(ys) + 1
    return (w, h, w * h)


def run_measure(hack: Path, names: list[str]):
    rows = []
    for n in names:
        w, h, area = measure_front_pic(hack, n)
        rows.append((n, w, h, area))
    for n, w, h, area in sorted(rows, key=lambda r: r[3]):
        print(f"  {n:16s} {w:2d} x {h:2d}   {area:6,d} px\u00b2")
    if len(rows) > 1:
        ordered = [r for r in rows]           # input order = line order
        for a, b in zip(ordered, ordered[1:]):
            if a[3]:
                print(f"  {a[0]} -> {b[0]}: {100 * (b[3] - a[3]) / a[3]:+.0f}%")
    print("\n  Reference, measured over 150 stock species: median 2,208 \u00b7 "
          "p90 3,776 \u00b7 max 4,096.\n  Torchic 1,075 -> Blaziken 3,200 is +198%; "
          "a line that grows less than that reads flat.")


# ------------------------------------------------------------ entry

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hack", default=str(hx.default_hack()), help="hack root (a pokeemerald fork)")
    ap.add_argument("--measure", action="store_true",
                    help="measure the drawn-content bounding box of each named species' front "
                         "sprite instead of adding one (doc 70 §2: measure, do not eyeball)")
    ap.add_argument("spec", nargs="+",
                    help="species spec JSON; with --measure, graphics/<name> dir names")
    args = ap.parse_args()
    hack = Path(args.hack)
    if not (hack / "include/constants/species.h").is_file():
        die(f"{hack} is not a pokeemerald fork")

    if args.measure:
        run_measure(hack, args.spec)
        return

    if len(args.spec) != 1:
        die("one spec at a time -- species are appended, and an append is not a batch")
    spec = load_spec(Path(args.spec[0]))

    if re.search(rf"#define SPECIES_{spec['ID']}\b",
                 (hack / "include/constants/species.h").read_text()):
        die(f"SPECIES_{spec['ID']} already exists -- nothing done")

    meta = donor_metadata(hack, spec["art_from"].upper())

    print(f"adding SPECIES_{spec['ID']} to {hack}:")
    add_species_constant(hack, spec["ID"])
    add_dex_constant(hack, spec["ID"])
    add_cry(hack, spec)
    add_art(hack, spec)
    add_learnset(hack, spec)
    add_species_info(hack, spec, meta)
    add_dex_orders(hack, spec["ID"])

    print(f"""
done. SPECIES_{spec['ID']} is wired. Next:
  1. rebuild (docker make; then make syms) -- pattern rules generate the
     .4bpp.lz/.gbapal.lz from the copied sources
  2. cheapest real proof (doc 64 §8): cold-boot verify spec reading
     gSpeciesInfo[SPECIES_{spec['ID']}] fields by symbol
  3. real art: replace graphics/{spec['dir']}/ sources (delete any
     generated .4bpp*/.lz/.gbapal* beside them) and update the pic-size/
     y-offset fields in custom_families.h to match""")


if __name__ == "__main__":
    main()
