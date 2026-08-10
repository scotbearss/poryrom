#!/usr/bin/env python3
"""make_dex.py -- a static, pokemondb-style dex site generated from the game's
OWN source data, so it can never drift from the game.

WHAT IT READS. The fork's `src/data/pokemon/species_info/*.h` (designated
initializers), `level_up_learnsets/`, `teachable_learnsets.h`, `moves_info.h`,
`abilities.h`, `items.h`, `types_info.h`, `trainers.h` (parties and all),
`wild_encounters.json` and `src/battle_main.c`'s trainer-class table, every
`data/maps/*/map.json` and its `scripts.inc`, `data/layouts/layouts.json`
and the block data and tilesets they name, plus `include/constants/pokedex.h`
and `include/constants/items.h` for dex/item order -- and then the SAME files
from the pinned engine clone, parsed by the same code, so that "new" and
"changed" are computed against the stock baseline rather than asserted.
Sprites come from `graphics/pokemon/<species>/` and are copied into the site,
which is fully self-contained: no external requests, no frameworks, works
from file:// in any browser.

IT ALSO READS THE WORKSPACE AROUND THE FORK for the dashboard: the built
ROM's size and mtime, `patches/<game>.patch`, the newest file under the
fork's own source dirs (so "is the backup behind the working copy" is
answered by fact rather than by memory), the game repo's git HEAD, the
game's own `verify/*.json` specs and which of their savestates exist here,
and `data/maps/`'s folder list against the engine's. All of it is read, none
of it asserted; anything unreadable is simply absent from the page.

IT READS -- AND WITH --record, APPENDS TO -- `<workspace>/devlog/`, the one
thing here that is stored rather than re-derived: one small JSON snapshot per
green build, git-TRACKED in the game repo, holding counts, one-line summaries
and a fingerprint per entry. A tree can only ever show its present state, so
history is the single fact this site cannot recompute if it is lost. Recording
happens ONLY with --record (the build ritual passes it after a green build);
every other run reads the history and writes nothing, and an entry that would
repeat what the newest one already says is not written at all.

IT READS `<workspace>/design/index.md` and `scope.md` for the one page here
that nothing can derive: the roadmap. No new markup was invented for it --
the identity block's machine-read `- **Key:** value` fields, the Phase block,
Locked decisions, Next actions, Open questions, the slice plan's
`### Slice N` headings with their `planned | building | done | cut` status
field, and the Cut list are all shapes the design doc already commits to.
Authored content is rendered dashed and labelled, everywhere it appears.
`narrative.md`'s `## Route order` is read the same way for the story thread:
numbered story beats, each naming the places it touches IN PLAY ORDER. That
order is never derived -- a world with loops has many valid ways through it
and no way to prove which was meant -- so the connection graph is walked for
two things only: what hangs off the route (bounded, see POCKET_HOPS) and what
the route never reaches.

WHAT IT WRITES, under <workspace>/dex/:
    index.html            the dashboard: build health, what exists, what is
                          added but unfinished
    pokedex.html          every species, sortable/filterable, NEW/CHANGED badges
    moves.html            every move, with a reverse "learned by" count
    abilities.html        every ability, with a reverse "species" count
    items.html            every item, with the trainers who carry it
    trainers.html         every trainer with a party, class and team
    locations.html        every map the game defines
    changes.html          the progress tracker: what this game added and altered
    devlog.html           build-by-build history, and what has moved since
                          the newest recorded build
    roadmap.html          the design doc's plan, marked as written rather
                          than derived, plus where it stopped agreeing with
                          itself or with the tree
    thread.html           the game in play order: an authored route of story
                          beats, every place on it filled in from the tree,
                          what hangs off it, and what it never reaches
    types.html            the game's own type chart
    pokemon/<key>.html    one page per species (stats, defenses, evos,
                          learnsets, where it lives, who trains it)
    moves/<key>.html      one page per move, cross-linked to every learner
    abilities/<key>.html  one page per ability, cross-linked to every holder
    items/<key>.html      one page per item
    trainers/<key>.html   one page per trainer: the party as a battle meets
                          it, and the lines they speak
    locations/<key>.html  one page per place: the map drawn from its own
                          block data, its exits, encounters, trainers, items
    assets/maps/          one rendered PNG per layout (needs Pillow; without
                          it every location page keeps everything but the
                          picture)
    assets/                style.css + copied sprite PNGs + vendored webfonts

THEMING. Six surfaces (accent, accent-2, heading face, radius, border weight;
banner/logo art come later) are read from <workspace>/design/dex_theme.toml
if present -- a flat `key = "value"` file, not real TOML, so no parser
dependency. A hack that sets nothing gets the built-in default look
(dex-site-requirements.md's direction "1a"). Fonts (Newsreader, IBM Plex
Sans/Mono) are vendored from this repo's tools/dex_fonts/ into every site's
assets/fonts/, never loaded from a CDN, so the site keeps working offline.

KNOWN LIMITATIONS, all deliberate (this is a regex parser, not a C compiler):
  * Preprocessor conditionals are NOT evaluated. `#if P_FAMILY_X` guards are
    ignored and every entry inside them is parsed; a game that compiles with
    families disabled will show species its ROM does not contain.
  * Config-dependent values (`(P_UPDATED_EXP_YIELDS >= GEN_5) ? 142 : 141`,
    `B_UPDATED_MOVE_DATA` move power blocks, the `*_RS` type-chart macros)
    take the FIRST/modern branch, which matches pokeemerald-expansion's
    default configuration. `HANDLE_EXPANDED_*_NAME(short, long)` (species,
    moves, items all have one) is the one exception: it takes the LAST
    literal, i.e. the long/expanded name -- not the first-branch rule, since
    both arguments are always valid C, just alternative names.
  * A rendered map is the terrain only: no NPC, item ball or warp is drawn
    on top of it, though all three are listed beside it. Map connections are
    named, not stitched into one world image.
  * Map animations (water, flowers) are not run: a tileset's `anim/` frames
    are ignored and the base tile is drawn, so moving water sits still.
  * Item balls are read from map.json, where the engine overloads the sight-
    radius field to hold the item. An item a script hands over is listed
    separately, as a gift, with the place but not the conditions.
  * Dialogue is QUOTED, never resolved: `{STR_VAR_1}` stays as written.
    Which of a battle macro's text arguments is the intro and which the
    defeat varies by macro, so the lines are shown in the order the macro
    names them and none is labelled.
  * A map's own writing is grouped by the engine's `<MapDir>_Text_<What>`
    naming convention. It is a convention, used to group and never to
    claim: a label that does not follow it is not shown under a map.
  * `trainers.h` is generated from `trainers.party` by trainerproc. It is
    git-tracked, so it is read as it stands rather than regenerated -- and
    the dashboard says so out loud when the .party source is the newer of
    the two, because then these pages show a team the build does not.
  * Trainer NAMES are not unique in the game (four Anna & Megs, dozens of
    Grunts). Every trainer link carries its constant as a tooltip and the
    hub carries it as a column; no distinguishing name is invented.
  * File-local #define macros (BEEDRILL_ATTACK, VIVILLON_MISC_INFO(...),
    ARCEUS_SPECIES_INFO(...)) are expanded textually, one family file's worth
    at a time, with `##` pasting honored -- but `#param` stringizing is not,
    and a macro defined outside src/data/pokemon/species_info/ is not seen.
  * If the type chart cannot be parsed, a built-in standard Gen-6+ 18-type
    chart is used and a warning is printed.
  * Two-frame sprite sheets (anim_front.png, icon.png) are detected by the
    height == 2*width heuristic and cropped to their first frame with CSS.

  * The dev log sees what the diff sees. A stock entry DELETED outright never
    differed from stock while it existed, so it appears in no snapshot's
    list; only the category's total moving records that it went.
  * The roadmap REPORTS the design doc, it does not audit it. A slice marked
    done is marked done by the person who wrote it; the only claims checked
    are the three §6.3 asks for (the plan's own in-order rule, its own status
    vocabulary, and an unbuilt slice naming something the tree has).

USAGE
    python3 tools/make_dex.py                       # workspace found via hx
    python3 tools/make_dex.py --game ~/src/mygame   # explicit game repo
    python3 tools/make_dex.py --record              # ...and log this build
    python3 tools/make_dex.py --out /tmp/dex --open

Exit 0 on success, 1 if zero species parsed, 2 if the trees cannot be found.
"""

from __future__ import annotations

import argparse
import filecmp
import fnmatch
import hashlib
import html
import json
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

import hx

# ------------------------------------------------------------ theme

# The six skinnable surfaces (dex-site-requirements.md's Theming section).
# Everything else in the CSS is fixed structure, not themeable.
THEME_DEFAULTS = {
    "accent": "0.55 0.13 42",       # terracotta -- primary accent, NEW badge, links, meters
    "accent2": "0.52 0.09 128",     # olive -- secondary accent
    "font_display": "'Newsreader', serif",
    "radius": "10px",
    "radius_sm": "6px",
    "border_w": "1px",
}

DEX_FONTS_DIR = Path(__file__).resolve().parent / "dex_fonts"

_THEME_KV_RE = re.compile(
    r'^\s*(\w+)\s*=\s*"([^"]*)"\s*(?:#.*)?$', re.M)


def load_theme(workspace: Path) -> dict:
    """dex_theme.toml is a flat key = "value" file living at
    <workspace>/design/dex_theme.toml -- deliberately not real TOML (no
    nesting, no lists), so no parser dependency is needed. A hack author who
    sets nothing gets direction 1a exactly."""
    theme = dict(THEME_DEFAULTS)
    path = workspace / "design" / "dex_theme.toml"
    if path.is_file():
        for key, value in _THEME_KV_RE.findall(read(path)):
            if key in theme:
                theme[key] = value
    return theme


def copy_fonts(out: Path):
    """Vendors the site's webfonts from the harness's own tools/dex_fonts/ --
    never from a CDN, so the site keeps working from file://."""
    dst = out / "assets/fonts"
    dst.mkdir(parents=True, exist_ok=True)
    if not DEX_FONTS_DIR.is_dir():
        return
    for src in DEX_FONTS_DIR.glob("*.woff2"):
        (dst / src.name).write_bytes(src.read_bytes())


# ------------------------------------------------------------ C-ish parsing

_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
# A directive plus its backslash continuations, so a multi-line #define
# vanishes whole instead of leaking its body into the token stream.
_PREPROC_RE = re.compile(r"^[ \t]*#[^\n]*(?:\\\n[^\n]*)*", re.M)
_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_SPECIES_RE = re.compile(r"\[(SPECIES_\w+)\]\s*=\s*\{")
_MOVE_ENTRY_RE = re.compile(r"\[(MOVE_\w+)\]\s*=\s*\{")
_ABILITY_ENTRY_RE = re.compile(r"\[(ABILITY_\w+)\]\s*=\s*\{")
_ITEM_ENTRY_RE = re.compile(r"\[(ITEM_\w+)\]\s*=\s*\{")


def strip_c(text: str) -> str:
    """Comments and preprocessor lines out; both #if branches stay in."""
    return _PREPROC_RE.sub("", _COMMENT_RE.sub("", text))


def _block(text: str, open_idx: int) -> tuple[str, int]:
    """The body of the brace block opening at text[open_idx] ('{')."""
    depth = 0
    for i in range(open_idx, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:i], i
    return text[open_idx + 1:], len(text)


def split_top(s: str) -> list[str]:
    """Split on commas at paren/brace depth zero."""
    out, buf, depth = [], [], 0
    for c in s:
        if c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
        if c == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def parse_fields(body: str) -> dict[str, str]:
    """`.name = value` pairs at top level of one initializer body.

    A value runs to the next top-level `.field =`, so macro invocations
    sitting between fields (FOOTPRINT(...), OVERWORLD(...)) fold into the
    preceding value harmlessly. Duplicate fields keep the FIRST occurrence:
    with preprocessor lines stripped, an #if/#elif/#else ladder leaves its
    branches in modern-config-first order.
    """
    starts, depth, i = [], 0, 0
    while i < len(body):
        c = body[i]
        if c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
        elif c == "." and depth == 0 and (i == 0 or not body[i - 1].isdigit()):
            m = re.match(r"\.(\w+)\s*=\s*", body[i:])
            if m:
                starts.append((m.group(1), i, i + m.end()))
                i += m.end()
                continue
        i += 1
    fields: dict[str, str] = {}
    for n, (name, fstart, vstart) in enumerate(starts):
        vend = starts[n + 1][1] if n + 1 < len(starts) else len(body)
        val = body[vstart:vend].strip().rstrip(",").strip()
        fields.setdefault(name, val)
    return fields


def first_int(expr: str | None) -> int | None:
    """First integer once identifiers are removed.

    `(P_UPDATED_EXP_YIELDS >= GEN_5) ? 142 : 141` -> 142: the true branch of
    a config ternary comes first, and expansion's defaults take it.
    """
    if not expr:
        return None
    m = re.search(r"-?\d+", _IDENT_RE.sub("", expr))
    return int(m.group()) if m else None


def resolve_int(expr: str | None, obj_macros: dict[str, str]) -> int | None:
    """first_int, retried through object-like macros: `.baseAttack =
    BEEDRILL_ATTACK` finds `#define BEEDRILL_ATTACK (cond ? 90 : 80)` -> 90."""
    v = first_int(expr)
    for _ in range(3):
        if v is not None or not expr:
            return v
        hit = [False]

        def sub(m, hit=hit):
            if m.group() in obj_macros:
                hit[0] = True
                return f" {obj_macros[m.group()]} "
            return m.group()

        expr = _IDENT_RE.sub(sub, expr)
        if not hit[0]:
            return None
        v = first_int(expr)
    return v


_DEFINE_RE = re.compile(
    r"^[ \t]*#[ \t]*define[ \t]+(\w+)(\([^)\n]*\))?[ \t]*"
    r"((?:[^\n]*\\\n)*[^\n]*)", re.M)


def parse_macros(text: str) -> tuple[dict[str, str], dict[str, tuple[list[str], str]]]:
    """File-local #defines: object-like -> body, function-like -> (params, body)."""
    obj: dict[str, str] = {}
    fn: dict[str, tuple[list[str], str]] = {}
    for m in _DEFINE_RE.finditer(text):
        name, params, body = m.group(1), m.group(2), m.group(3)
        body = _COMMENT_RE.sub("", body.replace("\\\n", "\n")).strip()
        if params is None:
            obj[name] = body
        else:
            fn[name] = ([p.strip() for p in params[1:-1].split(",")
                         if p.strip()], body)
    return obj, fn


def expand_fn_macros(text: str,
                     fn: dict[str, tuple[list[str], str]], depth: int = 0) -> str:
    """Textual one-level-at-a-time expansion of function-like macros, so
    `[SPECIES_ARCEUS_FIRE] = ARCEUS_SPECIES_INFO(TYPE_FIRE, ...)` and the
    VIVILLON_MISC_INFO stat blocks become ordinary initializer text.
    `a ## b` pastes; `#param` stringizing is not supported (nothing the dex
    reads uses it at the supported pins)."""
    if depth > 3 or not fn:
        return text
    changed = False
    for name, (params, mbody) in fn.items():
        pat = re.compile(r"\b" + re.escape(name) + r"\s*\(")
        for _ in range(500):        # a self-recursive macro must not hang us
            m = pat.search(text)
            if not m:
                break
            start = m.end() - 1
            level, i = 0, start
            while i < len(text):
                if text[i] == "(":
                    level += 1
                elif text[i] == ")":
                    level -= 1
                    if level == 0:
                        break
                i += 1
            args = split_top(text[start + 1:i])
            rep = mbody
            for p, a in zip(params, args):
                rep = re.sub(r"\b" + re.escape(p) + r"\b", a.strip(), rep)
            rep = re.sub(r"\s*##\s*", "", rep)
            text = text[:m.start()] + rep + text[i + 1:]
            changed = True
    return expand_fn_macros(text, fn, depth + 1) if changed else text


def last_string_literal(expr: str) -> str | None:
    """The LAST "..." literal in expr. `HANDLE_EXPANDED_*_NAME(short, long)`
    macros (species/moves/items all have one) put the modern/expanded name
    last as the second argument; a plain single-literal name is unaffected.
    Never use join_strings for a *name* field -- it concatenates multiple
    literals instead of picking one, which turns a two-argument expanded-name
    macro into "ShortLong" mashed together."""
    lits = _STRING_RE.findall(expr)
    return lits[-1] if lits else None


def join_strings(expr: str) -> str | None:
    """Adjacent "..." literals joined; \\n becomes a space."""
    lits = _STRING_RE.findall(expr)
    if not lits:
        return None
    text = "".join(lits)
    text = text.replace("\\n", " ").replace('\\"', '"').replace("\\\\", "\\")
    return re.sub(r"\s+", " ", text).strip()


def parse_shared_texts(text: str) -> dict[str, str]:
    """shared_dex_text.h: `const u8 gXPokedexText[] = _( "..." );`"""
    out = {}
    for m in re.finditer(r"const u8 (\w+)\[\]\s*=\s*_?\((.*?)\)\s*;",
                         strip_c(text), re.S):
        joined = join_strings(m.group(2))
        if joined:
            out[m.group(1)] = joined
    return out


def parse_type_defines(text: str) -> dict[str, str]:
    """`#define RALTS_FAMILY_TYPE2 (cond ? TYPE_FAIRY : TYPE_PSYCHIC)` ->
    first TYPE_ symbol, i.e. the modern-config branch."""
    out = {}
    for m in re.finditer(r"^\s*#define\s+(\w+)\s+(.+)$", text, re.M):
        t = re.search(r"TYPE_\w+", m.group(2))
        if t:
            out[m.group(1)] = t.group()
    return out


def parse_species_text(text: str, shared_texts: dict[str, str] | None = None,
                       type_defines: dict[str, str] | None = None,
                       macros: tuple[dict, dict] | None = None) -> dict[str, dict]:
    """Every `[SPECIES_X] = { ... }` block -> a normalized entry dict.

    Preprocessor guards (#if P_FAMILY_...) are stripped, not evaluated, so
    ALL entries parse. File-local macros (given, or self-extracted from this
    text) are expanded first, so macro-built entries parse like literal ones.
    Missing fields stay absent -- never fabricated.
    """
    shared_texts = shared_texts or {}
    type_defines = type_defines or {}
    obj_macros, fn_macros = macros if macros else parse_macros(text)
    clean = expand_fn_macros(strip_c(text), fn_macros)
    out: dict[str, dict] = {}
    pos = 0
    while True:
        m = _SPECIES_RE.search(clean, pos)
        if not m:
            break
        body, end = _block(clean, m.end() - 1)
        pos = end + 1
        const = m.group(1)
        if const in out:            # an #if/#else pair: keep the first branch
            continue
        f = parse_fields(body)
        sp: dict = {"const": const}
        for stat in ("baseHP", "baseAttack", "baseDefense", "baseSpeed",
                     "baseSpAttack", "baseSpDefense", "catchRate", "expYield",
                     "height", "weight"):
            v = resolve_int(f.get(stat), obj_macros)
            if v is not None:
                sp[stat] = v
        if "types" in f:
            inner = re.search(r"MON_TYPES\s*\((.*)\)", f["types"], re.S)
            toks = split_top(inner.group(1)) if inner else []
            types = []
            for t in toks:
                t = t.strip()
                types.append(t if t.startswith("TYPE_")
                             else type_defines.get(t, t))
            sp["types"] = types
        if "abilities" in f:
            sp["abilities"] = re.findall(r"ABILITY_\w+", f["abilities"])
        if "eggGroups" in f:
            sp["eggGroups"] = re.findall(r"EGG_GROUP_\w+", f["eggGroups"])
        if "genderRatio" in f:
            sp["genderRatio"] = re.sub(r"\s+", " ", f["genderRatio"]).strip()
        if "speciesName" in f:
            nm = last_string_literal(f["speciesName"])  # HANDLE_EXPANDED_SPECIES_NAME
            if nm:
                sp["name"] = nm
        if "categoryName" in f:
            cat = join_strings(f["categoryName"])
            if cat:
                sp["category"] = cat
        if "natDexNum" in f:
            d = re.search(r"NATIONAL_DEX_\w+", f["natDexNum"])
            if d:
                sp["natDexNum"] = d.group()
        if "description" in f:
            desc = join_strings(f["description"])
            if desc is None:        # a symbol into shared_dex_text.h
                sym = re.search(r"\w+", f["description"])
                desc = shared_texts.get(sym.group()) if sym else None
            if desc:
                sp["description"] = desc
        for ref in ("levelUpLearnset", "teachableLearnset",
                    "frontPic", "iconSprite"):
            if ref in f:
                s = re.search(r"\w+", f[ref])
                if s:
                    sp[ref] = s.group()
        if "evolutions" in f:
            evos = []
            inner = re.search(r"EVOLUTION\s*\((.*)\)", f["evolutions"], re.S)
            if inner:
                text_in, i = inner.group(1), 0
                while True:
                    b = text_in.find("{", i)
                    if b < 0:
                        break
                    ebody, eend = _block(text_in, b)
                    i = eend + 1
                    parts = split_top(ebody)
                    if len(parts) >= 3:
                        evos.append((parts[0].strip(),
                                     ", ".join(re.sub(r"\s+", " ", p).strip()
                                               for p in parts[1:-1]),
                                     parts[-1].strip()))
            if evos:
                sp["evolutions"] = evos
        out[const] = sp
    return out


def parse_level_up_learnsets(text: str) -> dict[str, list[tuple[int, str]]]:
    out = {}
    for m in re.finditer(
            r"const struct LevelUpMove (\w+)\[\]\s*=\s*\{(.*?)\};",
            strip_c(text), re.S):
        out[m.group(1)] = [
            (int(mm.group(1)), mm.group(2)) for mm in re.finditer(
                r"LEVEL_UP_MOVE\(\s*(\d+)\s*,\s*(MOVE_\w+)\s*\)", m.group(2))]
    return out


def parse_teachable_learnsets(text: str) -> dict[str, list[str]]:
    out = {}
    for m in re.finditer(r"const u16 (\w+)\[\]\s*=\s*\{(.*?)\};",
                         strip_c(text), re.S):
        out[m.group(1)] = re.findall(r"MOVE_\w+", m.group(2))
    return out


def parse_moves_info(text: str) -> dict[str, dict]:
    """Move name/type/power/accuracy/pp/priority/category/description per
    MOVE_X. First branch of any #if ladder wins (see module docstring)."""
    clean = strip_c(text)
    out: dict[str, dict] = {}
    pos = 0
    while True:
        m = _MOVE_ENTRY_RE.search(clean, pos)
        if not m:
            break
        body, end = _block(clean, m.end() - 1)
        pos = end + 1
        f = parse_fields(body)
        mv = {"const": m.group(1)}
        if "name" in f:
            nm = last_string_literal(f["name"])
            if nm:
                mv["name"] = nm
        if "description" in f:
            desc = join_strings(f["description"])
            if desc:
                mv["description"] = desc
        t = re.search(r"TYPE_\w+", f.get("type", ""))
        if t:
            mv["type"] = t.group()
        c = re.search(r"DAMAGE_CATEGORY_(\w+)", f.get("category", ""))
        if c:
            mv["category"] = c.group(1).title()
        for k in ("power", "accuracy", "pp", "priority"):
            v = first_int(f.get(k))
            if v is not None:
                mv[k] = v
        out.setdefault(m.group(1), mv)
    return out


def parse_abilities_info(text: str) -> dict[str, dict]:
    """Ability name/description per ABILITY_X, same designated-initializer
    shape as species and moves (confirmed against a real
    pokeemerald-expansion clone -- dex-site-requirements.md open question)."""
    clean = strip_c(text)
    out: dict[str, dict] = {}
    pos = 0
    while True:
        m = _ABILITY_ENTRY_RE.search(clean, pos)
        if not m:
            break
        body, end = _block(clean, m.end() - 1)
        pos = end + 1
        f = parse_fields(body)
        ab = {"const": m.group(1)}
        if "name" in f:
            nm = last_string_literal(f["name"])
            if nm:
                ab["name"] = nm
        if "description" in f:
            desc = join_strings(f["description"])
            if desc:
                ab["description"] = desc
        out.setdefault(m.group(1), ab)
    return out


def parse_items_info(text: str) -> dict[str, dict]:
    """Item name/description/price/pocket per ITEM_X. Descriptions are
    either an inline literal or a symbol into this same file's own
    `static const u8 sXDesc[] = _(...)` block (items.h has no separate
    shared-text file the way species does), so shared texts are parsed
    from `text` itself first."""
    shared = parse_shared_texts(text)
    clean = strip_c(text)
    out: dict[str, dict] = {}
    pos = 0
    while True:
        m = _ITEM_ENTRY_RE.search(clean, pos)
        if not m:
            break
        body, end = _block(clean, m.end() - 1)
        pos = end + 1
        f = parse_fields(body)
        it = {"const": m.group(1)}
        if "name" in f:
            nm = last_string_literal(f["name"])
            if nm:
                it["name"] = nm
        if "description" in f:
            desc = join_strings(f["description"])
            if desc is None:        # a symbol into this file's own sXDesc[]
                sym = re.search(r"\w+", f["description"])
                desc = shared.get(sym.group()) if sym else None
            if desc:
                it["description"] = desc
        p = first_int(f.get("price"))
        if p is not None:
            it["price"] = p
        pk = re.search(r"POCKET_\w+", f.get("pocket", ""))
        if pk:
            it["pocket"] = pk.group()
        out.setdefault(m.group(1), it)
    return out


def parse_item_order(text: str) -> dict[str, int]:
    """include/constants/items.h's `#define ITEM_X <n>` list -- item IDs
    are position-sensitive (comment in that file warns against reordering
    the ball block), so dex order follows these values, not items.h's own
    file order."""
    return {name: int(num) for name, num in re.findall(
        r"^\s*#define\s+(ITEM_\w+)\s+(\d+)\s*$", text, re.M)}


# ------------------------------------------------------ Track A2: trainers

_TRAINER_ENTRY_RE = re.compile(r"\[(TRAINER_\w+)\]\s*=\s*\{")
_TRAINER_CLASS_RE = re.compile(r'TRAINER_CLASS\(\s*(\w+)\s*,\s*"((?:[^"\\]|\\.)*)"')


def parse_trainer_classes(text: str) -> dict[str, str]:
    """gTrainerClasses in src/battle_main.c: TRAINER_CLASS(HIKER, "HIKER", 10)
    -> {"TRAINER_CLASS_HIKER": "HIKER"}. The display strings are the game's
    own, control codes and all; prettify_caps() does the reading-for-humans."""
    return {f"TRAINER_CLASS_{key}": name
            for key, name in _TRAINER_CLASS_RE.findall(strip_c(text))}


_INCBIN_RE = re.compile(
    r'const\s+u32\s+gTrainerFrontPic_(\w+)\[\]\s*=\s*INCBIN_U32\("([^"]+)"\)')
_TRAINER_SPRITE_RE = re.compile(r"TRAINER_SPRITE\(\s*(\w+)\s*,\s*(\w+)")


def parse_trainer_pics(text: str) -> dict[str, str]:
    """src/data/graphics/trainers.h -> {TRAINER_PIC_HIKER: 'graphics/.../
    hiker.png'}. Two hops, both stated in that one file: TRAINER_SPRITE names
    the symbol, the INCBIN names the compiled file, and the source PNG sits
    where the compiled file does."""
    incbins = {sym: path for sym, path in _INCBIN_RE.findall(text)}
    out = {}
    for pic, sym in _TRAINER_SPRITE_RE.findall(text):
        path = incbins.get(sym)
        if not path:
            continue
        out[f"TRAINER_PIC_{pic}"] = re.sub(r"\.4bpp(\.lz)?$", ".png", path)
    return out


def parse_trainer_party(expr: str | None) -> list[dict]:
    """`.party = (const struct TrainerMon[]) { {...}, {...} }` -> one dict per
    mon. The cast in front of the brace is why this cannot just read a field."""
    if not expr:
        return []
    open_idx = expr.find("{")
    if open_idx < 0:
        return []
    body, _ = _block(expr, open_idx)
    party = []
    for chunk in split_top(body):
        chunk = chunk.strip()
        if not chunk.startswith("{"):
            continue
        inner, _ = _block(chunk, 0)
        f = parse_fields(inner)
        mon = {"species": _ident(f.get("species")),
               "lvl": first_int(f.get("lvl")),
               "heldItem": _ident(f.get("heldItem")),
               "ability": _ident(f.get("ability")),
               "nature": _ident(f.get("nature")),
               "moves": [m for m in re.findall(r"\bMOVE_\w+", f.get("moves") or "")
                         if m != "MOVE_NONE"],
               "shiny": "TRUE" in (f.get("isShiny") or "")}
        if mon["species"]:
            party.append(mon)
    return party


def _ident(expr: str | None) -> str | None:
    if not expr:
        return None
    m = _IDENT_RE.search(expr)
    return m.group(0) if m else None


def parse_trainers(text: str) -> dict[str, dict]:
    """src/data/trainers.h -> one record per trainer, party included.

    The file is GENERATED from trainers.party by trainerproc and says so in
    its own header, but it is git-tracked, so it is read rather than
    regenerated -- with the staleness of that arrangement reported on the
    dashboard rather than assumed away (dex-site-requirements.md §9.3)."""
    text = strip_c(text)
    out: dict[str, dict] = {}
    for i, m in enumerate(_TRAINER_ENTRY_RE.finditer(text)):
        const = m.group(1)
        body, _ = _block(text, m.end() - 1)
        f = parse_fields(body)
        party = parse_trainer_party(f.get("party"))
        levels = [p["lvl"] for p in party if p["lvl"] is not None]
        out[const] = {
            "const": const,
            "order": i,
            "name": last_string_literal(f.get("trainerName") or "") or "",
            "class": _ident(f.get("trainerClass")),
            "pic": _ident(f.get("trainerPic")),
            "double": "TRUE" in (f.get("doubleBattle") or ""),
            "items": [it for it in re.findall(r"\bITEM_\w+", f.get("items") or "")
                      if it != "ITEM_NONE"],
            "party": party,
            "maxLevel": max(levels) if levels else None,
        }
    return out


# ------------------------------------------------- Track A2: wild encounters

# The JSON's `fields` table gives each slot INDEX a weight; a species' real
# rarity is the sum of the weights of every slot it occupies. Fishing is not
# one method but three, split by rod, and its groups say which slots belong
# to which rod.
ENCOUNTER_LABELS = {
    "land_mons": "Walking",
    "water_mons": "Surfing",
    "rock_smash_mons": "Rock Smash",
    "fishing_mons": "Fishing",
}


def parse_wild_encounters(text: str) -> dict[str, dict]:
    """src/data/wild_encounters.json (porymap's own source, not the compiled
    header) -> {MAP_CONST: {"methods": {label: {"rate": n, "slots": [...]}}}}.

    Slots are aggregated per species, the way a reader thinks about them: a
    species filling four of twelve walking slots is one line at the summed
    rarity, with the level range those slots actually span."""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    out: dict[str, dict] = {}
    for group in data.get("wild_encounter_groups", []):
        if not group.get("for_maps"):
            continue
        weights, rod_groups = {}, {}
        for spec in group.get("fields", []):
            weights[spec.get("type")] = spec.get("encounter_rates") or []
            if spec.get("groups"):
                rod_groups[spec.get("type")] = spec["groups"]
        for enc in group.get("encounters", []):
            map_const = enc.get("map")
            if not map_const:
                continue
            methods = {}
            for key, label in ENCOUNTER_LABELS.items():
                table = enc.get(key)
                if not isinstance(table, dict) or not table.get("mons"):
                    continue
                rates = weights.get(key, [])
                groups = rod_groups.get(key) or {None: range(len(table["mons"]))}
                for gname, idxs in groups.items():
                    idxs = list(idxs)
                    total = sum(rates[i] for i in idxs if i < len(rates)) or 100
                    slots: dict[str, dict] = {}
                    for i in idxs:
                        if i >= len(table["mons"]):
                            continue
                        mon = table["mons"][i]
                        sp = mon.get("species")
                        if not sp:
                            continue
                        w = rates[i] if i < len(rates) else 0
                        rec = slots.setdefault(sp, {"species": sp, "pct": 0.0,
                                                    "min": mon.get("min_level"),
                                                    "max": mon.get("max_level")})
                        rec["pct"] += 100.0 * w / total
                        for bound, fn in (("min", min), ("max", max)):
                            v = mon.get(f"{bound}_level")
                            if v is not None:
                                cur = rec[bound]
                                rec[bound] = v if cur is None else fn(cur, v)
                    if not slots:
                        continue
                    name = gname.replace("_", " ").title() if gname else label
                    methods[name] = {
                        # A fishing table's single encounter rate belongs to
                        # the rod as a whole, not to each of the three rods
                        # it was split into, so it is not repeated there.
                        "rate": None if gname else table.get("encounter_rate"),
                        "slots": sorted(slots.values(),
                                        key=lambda s: -s["pct"]),
                    }
            if methods:
                out[map_const] = {"map": map_const, "methods": methods,
                                  "label": enc.get("base_label") or ""}
    return out


# ------------------------------------------ Track A4: the game's own words

_TEXT_LABEL_RE = re.compile(r"^(\w+):{1,2}\s*$")
_DOT_STRING_RE = re.compile(r'^\s*\.string\s+"(.*)"\s*$')
# trainerbattle_single TRAINER_X, IntroText, DefeatText[, script]
# ...and its double/rematch/no_intro cousins, which differ in how many
# arguments follow but not in where the trainer and its text sit.
_TRAINERBATTLE_RE = re.compile(
    r"^\s*(trainerbattle\w*)\s+([^\n]+)$", re.M)
_GIVEITEM_RE = re.compile(r"^\s*giveitem\w*\s+(ITEM_\w+)", re.M)


def parse_text_labels(text: str) -> dict[str, str]:
    """`Label:` (or `Label::`) followed by .string lines -> {label: raw}.
    The raw form keeps the game's own control codes; game_string() reads
    them for the page."""
    out, label, buf = {}, None, []

    def flush():
        if label and buf:
            out.setdefault(label, "".join(buf))

    for line in text.splitlines():
        m = _TEXT_LABEL_RE.match(line)
        if m:
            flush()
            label, buf = m.group(1), []
            continue
        s = _DOT_STRING_RE.match(line)
        if s:
            buf.append(s.group(1))
        elif buf and line.strip() and not line.strip().startswith("@"):
            flush()
            label, buf = None, []
    flush()
    return out


def parse_trainerbattles(text: str) -> dict[str, list[str]]:
    """{TRAINER_X: [text labels the battle macro names]}. Which argument
    means what varies by macro, so the labels are kept in order and
    resolved by name later -- a label with no text behind it is simply not
    shown, rather than guessed at."""
    out: dict[str, list[str]] = {}
    for _, args in _TRAINERBATTLE_RE.findall(text):
        parts = [a.strip() for a in args.split(",")]
        if not parts or not parts[0].startswith("TRAINER_"):
            continue
        labels = [p for p in parts[1:]
                  if re.fullmatch(r"\w+", p) and "_Text_" in p]
        if labels:
            out.setdefault(parts[0], labels)
    return out


def parse_giveitems(text: str) -> set[str]:
    """Items a script hands over. Not a ground item and not a trainer's
    held item -- the third way a player gets something."""
    return set(_GIVEITEM_RE.findall(text))


def group_texts(texts: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
    """Text labels bucketed by the map name they are named after. The engine
    names every one `<MapDir>_Text_<What>`, so the separator does the
    grouping -- and does it exactly: RustboroCity_TrainingAnnex_Text_Coach
    belongs to the annex, not to Rustboro City, even though one name is a
    prefix of the other. This is a CONVENTION used to group, never to
    claim: a label that does not follow it is simply not grouped."""
    out: dict[str, list[tuple[str, str]]] = {}
    for label, raw in texts.items():
        head, sep, _ = label.partition("_Text_")
        if sep:
            out.setdefault(head, []).append((label, raw))
    return {k: sorted(v) for k, v in out.items()}


def game_string(raw: str | None) -> list[str]:
    """One .string as the box would show it: paragraphs split on \\p, line
    breaks flattened to spaces, the terminator dropped. Control codes in
    braces ({PLAYER}, {STR_VAR_1}) are LEFT AS THEY ARE -- this is the
    game's own text, and inventing a name for a variable would be writing
    dialogue rather than quoting it."""
    if not raw:
        return []
    body = raw[:-1] if raw.endswith("$") else raw
    out = []
    for para in body.split(r"\p"):
        line = re.sub(r"\\[nl]", " ", para)
        line = re.sub(r"\\.", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            out.append(line)
    return out


# ---------------------------------------------- Track A3: maps and tilesets

# The block word's three fields and the primary/secondary split, both read
# from the fork's own headers rather than assumed -- a hack that raises
# NUM_TILES_IN_PRIMARY renders correctly or not at all, never subtly wrong.
FIELDMAP_DEFAULTS = {
    "NUM_TILES_IN_PRIMARY": 512,
    "NUM_METATILES_IN_PRIMARY": 512,
    "NUM_PALS_IN_PRIMARY": 6,
}
MAPGRID_DEFAULTS = {
    "MAPGRID_METATILE_ID_MASK": 0x03FF,
    "MAPGRID_ELEVATION_MASK": 0xF000,
}

_TS_TILES_RE = re.compile(
    r'\b(gTilesetTiles_\w+)\[\]\s*=\s*INCBIN_U32\("([^"]+)"\)')
_TS_PALS_RE = re.compile(
    r'\b(gTilesetPalettes_\w+)\[\]\[16\]\s*=\s*\{\s*INCBIN_U16\("([^"]+)"\)')
_TS_META_RE = re.compile(
    r'\b(gMetatiles_\w+)\[\]\s*=\s*INCBIN_U16\("([^"]+)"\)')
_TILESET_HEADER_RE = re.compile(
    r"const\s+struct\s+Tileset\s+(gTileset_\w+)\s*=\s*\{(.*?)\}\s*;", re.S)
_TS_FIELD_RE = re.compile(r"\.(tiles|palettes|metatiles)\s*=\s*(\w+)")


def parse_defines_int(text: str, defaults: dict) -> dict:
    """`#define NAME <int>` for a known set of names, defaulting only where
    the header does not say."""
    out = dict(defaults)
    for name in defaults:
        m = re.search(rf"^\s*#define\s+{name}\s+(0x[0-9A-Fa-f]+|\d+)",
                      text, re.M)
        if m:
            out[name] = int(m.group(1), 0)
    return out


def parse_tileset_paths(graphics: str, metatiles: str,
                        headers: str) -> dict[str, dict]:
    """gTileset_General -> where its tiles, palettes and metatiles actually
    live. Each of the three is followed through its OWN symbol rather than
    assumed to sit beside the tiles: every secret-base tileset shares one
    metatiles.bin a directory up from its art, and a renderer that guessed
    siblings drew nothing for two dozen maps before this followed the
    header's word instead."""
    tiles = dict(_TS_TILES_RE.findall(graphics))
    pals = dict(_TS_PALS_RE.findall(graphics))
    metas = dict(_TS_META_RE.findall(metatiles))
    out = {}
    for name, body in _TILESET_HEADER_RE.findall(headers):
        fields = dict(_TS_FIELD_RE.findall(body))
        tpath = tiles.get(fields.get("tiles", ""))
        if not tpath:
            continue
        ppath = pals.get(fields.get("palettes", ""))
        out[name] = {
            "tiles": re.sub(r"\.4bpp(\.lz)?$", ".png", tpath),
            "palettes": os.path.dirname(ppath) if ppath
                        else os.path.join(os.path.dirname(tpath), "palettes"),
            "metatiles": metas.get(fields.get("metatiles", "")) or "",
        }
    return out


def read_jasc_pal(path: Path) -> list[tuple[int, int, int]]:
    """A JASC-PAL is CRLF text: magic, version, count, then 'R G B' lines.
    (export_hack learned the CRLF the hard way; this only reads.)"""
    try:
        lines = path.read_text(errors="replace").split("\n")
    except OSError:
        return []
    out = []
    for line in lines[3:]:
        bits = line.split()
        if len(bits) >= 3 and all(b.isdigit() for b in bits[:3]):
            out.append(tuple(int(b) for b in bits[:3]))
    return out


def read_u16s(path: Path) -> list[int]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    return list(struct.unpack(f"<{len(data) // 2}H", data[:len(data) // 2 * 2]))


def parse_layouts(text: str) -> dict[str, dict]:
    """data/layouts/layouts.json -> {LAYOUT_ID: row}."""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return {row["id"]: row for row in data.get("layouts", [])
            if isinstance(row, dict) and row.get("id")}


# An object event holding an item ball stores the item in the field that
# would otherwise be a sight radius -- the engine overloads it, so the item
# on the ground really is derivable from map.json alone.
_ITEM_FIELD = "trainer_sight_or_berry_tree_id"
_SCRIPT_LABEL_RE = re.compile(r"^(\w+)::", re.M)
_SCRIPT_TRAINER_RE = re.compile(r"\b(TRAINER_\w+)")


def parse_script_trainers(text: str) -> dict[str, str]:
    """A map's scripts.inc: label -> the first trainer constant its body
    names. This is the one hop between "an NPC stands here" (map.json) and
    "and this is the team they battle with" (trainers.h)."""
    out = {}
    labels = list(_SCRIPT_LABEL_RE.finditer(text))
    for i, m in enumerate(labels):
        end = labels[i + 1].start() if i + 1 < len(labels) else len(text)
        found = _SCRIPT_TRAINER_RE.search(text, m.end(), end)
        if found and found.group(1) != "TRAINER_NONE":
            out.setdefault(m.group(1), found.group(1))
    return out


_BADGE_SET_RE = re.compile(r"setflag\s+FLAG_BADGE0*(\d+)_GET\b")
_DEFEATED_SET_RE = re.compile(r"setflag\s+(FLAG_DEFEATED_[A-Z0-9_]+)\b")
_MESSAGE_LABEL_RE = re.compile(r"^\s*(?:message|msgbox)\s+(\w+)", re.M)
_BADGE_NAME_RE = re.compile(r"received the\s+([A-Za-z][A-Za-z '&-]*?)\s*BADGE",
                            re.I)


def parse_gym(script_text: str, texts: dict[str, str]) -> dict | None:
    """A gym, derived from the one thing that actually makes a place a gym:
    its scripts award a badge.

    The tempting definition is the map header's `MAP_BATTLE_SCENE_GYM`, and
    it is wrong -- in the stock engine thirteen Battle Pyramid rooms carry
    it and are not gyms, while a gym's other floors do not carry the badge.
    Awarding a badge is neither over- nor under-inclusive: in stock it
    selects exactly the eight.

    Everything here is read or absent. The badge NUMBER is certain (it is
    the flag). The badge NAME is not data anywhere in the tree -- no table
    holds it -- so it is lifted from the game's own congratulation line if
    that line is phrased the way the engine phrases it, and simply left out
    if it is not. A gym page that says "the first badge" is honest; one
    that invents "the Stone Badge" is not."""
    labels = list(_SCRIPT_LABEL_RE.finditer(script_text))
    bodies = [(m.group(1), script_text[m.end():
                                       (labels[i + 1].start()
                                        if i + 1 < len(labels)
                                        else len(script_text))])
              for i, m in enumerate(labels)]

    award = next(((name, body) for name, body in bodies
                  if _BADGE_SET_RE.search(body)), None)
    if not award:
        return None
    award_label, award_body = award
    badge = int(_BADGE_SET_RE.search(award_body).group(1))

    beaten = _DEFEATED_SET_RE.search(award_body)
    name = None
    for lab in _MESSAGE_LABEL_RE.findall(award_body):
        got = _BADGE_NAME_RE.search(" ".join(game_string(texts.get(lab))))
        if got:
            name = prettify_caps(got.group(1).strip() + " Badge")
            break

    # The leader is whoever's battle leads to that award, and the engine
    # writes that in two shapes. Usually the award is its own label, named
    # by the script that fought for it (Rustboro: the win-script argument of
    # Roxanne's trainerbattle). Sometimes the battle and the award are the
    # same label (Petalburg: Norman is fought and the badge handed over
    # without a jump). So look inside the award first, then at whoever
    # points to it. Neither shape matching means the chain is built some
    # third way, and the gym is reported with no leader rather than a
    # guessed one.
    def trainer_in(body):
        found = _SCRIPT_TRAINER_RE.search(body)
        return found.group(1) if found and found.group(1) != "TRAINER_NONE" \
            else None

    leader = trainer_in(award_body)
    if not leader:
        for label, body in bodies:
            if label != award_label and award_label in body:
                leader = trainer_in(body)
                if leader:
                    break
    return {"badge": badge, "badge_name": name, "leader": leader,
            "defeated_flag": beaten.group(1) if beaten else None,
            "award_script": award_label}


_PROGRESS_FLAG = r"(FLAG_BADGE0*\d+_GET|FLAG_DEFEATED_[A-Z0-9_]+)"
_PROGRESS_TEST_RE = re.compile(
    r"(?:\b\w*_if_(?:un)?set|\bcheckflag)\s+" + _PROGRESS_FLAG)


def parse_progress_checks(script_text: str) -> list[str]:
    """Which badges and gym victories a place's scripts READ.

    This is the derivable half of §12.3's second item. "Which story beat is
    done" cannot be read from a source tree at all -- doneness lives in a
    save file, and a static site has no save. What a tree does hold is which
    progress flags each place's scripts test, and that is a real fact about
    how the game is gated.

    It is deliberately called a check and never a gate. Of the twenty stock
    maps that read a badge flag, several do it to move a shopkeeper or
    reveal a florist -- reading a flag is not the same as barring a door,
    and this parse cannot tell the two apart. Saying "checks" is true;
    saying "requires" would not be."""
    return sorted(set(_PROGRESS_TEST_RE.findall(script_text)))


def badge_number(flag: str) -> int | None:
    """The badge a FLAG_BADGE0n_GET names, or None for anything else."""
    m = re.fullmatch(r"FLAG_BADGE0*(\d+)_GET", flag)
    return int(m.group(1)) if m else None


def parse_map_json(text: str) -> dict | None:
    """One map's own header and events, kept to what a reader can be shown:
    where it is, what it connects to, who stands in it, what lies on the
    ground."""
    try:
        d = json.loads(text)
    except ValueError:
        return None
    if not isinstance(d, dict) or not d.get("id"):
        return None
    objs = d.get("object_events") or []
    trainers, ground, npcs = [], [], 0
    for o in objs:
        if not isinstance(o, dict):
            continue
        gfx = o.get("graphics_id") or ""
        if str(o.get("trainer_type", "")).endswith(("NORMAL", "BURIED")):
            trainers.append({"script": o.get("script") or "",
                             "x": o.get("x"), "y": o.get("y"), "gfx": gfx})
        elif "ITEM_BALL" in gfx:
            item = str(o.get(_ITEM_FIELD) or "")
            ground.append({"item": item if item.startswith("ITEM_") else "",
                           "x": o.get("x"), "y": o.get("y"), "hidden": False})
        else:
            npcs += 1
    for b in d.get("bg_events") or []:
        if isinstance(b, dict) and b.get("type") == "hidden_item":
            ground.append({"item": str(b.get("item") or ""), "x": b.get("x"),
                           "y": b.get("y"), "hidden": True})
    return {
        "id": d["id"],
        "name": d.get("name") or "",
        "layout": d.get("layout") or "",
        "section": d.get("region_map_section") or "",
        "type": d.get("map_type") or "",
        "weather": d.get("weather") or "",
        "connections": [c for c in (d.get("connections") or [])
                        if isinstance(c, dict) and c.get("map")],
        "warps": [w.get("dest_map") for w in (d.get("warp_events") or [])
                  if isinstance(w, dict) and w.get("dest_map")],
        "trainers": trainers,
        "ground": [g for g in ground if g["item"]],
        "npcs": npcs,
    }


class MapRenderer:
    """Composites a layout into one PNG the way the hardware would: every
    block is a metatile, every metatile is eight 8x8 tiles in two layers,
    every tile picks 16 colours out of the tileset's own palette and may be
    flipped either way. Nothing here is clever -- it is the format, followed.

    Pillow is imported lazily and its absence is a skipped section, never a
    failed run: the rest of the site does not depend on pictures.
    """

    def __init__(self, fork: Path, dirs: dict[str, str], consts: dict,
                 masks: dict, warn):
        self.fork = fork
        self.dirs = dirs
        self.warn = warn
        self.n_tiles = consts["NUM_TILES_IN_PRIMARY"]
        self.n_metatiles = consts["NUM_METATILES_IN_PRIMARY"]
        self.n_pals = consts["NUM_PALS_IN_PRIMARY"]
        self.mt_mask = masks["MAPGRID_METATILE_ID_MASK"]
        self._sets: dict[str, dict] = {}
        self._blocks: dict[tuple, dict] = {}
        self.Image = None

    def available(self) -> bool:
        if self.Image is None:
            try:
                from PIL import Image
            except ImportError:
                self.Image = False
                self.warn("Pillow is not installed, so no map is rendered; "
                          "everything else on the location pages is unaffected")
            else:
                self.Image = Image
        return bool(self.Image)

    def tileset(self, symbol: str) -> dict | None:
        """One tileset's tiles (as an index grid), palettes and metatiles."""
        if symbol in self._sets:
            return self._sets[symbol]
        where = self.dirs.get(symbol)
        self._sets[symbol] = None
        if not where:
            return None
        png = self.fork / where["tiles"]
        if not png.is_file():
            return None
        img = self.Image.open(png)
        if img.mode != "P":
            # Indexed colour is the whole point: the PNG's own palette is
            # thrown away and the game's .pal files supply the colours.
            img = img.convert("P")
        pals_dir = self.fork / where["palettes"]
        rec = {"img": img, "px": img.load(), "w": img.width, "h": img.height,
               "pals": [read_jasc_pal(pals_dir / f"{i:02d}.pal")
                        for i in range(16)],
               "metatiles": read_u16s(self.fork / where["metatiles"])
                            if where["metatiles"] else []}
        self._sets[symbol] = rec
        return rec

    def _tile_pixels(self, ts, tile_id, pal, xflip, yflip):
        """One 8x8 tile as a list of (r,g,b,a), palette applied, flips
        applied, colour 0 transparent (the caller decides if that matters)."""
        cols = ts["w"] // 8
        tx, ty = (tile_id % cols) * 8, (tile_id // cols) * 8
        if ty + 8 > ts["h"]:
            return None
        colours = pal or []
        out = []
        for y in range(8):
            sy = ty + (7 - y if yflip else y)
            for x in range(8):
                sx = tx + (7 - x if xflip else x)
                idx = ts["px"][sx, sy]
                rgb = colours[idx] if idx < len(colours) else (0, 0, 0)
                out.append((*rgb, 0 if idx == 0 else 255))
        return out

    def block_image(self, pri: str, sec: str, block: int):
        """One 16x16 metatile, cached per tileset pair."""
        key = (pri, sec, block)
        if key in self._blocks:
            return self._blocks[key]
        which, local = ((pri, block) if block < self.n_metatiles
                        else (sec, block - self.n_metatiles))
        ts = self.tileset(which)
        img = None
        if ts and (local + 1) * 8 <= len(ts["metatiles"]):
            img = self.Image.new("RGBA", (16, 16), (0, 0, 0, 0))
            for layer in range(2):
                for i in range(4):
                    word = ts["metatiles"][local * 8 + layer * 4 + i]
                    tile_id = word & 0x03FF
                    xflip, yflip = bool(word & 0x400), bool(word & 0x800)
                    pal_no = (word >> 12) & 0xF
                    src = (self.tileset(pri) if tile_id < self.n_tiles
                           else self.tileset(sec))
                    tid = (tile_id if tile_id < self.n_tiles
                           else tile_id - self.n_tiles)
                    pal_src = (self.tileset(pri) if pal_no < self.n_pals
                               else self.tileset(sec))
                    if not src or not pal_src:
                        continue
                    pal = pal_src["pals"][pal_no] if pal_no < len(pal_src["pals"]) else []
                    px = self._tile_pixels(src, tid, pal, xflip, yflip)
                    if not px:
                        continue
                    tile = self.Image.new("RGBA", (8, 8))
                    tile.putdata(px)
                    dst = ((i % 2) * 8, (i // 2) * 8)
                    if layer == 0:
                        # The bottom layer is the ground: its colour 0 is a
                        # real colour, not a hole.
                        tile = tile.convert("RGB").convert("RGBA")
                        img.paste(tile, dst)
                    else:
                        img.paste(tile, dst, tile)
        self._blocks[key] = img
        return img

    def render(self, layout: dict):
        """A whole layout as one image, or None if anything it needs is
        missing -- an unreadable map is left out, never half-drawn."""
        if not self.available():
            return None
        w, h = layout.get("width") or 0, layout.get("height") or 0
        blocks = read_u16s(self.fork / (layout.get("blockdata_filepath") or ""))
        if not (w and h) or len(blocks) < w * h:
            return None
        pri = layout.get("primary_tileset") or ""
        sec = layout.get("secondary_tileset") or ""
        if not self.tileset(pri):
            return None
        out = self.Image.new("RGBA", (w * 16, h * 16), (0, 0, 0, 255))
        drawn = 0
        for i in range(w * h):
            img = self.block_image(pri, sec, blocks[i] & self.mt_mask)
            if img is None:
                continue
            out.paste(img, ((i % w) * 16, (i // w) * 16))
            drawn += 1
        return out if drawn else None


# Standard Gen-6+ chart, the documented fallback when types_info.h resists
# parsing. Keys are (attacker, defender); unlisted pairs are 1.0.
_G6 = {
    "NORMAL":   {"ROCK": .5, "GHOST": 0, "STEEL": .5},
    "FIGHTING": {"NORMAL": 2, "FLYING": .5, "POISON": .5, "ROCK": 2, "BUG": .5,
                 "GHOST": 0, "STEEL": 2, "PSYCHIC": .5, "ICE": 2, "DARK": 2,
                 "FAIRY": .5},
    "FLYING":   {"FIGHTING": 2, "ROCK": .5, "BUG": 2, "STEEL": .5, "GRASS": 2,
                 "ELECTRIC": .5},
    "POISON":   {"POISON": .5, "GROUND": .5, "ROCK": .5, "GHOST": .5,
                 "STEEL": 0, "GRASS": 2, "FAIRY": 2},
    "GROUND":   {"FLYING": 0, "POISON": 2, "ROCK": 2, "BUG": .5, "STEEL": 2,
                 "FIRE": 2, "GRASS": .5, "ELECTRIC": 2},
    "ROCK":     {"FIGHTING": .5, "FLYING": 2, "GROUND": .5, "BUG": 2,
                 "FIRE": 2, "ICE": 2},
    "BUG":      {"FIGHTING": .5, "FLYING": .5, "POISON": .5, "GHOST": .5,
                 "STEEL": .5, "FIRE": .5, "GRASS": 2, "PSYCHIC": 2, "DARK": 2,
                 "FAIRY": .5},
    "GHOST":    {"NORMAL": 0, "GHOST": 2, "PSYCHIC": 2, "DARK": .5},
    "STEEL":    {"ROCK": 2, "STEEL": .5, "FIRE": .5, "WATER": .5,
                 "ELECTRIC": .5, "ICE": 2, "FAIRY": 2},
    "FIRE":     {"ROCK": .5, "BUG": 2, "STEEL": 2, "FIRE": .5, "WATER": .5,
                 "GRASS": 2, "ICE": 2, "DRAGON": .5},
    "WATER":    {"GROUND": 2, "ROCK": 2, "FIRE": 2, "WATER": .5, "GRASS": .5,
                 "DRAGON": .5},
    "GRASS":    {"FLYING": .5, "POISON": .5, "GROUND": 2, "ROCK": 2, "BUG": .5,
                 "STEEL": .5, "FIRE": .5, "WATER": 2, "GRASS": .5,
                 "DRAGON": .5},
    "ELECTRIC": {"FLYING": 2, "GROUND": 0, "WATER": 2, "GRASS": .5,
                 "ELECTRIC": .5, "DRAGON": .5},
    "PSYCHIC":  {"FIGHTING": 2, "POISON": 2, "STEEL": .5, "PSYCHIC": .5,
                 "DARK": 0},
    "ICE":      {"FLYING": 2, "GROUND": 2, "STEEL": .5, "FIRE": .5,
                 "WATER": .5, "GRASS": 2, "ICE": .5, "DRAGON": 2},
    "DRAGON":   {"STEEL": .5, "DRAGON": 2, "FAIRY": 0},
    "DARK":     {"FIGHTING": .5, "GHOST": 2, "PSYCHIC": 2, "DARK": .5,
                 "FAIRY": .5},
    "FAIRY":    {"FIGHTING": 2, "POISON": .5, "STEEL": .5, "FIRE": .5,
                 "DRAGON": 2, "DARK": 2},
}
FALLBACK_ORDER = list(_G6)
FALLBACK_CHART = {("TYPE_" + a, "TYPE_" + d): v
                  for a, row in _G6.items() for d, v in row.items()}


def parse_type_chart(text: str) -> tuple[list[str], dict[tuple[str, str], float]]:
    """gTypeEffectivenessTable -> (type order, {(atk, def): multiplier}).

    `______` is 1.0, `X(v)` is v, and a `*_RS` config macro resolves to the
    first X(v) in its own #define -- the modern-matchup branch.
    """
    rs = {}
    for m in re.finditer(r"^\s*#define\s+(\w+)\s+(.+)$", text, re.M):
        x = re.search(r"X\(([\d.]+)\)", m.group(2))
        if x:
            rs[m.group(1)] = float(x.group(1))
    tbl = re.search(r"gTypeEffectivenessTable\s*\[[^]]*\]\s*\[[^]]*\]\s*=\s*\{",
                    _COMMENT_RE.sub("", text))
    if not tbl:
        return [], {}
    body, _ = _block(text if False else _COMMENT_RE.sub("", text),
                     tbl.end() - 1)
    order, rows = [], []
    for rm in re.finditer(r"\[(TYPE_\w+)\]\s*=\s*\{([^}]*)\}", body):
        order.append(rm.group(1))
        rows.append([t.strip() for t in rm.group(2).split(",")])
    chart: dict[tuple[str, str], float] = {}
    for atk, row in zip(order, rows):
        for j, tok in enumerate(row):
            if j >= len(order):
                break
            if tok == "______" or tok == "":
                val = 1.0
            else:
                x = re.search(r"X\(([\d.]+)\)", tok)
                val = float(x.group(1)) if x else rs.get(tok)
            if val is None:
                return [], {}       # a token we cannot read: refuse, fall back
            if val != 1.0:
                chart[(atk, order[j])] = val
    return order, chart


def parse_sprite_dirs(text: str) -> dict[str, str]:
    """src/data/graphics/pokemon.h: `const u32 gMonFrontPic_X[] =
    INCBIN_U32("graphics/pokemon/<dir>/anim_front.4bpp.lz");` -- the game's
    OWN symbol-to-directory mapping, which is why Castform's normal form
    finds `castform/` without any name heuristics."""
    return {m.group(1): m.group(2) for m in re.finditer(
        r'const u\d+ (g\w+)\[\]\s*=\s*INCBIN_U\d+\("(graphics/pokemon/[^"]+)/[^"/]+"\)',
        text)}


def parse_dex_order(text: str) -> dict[str, int]:
    """include/constants/pokedex.h's first enum: NATIONAL_DEX_X -> ordinal."""
    m = re.search(r"enum\s*\{(.*?)\};", strip_c(text), re.S)
    if not m:
        return {}
    return {name: i for i, name in
            enumerate(re.findall(r"NATIONAL_DEX_\w+", m.group(1)))}


# ------------------------------------------------------------ the diff

# Fields compared against the stock engine, with display labels. Species'
# list is the default; moves/abilities/items pass their own (Track A1).
COMPARE_FIELDS = [
    ("name", "Name"), ("category", "Category"), ("types", "Types"),
    ("baseHP", "HP"), ("baseAttack", "Attack"), ("baseDefense", "Defense"),
    ("baseSpAttack", "Sp. Atk"), ("baseSpDefense", "Sp. Def"),
    ("baseSpeed", "Speed"), ("catchRate", "Catch rate"),
    ("expYield", "Exp. yield"), ("abilities", "Abilities"),
    ("genderRatio", "Gender ratio"), ("eggGroups", "Egg groups"),
    ("height", "Height"), ("weight", "Weight"),
    ("description", "Dex text"), ("evolutions", "Evolutions"),
    ("levelUpMoves", "Level-up moves"), ("teachableMoves", "Teachable moves"),
]

MOVE_COMPARE_FIELDS = [
    ("name", "Name"), ("type", "Type"), ("category", "Category"),
    ("power", "Power"), ("accuracy", "Accuracy"), ("pp", "PP"),
    ("priority", "Priority"), ("description", "Effect"),
]

ABILITY_COMPARE_FIELDS = [
    ("name", "Name"), ("description", "Effect"),
]

ITEM_COMPARE_FIELDS = [
    ("name", "Name"), ("description", "Effect"), ("price", "Price"),
    ("pocket", "Pocket"),
]
# A trainer's party is compared whole -- every species, level, held item and
# move in it -- because a re-tuned team is exactly the change this page
# exists to show, and one mon's level moving is not a smaller fact than a
# renamed trainer.
TRAINER_COMPARE_FIELDS = [
    ("name", "Name"), ("class", "Class"), ("double", "Double battle"),
    ("items", "Bag items"), ("party", "Party"), ("lines", "Dialogue"),
]
# A place is compared as a place: the ground it is drawn on, what lives
# there, who stands in it, what lies about, and where its edges lead.
MAP_COMPARE_FIELDS = [
    ("layout", "Layout"), ("terrain", "Terrain"), ("size", "Size"),
    ("encounters", "Encounters"), ("trainers", "Trainers here"),
    ("ground", "Items here"), ("npcs", "Other NPCs"),
    ("connections", "Connections"), ("weather", "Weather"),
    ("type", "Map type"), ("text", "Dialogue"), ("gym", "Gym"),
]


def classify(ours: dict, stock: dict | None, fields=COMPARE_FIELDS):
    """-> ("new"|"changed"|"same", [(label, old, new), ...]).

    A field absent on BOTH sides is not a difference; absent on one side is.
    """
    if stock is None:
        return "new", []
    diffs = []
    for key, label in fields:
        a, b = stock.get(key), ours.get(key)
        if a != b:
            diffs.append((label, a, b))
    return ("changed", diffs) if diffs else ("same", [])


# ------------------------------------------------------------ prettifying

# Longest first: MAP_TYPE_INDOOR must lose all of "MAP_TYPE_", not just the
# "MAP_" that would leave it reading "Type Indoor".
_PREFIXES = ("SPECIES_", "MOVE_", "ABILITY_", "ITEM_", "TYPE_", "EGG_GROUP_",
             "NATIONAL_DEX_", "EVO_", "TRAINING_CATEGORY_", "TRAINING_EVO_",
             "MAP_TYPE_", "MAP_BATTLE_SCENE_", "MAP_", "WEATHER_", "FLAG_",
             "POCKET_")


def pretty(sym: str) -> str:
    """SPECIES_MR_MIME -> 'Mr Mime'; a plain number stays a number."""
    s = sym.strip()
    for p in _PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
            break
    return " ".join(w.capitalize() for w in s.split("_")) if s else sym


def type_label(t: str) -> str:
    return pretty(t) if t.startswith("TYPE_") else t


def slug(const: str) -> str:
    """SPECIES_/MOVE_/ABILITY_/ITEM_ constant -> its lowercase URL key."""
    for p in ("SPECIES_", "MOVE_", "ABILITY_", "ITEM_", "TRAINER_", "MAP_"):
        if const.startswith(p):
            return const[len(p):].lower()
    return const.lower()


_FLOOR_RE = re.compile(r"B?\d+F|\d+R")
_WORD_NUM_RE = re.compile(r"([A-Z]+)(\d+)$")
_MAP_SMALL_WORDS = {"of", "the", "and", "in", "on", "de"}


def prettify_caps(s: str) -> str:
    """The game's own display text, read for the web. Words the game shouts
    (every trainer name and class is upper case in the ROM) are sentence-cased;
    words that already carry lower case are left exactly as the game wrote
    them, so an expansion-era mixed-case name is never mangled. `é` is not
    ASCII, so POKéMANIAC still tests as a shouted word."""
    def word(w):
        if re.search(r"[a-z]", w):
            return w
        # Each run of letters is sentence-cased on its own, so TATE&LIZA
        # comes back as Tate&Liza rather than Tate&liza. `é` counts as a
        # letter here or POKéMANIAC would split into three runs.
        return re.sub(r"[A-Za-zé']+", lambda m: m.group(0).capitalize(), w)
    return " ".join(word(w) for w in s.replace("{PKMN}", "POKéMON").split())


def map_label(const: str) -> str:
    """MAP_ROUTE101 -> 'Route 101', MAP_CAVE_OF_ORIGIN_1F -> 'Cave of Origin
    1F'. Digits run on in the constant and must not run on in the reading,
    but a floor is a floor and stays upper case."""
    raw = const[4:] if const.startswith("MAP_") else const
    out = []
    for tok in raw.split("_"):
        if _FLOOR_RE.fullmatch(tok):
            out.append(tok.upper())
            continue
        m = _WORD_NUM_RE.fullmatch(tok)
        if m:
            out.append(f"{m.group(1).capitalize()} {m.group(2)}")
            continue
        word = tok.capitalize()
        out.append(word.lower() if out and word.lower() in _MAP_SMALL_WORDS
                   else word)
    return " ".join(out)


def gender_text(raw: str | None) -> str | None:
    if not raw:
        return None
    if "MON_GENDERLESS" in raw:
        return "Genderless"
    if "MON_FEMALE" in raw:
        return "Female only"
    if "MON_MALE" in raw:
        return "Male only"
    m = re.search(r"PERCENT_FEMALE\(([\d.]+)\)", raw)
    if m:
        f = float(m.group(1))
        return f"{100 - f:g}% male, {f:g}% female"
    return raw


_EVO_TEXT = {
    "EVO_LEVEL": "Level {p}", "EVO_ITEM": "Use {p}",
    "EVO_FRIENDSHIP": "High friendship",
    "EVO_FRIENDSHIP_DAY": "High friendship, daytime",
    "EVO_FRIENDSHIP_NIGHT": "High friendship, nighttime",
    "EVO_TRADE": "Trade", "EVO_TRADE_ITEM": "Trade holding {p}",
    "EVO_LEVEL_DAY": "Level {p}, daytime",
    "EVO_LEVEL_NIGHT": "Level {p}, nighttime",
    "EVO_LEVEL_ATK_GT_DEF": "Level {p}, Attack > Defense",
    "EVO_LEVEL_ATK_LT_DEF": "Level {p}, Attack < Defense",
    "EVO_LEVEL_ATK_EQ_DEF": "Level {p}, Attack = Defense",
    "EVO_LEVEL_SILCOON": "Level {p} (personality: Silcoon)",
    "EVO_LEVEL_CASCOON": "Level {p} (personality: Cascoon)",
    "EVO_LEVEL_NINJASK": "Level {p}", "EVO_LEVEL_SHEDINJA": "Level {p}, spare slot",
    "EVO_BEAUTY": "Beauty ≥ {p}", "EVO_MOVE": "Knows {p}",
    "EVO_LEVEL_DUSK": "Level {p}, dusk", "EVO_ITEM_DAY": "Use {p}, daytime",
    "EVO_ITEM_NIGHT": "Use {p}, nighttime",
    "EVO_ITEM_MALE": "Use {p} (male)", "EVO_ITEM_FEMALE": "Use {p} (female)",
    "EVO_LEVEL_MALE": "Level {p} (male)", "EVO_LEVEL_FEMALE": "Level {p} (female)",
}


def evo_text(method: str, param: str) -> str:
    """A readable condition; unknown methods degrade to prettified symbols,
    never to invented text."""
    syms = re.findall(r"[A-Za-z_]\w*|\d+", param)
    ptxt = ", ".join(pretty(s) if not s.isdigit() else s
                     for s in syms
                     if s not in ("TRAINING_EVO_PARAM",)) or param
    tpl = _EVO_TEXT.get(method)
    if tpl:
        return tpl.format(p=ptxt)
    return f"{pretty(method)} ({ptxt})" if ptxt else pretty(method)


# ------------------------------------------------------------ loading a tree

def read(path: Path) -> str:
    return path.read_text(errors="replace") if path.is_file() else ""


def load_tree(root: Path, warn) -> dict:
    """Parse one pokeemerald-expansion tree into a model dict."""
    data = root / "src/data"
    pokemon = data / "pokemon"
    shared = parse_shared_texts(read(pokemon / "species_info/shared_dex_text.h"))
    species_files = sorted((pokemon / "species_info").glob("*.h"))
    species_files = [p for p in species_files if p.name != "shared_dex_text.h"]
    tdefs = {}
    obj_all: dict[str, str] = {}
    fn_all: dict[str, tuple] = {}
    for p in species_files:
        t = read(p)
        tdefs.update(parse_type_defines(t))
        obj, fn = parse_macros(t)
        obj_all.update(obj)
        fn_all.update(fn)
    species: dict[str, dict] = {}
    for p in species_files:
        for const, sp in parse_species_text(read(p), shared, tdefs,
                                            (obj_all, fn_all)).items():
            if const in species:
                warn(f"{p.name}: duplicate entry {const}; first kept")
            else:
                sp["order"] = len(species)
                species[const] = sp

    lvl: dict[str, list] = {}
    lvl_dir = pokemon / "level_up_learnsets"
    for p in (sorted(lvl_dir.glob("*.h")) if lvl_dir.is_dir()
              else [pokemon / "level_up_learnsets.h"]):
        lvl.update(parse_level_up_learnsets(read(p)))
    teach = parse_teachable_learnsets(read(pokemon / "teachable_learnsets.h"))
    if not teach:
        warn("teachable_learnsets.h yielded nothing; teachable moves omitted")

    moves: dict[str, dict] = {}
    for p in ([data / "moves_info.h"] + sorted((data / "moves_info").glob("*.h"))
              if (data / "moves_info").is_dir() else [data / "moves_info.h"]):
        moves.update(parse_moves_info(read(p)))

    abilities = parse_abilities_info(read(data / "abilities.h"))
    items = parse_items_info(read(data / "items.h"))
    item_order = parse_item_order(read(root / "include/constants/items.h"))

    order, chart = parse_type_chart(read(data / "types_info.h"))
    if not chart:
        warn("types_info.h chart not parsed; using the built-in Gen-6+ chart")
        order = ["TYPE_" + t for t in FALLBACK_ORDER]
        chart = dict(FALLBACK_CHART)

    dex = parse_dex_order(read(root / "include/constants/pokedex.h"))
    sprite_dirs = parse_sprite_dirs(read(data / "graphics/pokemon.h"))

    # Track A2. trainers.h is generated from trainers.party but git-tracked,
    # so it is read as it stands; wild_encounters.json is porymap's own
    # source, never the compiled header beside it.
    trainers = parse_trainers(read(data / "trainers.h"))
    if not trainers:
        warn("trainers.h yielded no trainers; the trainer pages are omitted")
    classes = parse_trainer_classes(read(root / "src/battle_main.c"))
    trainer_pics = parse_trainer_pics(read(data / "graphics/trainers.h"))
    encounters = parse_wild_encounters(read(data / "wild_encounters.json"))
    if not encounters:
        warn("wild_encounters.json yielded nothing; encounter tables omitted")

    # Track A3. One record per map: its own header and events, the layout it
    # draws, and the trainer each of its script labels battles with.
    layouts = parse_layouts(read(root / "data/layouts/layouts.json"))
    maps: dict[str, dict] = {}
    map_root = root / "data/maps"
    # Track A4: the game's own words, gathered as the maps are read. The
    # shared corpus first, then each map's own script file, which may both
    # define text and name the battles that use it.
    texts: dict[str, str] = {}
    for p in sorted((root / "data/text").glob("*.inc")):
        texts.update(parse_text_labels(read(p)))
    battles: dict[str, list[str]] = {}
    gifts: dict[str, set[str]] = {}
    for d in (sorted(p for p in map_root.iterdir() if p.is_dir())
              if map_root.is_dir() else []):
        rec = parse_map_json(read(d / "map.json"))
        if not rec:
            continue
        script_text = read(d / "scripts.inc")
        rec["dir"] = d.name
        rec["scripts"] = parse_script_trainers(script_text)
        own_texts = parse_text_labels(script_text)
        # The badge line lives in this same file, so the gym is read here
        # while its own words are in hand rather than after the corpus is
        # merged and the label could belong to anybody.
        rec["gym"] = parse_gym(script_text, own_texts)
        rec["checks"] = parse_progress_checks(script_text)
        texts.update(own_texts)
        battles.update(parse_trainerbattles(script_text))
        for item in parse_giveitems(script_text):
            gifts.setdefault(item, set()).add(rec["id"])
        maps[rec["id"]] = rec
    for p in sorted((root / "data/scripts").glob("*.inc")):
        shared = read(p)
        texts.update(parse_text_labels(shared))
        battles.update(parse_trainerbattles(shared))
    # A trainer's own lines, resolved through the battle macro that names
    # them. Unresolvable labels are dropped, never invented.
    for const, labels in battles.items():
        tr = trainers.get(const)
        if not tr:
            continue
        tr["lines"] = [game_string(texts[lab]) for lab in labels
                       if lab in texts]
    by_prefix = group_texts(texts)
    for rec in maps.values():
        rec["text"] = [(lab, game_string(raw))
                       for lab, raw in by_prefix.get(rec["dir"], [])]
    for rec in maps.values():
        # The terrain itself, as a digest: comparing two maps' block data is
        # how "this place was redrawn" becomes a fact rather than a feeling,
        # and a digest says it without carrying a million numbers around.
        lay = layouts.get(rec["layout"]) or {}
        blocks = root / (lay.get("blockdata_filepath") or "")
        rec["terrain"] = (hashlib.sha1(blocks.read_bytes()).hexdigest()[:12]
                          if blocks.is_file() else "")
        rec["size"] = (lay.get("width"), lay.get("height"))
        rec["encounters"] = (encounters.get(rec["id"]) or {}).get("methods") or {}
    # The SECONDARY tilesets incbin from src/data/tilesets/graphics.h; the
    # primary ones (general, building, ...) live over in src/graphics.c.
    # Both are read, because a map needs one of each.
    tileset_dirs = parse_tileset_paths(
        read(data / "tilesets/graphics.h") + read(root / "src/graphics.c"),
        read(data / "tilesets/metatiles.h") + read(root / "src/graphics.c"),
        read(data / "tilesets/headers.h"))
    fieldmap = parse_defines_int(read(root / "include/fieldmap.h"),
                                 FIELDMAP_DEFAULTS)
    mapgrid = parse_defines_int(read(root / "include/global.fieldmap.h"),
                                MAPGRID_DEFAULTS)

    # Resolve learnset references onto each species so diffs compare MOVES,
    # not symbol names.
    for sp in species.values():
        ref = sp.get("levelUpLearnset")
        if ref and ref in lvl:
            sp["levelUpMoves"] = lvl[ref]
        elif ref:
            sp["levelUpMoves"] = None
        tref = sp.get("teachableLearnset")
        if tref and tref in teach:
            sp["teachableMoves"] = sorted(set(teach[tref]))
    return {"species": species, "moves": moves, "chart": chart,
            "type_order": order, "dex": dex, "sprite_dirs": sprite_dirs,
            "abilities": abilities, "items": items, "item_order": item_order,
            "trainers": trainers, "trainer_classes": classes,
            "trainer_pics": trainer_pics, "encounters": encounters,
            "maps": maps, "layouts": layouts, "tileset_dirs": tileset_dirs,
            "fieldmap": fieldmap, "mapgrid": mapgrid, "gifts": gifts}


# ------------------------------------------------------------ sprites

def png_size(path: Path) -> tuple[int, int] | None:
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", head[16:24])
    except OSError:
        return None


def copy_png_index0_transparent(src: Path, dst: Path):
    """Copy a sprite PNG, making palette index 0 transparent.

    The GBA hardware never draws palette slot 0 -- the magenta/green
    backdrop in the repo's PNGs is that slot made visible. For an indexed
    (color type 3) PNG without a tRNS chunk, inserting `tRNS = 00` after
    PLTE applies the exact rule the game applies. Anything else is copied
    unchanged.
    """
    import zlib
    data = src.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        dst.write_bytes(data)
        return
    color_type = data[25] if len(data) > 25 else None
    if color_type != 3 or b"tRNS" in data[:2048]:
        dst.write_bytes(data)
        return
    out, i = [data[:8]], 8
    inserted = False
    while i + 8 <= len(data):
        length = struct.unpack(">I", data[i:i + 4])[0]
        ctype = data[i + 4:i + 8]
        chunk = data[i:i + 12 + length]
        out.append(chunk)
        if ctype == b"PLTE" and not inserted:
            trns = b"\x00"
            out.append(struct.pack(">I", len(trns)) + b"tRNS" + trns
                       + struct.pack(">I", zlib.crc32(b"tRNS" + trns)))
            inserted = True
        i += 12 + length
    dst.write_bytes(b"".join(out))


def sprite_dir(graphics: Path, const: str) -> Path | None:
    """SPECIES_VENUSAUR_MEGA -> graphics/pokemon/venusaur/mega, found by
    trying every underscore->slash split, fewest directories first."""
    parts = const[len("SPECIES_"):].lower().split("_")
    n = len(parts)
    cands = []
    for mask in range(1 << max(0, n - 1)):
        segs, cur = [], [parts[0]]
        for i in range(1, n):
            if mask & (1 << (i - 1)):
                segs.append("_".join(cur))
                cur = [parts[i]]
            else:
                cur.append(parts[i])
        segs.append("_".join(cur))
        cands.append((len(segs), "/".join(segs)))
    for _, rel in sorted(cands):
        d = graphics / rel
        if d.is_dir() and ((d / "icon.png").is_file()
                           or (d / "front.png").is_file()
                           or (d / "anim_front.png").is_file()):
            return d
    return None


# ------------------------------------------------------------ build health

# Track B1 (dex-site-requirements.md §6.1). Everything below is READ, never
# asserted: file times, a git log line, the game's own verify specs, a
# directory count. Nothing here is a promise about what a number means --
# the dashboard states what it found and lets the arithmetic speak.

# Where a fork's own source lives. The backup-staleness check compares the
# newest file under these against the patch's own mtime, so build/ (which
# every build touches) is deliberately not among them.
SOURCE_DIRS = ("src", "data", "graphics", "include", "asm")

# ...and WHICH files count. A pokeemerald build writes generated files back
# INTO the source tree -- gbagfx's `*.4bpp`/`*.lz`/`*.gbapal`, mapjson's
# header.inc/events.inc/connections.inc -- so "the newest file in the tree"
# counted naively reports every successful build as unsaved work. Two
# authorities on which half of the tree a human wrote already exist and are
# used rather than restated: export_hack.py's GENERATED (what the backup
# patch itself refuses to carry) and the ENGINE's own .gitignore (what
# upstream says its build produces). Neither is guessed at here, and if one
# grows a pattern this picks it up for free.
try:
    from export_hack import GENERATED as _EXPORT_GENERATED
except ImportError:                                  # pragma: no cover
    _EXPORT_GENERATED = ["build", ".git", "*.4bpp", "*.lz", "*.gbapal",
                         "*.1bpp", "events.inc", "header.inc",
                         "connections.inc", "groups.inc", "headers.inc",
                         "layouts.inc", "layouts_table.inc", "map_groups.h",
                         "layouts.h", "map_group_count.h"]


def generated_patterns(engine: Path | None = None) -> tuple[list[str], list[str]]:
    """(basename patterns, relative-path patterns). A .gitignore line with a
    slash in it addresses a path; everything else addresses a name."""
    names, paths = list(_EXPORT_GENERATED), []
    if engine:
        try:
            lines = (engine / ".gitignore").read_text(
                encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            line = line.rstrip("/").lstrip("/")
            (paths if "/" in line else names).append(line)
    return names, paths


def is_generated(rel: str, name: str, pats) -> bool:
    names, paths = pats
    return (any(fnmatch.fnmatch(name, p) for p in names)
            or any(fnmatch.fnmatch(rel, p) for p in paths))


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit}{'' if n == 1 else 's'} ago"


def human_age(seconds: float) -> str:
    """A file's age in the coarsest honest unit. Negative ages (a file
    stamped in the future, which a restored backup really does produce)
    read as "just now" rather than as a nonsense negative."""
    s = int(seconds)
    if s < 45:
        return "just now"
    for unit, size, roll in (("minute", 60, 60), ("hour", 3600, 24),
                             ("day", 86400, 61)):
        n = max(1, round(s / size))
        if n < roll:
            return _plural(n, unit)
    return _plural(round(s / 2629800), "month")


def human_size(n: int) -> str:
    for unit, size in (("MiB", 1 << 20), ("KiB", 1 << 10)):
        if n >= size:
            return f"{n / size:.1f} {unit}"
    return f"{n} B"


def stat_file(path: Path) -> dict | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return {"path": str(path), "name": path.name, "size": st.st_size,
            "mtime": st.st_mtime}


# A restored tree can put tens of thousands of files past the cutoff. The
# byte-compare below is what makes the reading honest, and it is bounded so
# a pathological tree costs seconds, not minutes; when the bound bites, the
# page says the number is a floor rather than pretending it is exact.
COMPARE_CAP = 4000


def survey_source(fork: Path, engine: Path | None, since: float | None,
                  pats=None) -> dict:
    """Which of the fork's own files have been touched since `since` -- and
    of those, which are actually THIS GAME'S, i.e. differ from the pinned
    engine's copy of the same path.

    Both halves are needed. A fork has no git of its own (HACK_MANIFEST.json
    says as much), so mtimes are the only reading available; but a build
    writes generated files back into the tree and a restore re-stamps the
    whole thing, and either would otherwise read as unsaved work. A file
    byte-identical to stock is not this game's work no matter how fresh its
    timestamp, so the comparison against the engine is what turns a
    timestamp into a fact."""
    pats = pats or generated_patterns(engine)
    total, touched, own, compared = 0, 0, [], 0
    for name in SOURCE_DIRS:
        root = fork / name
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            here = os.path.relpath(dirpath, fork)
            dirnames[:] = [d for d in dirnames
                           if d not in (".git", "build")
                           and not is_generated(f"{here}/{d}", d, pats)]
            for fn in filenames:
                rel = os.path.normpath(os.path.join(here, fn))
                if fn.startswith(".") or is_generated(rel, fn, pats):
                    continue
                p = Path(dirpath) / fn
                try:
                    mt = p.stat().st_mtime
                except OSError:
                    continue
                total += 1
                if since is None or mt <= since:
                    continue
                touched += 1
                if engine and compared < COMPARE_CAP:
                    compared += 1
                    base = engine / rel
                    try:
                        if base.is_file() and filecmp.cmp(str(p), str(base),
                                                          shallow=False):
                            continue        # identical to stock: not ours
                    except OSError:
                        pass
                own.append({"file": rel, "mtime": mt})
    own.sort(key=lambda r: r["mtime"], reverse=True)
    return {"total": total, "touched": touched, "own": own,
            "capped": compared >= COMPARE_CAP}


_PATCH_TARGET_RE = re.compile(r"^\+\+\+ (\S+)", re.M)
_PATCH_BINARY_RE = re.compile(r"^Binary files \S+ and (\S+) differ$", re.M)


def backed_up_paths(patch: Path, assets: Path, fork_name: str) -> set[str]:
    """Every fork path the backup actually carries: the paths named by the
    patch's own file headers, plus the binary sources copied beside it.
    A file this game owns that appears in neither is not backed up at all --
    which, unlike a timestamp, is not a matter of interpretation."""
    found = set()

    def strip(p: str) -> str:
        parts = p.split("/")
        if len(parts) > 2 and parts[1] == fork_name:
            return "/".join(parts[2:])
        return "/".join(parts[1:]) if len(parts) > 1 else p

    try:
        text = patch.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return found
    for rx in (_PATCH_TARGET_RE, _PATCH_BINARY_RE):
        for m in rx.finditer(text):
            found.add(strip(m.group(1)))
    root = assets / fork_name
    if root.is_dir():
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                found.add(os.path.relpath(os.path.join(dirpath, fn), root))
    return found


def read_marker(workspace: Path, game: str) -> dict:
    """What the last export PROVED, file by file, if it left the note.

    §9.7's ambiguity in one sentence: a file stamped newer than the patch is
    either an edit that is not backed up or a tree restored out of that same
    patch, and a clock cannot tell those apart. A content digest can. This
    reads the digests the exporter wrote; an absent or unreadable marker is
    an absence, and the dashboard falls back to saying it cannot tell --
    which is what it said before this existed."""
    try:
        d = json.loads((workspace / "patches" /
                        f"{game}.verified.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d.get("files") or {} if isinstance(d, dict) else {}


def unexported(fork: Path, marker: dict, candidates) -> list[dict] | None:
    """Of files stamped newer than the patch, the ones whose CONTENT differs
    from what the export proved. None when there is no marker to check
    against -- the caller must then hedge, rather than report zero."""
    if not marker:
        return None
    moved = []
    for rec in candidates:
        want = marker.get(rec["file"])
        try:
            got = hashlib.sha256(
                (fork / rec["file"]).read_bytes()).hexdigest()
        except OSError:
            got = None
        # Not in the marker at all is handled as "not carried" elsewhere;
        # here only a real content difference counts.
        if want and got and want != got:
            moved.append(rec)
    return moved


def git_head(repo: Path) -> dict | None:
    """The workspace repo's HEAD. The FORK has no git (it is a fork, not a
    clone), so this is always the game repo around it -- which is what
    "which commit is this site standing on" actually means."""
    def run(*args):
        return subprocess.run(("git", "-C", str(repo)) + args,
                              capture_output=True, text=True, timeout=20)
    try:
        head = run("log", "-1", "--format=%h\x1f%cs\x1f%ct\x1f%s")
        if head.returncode != 0:
            return None
        parts = (head.stdout.rstrip("\n").split("\x1f") + ["", "", "", ""])[:4]
        sha, date, epoch, subject = parts
        dirty = run("status", "--porcelain")
        n_dirty = (len([l for l in dirty.stdout.splitlines() if l.strip()])
                   if dirty.returncode == 0 else None)
        branch = run("rev-parse", "--abbrev-ref", "HEAD")
        return {"sha": sha, "date": date, "subject": subject,
                "epoch": int(epoch) if epoch.isdigit() else None,
                "dirty": n_dirty,
                "branch": branch.stdout.strip() if branch.returncode == 0 else ""}
    except (OSError, subprocess.SubprocessError):
        return None


def read_specs(workspace: Path) -> dict:
    """The game's own checks, counted -- and, more usefully, counted for
    whether they can RUN here: a spec that resumes from a savestate is dead
    weight on a machine where that state was never generated (savestates
    are gitignored). Reporting every check as if it ran when none of them
    could is exactly the "skipped and passed look identical" failure the
    build ritual forbids, so the dashboard separates the two numbers."""
    out = {"specs": 0, "asserts": 0, "needs_state": 0, "runnable": 0,
           "missing_states": [], "unreadable": 0}
    vdir = workspace / "verify"
    if not vdir.is_dir():
        return out
    saves = workspace / "saves"
    for path in sorted(vdir.glob("*.json")):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out["unreadable"] += 1
            continue
        if not isinstance(spec, dict) or "assert" not in spec:
            continue
        out["specs"] += 1
        asserts = spec.get("assert")
        out["asserts"] += len(asserts) if isinstance(asserts, list) else 0
        state = spec.get("savestate")
        if state:
            out["needs_state"] += 1
            if (saves / str(state)).is_file():
                out["runnable"] += 1
            elif str(state) not in out["missing_states"]:
                out["missing_states"].append(str(state))
        else:
            out["runnable"] += 1
    return out


def count_maps(root: Path) -> set[str]:
    """Map folder names under data/maps/. A directory listing is the whole
    of what Track A3 hasn't built yet -- it says how many maps exist and
    which ones are this game's, and claims nothing about their contents."""
    d = root / "data/maps"
    if not d.is_dir():
        return set()
    return {p.name for p in d.iterdir() if p.is_dir() and (p / "map.json").is_file()}


def read_manifest(fork: Path) -> dict:
    """new_hack.py stamps HACK_MANIFEST.json when it forks the engine: what
    it forked, from which commit, when."""
    path = fork / "HACK_MANIFEST.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def collect_health(workspace: Path, fork: Path, engine: Path, game: str,
                   now: float) -> dict:
    """Everything the dashboard reports, gathered in one pass so the render
    is pure formatting."""
    rom = None
    for cand in (workspace / f"{game}.gba", fork / "pokeemerald.gba"):
        rom = stat_file(cand)
        if rom:
            break
    fork_maps, stock_maps = count_maps(fork), count_maps(engine)
    # dex-site-requirements.md §9.3: trainers.h is generated from
    # trainers.party by trainerproc, and the site reads the generated file.
    # If the source is the newer of the two, the trainers pages are showing
    # a team the build no longer compiles.
    party_src = stat_file(fork / "src/data/trainers.party")
    party_out = stat_file(fork / "src/data/trainers.h")
    trainers_stale = bool(party_src and party_out
                          and party_src["mtime"] > party_out["mtime"])
    manifest = read_manifest(fork)
    patch = stat_file(workspace / "patches" / f"{game}.patch")
    # Everything the survey has to say is about work done since the last
    # thing that captured the tree -- whichever of the backup and the ROM
    # happened first.
    stamps = [r["mtime"] for r in (patch, rom) if r]
    return {
        "now": now,
        "rom": rom,
        "patch": patch,
        "source": survey_source(fork, engine, min(stamps) if stamps else None,
                                generated_patterns(engine)),
        "backed_up": (backed_up_paths(workspace / "patches" / f"{game}.patch",
                                      workspace / "patches/assets", game)
                      if patch else set()),
        "git": git_head(workspace),
        "marker": read_marker(workspace, game),
        "fork_root": fork,
        "checks": read_specs(workspace),
        "maps": {"fork": len(fork_maps), "stock": len(stock_maps),
                 "new": sorted(fork_maps - stock_maps)},
        "base_commit": (manifest.get("base_commit") or "")[:8],
        "forked": manifest.get("created") or "",
        "trainers_stale": trainers_stale,
    }


# ------------------------------------------------------------ the dev log

# Track B2 (dex-site-requirements.md §6.2). Diffing this tree against stock
# is the site's oldest trick; a HISTORY of those diffs is the one thing a
# tree cannot be asked for, because a tree only ever shows its present
# state. So the history is kept: one small file per green build, git-TRACKED
# in the game repo beside the checks and the patch, because it is the only
# part of this site that could not be regenerated if it were lost.
#
# Still nothing authored. Every entry is a snapshot of the same derivation
# the rest of the site runs on, taken at the moment a build went green, and
# every sentence the page writes is arithmetic BETWEEN two snapshots.

DEVLOG_DIR = "devlog"
DEVLOG_VERSION = 1

# Per category, per entry. A hack that has rewritten six hundred species has
# said what it is; past that the counts stay exact and the naming stops, so
# one entry stays kilobytes rather than megabytes.
DEVLOG_CAP = 600

DEVLOG_README = """\
# devlog

One file per green build, written by the harness's dex generator
(`make_dex.py --record`) and read back by the site's Dev log page.

Each entry is a snapshot of what this game had added or altered relative to
the pinned stock engine at the moment that build went green: counts, one-line
summaries, and a short fingerprint per entry so the next build can tell which
of them moved. No assets, no prose, a few kilobytes each.

**These are tracked in git on purpose.** Everything else the site shows is
re-derived from the tree on every run. This is the only part that could not
be, because a tree only ever shows its present state.
"""


def devlog_digest(entity: dict, fields) -> str:
    """A short, stable fingerprint of exactly the fields the diff compares.

    It fingerprints the ENTITY, never its diff: a new species has no diff at
    all, so a diff-based fingerprint would be blind to every edit after the
    one that introduced it."""
    payload = json.dumps([entity.get(k) for k, _ in fields],
                         sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def devlog_path(workspace: Path) -> Path:
    return workspace / DEVLOG_DIR


def read_devlog(workspace: Path) -> list[dict]:
    """Every recorded build, oldest first. An entry that will not parse is
    skipped, never fatal -- one bad file must not cost a build its site."""
    out = []
    d = devlog_path(workspace)
    if not d.is_dir():
        return out
    for path in sorted(d.glob("*.json")):
        try:
            e = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(e, dict) and isinstance(e.get("categories"), dict):
            e["file"] = path.name
            out.append(e)
    out.sort(key=lambda e: (e.get("at") or 0, e.get("file") or ""))
    return out


def devlog_content(entry: dict) -> str:
    """What an entry says about the GAME, with everything about the moment it
    was taken stripped out. Two builds of the same tree say the same thing
    even though their clocks, their ROM and their commit all differ."""
    return json.dumps(entry.get("categories") or {}, sort_keys=True,
                      default=str)


def record_devlog(workspace: Path, entry: dict,
                  history: list[dict]) -> tuple[Path | None, str]:
    """Append one entry, unless the newest one already says the same thing.

    A green build that changed no data is a real build and a boring record:
    writing it would grow the history without growing what it knows. Which
    of the two happened is returned in words rather than left to be guessed
    from an exit code."""
    if history and devlog_content(history[-1]) == devlog_content(entry):
        when = history[-1].get("date") or history[-1].get("file") or "earlier"
        return None, ("nothing this game owns has changed since the build "
                      f"recorded {when} -- no entry written")
    d = devlog_path(workspace)
    d.mkdir(parents=True, exist_ok=True)
    readme = d / "README.md"
    if not readme.exists():
        readme.write_text(DEVLOG_README, encoding="utf-8")
    stamp = time.strftime("%Y%m%d-%H%M%S",
                          time.localtime(entry.get("at") or time.time()))
    path, n = d / f"{stamp}.json", 2
    while path.exists():
        path, n = d / f"{stamp}-{n}.json", n + 1
    path.write_text(json.dumps(entry, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    entry["file"] = path.name
    return path, f"recorded {path.name}"


def devlog_delta(old: dict | None, new: dict) -> dict:
    """What moved between two snapshots, per category: entries that STARTED
    differing from stock, entries that were already differing and now differ
    differently, and entries that stopped.

    A category's own total is carried too, because that is the only reading
    that catches a stock entry deleted outright -- it was never in either
    snapshot's list, having never differed from stock while it existed."""
    out = {}
    for cat, cur in (new.get("categories") or {}).items():
        was = ((old or {}).get("categories") or {}).get(cat) or {}
        prev, now = was.get("entries") or {}, cur.get("entries") or {}
        added = [k for k in now if k not in prev]
        edited = [k for k in now if k in prev
                  and now[k].get("digest") != prev[k].get("digest")]
        gone = [k for k in prev if k not in now]
        moved = was.get("total") is not None and was["total"] != cur.get("total")
        # Deletions, by name at last. A snapshot from before this was
        # recorded has no `removed` key at all, and an absent list is not
        # an empty one -- treating it as empty would report every deletion
        # the game ever made as if it had happened at this build. So the
        # comparison is only made when both snapshots kept the list.
        deleted = []
        if isinstance(was.get("removed"), list) and \
                isinstance(cur.get("removed"), list):
            before = set(was["removed"])
            deleted = [k for k in cur["removed"] if k not in before]
        if added or edited or gone or moved or deleted:
            out[cat] = {"added": added, "edited": edited, "gone": gone,
                        "deleted": deleted,
                        "from": was.get("total"), "to": cur.get("total"),
                        "partial": bool(cur.get("capped") or was.get("capped"))}
    return out


def human_delta(n: int) -> str:
    """A signed byte cost. Zero is not a cost and reads as nothing at all."""
    if not n:
        return ""
    return ("+" if n > 0 else "−") + human_size(abs(n))


# ------------------------------------------------------- the design doc

# Track B3 (dex-site-requirements.md §6.3 and §9.4). The roadmap is the one
# section of this site that cannot be derived, because it describes code
# that does not exist yet -- so it is READ FROM THE DESIGN DOC, and §9.4's
# question ("what is the lightest markup a generator can read out of a doc a
# human still writes normally?") turned out to have already been answered:
# the doc has a convention, it is load-bearing, and its own template says so
# in as many words -- "Machine-read fields keep the exact `- **Key:** value`
# form on one line -- do not reformat them." Nothing new is invented here.
# Every shape below is one the design doc already commits to:
#
#   design/index.md    ## Phase, ## Locked decisions, ## Next actions,
#                      ## Open questions, and the Identity key/value block
#   design/scope.md    ## Slice plan -> ### Slice N: title, each with a
#                      `- **Status:** planned | building | done | cut` and
#                      the Soul / Build / Fake / Failure-condition fields;
#                      plus ## Cut list
#
# What the site adds is not markup. It is the reading a human does not do:
# whether the doc still agrees with itself, and whether it still agrees with
# the tree (§6.3's "worth a build-time warning, not silent acceptance").

DESIGN_STATUSES = ("planned", "building", "done", "cut")

# How far off the route a place can be and still count as hanging off it.
# See route_thread() for why this is bounded at all.
POCKET_HOPS = 2

# Every heading this reads for. Matched by CONTAINMENT, case-folded, because
# a doc under a hard line budget writes its headings to fit rather than to
# be parsed.
DESIGN_HEADINGS = ("identity", "phase", "locked decisions", "open questions",
                   "next actions", "slice plan", "cut list", "file map",
                   "door classification", "scope math", "premise",
                   "route order", "art brief")

_MD_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*?)\s*#*$")
_MD_FIELD_RE = re.compile(r"^\s*[-*]\s+\*\*(.+?):?\*\*:?\s*(.*)$")
_MD_SLICE_RE = re.compile(r"^\s*Slice\s+([\d.]+)\s*[:—-]\s*(.*)$", re.I)
_MD_NUMBERED_RE = re.compile(r"^(\d+)\.\s+(.*)$")
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_CODE_RE = re.compile(r"`([^`]*)`")


def clip(s: str, n: int) -> str:
    """Quoting someone's words back to them, shortened at a word rather than
    mid-syllable."""
    s = md_plain(s)
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return (cut or s[:n]).rstrip(" ,;:—-") + "…"


def md_plain(s: str) -> str:
    """Markdown emphasis stripped down to the words. The site has its own
    typography; the doc's asterisks are not part of what it said."""
    s = _MD_LINK_RE.sub(r"\1", s)
    s = _MD_CODE_RE.sub(r"\1", s)
    s = _MD_BOLD_RE.sub(r"\1", s)
    return re.sub(r"\s+", " ", s.replace("~~", "").replace("*", "")).strip()


def split_sections(text: str) -> list[dict]:
    """-> [{level, title, raw, body}], with one wrinkle the real docs forced.

    A heading line can carry TWO sections, because a doc held to a hard line
    budget will squash them ("## Open questions (max 5) -- none. ## Next
    actions (max 3)"). The body then belongs to the LAST section named on
    that line, and each earlier one keeps the words that followed its own
    name -- which, in the case that forced this, IS its whole answer."""
    out: list[dict] = []
    body: list[str] = []
    for line in text.splitlines():
        m = _MD_HEADING_RE.match(line)
        if not m:
            body.append(line)
            continue
        level, title = len(m.group(1)), m.group(2)
        low = title.lower()
        hits = sorted((low.find(p), p) for p in DESIGN_HEADINGS if p in low)
        if len(hits) > 1:
            for (start, _), (nxt, _) in zip(hits, hits[1:]):
                out.append({"level": level, "raw": "", "body": [],
                            "title": title[start:nxt].strip(" .—-#")})
            title = title[hits[-1][0]:].strip()
        body = []
        out.append({"level": level, "title": title, "raw": line, "body": body})
    return out


def find_section(sections, phrase: str, deep: bool = False) -> list[str]:
    """The body of the first heading whose words contain `phrase`.

    With deep=True the subsections under it come too, headings and all --
    which the slice plan needs, since every slice in it is a heading of its
    own and would otherwise fall outside the section that owns them."""
    for i, s in enumerate(sections):
        if phrase not in s["title"].lower():
            continue
        if not deep:
            return s["body"]
        out = list(s["body"])
        for t in sections[i + 1:]:
            if t["level"] <= s["level"]:
                break
            out.append(t["raw"])
            out.extend(t["body"])
        return out
    return []


def section_title(sections, phrase: str) -> str:
    for s in sections:
        if phrase in s["title"].lower():
            return s["title"]
    return ""


def parse_md_fields(lines) -> dict[str, str]:
    """`- **Key:** value` pairs, with continuation lines folded in. The
    template calls these machine-read and asks that they not be reformatted;
    this is the code that reads them."""
    out, key = {}, None
    for line in lines:
        m = _MD_FIELD_RE.match(line)
        if m:
            key = md_plain(m.group(1)).lower()
            out[key] = md_plain(m.group(2))
        elif key and line.strip() and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + md_plain(line)).strip()
        elif not line.strip():
            key = None
    return out


def parse_md_list(lines) -> list[str]:
    """Bullets or a numbered list, each item folded onto one line. Used for
    next actions and open questions, both of which the doc keeps short by
    rule and long by habit."""
    items: list[str] = []
    for line in lines:
        m = _MD_NUMBERED_RE.match(line.strip()) if line[:1].isdigit() else None
        bullet = re.match(r"^[-*]\s+(.*)$", line.strip())
        if m:
            items.append(md_plain(m.group(2)))
        elif bullet and not _MD_FIELD_RE.match(line):
            items.append(md_plain(bullet.group(1)))
        elif items and line.strip() and line.startswith((" ", "\t")):
            items[-1] = (items[-1] + " " + md_plain(line)).strip()
        elif not line.strip():
            continue
    return [i for i in items if i and i.lower() not in ("none", "none yet",
                                                        "tbd")]


def parse_md_table(lines) -> list[list[str]]:
    """A pipe table's data rows. The header and the dashes under it are
    dropped; nothing else is interpreted."""
    rows = []
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [md_plain(c) for c in s.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    return rows[1:] if rows else []


def parse_slices(lines) -> list[dict]:
    """The slice plan, one entry per `### Slice N: title`.

    The status word is taken as the first word of the Status field that the
    doc's OWN vocabulary recognises; anything else is kept verbatim and
    reported as unrecognised rather than guessed at. A real doc writes
    "**done** 2026-07-26 -- build record ..." and "BUILT 2026-07-30,
    verified, **NOT visually finished**", and only one of those two is a
    word the plan defined."""
    slices, cur = [], None
    for line in lines:
        head = _MD_HEADING_RE.match(line)
        if head:
            m = _MD_SLICE_RE.match(md_plain(head.group(2)))
            if m:
                cur = {"n": m.group(1), "title": m.group(2).strip(),
                       "lines": []}
                slices.append(cur)
            elif cur and len(head.group(1)) <= 3:
                cur = None          # a heading at slice level ends the plan
            continue
        if cur is not None:
            cur["lines"].append(line)
    for s in slices:
        fields = parse_md_fields(s.pop("lines"))
        raw = fields.get("status", "")
        words = md_plain(raw).replace(",", " ").split()
        word = next((w.lower() for w in words
                     if w.lower().strip(".:") in DESIGN_STATUSES), "")
        s["status"] = word.strip(".:") if word else ""
        s["status_raw"] = raw
        for key in ("soul", "build", "fake", "do not fake",
                    "failure condition", "success criteria",
                    "hardware budget"):
            s[key.replace(" ", "_")] = next(
                (v for k, v in fields.items() if k.startswith(key)), "")
    return slices


_DASH_RE = re.compile(r"\s+(?:—|–|--)\s+|\s+-\s+")


def split_dash(s: str) -> tuple[str, str]:
    """"Name — the sentence about it" -> ("Name", "the sentence about it").
    An em dash, an en dash, two hyphens or a spaced hyphen; a line with none
    of them is all head and no tail."""
    m = _DASH_RE.search(s)
    return (s[:m.start()].strip(), s[m.end():].strip()) if m else (s.strip(), "")


def parse_route(lines) -> list[dict]:
    """The `## Route order` section: numbered story beats, each naming the
    places it touches in play order (dex-site-requirements.md §11.2).

    Two forms, both read, because the compact one is what a spine looks like
    before anyone has written a word of prose:

        1. **The parcel** — Oak's errand.
           - **Places:** Pallet Town, Route 1, Viridian City

        1. **The parcel** — Oak's errand.
           - **Gate:** the lab door is open
           - Pallet Town — three houses and a lab.
           - Route 1

    A bullet that is a `**Key:** value` field is a field; every other bullet
    is a place, and whatever follows its dash is that place's own sentence --
    which is also the curated note C2 wanted, written once."""
    beats: list[dict] = []
    for line in lines:
        num = _MD_NUMBERED_RE.match(line.strip())
        if num and not line.startswith((" ", "\t")):
            title, sentence = split_dash(md_plain(num.group(2)))
            beats.append({"n": num.group(1), "title": title,
                          "sentence": sentence, "gate": "", "places": []})
            continue
        if not beats:
            continue
        beat = beats[-1]
        field = _MD_FIELD_RE.match(line)
        if field:
            key, value = md_plain(field.group(1)).lower(), md_plain(field.group(2))
            if key.startswith("place"):
                for name in value.split(","):
                    if name.strip():
                        beat["places"].append({"name": name.strip(), "note": ""})
            else:
                beat[key] = value
            continue
        bullet = re.match(r"^\s+[-*]\s+(.*)$", line)
        if bullet:
            name, note = split_dash(md_plain(bullet.group(1)))
            if name:
                beat["places"].append({"name": name, "note": note})
        elif line.strip() and line.startswith((" ", "\t")):
            # A continuation line belongs to the last thing that opened.
            target = beat["places"][-1] if beat["places"] else beat
            key = "note" if beat["places"] else "sentence"
            target[key] = (target.get(key, "") + " " + md_plain(line)).strip()
    return [b for b in beats if b["places"] or b["title"]]


_BRIEF_HEAD_RE = re.compile(r"^\s*(.*?)\s*(?:\((.*)\))?\s*$")


def parse_species_briefs(lines) -> list[dict]:
    """The design doc's per-species art briefs (C2's species half).

    Same rule as everywhere else: no new markup. `art.md` already carries a
    briefs section with one `### Name (SPECIES_CONST, dexno)` heading per
    species and the canonical description as a BLOCKQUOTE under it -- the
    doc's own rule is that this text is pasted verbatim into every
    generation that touches the species, which is exactly what makes it the
    canonical prose about that creature.

    Only the blockquote is taken. The rest of a brief's section is process
    -- pixel targets, "REDRAW PENDING", what a regeneration got wrong --
    which is the author talking to themselves, not about the animal."""
    briefs, cur = [], None
    for line in lines:
        head = _MD_HEADING_RE.match(line)
        if head:
            name, paren = _BRIEF_HEAD_RE.match(md_plain(head.group(2))).groups()
            const = None
            for token in re.findall(r"\bSPECIES_[A-Z0-9_]+\b", paren or ""):
                const = token
            cur = {"name": name, "const": const, "lines": []}
            briefs.append(cur)
            continue
        if cur is not None and line.lstrip().startswith(">"):
            cur["lines"].append(md_plain(line.lstrip().lstrip(">")))
    out = []
    for b in briefs:
        text = " ".join(x for x in b.pop("lines") if x).strip()
        if text:
            out.append(dict(b, text=text))
    return out


def load_design(workspace: Path) -> dict:
    """Everything the roadmap reads, gathered from the design doc. Every
    absence is an absence: a game with no design doc gets a page that says
    so, not a page of invented plans."""
    def read_doc(name):
        try:
            return (workspace / "design" / name).read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            return ""

    index_txt, scope_txt = read_doc("index.md"), read_doc("scope.md")
    narrative_txt, art_txt = read_doc("narrative.md"), read_doc("art.md")
    index, scope = split_sections(index_txt), split_sections(scope_txt)
    narrative, art = split_sections(narrative_txt), split_sections(art_txt)
    ident = parse_md_fields(find_section(index, "identity"))
    phase = parse_md_fields(find_section(index, "phase"))
    questions = parse_md_list(find_section(index, "open questions"))
    # A heading that answered itself inline ("Open questions -- none.") has
    # its answer in the heading, not under it.
    q_title = section_title(index, "open questions")
    return {
        "found": bool(index_txt or scope_txt),
        "route": parse_route(find_section(narrative, "route order", deep=True)),
        "briefs": parse_species_briefs(find_section(art, "art brief", deep=True)),
        "name": ident.get("name", ""),
        "pitch": ident.get("pitch", ""),
        "loop": ident.get("core loop", ""),
        "archetype": ident.get("archetype", ""),
        "phase": phase.get("phase", ""),
        "entered": phase.get("entered", ""),
        "decisions": parse_md_table(find_section(index, "locked decisions")),
        "next": parse_md_list(find_section(index, "next actions")),
        "questions": questions,
        "questions_inline": md_plain(q_title),
        "slices": parse_slices(find_section(scope, "slice plan", deep=True)),
        "cuts": parse_md_table(find_section(scope, "cut list")),
    }


def design_contradictions(design: dict, owned: set[str]) -> list[str]:
    """Where the doc stops agreeing with itself, or with the tree.

    §6.3 asked for a build-time warning rather than silent acceptance. Three
    readings are available without guessing, and all three fire on real
    documents:

    1. The plan's own stated rule is that slices land IN ORDER. A slice still
       marked planned sitting above one marked done breaks that rule, and is
       what a stale status field actually looks like.
    2. The plan defines its own four status words. A fifth one is not a
       status the plan can be read against.
    3. A slice not yet built that names something the tree already contains
       is describing work that has happened."""
    out = []
    slices = design.get("slices") or []
    done_at = [i for i, s in enumerate(slices) if s["status"] == "done"]
    last_done = max(done_at) if done_at else -1
    for i, s in enumerate(slices):
        name = f"Slice {s['n']}"
        if s["status"] in ("planned", "building") and i < last_done:
            out.append(f"{name} is marked {s['status']}, but slices below it "
                       "are marked done and the plan's own rule is that they "
                       "land in order. One of the two is out of date.")
        if not s["status"] and s["status_raw"]:
            out.append(f"{name}'s status reads “{clip(s['status_raw'], 70)}”, "
                       "which is not one of the four words the plan defines, "
                       "so this page cannot say where it stands.")
        if s["status"] in ("planned", "cut"):
            named = {c for c in _CONST_IN_PROSE_RE.findall(
                " ".join(str(v) for v in s.values())) if c in owned}
            if named:
                out.append(f"{name} is marked {s['status']}, but the tree "
                           "already contains "
                           + ", ".join(sorted(named)[:4])
                           + ", which it names.")
    return out


def doubted_slices(design: dict, owned: set[str]) -> set[int]:
    """Indices of slices whose "not done yet" the doc itself argues with.

    The same two readings design_contradictions() prints, asked as a
    question with an answer instead of a sentence: is there reason to think
    this slice has already been built? The builder's roadmap prints the
    doubt beside the slice and shows both. The publish teaser cannot print
    doubt without printing status, so it withholds instead -- a promise the
    generator half-believes is already kept is the one kind of promise a
    published page must not make. Failing silent here is the safe
    direction: the cost is a teaser that is too short, and the cost of the
    other direction is advertising finished work as still to come."""
    slices = design.get("slices") or []
    done_at = [i for i, s in enumerate(slices) if s["status"] == "done"]
    last_done = max(done_at) if done_at else -1
    doubted = set()
    for i, s in enumerate(slices):
        if s["status"] in ("planned", "building") and i < last_done:
            doubted.add(i)          # the plan says slices land in order
        if s["status"] == "planned" and {
                c for c in _CONST_IN_PROSE_RE.findall(
                    " ".join(str(v) for v in s.values())) if c in owned}:
            doubted.add(i)          # it names things the tree already has
    return doubted


_CONST_IN_PROSE_RE = re.compile(
    r"\b(?:SPECIES|MOVE|ABILITY|ITEM|TRAINER|MAP)_[A-Z0-9_]+\b")


# ------------------------------------------------------------ HTML

# Every type chip's (light hue/chroma-tier, dark hue/chroma-tier); four of
# these are pinned to the exact values dex-site-requirements.md's design
# tokens call out (fire, grass, and the ghost/poison + rock/ground pairs it
# deliberately doubles up), the rest generated on the same formula, one hue
# each, per that doc's instruction.
_VIVID = "vivid"
_LOW = "low"
TYPE_COLOR_SPEC = {
    "normal":   (90, _LOW),    "fire":     (45, _VIVID),
    "water":    (228, _VIVID), "electric": (95, _VIVID),
    "grass":    (128, _VIVID), "ice":      (195, _VIVID),
    "fighting": (18, _VIVID),  "poison":   (300, _VIVID),
    "ground":   (65, _LOW),    "flying":   (255, _VIVID),
    "psychic":  (350, _VIVID), "bug":      (108, _VIVID),
    "rock":     (65, _LOW),    "ghost":    (300, _VIVID),
    "dragon":   (288, _VIVID), "dark":     (50, _LOW),
    "steel":    (240, _LOW),   "fairy":    (325, _VIVID),
    "mystery":  (90, _LOW),    "stellar":  (175, _VIVID),
    "none":     (90, _LOW),
}
# fire/grass/poison(=ghost)/rock(=ground) reproduce the doc's exact triples;
# everything else is (formula bg-L, bg-C, text-L, text-C) per tier.
_TYPE_EXACT_LIGHT = {
    "fire": ("0.93 0.05 45", "0.40 0.10 42"),
    "grass": ("0.93 0.035 128", "0.38 0.08 128"),
    "poison": ("0.92 0.04 300", "0.40 0.09 300"),
    "ghost": ("0.92 0.04 300", "0.40 0.09 300"),
    "rock": ("0.92 0.02 70", "0.40 0.03 60"),
    "ground": ("0.92 0.02 70", "0.40 0.03 60"),
}
_TIER_FORMULA_LIGHT = {_VIVID: (0.93, 0.045, 0.40, 0.095), _LOW: (0.91, 0.015, 0.40, 0.025)}
_TIER_FORMULA_DARK = {_VIVID: (0.30, 0.06, 0.86, 0.07), _LOW: (0.28, 0.02, 0.78, 0.03)}


def _type_color_vars() -> str:
    lines = []
    for name, (hue, tier) in TYPE_COLOR_SPEC.items():
        if name in _TYPE_EXACT_LIGHT:
            bg, fg = _TYPE_EXACT_LIGHT[name]
        else:
            bl, bc, fl, fc = _TIER_FORMULA_LIGHT[tier]
            bg, fg = f"{bl} {bc} {hue}", f"{fl} {fc} {hue}"
        lines.append(f"  --type-{name}-bg: oklch({bg}); --type-{name}-fg: oklch({fg});")
    return "\n".join(lines)


def _type_color_vars_dark() -> str:
    lines = []
    for name, (hue, tier) in TYPE_COLOR_SPEC.items():
        bl, bc, fl, fc = _TIER_FORMULA_DARK[tier]
        lines.append(f"  --type-{name}-bg: oklch({bl} {bc} {hue}); "
                     f"--type-{name}-fg: oklch({fl} {fc} {hue});")
    return "\n".join(lines)


def build_css(theme: dict) -> str:
    """Assembles the token system from dex-site-requirements.md: six
    themeable surfaces (from `theme`) plus fixed structure -- typography,
    spacing, chrome, badges, type chips -- identical across every hack
    unless the surfaces above change it. Light values are the doc's
    `oklch()` tokens verbatim; dark values apply its stated transform
    (raise L to ~0.68, drop C ~20%) to the same hues, everywhere that
    transform generalizes."""
    return f"""\
@font-face {{ font-family: 'Newsreader'; font-weight: 400; font-style: normal;
  font-display: swap; src: url('fonts/Newsreader-400.woff2') format('woff2'); }}
@font-face {{ font-family: 'Newsreader'; font-weight: 500; font-style: normal;
  font-display: swap; src: url('fonts/Newsreader-500.woff2') format('woff2'); }}
@font-face {{ font-family: 'IBM Plex Sans'; font-weight: 400; font-style: normal;
  font-display: swap; src: url('fonts/IBMPlexSans-400.woff2') format('woff2'); }}
@font-face {{ font-family: 'IBM Plex Sans'; font-weight: 500; font-style: normal;
  font-display: swap; src: url('fonts/IBMPlexSans-500.woff2') format('woff2'); }}
@font-face {{ font-family: 'IBM Plex Sans'; font-weight: 600; font-style: normal;
  font-display: swap; src: url('fonts/IBMPlexSans-600.woff2') format('woff2'); }}
@font-face {{ font-family: 'IBM Plex Mono'; font-weight: 400; font-style: normal;
  font-display: swap; src: url('fonts/IBMPlexMono-400.woff2') format('woff2'); }}
@font-face {{ font-family: 'IBM Plex Mono'; font-weight: 500; font-style: normal;
  font-display: swap; src: url('fonts/IBMPlexMono-500.woff2') format('woff2'); }}
@font-face {{ font-family: 'IBM Plex Mono'; font-weight: 600; font-style: normal;
  font-display: swap; src: url('fonts/IBMPlexMono-600.woff2') format('woff2'); }}

:root {{
  /* the six themeable surfaces -- dex-site-requirements.md's Theming table */
  --accent: oklch({theme['accent']});
  --accent-2: oklch({theme['accent2']});
  --font-display: {theme['font_display']};
  --radius: {theme['radius']};
  --radius-sm: {theme['radius_sm']};
  --border-w: {theme['border_w']};

  /* fixed tokens -- not themeable */
  --font-body: 'IBM Plex Sans', sans-serif;
  --font-mono: 'IBM Plex Mono', monospace;
  --bg-page: oklch(0.945 0.006 90);
  --bg-surface: oklch(0.99 0.008 80);
  --bg-subtle: oklch(0.965 0.012 85);
  --bg-row-alt: oklch(0.975 0.008 85);
  --ink: oklch(0.25 0.03 55);
  --ink-body: oklch(0.32 0.02 60);
  --ink-muted: oklch(0.48 0.02 60);
  --ink-faint: oklch(0.55 0.02 60);
  --rule: oklch(0.90 0.015 70);
  --rule-soft: oklch(0.94 0.01 70);
  --rule-dashed: oklch(0.78 0.02 70);
  --ok: oklch(0.60 0.10 145);
  --warn: oklch(0.72 0.13 70);
  --badge-new-fg: oklch(0.99 0 0);
  --status-changed-bg: oklch(0.92 0.04 128);
  --status-changed-fg: oklch(0.30 0.04 128);
  --shadow: 0 1px 2px oklch(0.4 0.02 60 / 0.06), 0 12px 32px oklch(0.4 0.02 60 / 0.05);
  --stripe: repeating-linear-gradient(135deg, oklch(0.93 0.02 70) 0 5px, oklch(0.90 0.025 65) 5px 10px);
{_type_color_vars()}
  color-scheme: light dark;
}}

@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ {_dark_tokens()} }} }}
:root[data-theme="dark"] {{ {_dark_tokens()} }}

* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg-page); color: var(--ink-body);
  font: 400 14px/1.5 var(--font-body); }}
a {{ color: inherit; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
h1, h2, h3 {{ font-family: var(--font-display); font-weight: 500; color: var(--ink); }}
""" + _CSS_STATIC


# Fixed structure: no theme values are interpolated below, only var(--...)
# references resolved by the browser -- so this half is a plain string, not
# an f-string, and its literal braces need no escaping.
_CSS_STATIC = """\
/* -- chrome: the slim inner-page bar, shared by every page ------------- */
.bar { display: flex; align-items: center; gap: 14px; padding: 14px 40px;
  background: var(--bg-surface); border-bottom: var(--border-w) solid var(--rule); }
.bar .logo { width: 26px; height: 26px; border-radius: var(--radius-sm);
  background: var(--accent); flex: none; }
.bar .word { font-family: var(--font-display); font-size: 19px; color: var(--ink); }
.bar nav { display: flex; gap: 20px; margin-left: 24px; font-size: 13px;
  color: var(--ink-muted); flex-wrap: wrap; }
.bar nav a.on { color: var(--accent); font-weight: 600; }
.bar .sha { margin-left: auto; font-family: var(--font-mono); font-size: 12px;
  color: var(--ink-faint); display: flex; align-items: center; gap: 10px; }
.bar .toggle { border: var(--border-w) solid var(--rule); border-radius: var(--radius-sm);
  padding: 4px 8px; cursor: pointer; background: transparent; color: var(--ink-muted);
  font: 12px var(--font-mono); }
.bar .toggle:hover { color: var(--ink); border-color: var(--ink-faint); }

main { max-width: 1120px; margin: 0 auto; padding: 30px 40px 60px; background: var(--bg-surface); }
h1 { font-size: 30px; margin: 12px 0 4px; }
h2 { font-size: 21px; margin: 30px 0 12px; padding-bottom: 6px;
     border-bottom: var(--border-w) solid var(--rule); }
.sub { color: var(--ink-muted); margin: 0 0 14px; }
table.data { border-collapse: collapse; width: 100%; }
table.data th, table.data td { padding: 9px 12px; border-bottom: var(--border-w) solid var(--rule-soft);
  text-align: left; white-space: nowrap; }
table.data th { font-family: var(--font-mono); font-size: 11px; text-transform: uppercase;
  letter-spacing: .1em; color: var(--ink-faint); cursor: default; font-weight: 500; }
table.data th[data-s] { cursor: pointer; }
table.data th[data-s]:hover { color: var(--ink); }
table.data td.num, table.data th.num { text-align: right; font-family: var(--font-mono); }
table.data tr:hover td { background: var(--bg-row-alt); }
.controls { display: flex; gap: 16px; align-items: center; margin: 12px 0;
  flex-wrap: wrap; }
.controls input[type=text] { padding: 6px 10px; border: var(--border-w) solid var(--rule);
  border-radius: var(--radius-sm); background: var(--bg-surface); color: var(--ink-body);
  min-width: 220px; font: 13px var(--font-body); }
.only-changes tr[data-status="same"] { display: none; }
.spr { display: inline-block; overflow: hidden; vertical-align: middle;
  border-radius: var(--radius-sm); }
.spr img { image-rendering: pixelated; display: block; }
.type-badge { display: inline-block; padding: 3px 8px; border-radius: var(--radius-sm);
  font-family: var(--font-mono); font-size: 11px; font-weight: 600; margin-right: 3px; }
.t-normal{background:var(--type-normal-bg);color:var(--type-normal-fg)}
.t-fire{background:var(--type-fire-bg);color:var(--type-fire-fg)}
.t-water{background:var(--type-water-bg);color:var(--type-water-fg)}
.t-electric{background:var(--type-electric-bg);color:var(--type-electric-fg)}
.t-grass{background:var(--type-grass-bg);color:var(--type-grass-fg)}
.t-ice{background:var(--type-ice-bg);color:var(--type-ice-fg)}
.t-fighting{background:var(--type-fighting-bg);color:var(--type-fighting-fg)}
.t-poison{background:var(--type-poison-bg);color:var(--type-poison-fg)}
.t-ground{background:var(--type-ground-bg);color:var(--type-ground-fg)}
.t-flying{background:var(--type-flying-bg);color:var(--type-flying-fg)}
.t-psychic{background:var(--type-psychic-bg);color:var(--type-psychic-fg)}
.t-bug{background:var(--type-bug-bg);color:var(--type-bug-fg)}
.t-rock{background:var(--type-rock-bg);color:var(--type-rock-fg)}
.t-ghost{background:var(--type-ghost-bg);color:var(--type-ghost-fg)}
.t-dragon{background:var(--type-dragon-bg);color:var(--type-dragon-fg)}
.t-dark{background:var(--type-dark-bg);color:var(--type-dark-fg)}
.t-steel{background:var(--type-steel-bg);color:var(--type-steel-fg)}
.t-fairy{background:var(--type-fairy-bg);color:var(--type-fairy-fg)}
.t-mystery{background:var(--type-mystery-bg);color:var(--type-mystery-fg)}
.t-stellar{background:var(--type-stellar-bg);color:var(--type-stellar-fg)}
.t-none{background:var(--type-none-bg);color:var(--type-none-fg)}
.badge { display: inline-block; padding: 3px 7px; border-radius: 4px;
  font-family: var(--font-mono); font-size: 10px; font-weight: 600; letter-spacing: .08em; }
.badge.new { background: var(--accent); color: var(--badge-new-fg); }
.badge.changed { background: var(--status-changed-bg); color: var(--status-changed-fg); }
.statbar { background: var(--bg-subtle); border-radius: 999px; height: 6px;
  min-width: 180px; width: 100%; overflow: hidden; }
.statbar div { height: 6px; background: var(--accent); }
table.stats td { border-bottom: none; padding: 3px 8px; }
table.stats { width: auto; min-width: 420px; }
table.kv td:first-child { color: var(--ink-muted); padding-right: 18px; }
.typedef { display: grid; grid-template-columns: repeat(9, minmax(52px, 1fr));
  gap: 4px; max-width: 640px; }
.typedef .cell { text-align: center; border: var(--border-w) solid var(--rule);
  border-radius: var(--radius-sm); padding: 4px 0 6px; font-size: 13px; }
.eff { display: inline-block; min-width: 26px; border-radius: var(--radius-sm);
  font-weight: 700; font-size: 12px; padding: 0 3px; font-family: var(--font-mono); }
.eff-0 { background: var(--ink); color: var(--bg-surface); }
.eff-25, .eff-50 { background: oklch(0.55 0.16 25); color: oklch(0.99 0 0); }
.eff-200, .eff-400 { background: oklch(0.50 0.13 145); color: oklch(0.99 0 0); }
.eff-100 { color: var(--ink-faint); }
.chart { border-collapse: collapse; font-size: 12px; }
.chart th, .chart td { border: var(--border-w) solid var(--rule); padding: 2px;
  text-align: center; min-width: 30px; }
.chart th.atk { text-align: right; padding-right: 6px; }
.evo-step { display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin: 6px 0; }
.evo-cond { color: var(--ink-muted); font-size: 13px; }
.evo-card { text-align: center; padding: 6px 10px; background: var(--bg-subtle);
  border-radius: var(--radius); }
.evo-children { display: flex; flex-direction: column; }
.movechips { display: flex; flex-wrap: wrap; gap: 4px; max-width: 900px; }
.movechips span { background: var(--bg-subtle); border: var(--border-w) solid var(--rule);
  border-radius: var(--radius-sm); padding: 1px 7px; font-size: 13px; }
.difftable td { white-space: normal; }
.pagenav { display: flex; justify-content: space-between; margin: 10px 0; }
.desc { max-width: 640px; }
.headrow { display: flex; gap: 24px; align-items: center; flex-wrap: wrap; }
.warn { color: var(--warn); }
.scroll-x { overflow-x: auto; }

/* -- the dashboard (dex-site-requirements.md B1) ----------------------- */
.tiles { display: grid; gap: 14px; margin: 16px 0 4px;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }
.tile { display: flex; flex-direction: column; gap: 5px; padding: 14px 16px;
  background: var(--bg-subtle); border: var(--border-w) solid var(--rule);
  border-radius: var(--radius); }
.tile .lbl { font: 500 11px/1 var(--font-mono); text-transform: uppercase;
  letter-spacing: .1em; color: var(--ink-faint); }
.tile .big { font-family: var(--font-display); font-size: 27px; line-height: 1.05;
  color: var(--ink); }
.tile .big.mono { font-family: var(--font-mono); font-size: 22px; }
.tile .note { font-size: 12px; color: var(--ink-muted); }
.tile.bad { border-color: var(--warn); }
.tile.bad .big { color: var(--warn); }
.flags { list-style: none; margin: 14px 0 0; padding: 0; display: flex;
  flex-direction: column; gap: 8px; max-width: 780px; }
.flags li { border-left: 3px solid var(--warn); padding: 3px 0 3px 12px;
  font-size: 13px; color: var(--ink-body); }
.flags li.ok { border-left-color: var(--ok); color: var(--ink-muted); }
.flags code { font-family: var(--font-mono); font-size: 12px; }
td.yes { color: var(--ok); }
td.no { color: var(--warn); }
td.muted, span.muted { color: var(--ink-faint); }

/* -- Track B2: the dev log --------------------------------------------- */
.build { border-top: var(--border-w) solid var(--rule); padding: 18px 0 4px; }
.build:first-of-type { border-top: none; }
.build h2 { margin: 0 0 4px; }
.build h2 .when { font-family: var(--font-mono); font-size: 15px;
  color: var(--ink-muted); font-weight: 400; margin-left: 8px; }
.buildmeta { display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 0 0 10px;
  font-size: 13px; color: var(--ink-muted); }
.buildmeta code { font-family: var(--font-mono); }
.logcats { display: grid; gap: 14px;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.logcat { background: var(--bg-subtle); border: var(--border-w) solid var(--rule);
  border-radius: var(--radius); padding: 10px 14px 12px; }
.logcat h3 { font: 500 11px/1 var(--font-mono); text-transform: uppercase;
  letter-spacing: .1em; color: var(--ink-faint); margin: 0 0 8px; }
.loglist { list-style: none; margin: 0; padding: 0; display: flex;
  flex-direction: column; gap: 5px; font-size: 13px; }
.loglist .badge { min-width: 34px; text-align: center; }
.loglist .muted { font-size: 12px; }
.badge.stock { background: var(--bg-page); color: var(--ink-faint);
  border: var(--border-w) solid var(--rule); }

/* -- Track B3: the roadmap, the one section nothing derives -------------
   Its whole visual job is to be impossible to mistake for a derived page:
   dashed everywhere, never the solid rules the rest of the site uses. */
.authored { border: 2px dashed var(--rule); border-radius: var(--radius);
  padding: 14px 18px; margin: 0 0 22px; max-width: 780px; }
.authored .lbl { font: 600 11px/1.6 var(--font-mono); text-transform: uppercase;
  letter-spacing: .12em; color: var(--ink-faint); display: block; }
.authored p { margin: 6px 0 0; font-size: 13px; color: var(--ink-body); }
/* Derived progress, sitting beside the beat's AUTHORED gate. Solid, and
   labelled, so the two are never read as the same claim. */
.beatprog { border-left: 4px solid var(--accent); border-radius: var(--radius);
  background: var(--bg-subtle); padding: 10px 14px; margin: 0 0 14px;
  max-width: 780px; }
.beatprog .lbl { font: 600 11px/1.6 var(--font-mono); text-transform: uppercase;
  letter-spacing: .12em; color: var(--ink-faint); display: block; }
.beatprog p { margin: 4px 0 0; font-size: 13px; color: var(--ink-body); }

/* A gym: derived like everything else, so SOLID -- the dashed border is
   reserved for what a person wrote (see .authored). */
.gymcard { border: 1px solid var(--rule); border-left: 4px solid var(--accent);
  border-radius: var(--radius); padding: 12px 16px; margin: 0 0 20px;
  max-width: 520px; }
.gymcard .lbl { font: 600 11px/1.6 var(--font-mono); text-transform: uppercase;
  letter-spacing: .12em; color: var(--accent); display: block; }
.gymcard dl { margin: 6px 0 0; display: grid; grid-template-columns: auto 1fr;
  gap: 4px 14px; font-size: 13px; }
.gymcard dt { color: var(--ink-faint); }
.gymcard dd { margin: 0; }

.plan { display: flex; flex-direction: column; gap: 14px; margin: 14px 0; }
.slice { border: 2px dashed var(--rule); border-radius: var(--radius);
  padding: 12px 16px 14px; }
.slice.done { border-style: solid; }
.slice.cut { opacity: .6; }
.slice h3 { margin: 0 0 2px; font-size: 17px; }
.slice.cut h3 { text-decoration: line-through; }
.slice .num { font-family: var(--font-mono); color: var(--ink-faint);
  font-size: 13px; margin-right: 8px; }
.slice dl { margin: 8px 0 0; display: grid; gap: 4px 14px;
  grid-template-columns: max-content 1fr; font-size: 13px; }
.slice dt { font: 500 10px/1.6 var(--font-mono); text-transform: uppercase;
  letter-spacing: .1em; color: var(--ink-faint); }
.slice dd { margin: 0; color: var(--ink-body); }
.chip { display: inline-block; padding: 2px 8px; border-radius: 999px;
  font: 600 10px/1.7 var(--font-mono); text-transform: uppercase;
  letter-spacing: .1em; border: var(--border-w) solid var(--rule);
  color: var(--ink-muted); vertical-align: 2px; }
.chip.done { border-color: var(--ok); color: var(--ok); }
.chip.building { border-color: var(--accent); color: var(--accent); }
.chip.unclear { border-color: var(--warn); color: var(--warn); }
/* Prose in a table wraps; only data columns get to stay on one line. */
table.data.wrap td { white-space: normal; max-width: 56ch; }

/* -- Track C1: the story thread -----------------------------------------
   The design problem was that a walkthrough is a narrative and everything
   under a place is a table. The answer is a spine: one unbroken rule down
   the left carrying beats and places, authored prose sitting ON it in the
   display serif at full measure, and every derived thing inset one step to
   the right in a quieter register -- mono micro-labels, hairline rules, no
   card chrome unless the content needs it. Reading only the left edge gives
   you the route. */
.eyebrow { font: 500 11px/1 var(--font-mono); text-transform: uppercase;
  letter-spacing: .12em; color: var(--ink-faint); margin: 0 0 6px; }
/* The micro-label every derived block wears, so a heading is never spent on
   one. Scoped nowhere: it means the same thing everywhere it appears. */
.lbl { display: block; font: 500 10px/1.6 var(--font-mono);
  text-transform: uppercase; letter-spacing: .1em; color: var(--ink-faint); }
/* A place pill is a name, not a status word: it keeps its own capitals. */
.plink { display: inline-block; padding: 3px 10px; border-radius: 999px;
  border: var(--border-w) solid var(--rule); font-size: 13px;
  text-decoration: none; }
.plink:hover { border-color: var(--accent); }
.plink .muted { font: 400 10px/1 var(--font-mono); text-transform: uppercase;
  letter-spacing: .06em; margin-left: 5px; }
.threadhead { display: flex; gap: 8px; margin: 0 0 26px; }
.thread { margin: 8px 0 0 46px; }
.thread > * { position: relative; border-left: 2px solid var(--rule);
  padding: 0 0 34px 30px; }
.thread > .beat { padding-top: 4px; padding-bottom: 6px; }
.thread > .beat + .place { padding-top: 2px; }
.thread > .place + .beat { padding-top: 28px; }
.beat .disc { position: absolute; left: -15px; top: 2px; width: 28px;
  height: 28px; border-radius: 999px; background: var(--accent);
  color: var(--badge-new-fg); font: 600 13px/28px var(--font-mono);
  text-align: center; }
.beat h2 { margin: 0 0 4px; border: none; padding: 0; }
.beat .lead { margin: 0 0 14px; font-size: 17px; color: var(--ink-body);
  max-width: 62ch; }
.place .dot { position: absolute; left: -5px; top: 10px; width: 8px;
  height: 8px; border-radius: 999px; background: var(--bg-surface);
  box-shadow: 0 0 0 2px var(--accent); }
.place.revisit .dot { box-shadow: 0 0 0 2px var(--rule-dashed); }
.place.unbuilt { border-left-style: dashed; border-left-color: var(--rule-dashed); }
.place.unbuilt .dot { box-shadow: 0 0 0 2px var(--rule-dashed); }
.place.unbuilt .authored { margin: 0; }
.place.unbuilt h3 { margin: 0 0 4px; color: var(--ink-muted); }
.place h3 { margin: 0 0 3px; font-family: var(--font-display);
  font-size: 21px; font-weight: 500; }
.place.revisit h3 a { color: var(--ink-muted); }
.place .note { margin: 0 0 10px; font-size: 16px; color: var(--ink-body);
  max-width: 62ch; }
.tag { display: inline-block; margin-left: 8px; padding: 1px 7px;
  border: var(--border-w) solid var(--rule-dashed); border-radius: 3px;
  font: 500 10px/1.6 var(--font-mono); text-transform: uppercase;
  letter-spacing: .08em; color: var(--ink-faint); vertical-align: 3px; }
.backlink { margin-left: 8px; font: 400 12px/1 var(--font-mono);
  color: var(--ink-faint); vertical-align: 3px; }
.census { display: flex; justify-content: space-between; gap: 16px;
  align-items: baseline; flex-wrap: wrap; margin: 8px 0 12px;
  padding: 5px 0; border-top: var(--border-w) solid var(--rule-soft);
  border-bottom: var(--border-w) solid var(--rule-soft);
  font: 400 12px/1.5 var(--font-mono); color: var(--ink-muted); }
.census a { font-size: 12px; }
.lbl.inline { display: inline; margin-left: 8px; }
.pbody { display: flex; gap: 18px; align-items: flex-start; flex-wrap: wrap; }
/* A map orients you; it is not reference material, and it is never blown up
   past the size it was drawn at. Height is capped by role so a 60x60-block
   route cannot take four screens on the way past it -- the place's own page
   is where you go to look properly. */
.pmap { border-radius: var(--radius); overflow: hidden;
  border: var(--border-w) solid var(--rule); line-height: 0;
  width: fit-content; max-width: 100%; }
.pmap img { display: block; image-rendering: pixelated; max-width: 100%;
  width: auto; height: auto; }
.pmap.wide img { max-height: 380px; }
.pmap.mid img { max-height: 260px; }
.pmap.small img { max-height: 190px; }
.mapfail { line-height: 1.5; padding: 12px 14px; background: var(--bg-subtle);
  min-height: 120px; }
.mapfail p { margin: 4px 0 0; font-size: 12px; color: var(--ink-muted); }
.pside { flex: 1 1 320px; }
.tcards { display: grid; gap: 8px; margin: 6px 0 0;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
.tcard { border: var(--border-w) solid var(--rule); border-radius: var(--radius-sm);
  padding: 7px 10px 8px; display: flex; flex-direction: column; gap: 2px;
  position: relative; }
.tcard .who { font-size: 14px; display: flex; flex-direction: column; }
.tcard .who .muted { font-size: 11px; }
.tcard .lv { position: absolute; right: 10px; top: 8px;
  font: 400 11px/1 var(--font-mono); color: var(--ink-muted); }
.tcard .team { display: flex; flex-wrap: wrap; margin-top: 2px; }
.tset details summary { display: inline-block; margin-top: 8px; padding: 3px 10px;
  border: var(--border-w) solid var(--rule); border-radius: 999px;
  font: 400 12px/1.5 var(--font-mono); color: var(--ink-muted); cursor: pointer; }
.tset details[open] summary { margin-bottom: 6px; }
.rollup, .pband, .pocket { margin-top: 14px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.wchip { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px 2px 4px;
  border: var(--border-w) solid var(--rule); border-radius: 999px;
  font-size: 13px; }
.wchip .muted { font: 400 11px/1 var(--font-mono); }
a.chip { text-decoration: none; }
a.chip:hover { border-color: var(--accent); }
.pband { display: flex; gap: 30px; flex-wrap: wrap; }
.pband > div { flex: 1 1 260px; }
ul.plain, ul.unreached { list-style: none; margin: 6px 0 0; padding: 0;
  font-size: 14px; }
ul.plain li, ul.unreached li { padding: 2px 0; }
ul.unreached { columns: 2; max-width: 780px; }
.saidhere { display: inline-block; margin-top: 12px;
  font: 400 12px/1 var(--font-mono); }
.pocket { background: var(--bg-subtle); border-radius: var(--radius);
  padding: 10px 14px 12px; margin-left: -30px; padding-left: 30px; }
.thread > .terminus { border-left: none; padding-bottom: 0;
  font: 400 12px/1 var(--font-mono); color: var(--ink-faint); }
.terminus .dot { position: absolute; left: -5px; top: 0; width: 8px;
  height: 8px; border-radius: 999px; background: var(--bg-surface);
  box-shadow: 0 0 0 2px var(--rule); }
.authored pre { font: 400 12px/1.7 var(--font-mono); color: var(--ink-body);
  background: var(--bg-subtle); border-radius: var(--radius-sm);
  padding: 10px 12px; overflow-x: auto; margin: 8px 0 0; }
@media (max-width: 900px) {
  .thread { margin-left: 22px; }
  .pmap.wide, .pmap.mid, .pmap.small { flex: 1 1 100%; max-width: 100%; }
  ul.unreached { columns: 1; }
}

/* -- Track A2: trainer parties ----------------------------------------- */
.party { display: grid; gap: 12px; margin: 12px 0;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
.mon { border: var(--border-w) solid var(--rule); border-radius: var(--radius);
  padding: 10px 12px; background: var(--bg-subtle); }
.mon-head { display: flex; align-items: center; gap: 8px; font-size: 15px;
  color: var(--ink); }
.mon-head .lvl { margin-left: auto; font-family: var(--font-mono);
  font-size: 12px; color: var(--ink-muted); }
.mon-meta { font-size: 12px; color: var(--ink-muted); margin: 4px 0 6px; }
.mon .movechips span { background: var(--bg-surface); font-size: 12px; }
.ident { font-family: var(--font-mono); font-size: 11px; color: var(--ink-faint); }
blockquote.say { margin: 10px 0; padding: 2px 0 2px 14px; max-width: 640px;
  border-left: 3px solid var(--accent-2); color: var(--ink-body); }
blockquote.say p { margin: 0 0 6px; }
blockquote.say p:last-child { margin-bottom: 0; }
details.says { margin: 18px 0; border-top: var(--border-w) solid var(--rule);
  padding-top: 10px; }
details.says summary { cursor: pointer; font-family: var(--font-display);
  font-size: 17px; color: var(--ink); }
details.says .line { margin: 12px 0; padding-left: 14px; max-width: 640px;
  border-left: 3px solid var(--rule); }
details.says .line p { margin: 2px 0; }
.tpic { image-rendering: pixelated; display: block; }
.mapshot { display: inline-block; max-width: 100%; overflow: auto;
  max-height: 70vh; margin: 14px 0; background: var(--bg-subtle);
  border: var(--border-w) solid var(--rule); border-radius: var(--radius); }
.mapshot img { image-rendering: pixelated; display: block; }
.tpic-wrap { border: var(--border-w) solid var(--rule); border-radius: var(--radius);
  background: var(--bg-subtle); padding: 6px; flex: none; }
tr.partial td:nth-child(2) { font-weight: 600; }
"""


def _dark_tokens() -> str:
    return f"""
    --bg-page: oklch(0.16 0.008 80); --bg-surface: oklch(0.20 0.01 75);
    --bg-subtle: oklch(0.24 0.012 75); --bg-row-alt: oklch(0.26 0.01 75);
    --ink: oklch(0.92 0.01 80); --ink-body: oklch(0.86 0.012 75);
    --ink-muted: oklch(0.68 0.015 75); --ink-faint: oklch(0.60 0.015 75);
    --rule: oklch(0.32 0.015 75); --rule-soft: oklch(0.28 0.012 75);
    --rule-dashed: oklch(0.42 0.02 75);
    --ok: oklch(0.68 0.08 145); --warn: oklch(0.74 0.11 70);
    --badge-new-fg: oklch(0.14 0.02 42);
    --status-changed-bg: oklch(0.30 0.05 128); --status-changed-fg: oklch(0.86 0.06 128);
    --stripe: repeating-linear-gradient(135deg, oklch(0.26 0.015 75) 0 5px, oklch(0.23 0.015 75) 5px 10px);
    {_type_color_vars_dark()}
    """

INDEX_JS = """\
(function () {
  var table = document.getElementById('dex'), tbody = table.tBodies[0];
  var ths = table.tHead.rows[0].cells;
  Array.prototype.forEach.call(ths, function (th, i) {
    if (!th.dataset.s) return;
    th.addEventListener('click', function () {
      var dir = th.dataset.d === 'a' ? -1 : 1;
      th.dataset.d = dir === 1 ? 'a' : 'd';
      var num = th.dataset.s === 'n';
      var rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function (a, b) {
        var x = a.cells[i].textContent.trim(), y = b.cells[i].textContent.trim();
        if (num) { return ((parseFloat(x) || 0) - (parseFloat(y) || 0)) * dir; }
        return x.localeCompare(y) * dir;
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
  });
  document.getElementById('q').addEventListener('input', function () {
    var q = this.value.toLowerCase();
    Array.prototype.forEach.call(tbody.rows, function (r) {
      r.style.display = r.dataset.f.indexOf(q) >= 0 ? '' : 'none';
    });
  });
  document.getElementById('only').addEventListener('change', function () {
    table.classList.toggle('only-changes', this.checked);
  });
})();
"""


def esc(s) -> str:
    return html.escape(str(s), quote=True)


# Reads the stored theme choice before first paint, so the page never
# flashes light-then-dark; the visible toggle in the bar just flips it.
_THEME_ANTIFLASH_JS = (
    "(function(){try{var t=localStorage.getItem('dex-theme');"
    "if(t)document.documentElement.setAttribute('data-theme',t);"
    "}catch(e){}})();"
)
_THEME_TOGGLE_JS = """\
(function () {
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.addEventListener('click', function () {
    var root = document.documentElement;
    var dark = matchMedia('(prefers-color-scheme: dark)').matches;
    var cur = root.getAttribute('data-theme') || (dark ? 'dark' : 'light');
    var next = cur === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('dex-theme', next); } catch (e) {}
  });
})();
"""

# Nav destinations that actually exist today; only real links, no dead ends
# (dex-site-requirements.md §4, "no fragmentation" / pokemondb's cross-link
# discipline). Grows as later tracks land (trainers, locations...).
_NAV = [("home", "index.html", "Home"),
        ("pokedex", "pokedex.html", "Pokédex"),
        ("moves", "moves.html", "Moves"),
        ("abilities", "abilities.html", "Abilities"),
        ("items", "items.html", "Items"),
        ("trainers", "trainers.html", "Trainers"),
        ("locations", "locations.html", "Locations"),
        ("gyms", "gyms.html", "Gyms"),
        ("thread", "thread.html", "Story thread"),
        ("changes", "changes.html", "Changes"),
        ("devlog", "devlog.html", "Dev log"),
        ("roadmap", "roadmap.html", "Roadmap"),
        ("types", "types.html", "Type chart")]

# Track D1: the same destinations under player-facing names. The files keep
# their names so every cross-link in the body text stays correct in both
# renders -- only the words in the bar change, because "Dev log" and
# "Roadmap" are what a builder calls them and not what a player does.
_NAV_PUBLISH = [(key, href,
                 {"devlog": "Patch notes", "roadmap": "What's next"}.get(key, label))
                for key, href, label in _NAV]


def page(title: str, body: str, game: str, depth: int = 0, active: str = "",
         nav_items=None) -> str:
    up = "../" * depth
    nav_links = []
    for key, href, label in (nav_items or _NAV):
        cls = ' class="on"' if key == active else ""
        nav_links.append(f'<a href="{up}{href}"{cls}>{esc(label)}</a>')
    nav = "".join(nav_links)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{up}assets/style.css">
<script>{_THEME_ANTIFLASH_JS}</script>
</head>
<body>
<div class="bar">
  <span class="logo"></span>
  <span class="word">{esc(game)}</span>
  <nav>{nav}</nav>
  <span class="sha"><button class="toggle" id="theme-toggle" type="button" aria-label="Toggle dark mode">&#9789;</button></span>
</div>
<main>
{body}
</main>
<script>{_THEME_TOGGLE_JS}</script>
</body>
</html>
"""


def type_badge(t: str) -> str:
    name = type_label(t)
    return f'<span class="type-badge t-{esc(name.lower())}">{esc(name)}</span>'


def status_badge(status: str) -> str:
    if status == "new":
        return '<span class="badge new">NEW</span>'
    if status == "changed":
        return '<span class="badge changed">CHG</span>'
    return ""


def eff_cell(mult: float) -> str:
    if mult == 1:
        return '<span class="eff eff-100"></span>'
    pct = int(round(mult * 100))
    label = {25: "¼", 50: "½"}.get(pct, f"{mult:g}")
    return f'<span class="eff eff-{pct}">{esc(label)}</span>'


def stat_bar(value: int) -> str:
    width = min(100.0, value / 255 * 100)
    hue = max(0, min(140, int(value * 140 / 180)))
    return (f'<div class="statbar"><div style="width:{width:.1f}%;'
            f'background:hsl({hue},72%,45%)"></div></div>')


class Site:
    """Everything needed to render, bundled so helpers stay short."""

    def __init__(self, fork_model, engine_model, fork_root, out, game, warn,
                 engine_ref=hx.DEFAULT_ENGINE_REF, health=None,
                 publish=False):
        # Track D1: the same derivation, a second render target. Everything
        # above this line is identical in both trees; `publish` only ever
        # decides what a page is allowed to SAY, never what was parsed.
        self.publish = publish
        self.nav = _NAV_PUBLISH if publish else _NAV
        self.health = health or {}
        self.f = fork_model
        self.e = engine_model
        self.out = out
        self.game = game
        self.warn = warn
        self.engine_ref = engine_ref
        self.graphics = fork_root / "graphics/pokemon"
        self.moves = fork_model["moves"]
        self.chart = fork_model["chart"]
        # Types shown to the player: those with any non-neutral interaction.
        active = {t for pair in self.chart for t in pair}
        self.types_shown = [t for t in fork_model["type_order"] if t in active]

        self.status: dict[str, tuple[str, list]] = {}
        for const, sp in self.f["species"].items():
            self.status[const] = classify(sp, self.e["species"].get(const))

        dex = fork_model["dex"]
        self.ordered = sorted(
            self.f["species"].values(),
            key=lambda s: (dex.get(s.get("natDexNum", ""), 10**6), s["order"]))
        self.pos = {sp["const"]: i for i, sp in enumerate(self.ordered)}

        # Evolution edges and their reverse, for chains.
        self.edges: dict[str, list[tuple[str, str]]] = {}
        self.preds: dict[str, str] = {}
        for const, sp in self.f["species"].items():
            for method, param, target in sp.get("evolutions", []):
                if target in self.f["species"]:
                    self.edges.setdefault(const, []).append(
                        (evo_text(method, param), target))
                    self.preds.setdefault(target, const)

        # -- Track A1: moves, abilities, items --------------------------
        self.abilities = fork_model["abilities"]
        self.items = fork_model["items"]

        self.move_status: dict[str, tuple[str, list]] = {}
        for const, mv in self.moves.items():
            self.move_status[const] = classify(
                mv, self.e["moves"].get(const), MOVE_COMPARE_FIELDS)
        # No separate "national move dex": internal ID order (file order,
        # since designated initializers appear in ID order) is the only
        # order that means anything here.
        self.moves_ordered = list(self.moves.values())

        self.ability_status: dict[str, tuple[str, list]] = {}
        for const, ab in self.abilities.items():
            self.ability_status[const] = classify(
                ab, self.e["abilities"].get(const), ABILITY_COMPARE_FIELDS)
        self.abilities_ordered = list(self.abilities.values())

        self.item_status: dict[str, tuple[str, list]] = {}
        for const, it in self.items.items():
            self.item_status[const] = classify(
                it, self.e["items"].get(const), ITEM_COMPARE_FIELDS)
        item_order = fork_model["item_order"]
        self.items_ordered = sorted(
            self.items.values(),
            key=lambda it: item_order.get(it["const"], 10 ** 6))

        # Reverse indices -- pokemondb/Bulbapedia's "no dead ends": every
        # move and ability page links back to who learns/has it.
        self.move_learners: dict[str, list[tuple[str, int | None]]] = {}
        for sp in self.f["species"].values():
            for lvl, mv in sp.get("levelUpMoves") or []:
                self.move_learners.setdefault(mv, []).append((sp["const"], lvl))
            for mv in sp.get("teachableMoves") or []:
                self.move_learners.setdefault(mv, []).append((sp["const"], None))

        self.ability_holders: dict[str, list[tuple[str, bool]]] = {}
        for sp in self.f["species"].values():
            for i, a in enumerate(sp.get("abilities", [])):
                if a and a != "ABILITY_NONE":
                    self.ability_holders.setdefault(a, []).append(
                        (sp["const"], i == 2))

        # -- Track A2: trainers and wild encounters ----------------------
        self.trainers = fork_model.get("trainers") or {}
        self.classes = fork_model.get("trainer_classes") or {}
        self.trainer_pics = fork_model.get("trainer_pics") or {}
        self.encounters = fork_model.get("encounters") or {}
        self.fork_root = fork_root
        self.pics: dict[str, tuple[str, tuple[int, int]]] = {}

        self.trainer_status: dict[str, tuple[str, list]] = {}
        for const, tr in self.trainers.items():
            self.trainer_status[const] = classify(
                tr, (self.e.get("trainers") or {}).get(const),
                TRAINER_COMPARE_FIELDS)
        # TRAINER_NONE is the engine's empty slot, not a trainer.
        self.trainers_ordered = [t for t in self.trainers.values()
                                 if t["const"] != "TRAINER_NONE" and t["party"]]

        # -- Track A3: the places themselves ------------------------------
        self.maps = fork_model.get("maps") or {}
        self.layouts = fork_model.get("layouts") or {}
        self.map_status: dict[str, tuple[str, list]] = {}
        for const, mp in self.maps.items():
            self.map_status[const] = classify(
                mp, (self.e.get("maps") or {}).get(const), MAP_COMPARE_FIELDS)
        self.maps_ordered = sorted(self.maps.values(),
                                   key=lambda m: map_label(m["id"]))
        self.renderer = MapRenderer(
            fork_root, fork_model.get("tileset_dirs") or {},
            fork_model.get("fieldmap") or FIELDMAP_DEFAULTS,
            fork_model.get("mapgrid") or MAPGRID_DEFAULTS, warn)
        self.map_images: dict[str, tuple[str, tuple[int, int]]] = {}

        # Which trainer each map's NPCs actually battle with, resolved
        # through that map's own scripts, and the reverse.
        self.trainer_home: dict[str, str] = {}
        for mp in self.maps.values():
            for spot in mp["trainers"]:
                const = mp["scripts"].get(spot["script"])
                spot["trainer"] = const
                if const:
                    self.trainer_home.setdefault(const, mp["id"])
        # The gyms, in badge order, and the two reverse lookups the pages
        # need: which map is a gym, and which trainer leads one. A gym is
        # a property OF a map, so it is stored beside the map rather than
        # in a list of its own that could fall out of step with it.
        self.gyms = sorted(
            ((mp["id"], mp["gym"]) for mp in self.maps.values()
             if mp.get("gym")),
            key=lambda pair: pair[1]["badge"])
        self.gym_of_leader = {g["leader"]: (mid, g) for mid, g in self.gyms
                              if g.get("leader")}

        self.gifts = fork_model.get("gifts") or {}
        self.item_places: dict[str, list[tuple[str, bool]]] = {}
        for mp in self.maps.values():
            for g in mp["ground"]:
                self.item_places.setdefault(g["item"], []).append(
                    (mp["id"], g["hidden"]))

        # Reverse indices, same no-dead-ends rule as moves and abilities:
        # a species says who trains it and where it lives; an item says who
        # carries it.
        self.species_trainers: dict[str, set[str]] = {}
        self.item_trainers: dict[str, set[str]] = {}
        for tr in self.trainers_ordered:
            for mon in tr["party"]:
                self.species_trainers.setdefault(mon["species"], set()).add(
                    tr["const"])
                if mon.get("heldItem") and mon["heldItem"] != "ITEM_NONE":
                    self.item_trainers.setdefault(mon["heldItem"], set()).add(
                        tr["const"])
            for it in tr["items"]:
                self.item_trainers.setdefault(it, set()).add(tr["const"])

        self.species_places: dict[str, list[tuple[str, str, dict]]] = {}
        for mp in self.maps_ordered:
            for method, table in mp["encounters"].items():
                for slot in table["slots"]:
                    self.species_places.setdefault(slot["species"], []).append(
                        (mp["id"], method, slot))

        self.sprites: dict[str, dict] = {}
        self.pages_written = 0

        # Track B2: the recorded builds, oldest first, and this run's own
        # snapshot. Both are set by the caller, because reading the history
        # is a workspace errand and writing to it is a decision (--record)
        # that rendering a page must never make on its own.
        self.history: list[dict] = []
        self.entry: dict | None = None

        # Track B3: the design doc, the one source on this site that a human
        # wrote rather than a build produced. Also set by the caller, and
        # empty by default, so nothing here can quietly start authoring.
        self.design: dict = {}
        self._species_notes: dict | None = None
        self._place_notes: dict | None = None

    # -- sprites ---------------------------------------------------------

    def key(self, const: str) -> str:
        return const[len("SPECIES_"):].lower()

    def copy_sprites(self):
        """The game's own graphics header maps each species' pic symbols to a
        directory; the underscore-splitting heuristic is only the fallback."""
        dst = self.out / "assets/sprites"
        dst.mkdir(parents=True, exist_ok=True)
        dirs = self.f.get("sprite_dirs", {})
        fork_root = self.graphics.parents[1]
        missing = 0
        for const, sp in self.f["species"].items():
            fallback = None

            def dir_for(sym):
                nonlocal fallback
                rel = dirs.get(sym or "")
                if rel:
                    return fork_root / rel
                if fallback is None:
                    fallback = sprite_dir(self.graphics, const) or False
                return fallback or None

            rec = {}
            fd = dir_for(sp.get("frontPic"))
            if fd:
                front = fd / "front.png"
                if not front.is_file():
                    front = fd / "anim_front.png"
                if front.is_file():
                    rec["front"] = front
            idir = dir_for(sp.get("iconSprite"))
            if idir and (idir / "icon.png").is_file():
                rec["icon"] = idir / "icon.png"
            copied = {}
            for kind, src in rec.items():
                size = png_size(src)
                if not size:
                    continue
                name = f"{self.key(const)}-{kind}.png"
                copy_png_index0_transparent(src, dst / name)
                copied[kind] = (name, size)
            if copied:
                self.sprites[const] = copied
            else:
                missing += 1
        if missing:
            self.warn(f"{missing} species resolved no sprites under "
                      f"{self.graphics}; their pages render without images")

    def copy_trainer_pics(self):
        """The trainers a page will actually show, and only those -- the pic
        table covers every class in the engine, most of which no trainer in
        this game uses."""
        wanted = {t["pic"] for t in self.trainers_ordered if t.get("pic")}
        dst = self.out / "assets/trainers"
        dst.mkdir(parents=True, exist_ok=True)
        for pic in sorted(wanted):
            rel = self.trainer_pics.get(pic)
            if not rel:
                continue
            src = self.fork_root / rel
            size = png_size(src) if src.is_file() else None
            if not size:
                continue
            name = f"{pic[len('TRAINER_PIC_'):].lower()}.png"
            copy_png_index0_transparent(src, dst / name)
            self.pics[pic] = (name, size)

    def pic_html(self, pic, depth, scale=1) -> str:
        rec = self.pics.get(pic or "")
        if not rec:
            return ""
        name, (w, h) = rec
        up = "../" * depth
        return (f'<img class="tpic" loading="lazy" '
                f'src="{up}assets/trainers/{name}" '
                f'style="width:{w * scale}px;height:{h * scale}px" alt="">')

    def sprite_html(self, const, kind, depth, scale=1):
        rec = self.sprites.get(const, {}).get(kind)
        if not rec:
            return ""
        name, (w, h) = rec
        fh = h // 2 if h == 2 * w else h     # two-frame sheet: first frame
        up = "../" * depth
        return (f'<span class="spr" style="width:{w * scale}px;height:{fh * scale}px">'
                f'<img loading="lazy" src="{up}assets/sprites/{name}" '
                f'style="width:{w * scale}px;height:{h * scale}px" alt=""></span>')

    # -- shared fragments --------------------------------------------------

    def link(self, const, depth):
        sp = self.f["species"][const]
        up = "../" * depth
        return (f'<a href="{up}pokemon/{self.key(const)}.html">'
                f'{esc(sp.get("name", pretty(const)))}</a>')

    def dexno(self, sp) -> str:
        n = self.f["dex"].get(sp.get("natDexNum", ""))
        return f"{n:04d}" if n else ""

    def fmt(self, field, value) -> str:
        """One diff-table cell, field-aware, HTML-escaped."""
        if value is None:
            return "&mdash;"
        if field == "Types":
            return " ".join(type_badge(t) for t in value)
        if field == "Abilities":
            return ", ".join(self.ability_link(a, depth=1)
                             for a in value if a != "ABILITY_NONE")
        if field == "Egg groups":
            return esc(", ".join(pretty(g) for g in value))
        if field == "Gender ratio":
            return esc(gender_text(value) or value)
        if field == "Height":
            return esc(f"{value / 10:.1f} m")
        if field == "Weight":
            return esc(f"{value / 10:.1f} kg")
        if field == "Evolutions":
            return esc("; ".join(
                f"{evo_text(m, p)} → {pretty(t)}" for m, p, t in value))
        if field == "Level-up moves":
            if not isinstance(value, list):
                return "&mdash;"
            return ", ".join(
                f"{lvl}: {self.move_link(mv, depth=1)}" for lvl, mv in value)
        if field == "Teachable moves":
            if not isinstance(value, list):
                return "&mdash;"
            return ", ".join(self.move_link(m, depth=1) for m in value)
        if field == "Bag items":
            return (", ".join(self.item_link(i, depth=1) for i in value)
                    or "&mdash;")
        if field == "Class":
            return esc(self.class_label(value))
        if field == "Double battle":
            return "yes" if value else "no"
        if field == "Dialogue":
            if not isinstance(value, list) or not value:
                return "none"
            # A trainer's lines are paragraphs; a map's are (label,
            # paragraphs) pairs. Both read as the words themselves.
            paras = [p[1] if isinstance(p, tuple) else p for p in value]
            return "<br>".join(esc(" ".join(p)) for p in paras)
        if field == "Party":
            if not isinstance(value, list):
                return "&mdash;"
            return "; ".join(
                (self.link(m["species"], 1) if m["species"] in self.f["species"]
                 else esc(pretty(m["species"])))
                + (f' Lv. {m["lvl"]}' if m.get("lvl") else "")
                for m in value) or "&mdash;"
        if field == "Encounters":
            if not isinstance(value, dict) or not value:
                return "none"
            return esc("; ".join(
                f"{method} {len(t['slots'])} species"
                for method, t in value.items()))
        if field == "Terrain":
            # A digest is not a fact a reader can use; that it differs is.
            return f'<span class="ident">{esc(value or "&mdash;")}</span>'
        if field == "Size":
            return esc(f"{value[0]}&times;{value[1]}") if value and value[0] else "&mdash;"
        if field == "Connections":
            if not value:
                return "none"
            return ", ".join(f'{esc(str(c.get("direction") or ""))} '
                             + self.map_link(c["map"], 1) for c in value)
        if field == "Trainers here":
            return str(len(value)) if isinstance(value, list) else "&mdash;"
        if field == "Items here":
            if not isinstance(value, list) or not value:
                return "none"
            return ", ".join(self.item_link(g["item"], 1) for g in value)
        return esc(value)

    def move_name(self, const) -> str:
        mv = self.moves.get(const)
        return mv["name"] if mv and "name" in mv else pretty(const)

    def move_link(self, const, depth=0) -> str:
        up = "../" * depth
        name = esc(self.move_name(const))
        if const not in self.moves:
            return name
        return f'<a href="{up}moves/{slug(const)}.html">{name}</a>'

    def ability_name(self, const) -> str:
        ab = self.abilities.get(const)
        return ab["name"] if ab and "name" in ab else pretty(const)

    def ability_link(self, const, depth=0) -> str:
        up = "../" * depth
        name = esc(self.ability_name(const))
        if const not in self.abilities:
            return name
        return f'<a href="{up}abilities/{slug(const)}.html">{name}</a>'

    def item_name(self, const) -> str:
        it = self.items.get(const)
        return it["name"] if it and "name" in it else pretty(const)

    def item_link(self, const, depth=0) -> str:
        up = "../" * depth
        name = esc(self.item_name(const))
        if const not in self.items:
            return name
        return f'<a href="{up}items/{slug(const)}.html">{name}</a>'

    def trainer_name(self, const) -> str:
        tr = self.trainers.get(const) or {}
        return prettify_caps(tr.get("name") or "") or pretty(const)

    def trainer_link(self, const, depth=0) -> str:
        """The game reuses trainer NAMES freely -- four trainers are called
        Anna & Meg, dozens are called Grunt -- so every link carries the
        constant that actually identifies it, as a tooltip here and as a
        column on the hub. Inventing a distinguishing name would be authored
        content; the game's own identifier is not."""
        up = "../" * depth
        name = esc(self.trainer_name(const))
        if const not in self.trainers:
            return name
        return (f'<a href="{up}trainers/{slug(const)}.html" '
                f'title="{esc(const)}">{name}</a>')

    def class_label(self, cls) -> str:
        if not cls:
            return ""
        return prettify_caps(self.classes.get(cls) or pretty(cls))

    def map_link(self, const, depth=0) -> str:
        up = "../" * depth
        name = esc(map_label(const))
        if const not in self.maps:
            return name
        return f'<a href="{up}locations/{slug(const)}.html">{name}</a>'

    def diff_table(self, diffs) -> str:
        """The old->new table every changed entry carries. Field-aware
        through fmt(), so a party or an encounter table reads as itself
        rather than as a Python repr."""
        rows = "".join(f"<tr><td>{esc(label)}</td>"
                       f"<td>{self.fmt(label, old)}</td>"
                       f"<td>{self.fmt(label, new)}</td></tr>"
                       for label, old, new in diffs)
        return (f"<h2>vs. stock ({esc(self.engine_ref)})</h2>"
                '<div class="scroll-x"><table class="data difftable">'
                "<thead><tr><th>Field</th><th>Stock</th><th>This game</th>"
                f"</tr></thead>{rows}</table></div>")

    def change_summary(self, diffs, limit=4) -> str:
        return esc("; ".join(self.change_bits(diffs, limit)))

    def change_bits(self, diffs, limit=4) -> list[str]:
        """What changed, in short plain phrases. Plain, because the dev log
        writes these into a file a human reads in git as well as into a
        page -- the escaping is the caller's business."""
        bits = []
        for label, old, new in diffs:
            if label in ("Level-up moves", "Teachable moves"):
                a = len(old) if isinstance(old, list) else 0
                b = len(new) if isinstance(new, list) else 0
                bits.append(f"{label.lower()} {a}→{b}")
            elif label in ("Dex text", "Evolutions"):
                bits.append(f"{label.lower()} changed")
            elif label == "Types":
                bits.append("types "
                            + "/".join(type_label(t) for t in (old or []))
                            + "→"
                            + "/".join(type_label(t) for t in (new or [])))
            elif label == "Party":
                a = len(old) if isinstance(old, list) else 0
                b = len(new) if isinstance(new, list) else 0
                bits.append(f"party {a}→{b}" if a != b else "party re-tuned")
            elif label == "Encounters":
                def n_species(v):
                    return len({s["species"] for t in (v or {}).values()
                                for s in t["slots"]}) if isinstance(v, dict) else 0
                bits.append(f"wild species {n_species(old)}→{n_species(new)}")
            elif label == "Terrain":
                bits.append("terrain redrawn")
            elif label == "Dialogue":
                bits.append("what they say changed")
            elif label in ("Trainers here", "Items here", "Connections"):
                a = len(old) if isinstance(old, (list, dict)) else 0
                b = len(new) if isinstance(new, (list, dict)) else 0
                bits.append(f"{label.lower()} {a}→{b}")
            elif label == "Size":
                def dims(v):
                    return f"{v[0]}×{v[1]}" if v and v[0] else "?"
                bits.append(f"size {dims(old)}→{dims(new)}")
            elif isinstance(old, int) and isinstance(new, int):
                bits.append(f"{label} {old}→{new}")
            else:
                bits.append(f"{label.lower()} changed")
        shown = bits[:limit]
        if len(bits) > limit:
            shown.append(f"+{len(bits) - limit} more")
        return shown

    # -- pages -------------------------------------------------------------

    def page(self, title: str, body: str, depth: int = 0,
             active: str = "") -> str:
        """Every page on this site goes out through here, so a render only
        has to be told once which nav it is wearing."""
        return page(title, body, self.game, depth=depth, active=active,
                    nav_items=self.nav)

    def write(self, rel: str, content: str):
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self.pages_written += 1

    # -- Track B1: the dashboard -------------------------------------------

    def tile(self, label, big, note, bad=False, mono=False) -> str:
        cls = "tile bad" if bad else "tile"
        bigcls = ' class="big mono"' if mono else ' class="big"'
        return (f'<div class="{cls}"><span class="lbl">{label}</span>'
                f"<span{bigcls}>{big}</span>"
                f'<span class="note">{note}</span></div>')

    def health_section(self) -> list[str]:
        """Build health: the ROM, the commit, the backup and the checks, plus
        every sentence about something being stale. Every figure is read from
        the tree, the ROM, the patch or the game's own verify specs -- nothing
        is asserted, and a fact that cannot be read is left out rather than
        guessed (dex-site-requirements.md §6.1 and §4.1).

        This is the whole of what the publish render drops (§7): it is the
        builder's instrument panel, and its numbers are answers to questions
        only the person building the game is asking."""
        h = self.health or {}
        now = h.get("now") or 0
        flags = []          # (bad?, sentence) -- rendered under the tiles

        def age(rec, key="mtime"):
            t = (rec or {}).get(key)
            return human_age(now - t) if t and now else ""

        # -- build health ---------------------------------------------------
        rom, patch, git = h.get("rom"), h.get("patch"), h.get("git")
        src = h.get("source") or {}
        own = src.get("own") or []          # this game's files, newest first
        about = "about " if src.get("capped") else ""

        def edits_after(rec):
            t = (rec or {}).get("mtime")
            return [r for r in own if t and r["mtime"] > t]

        tiles = []
        if rom:
            after_rom = edits_after(rom)
            tiles.append(self.tile(
                "ROM", esc(age(rom) or "built"),
                f'{esc(rom["name"])} &middot; {esc(human_size(rom["size"]))}'
                + (f" &middot; {len(after_rom)} edit"
                   f"{'s' if len(after_rom) != 1 else ''} since"
                   if after_rom else " &middot; newer than every edit"),
                bad=bool(after_rom)))
            if after_rom:
                n = len(after_rom)
                flags.append((True,
                              f"{about}{n} of this game's own source file"
                              f"{'s have' if n != 1 else ' has'} changed since "
                              f"the ROM was built (newest: "
                              f'<code>{esc(after_rom[0]["file"])}</code>, '
                              f"{age(after_rom[0])}), so the ROM does not "
                              "contain that work."))
        else:
            tiles.append(self.tile("ROM", "none", "no built ROM in the game "
                                                  "repo", bad=True))
            flags.append((True, "No ROM sits at the top of the game repo, so "
                                "there is nothing to pick up and play."))
        if git:
            dirty = git.get("dirty")
            note = esc(git.get("branch") or "detached")
            if dirty:
                note += f" &middot; {dirty} uncommitted change" + ("s" if dirty != 1 else "")
            elif dirty == 0:
                note += " &middot; clean"
            if git.get("epoch"):
                note += f" &middot; {human_age(now - git['epoch'])}"
            tiles.append(self.tile("Commit", esc(git["sha"]), note,
                                   bad=bool(dirty), mono=True))
        if patch:
            carried = h.get("backed_up") or set()
            missing = [r for r in own if r["file"] not in carried]
            after_patch = edits_after(patch)
            # §9.7 closed: where the exporter left digests, "newer than the
            # patch" is settled by content instead of guessed at by clock.
            moved = unexported(h.get("fork_root") or Path("."),
                               h.get("marker") or {}, after_patch)
            n = len(moved) if moved is not None else len(after_patch)
            note = f'{esc(patch["name"])} &middot; {esc(human_size(patch["size"]))}'
            if missing:
                note += (f" &middot; {len(missing)} file"
                         f"{'s' if len(missing) != 1 else ''} not carried")
            elif n and moved is not None:
                note += (f" &middot; {n} file{'s' if n != 1 else ''} not in "
                         "the backup")
            elif n:
                note += f" &middot; {about}{n} file{'s' if n != 1 else ''} newer"
            elif moved is not None and after_patch:
                note += (f" &middot; {len(after_patch)} newer, all "
                         "byte-identical")
            else:
                note += " &middot; carries everything this game owns"
            tiles.append(self.tile("Backup", esc(age(patch) or "exported"),
                                   note, bad=bool(missing or n)))
            if missing:
                names = ", ".join(f'<code>{esc(r["file"])}</code>'
                                  for r in missing[:4])
                more = (f" and {len(missing) - 4} more"
                        if len(missing) > 4 else "")
                flags.append((True, f"The backup patch does not carry "
                                    f"{len(missing)} file"
                                    f"{'s' if len(missing) != 1 else ''} this "
                                    f"game owns: {names}{more}. Export again "
                                    "&mdash; the fork is gitignored, so those "
                                    "exist on one disk only."))
            elif n and moved is not None:
                # No longer a hedge: the export wrote down what it proved,
                # so this is a content difference, not a clock difference.
                flags.append((True,
                              f"{n} file{'s' if n != 1 else ''} this game owns "
                              f"{'have' if n != 1 else 'has'} changed since the "
                              f"backup was verified (newest: "
                              f'<code>{esc(moved[0]["file"])}</code>, '
                              f"{age(moved[0])}). The patch does not contain "
                              "that work &mdash; export again."))
            elif n:
                flags.append((True,
                              f"The patch carries every file this game owns, "
                              f"but {about}{n} of them "
                              f"{'are' if n != 1 else 'is'} stamped newer than "
                              f"the export (newest: "
                              f'<code>{esc(after_patch[0]["file"])}</code>, '
                              f"{age(after_patch[0])}). That is either an edit "
                              "made since, or a tree restored from this same "
                              "patch &mdash; timestamps cannot tell those "
                              "apart. Export once to leave a marker and this "
                              "page will stop having to guess."))
            elif moved is not None and after_patch:
                flags.append((False,
                              f"{len(after_patch)} file"
                              f"{'s are' if len(after_patch) != 1 else ' is'} "
                              "stamped newer than the backup and byte-identical "
                              "to what it carries &mdash; a restored tree, not "
                              "unsaved work. Read from the digests the export "
                              "left, not from the clock."))
        else:
            tiles.append(self.tile("Backup", "none", "no patch exported",
                                   bad=True))
            flags.append((True, "No patch has been exported. The fork is "
                                "gitignored, so nothing in it is backed up."))
        ch = h.get("checks") or {}
        if ch.get("specs"):
            short = ch["specs"] - ch["runnable"]
            tiles.append(self.tile(
                "Checks", f'{ch["runnable"]} / {ch["specs"]}',
                f'runnable here &middot; {ch["asserts"]} assertions',
                bad=bool(short)))
            if short:
                states = ch["missing_states"]
                named = ", ".join(esc(m) for m in states[:4])
                more = f" and {len(states) - 4} more" if len(states) > 4 else ""
                many = len(states) != 1
                flags.append((True, f"{short} check{'s' if short != 1 else ''} "
                                    "cannot run on this machine: the savestate"
                                    f"{'s' if many else ''} {named}{more} "
                                    f"{'are' if many else 'is'} not in the "
                                    "game's saves folder. A check that cannot "
                                    "run is not a check that passed."))
        if h.get("trainers_stale"):
            flags.append((True, "<code>trainers.party</code> is newer than the "
                                "<code>trainers.h</code> generated from it, so "
                                "every trainer page here shows a team the build "
                                "no longer compiles. Rebuild to regenerate it."))
        parts = ["<h2>Build health</h2>",
                 '<div class="tiles">' + "".join(tiles) + "</div>"]
        if flags:
            items = "".join(('<li class="ok">' if not bad else "<li>")
                            + text + "</li>" for bad, text in flags)
            parts.append(f'<ul class="flags">{items}</ul>')
        else:
            parts.append('<ul class="flags"><li class="ok">Nothing is stale: '
                         "the ROM, the backup and the checks all match the "
                         "source tree as it stands.</li></ul>")
        return parts

    def build_dashboard(self):
        """The home page. Both renders answer "what is in this game" from the
        same parse; only the private one also answers "what state is the
        workbench in"."""
        h = self.health or {}
        now = h.get("now") or 0
        title = esc(h.get("title") or self.game)
        design = self.design or {}

        if self.publish:
            parts = [f"<h1>{title}</h1>"]
            if design.get("pitch"):
                parts.append(f'<p class="lead">{esc(design["pitch"])}</p>')
            if design.get("loop"):
                parts.append(f'<p class="sub">{esc(design["loop"])}</p>')
            parts.append('<p class="sub">Every page here is generated from '
                         "the game itself &mdash; its species, its people, its "
                         "places and its words are read out of the game rather "
                         "than written up by hand, so what this site says is "
                         "what the game does.</p>")
        else:
            parts = [f"<h1>{title}</h1>",
                     '<p class="sub">Everything below is read out of this '
                     "game's own tree, ROM and checks at generation time. "
                     "Nothing here is hand-maintained, so nothing here can "
                     "quietly go out of date.</p>"]
            parts += self.health_section()

        # -- what exists ------------------------------------------------------
        def counts(status_map, keys):
            n_new = sum(1 for k in keys if status_map[k][0] == "new")
            n_chg = sum(1 for k in keys if status_map[k][0] == "changed")
            return n_new, n_chg

        sp_new, sp_chg = counts(self.status, list(self.status))
        mv_keys = [m["const"] for m in self.moves_ordered]
        mv_new, mv_chg = counts(self.move_status, mv_keys)
        ab_keys = [a["const"] for a in self.abilities_ordered
                   if a["const"] != "ABILITY_NONE"]
        ab_new, ab_chg = counts(self.ability_status, ab_keys)
        it_keys = [i["const"] for i in self.items_ordered
                   if i["const"] != "ITEM_NONE"]
        it_new, it_chg = counts(self.item_status, it_keys)
        maps = h.get("maps") or {}

        def yours(n_new, n_chg):
            if not n_new and not n_chg:
                return "all stock"
            bits = []
            if n_new:
                bits.append(f"{n_new} new")
            if n_chg:
                bits.append(f"{n_chg} changed")
            return " &middot; ".join(bits)

        # How much is still unfinished is a fact about the workbench, not
        # about the game, so the counts stay in both renders and the
        # what's-missing suffixes are private (§7).
        no_art = 0 if self.publish else sum(
            1 for sp in self.ordered
            if not self.sprites.get(sp["const"], {}).get("front"))
        stock_tiles = [
            self.tile('<a href="pokedex.html">Species</a>', len(self.ordered),
                      yours(sp_new, sp_chg)
                      + (f" &middot; {no_art} without art" if no_art else "")),
            self.tile('<a href="moves.html">Moves</a>', len(mv_keys),
                      yours(mv_new, mv_chg)),
            self.tile('<a href="abilities.html">Abilities</a>', len(ab_keys),
                      yours(ab_new, ab_chg)),
            self.tile('<a href="items.html">Items</a>', len(it_keys),
                      yours(it_new, it_chg)),
        ]
        tr_keys = [t["const"] for t in self.trainers_ordered]
        tr_new, tr_chg = counts(self.trainer_status, tr_keys)
        mp_keys = [m["id"] for m in self.maps_ordered]
        mp_new, mp_chg = counts(self.map_status, mp_keys)
        if tr_keys:
            stock_tiles.append(self.tile(
                '<a href="trainers.html">Trainers</a>', len(tr_keys),
                yours(tr_new, tr_chg)))
        if mp_keys:
            drawn = len(self.map_images)
            undrawn = 0 if self.publish else len(mp_keys) - drawn
            stock_tiles.append(self.tile(
                '<a href="locations.html">Places</a>', len(mp_keys),
                yours(mp_new, mp_chg)
                + (f" &middot; {undrawn} undrawn" if undrawn > 0 else "")))
        elif maps.get("fork"):
            n = len(maps.get("new") or [])
            stock_tiles.append(self.tile(
                "Maps", maps["fork"],
                f"{n} not in stock" if n else "all stock"))
        if self.gyms:
            # "A leader this parse could not trace" is a confession about
            # the parse, which is the builder's business and no player's.
            no_leader = 0 if self.publish else sum(
                1 for _m, g in self.gyms if not g.get("leader"))
            stock_tiles.append(self.tile(
                '<a href="gyms.html">Gyms</a>', len(self.gyms),
                f"{no_leader} leader{'s' if no_leader != 1 else ''} not "
                "derived" if no_leader else "one per badge"))
        parts.append("<h2>What's in it</h2>" if self.publish
                     else "<h2>What exists</h2>")
        parts.append('<div class="tiles">' + "".join(stock_tiles) + "</div>")
        parts.append('<p class="sub">Counted against stock '
                     f'{esc(self.engine_ref)}. "New" and "changed" are the same '
                     'diff <a href="changes.html">Changes</a> lists entry by '
                     "entry.</p>")
        # Everything past this point answers "how far along is the work",
        # which is the question the publish render exists not to answer.
        # Where to go next takes its place (§7).
        if self.publish:
            parts.append("<h2>Where to start</h2>")
            parts.append(
                '<ul class="flags">'
                '<li class="ok">The <a href="thread.html">story thread</a> '
                "walks the game in play order, from the first step to the "
                "last one written down.</li>"
                '<li class="ok">The <a href="changes.html">changes</a> page '
                "is everything this game does differently from the game it "
                "grew out of.</li>"
                '<li class="ok">The <a href="pokedex.html">Pok&eacute;dex</a> '
                "and its neighbours in the bar above are the exhaustive "
                "half: every species, move, ability, item, person and place."
                "</li></ul>")
            self.write("index.html",
                       self.page(f"{self.game}", "\n".join(parts),
                                 active="home"))
            return

        if maps.get("new"):
            shown = ", ".join(esc(m) for m in maps["new"][:8])
            more = (f" and {len(maps['new']) - 8} more"
                    if len(maps["new"]) > 8 else "")
            parts.append(f'<p class="sub">Map folders this game owns: '
                         f"{shown}{more}. Their contents are counted, not "
                         "compared &mdash; only the folder list is read.</p>")

        # -- since the last recorded build ------------------------------------
        # Track B2 made this line real: it used to be aspirational, because
        # nothing kept a record of what the last build contained.
        hist = self.history or []
        parts.append("<h2>Since the last build</h2>")
        if not hist:
            parts.append('<p class="sub">No build has been recorded yet. The '
                         '<a href="devlog.html">dev log</a> starts keeping '
                         "history at the next green build.</p>")
        else:
            newest = hist[-1]
            since = devlog_delta(newest, self.entry or self.devlog_entry())
            when = esc(newest.get("date") or "earlier")
            ago = (f" ({human_age(now - newest['at'])})"
                   if newest.get("at") and now else "")
            if not since:
                parts.append(f'<p class="sub">Nothing this game owns has '
                             f"changed since the build recorded {when}{ago}. "
                             'The <a href="devlog.html">dev log</a> has the '
                             "history.</p>")
            else:
                counted = []
                for key, label, *_ in self.devlog_categories():
                    d = since.get(key)
                    if not d:
                        continue
                    n = len(d["added"]) + len(d["edited"]) + len(d["gone"])
                    # A category can be here on its total alone: a stock
                    # entry deleted outright never differed from stock, so
                    # it is in no snapshot's list, only in the count.
                    counted.append(f"{n} {label.lower()}" if n
                                   else f"the {label.lower()} count")
                bits = ", ".join(counted)
                parts.append(f'<p class="sub">Changed since the build recorded '
                             f"{when}{ago}: {esc(bits)}. The "
                             '<a href="devlog.html">dev log</a> names them, and '
                             "will record them at the next green build.</p>")

        # -- the new content, finished or not ---------------------------------
        # The half of "ground truth" no reference site has to do: a species
        # this game invented can exist in the tree while its art, dex text or
        # learnset does not. Read straight off the parse, so a placeholder
        # cannot pass for finished work.
        news = [sp for sp in self.ordered if self.status[sp["const"]][0] == "new"]
        parts.append("<h2>New content, finished or not</h2>")
        if news:
            rows = []
            for sp in news:
                const = sp["const"]
                # Only things whose absence means UNFINISHED are scored. A
                # species that does not evolve is a design decision, not a
                # gap, so the evolution column states what is there and is
                # never marked against the row.
                got = [bool(self.sprites.get(const, {}).get("front")),
                       bool(self.sprites.get(const, {}).get("icon")),
                       bool(sp.get("description")),
                       bool(sp.get("levelUpMoves"))]
                cells = "".join('<td class="yes">&check;</td>' if v
                                else '<td class="no">&mdash;</td>' for v in got)
                evos = sp.get("evolutions") or []
                cells += ("<td>" + ", ".join(self.link(t, 0) for _, _, t in evos
                                             if t in self.f["species"]) + "</td>"
                          if evos else '<td class="muted">does not evolve</td>')
                tr = "<tr>" if all(got) else '<tr class="partial">'
                rows.append(f"{tr}<td>{self.sprite_html(const, 'icon', 0)}</td>"
                            f"<td>{self.link(const, 0)}</td>{cells}</tr>")
            parts.append('<p class="sub">A species can exist in the tree with '
                         "its art, its dex text or its learnset still missing. "
                         "These are read off the same parse the rest of the "
                         "site is built from.</p>")
            parts.append('<table class="data"><thead><tr><th></th><th>Species</th>'
                         "<th>Front art</th><th>Icon</th><th>Dex text</th>"
                         "<th>Learnset</th><th>Evolves to</th></tr></thead>"
                         + "".join(rows) + "</table>")
        else:
            parts.append('<p class="sub">This tree has not added a species '
                         "yet.</p>")

        for label, keys, lookup, status_map, name_of in (
                ("moves", mv_keys, self.moves, self.move_status, self.move_name),
                ("abilities", ab_keys, self.abilities, self.ability_status,
                 self.ability_name),
                ("items", it_keys, self.items, self.item_status, self.item_name)):
            blank = [k for k in keys if status_map[k][0] == "new"
                     and not (lookup[k].get("description") or "").strip()]
            if blank:
                names = ", ".join(esc(name_of(k)) for k in blank[:6])
                more = f" and {len(blank) - 6} more" if len(blank) > 6 else ""
                verb = "has" if len(blank) == 1 else "have"
                parts.append(f'<p class="sub">{len(blank)} new {label} {verb} '
                             f"no description text: {names}{more}.</p>")

        # -- and the one line here that nobody derived --------------------
        # The dashboard is otherwise entirely read off the tree, so the
        # doc's next action arrives wearing the roadmap's dashed label and
        # nothing else on this page looks like it.
        if design.get("next"):
            nxt = design["next"][0]
            more = (f' <span class="muted">and {len(design["next"]) - 1} more on '
                    'the <a href="roadmap.html">roadmap</a></span>'
                    if len(design["next"]) > 1 else "")
            parts.append("<h2>What is meant to happen next</h2>")
            parts.append('<div class="authored"><span class="lbl">From the '
                         "design doc, not from the game</span>"
                         f"<p>{esc(clip(nxt, 400))}{more}</p></div>")

        self.write("index.html",
                   self.page(f"{self.game} - build status", "\n".join(parts),
                        active="home"))

    def build_pokedex(self):
        rows = []
        for sp in self.ordered:
            const = sp["const"]
            status = self.status[const][0]
            stats = [sp.get(k) for k in ("baseHP", "baseAttack", "baseDefense",
                                         "baseSpAttack", "baseSpDefense",
                                         "baseSpeed")]
            total = sum(stats) if all(v is not None for v in stats) else None
            filt = " ".join([sp.get("name", pretty(const)).lower(),
                             *[type_label(t).lower() for t in sp.get("types", [])],
                             status])
            cells = [
                f"<td>{self.sprite_html(const, 'icon', 0)}</td>",
                f'<td class="num">{self.dexno(sp)}</td>',
                f"<td>{self.link(const, 0)}</td>",
                "<td>" + " ".join(type_badge(t) for t in sp.get("types", [])) + "</td>",
                f'<td class="num"><b>{total if total is not None else "&mdash;"}</b></td>',
                *(f'<td class="num">{v if v is not None else "&mdash;"}</td>'
                  for v in stats),
                f"<td>{status_badge(status)}</td>",
            ]
            rows.append(f'<tr data-status="{status}" data-f="{esc(filt)}">'
                        + "".join(cells) + "</tr>")
        n_new = sum(1 for s in self.status.values() if s[0] == "new")
        n_chg = sum(1 for s in self.status.values() if s[0] == "changed")
        body = f"""<h1>Pokédex</h1>
<p class="sub">{len(self.ordered)} species &middot; {n_new} new &middot;
{n_chg} changed vs. stock ({esc(self.engine_ref)}) &middot; generated from the
game's own source data</p>
<div class="controls">
  <input type="text" id="q" placeholder="Filter by name or type&hellip;">
  <label><input type="checkbox" id="only"> Only my changes</label>
</div>
<div class="scroll-x">
<table class="data" id="dex">
<thead><tr>
  <th></th><th class="num" data-s="n">#</th><th data-s="t">Name</th>
  <th data-s="t">Types</th><th class="num" data-s="n">Total</th>
  <th class="num" data-s="n">HP</th><th class="num" data-s="n">Atk</th>
  <th class="num" data-s="n">Def</th><th class="num" data-s="n">SpA</th>
  <th class="num" data-s="n">SpD</th><th class="num" data-s="n">Spe</th>
  <th data-s="t">&Delta;</th>
</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
</div>
<script>
{INDEX_JS}
</script>"""
        self.write("pokedex.html",
                   self.page(f"Pokédex - {self.game}", body, active="pokedex"))

    def defenses(self, types_of) -> list[tuple[str, float]]:
        out = []
        for atk in self.types_shown:
            mult = 1.0
            for d in dict.fromkeys(types_of):
                mult *= self.chart.get((atk, d), 1.0)
            out.append((atk, mult))
        return out

    def chain_html(self, const, depth, seen=None) -> str:
        seen = seen or set()
        if const in seen:
            return ""
        seen.add(const)
        card = (f'<div class="evo-card">{self.sprite_html(const, "front", depth)}'
                f"<div>{self.link(const, depth)}</div></div>")
        kids = self.edges.get(const, [])
        if not kids:
            return f'<div class="evo-step">{card}</div>'
        inner = "".join(
            f'<div class="evo-step"><span class="evo-cond">&rarr; {esc(cond)}</span>'
            + self.chain_html(target, depth, seen) + "</div>"
            for cond, target in kids)
        return (f'<div class="evo-step">{card}'
                f'<div class="evo-children">{inner}</div></div>')

    def build_species_pages(self):
        for i, sp in enumerate(self.ordered):
            const = sp["const"]
            status, diffs = self.status[const]
            name = sp.get("name", pretty(const))
            parts = [f'<div class="headrow">'
                     f'{self.sprite_html(const, "front", 1, scale=2)}'
                     f"<div><h1>{esc(name)} "
                     f'<span class="sub">#{self.dexno(sp) or "?"}</span> '
                     f"{status_badge(status)}</h1>"
                     "<p>" + " ".join(type_badge(t) for t in sp.get("types", []))
                     + "</p></div></div>"]

            if sp.get("description"):
                parts.append(f'<p class="desc">{esc(sp["description"])}</p>')

            # C2: the curated note, above the data the way Bulbapedia puts
            # "Biology" above every table -- and dashed, because unlike the
            # dex text below it this was written about the creature rather
            # than compiled into the ROM.
            note = self.species_notes().get(const)
            if note:
                parts.append(self.authored_note(esc(note), depth=1))

            # Dex data
            kv = []
            if sp.get("category"):
                kv.append(("Category", esc(sp["category"])))
            if sp.get("height") is not None:
                kv.append(("Height", self.fmt("Height", sp["height"])))
            if sp.get("weight") is not None:
                kv.append(("Weight", self.fmt("Weight", sp["weight"])))
            ab = [a for a in sp.get("abilities", []) if a != "ABILITY_NONE"]
            if ab:
                labels = [self.ability_link(a, depth=1) for a in ab[:2]]
                if len(sp.get("abilities", [])) >= 3 \
                        and sp["abilities"][2] != "ABILITY_NONE":
                    labels = [self.ability_link(a, depth=1)
                              for a in sp["abilities"][:2]
                              if a != "ABILITY_NONE"]
                    labels.append(self.ability_link(sp["abilities"][2], depth=1)
                                  + " (hidden)")
                kv.append(("Abilities", ", ".join(labels)))
            if sp.get("catchRate") is not None:
                kv.append(("Catch rate", sp["catchRate"]))
            if sp.get("expYield") is not None:
                kv.append(("Exp. yield", sp["expYield"]))
            g = gender_text(sp.get("genderRatio"))
            if g:
                kv.append(("Gender ratio", esc(g)))
            if sp.get("eggGroups"):
                kv.append(("Egg groups",
                           esc(", ".join(pretty(x) for x in sp["eggGroups"]))))
            if kv:
                parts.append("<h2>Dex data</h2><table class=\"data kv\">"
                             + "".join(f"<tr><td>{k}</td><td>{v}</td></tr>"
                                       for k, v in kv) + "</table>")

            # Base stats
            stats = [("HP", sp.get("baseHP")), ("Attack", sp.get("baseAttack")),
                     ("Defense", sp.get("baseDefense")),
                     ("Sp. Atk", sp.get("baseSpAttack")),
                     ("Sp. Def", sp.get("baseSpDefense")),
                     ("Speed", sp.get("baseSpeed"))]
            if all(v is not None for _, v in stats):
                total = sum(v for _, v in stats)
                rows = "".join(
                    f'<tr><td>{k}</td><td class="num">{v}</td>'
                    f"<td>{stat_bar(v)}</td></tr>" for k, v in stats)
                parts.append(f"""<h2>Base stats</h2>
<table class="data stats">{rows}
<tr><td><b>Total</b></td><td class="num"><b>{total}</b></td><td></td></tr>
</table>""")
            else:
                self.warn(f"{const}: base stats incomplete; page rendered "
                          "with what was parsed")

            # vs. stock
            if status == "changed":
                rows = "".join(
                    f"<tr><td>{esc(label)}</td><td>{self.fmt(label, old)}</td>"
                    f"<td>{self.fmt(label, new)}</td></tr>"
                    for label, old, new in diffs)
                parts.append(f"""<h2>vs. stock ({esc(self.engine_ref)})</h2>
<div class="scroll-x"><table class="data difftable">
<thead><tr><th>Field</th><th>Stock</th><th>This game</th></tr></thead>
{rows}</table></div>""")

            # Type defenses
            if sp.get("types"):
                cells = "".join(
                    f'<div class="cell">{type_badge(t)}<br>{eff_cell(m)}</div>'
                    for t, m in self.defenses(sp["types"]))
                parts.append("<h2>Type defenses</h2>"
                             f'<p class="sub">Damage taken by {esc(name)}, '
                             "from the game's own type chart</p>"
                             f'<div class="typedef">{cells}</div>')

            # Evolution chain
            root = const
            hops = set()
            while root in self.preds and root not in hops:
                hops.add(root)
                root = self.preds[root]
            if self.edges.get(root) or root != const:
                parts.append("<h2>Evolution</h2>" + self.chain_html(root, 1))

            # Level-up learnset
            lum = sp.get("levelUpMoves")
            if isinstance(lum, list) and lum:
                rows = []
                for lvl, mv in lum:
                    info = self.moves.get(mv, {})
                    rows.append(
                        f'<tr><td class="num">{lvl}</td>'
                        f"<td>{self.move_link(mv, depth=1)}</td>"
                        f"<td>{type_badge(info['type']) if info.get('type') else ''}</td>"
                        f"<td>{esc(info.get('category', ''))}</td>"
                        f'<td class="num">{info.get("power") or "&mdash;"}</td>'
                        f'<td class="num">{info.get("accuracy") or "&mdash;"}</td></tr>')
                parts.append(f"""<h2>Level-up moves</h2>
<div class="scroll-x"><table class="data">
<thead><tr><th class="num">Lv.</th><th>Move</th><th>Type</th><th>Cat.</th>
<th class="num">Power</th><th class="num">Acc.</th></tr></thead>
{''.join(rows)}</table></div>""")
            elif lum is None and sp.get("levelUpLearnset"):
                self.warn(f"{const}: learnset {sp['levelUpLearnset']} not found")

            # Teachable moves
            tm = sp.get("teachableMoves")
            if tm:
                chips = "".join(f"<span>{self.move_link(m, depth=1)}</span>"
                                for m in sorted(tm, key=self.move_name))
                parts.append(f"<h2>Teachable moves</h2>"
                             f'<div class="movechips">{chips}</div>')

            # Track A2's payoff on the species page: where it lives and who
            # brings it to a fight. Both are reverse indices over data the
            # game already stated somewhere else.
            places = self.species_places.get(const) or []
            if places:
                rows = []
                for map_const, method, slot in places:
                    lo, hi = slot.get("min"), slot.get("max")
                    lvl = ((f"{lo}" if lo == hi else f"{lo}&ndash;{hi}")
                           if lo else "&mdash;")
                    rows.append(f"<tr><td>{self.map_link(map_const, 1)}</td>"
                                f"<td>{esc(method)}</td>"
                                f'<td class="num">{lvl}</td>'
                                f'<td class="num">{slot["pct"]:.0f}%</td></tr>')
                parts.append('<h2>Where it lives</h2><div class="scroll-x">'
                             '<table class="data"><thead><tr><th>Place</th>'
                             '<th>How</th><th class="num">Levels</th>'
                             '<th class="num">Chance</th></tr></thead>'
                             + "".join(rows) + "</table></div>")
            # Bulbapedia runs an "In the anime / in the TCG" slot under every
            # species. A solo hack's equivalent is its own story: who brings
            # this species to a fight, what they are, and where they stand.
            owners = sorted(self.species_trainers.get(const) or (),
                            key=self.trainer_name)
            if owners:
                rows = []
                for t in owners:
                    tr = self.trainers.get(t) or {}
                    levels = sorted(m["lvl"] for m in tr.get("party", [])
                                    if m["species"] == const and m.get("lvl"))
                    where = self.trainer_home.get(t)
                    rows.append(
                        f"<tr><td>{self.trainer_link(t, 1)}</td>"
                        f'<td>{esc(self.class_label(tr.get("class")))}</td>'
                        f'<td>{self.map_link(where, 1) if where else "&mdash;"}</td>'
                        f'<td class="num">'
                        f'{", ".join(str(v) for v in levels) or "&mdash;"}</td>'
                        "</tr>")
                parts.append(f"<h2>Appears in this game ({len(owners)})</h2>"
                             '<div class="scroll-x"><table class="data">'
                             "<thead><tr><th>Trainer</th><th>Class</th>"
                             '<th>Where</th><th class="num">Level</th></tr>'
                             "</thead>" + "".join(rows) + "</table></div>")

            # Prev / next
            prev_sp = self.ordered[i - 1] if i > 0 else None
            next_sp = self.ordered[i + 1] if i + 1 < len(self.ordered) else None
            nav = ['<div class="pagenav">']
            nav.append("<span>&larr; " + self.link(prev_sp["const"], 1)
                       + "</span>" if prev_sp else "<span></span>")
            nav.append("<span>" + self.link(next_sp["const"], 1)
                       + " &rarr;</span>" if next_sp else "<span></span>")
            nav.append("</div>")
            parts.append("".join(nav))

            self.write(f"pokemon/{self.key(const)}.html",
                       self.page(f"{name} - {self.game} dex",
                            "\n".join(parts), depth=1, active="pokedex"))

    # -- Track A1: moves, abilities, items ----------------------------------

    def build_moves(self):
        rows = []
        for mv in self.moves_ordered:
            const = mv["const"]
            status = self.move_status[const][0]
            n_learners = len(self.move_learners.get(const, []))
            filt = " ".join([
                mv.get("name", pretty(const)).lower(),
                type_label(mv["type"]).lower() if mv.get("type") else "",
                (mv.get("category") or "").lower(), status])
            cells = [
                f"<td>{self.move_link(const, 0)}</td>",
                f"<td>{type_badge(mv['type']) if mv.get('type') else ''}</td>",
                f"<td>{esc(mv.get('category', ''))}</td>",
                *(f'<td class="num">{mv[k] if mv.get(k) is not None else "&mdash;"}</td>'
                  for k in ("power", "accuracy", "pp")),
                f'<td class="num">{n_learners}</td>',
                f"<td>{status_badge(status)}</td>",
            ]
            rows.append(f'<tr data-status="{status}" data-f="{esc(filt)}">'
                        + "".join(cells) + "</tr>")
        n_new = sum(1 for s in self.move_status.values() if s[0] == "new")
        n_chg = sum(1 for s in self.move_status.values() if s[0] == "changed")
        body = f"""<h1>Moves</h1>
<p class="sub">{len(self.moves_ordered)} moves &middot; {n_new} new &middot;
{n_chg} changed vs. stock ({esc(self.engine_ref)})</p>
<div class="controls">
  <input type="text" id="q" placeholder="Filter by name or type&hellip;">
  <label><input type="checkbox" id="only"> Only my changes</label>
</div>
<div class="scroll-x">
<table class="data" id="dex">
<thead><tr>
  <th data-s="t">Name</th><th data-s="t">Type</th><th data-s="t">Cat.</th>
  <th class="num" data-s="n">Power</th><th class="num" data-s="n">Acc.</th>
  <th class="num" data-s="n">PP</th><th class="num" data-s="n">Learned by</th>
  <th data-s="t">&Delta;</th>
</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
</div>
<script>
{INDEX_JS}
</script>"""
        self.write("moves.html",
                   self.page(f"Moves - {self.game} dex", body, active="moves"))

    def build_move_pages(self):
        for i, mv in enumerate(self.moves_ordered):
            const = mv["const"]
            status, diffs = self.move_status[const]
            name = mv.get("name", pretty(const))
            parts = [f"<div class=\"headrow\"><div><h1>{esc(name)} "
                     f"{status_badge(status)}</h1>"
                     + (f"<p>{type_badge(mv['type'])}</p>" if mv.get("type") else "")
                     + "</div></div>"]
            if mv.get("description"):
                parts.append(f'<p class="desc">{esc(mv["description"])}</p>')

            kv = []
            if mv.get("category"):
                kv.append(("Category", esc(mv["category"])))
            for label, key in (("Power", "power"), ("Accuracy", "accuracy"),
                               ("PP", "pp"), ("Priority", "priority")):
                if mv.get(key) is not None:
                    kv.append((label, mv[key]))
            if kv:
                parts.append("<h2>Move data</h2><table class=\"data kv\">"
                             + "".join(f"<tr><td>{k}</td><td>{v}</td></tr>"
                                       for k, v in kv) + "</table>")

            if status == "changed":
                rows = "".join(
                    f"<tr><td>{esc(label)}</td>"
                    f'<td>{esc(old) if old is not None else "&mdash;"}</td>'
                    f'<td>{esc(new) if new is not None else "&mdash;"}</td></tr>'
                    for label, old, new in diffs)
                parts.append(f"""<h2>vs. stock ({esc(self.engine_ref)})</h2>
<div class="scroll-x"><table class="data difftable">
<thead><tr><th>Field</th><th>Stock</th><th>This game</th></tr></thead>
{rows}</table></div>""")

            learners = self.move_learners.get(const, [])
            lvl_list = sorted((c, lvl) for c, lvl in learners if lvl is not None)
            tm_set = sorted({c for c, lvl in learners if lvl is None},
                            key=lambda c: self.link(c, 1))
            if lvl_list:
                rows = "".join(
                    f'<tr><td class="num">{lvl}</td><td>{self.link(c, 1)}</td></tr>'
                    for c, lvl in sorted(lvl_list, key=lambda t: t[1]))
                parts.append(f"""<h2>Learned by level-up ({len(lvl_list)})</h2>
<div class="scroll-x"><table class="data">
<thead><tr><th class="num">Lv.</th><th>Species</th></tr></thead>
{rows}</table></div>""")
            if tm_set:
                chips = "".join(f"<span>{self.link(c, 1)}</span>" for c in tm_set)
                parts.append(f"<h2>Also teachable to ({len(tm_set)})</h2>"
                             f'<div class="movechips">{chips}</div>')
            if not learners:
                parts.append('<p class="sub">No species in this game '
                             "learns this move yet.</p>")

            prev_mv = self.moves_ordered[i - 1] if i > 0 else None
            next_mv = self.moves_ordered[i + 1] if i + 1 < len(self.moves_ordered) else None
            nav = ['<div class="pagenav">']
            nav.append("<span>&larr; " + self.move_link(prev_mv["const"], 1)
                       + "</span>" if prev_mv else "<span></span>")
            nav.append("<span>" + self.move_link(next_mv["const"], 1)
                       + " &rarr;</span>" if next_mv else "<span></span>")
            nav.append("</div>")
            parts.append("".join(nav))

            self.write(f"moves/{slug(const)}.html",
                       self.page(f"{name} - {self.game} dex", "\n".join(parts),
                            depth=1, active="moves"))

    def build_abilities(self):
        rows = []
        for ab in self.abilities_ordered:
            const = ab["const"]
            if const == "ABILITY_NONE":
                continue
            status = self.ability_status[const][0]
            n_holders = len(self.ability_holders.get(const, []))
            name = ab.get("name", pretty(const))
            filt = f"{name.lower()} {status}"
            cells = [
                f"<td>{self.ability_link(const, 0)}</td>",
                f'<td class="desc">{esc(ab.get("description", ""))}</td>',
                f'<td class="num">{n_holders}</td>',
                f"<td>{status_badge(status)}</td>",
            ]
            rows.append(f'<tr data-status="{status}" data-f="{esc(filt)}">'
                        + "".join(cells) + "</tr>")
        shown = [a for a in self.abilities_ordered if a["const"] != "ABILITY_NONE"]
        n_new = sum(1 for a in shown if self.ability_status[a["const"]][0] == "new")
        n_chg = sum(1 for a in shown if self.ability_status[a["const"]][0] == "changed")
        body = f"""<h1>Abilities</h1>
<p class="sub">{len(shown)} abilities &middot; {n_new} new &middot;
{n_chg} changed vs. stock ({esc(self.engine_ref)})</p>
<div class="controls">
  <input type="text" id="q" placeholder="Filter by name&hellip;">
  <label><input type="checkbox" id="only"> Only my changes</label>
</div>
<div class="scroll-x">
<table class="data" id="dex">
<thead><tr>
  <th data-s="t">Name</th><th data-s="t">Effect</th>
  <th class="num" data-s="n">Species</th><th data-s="t">&Delta;</th>
</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
</div>
<script>
{INDEX_JS}
</script>"""
        self.write("abilities.html",
                   self.page(f"Abilities - {self.game} dex", body, active="abilities"))

    def build_ability_pages(self):
        shown = [a for a in self.abilities_ordered if a["const"] != "ABILITY_NONE"]
        for i, ab in enumerate(shown):
            const = ab["const"]
            status, diffs = self.ability_status[const]
            name = ab.get("name", pretty(const))
            parts = [f"<h1>{esc(name)} {status_badge(status)}</h1>"]
            if ab.get("description"):
                parts.append(f'<p class="desc">{esc(ab["description"])}</p>')

            if status == "changed":
                rows = "".join(
                    f"<tr><td>{esc(label)}</td>"
                    f'<td>{esc(old) if old is not None else "&mdash;"}</td>'
                    f'<td>{esc(new) if new is not None else "&mdash;"}</td></tr>'
                    for label, old, new in diffs)
                parts.append(f"""<h2>vs. stock ({esc(self.engine_ref)})</h2>
<div class="scroll-x"><table class="data difftable">
<thead><tr><th>Field</th><th>Stock</th><th>This game</th></tr></thead>
{rows}</table></div>""")

            holders = self.ability_holders.get(const, [])
            if holders:
                rows = "".join(
                    f"<tr><td>{self.link(c, 1)}</td>"
                    f'<td>{"hidden" if hidden else ""}</td></tr>'
                    for c, hidden in holders)
                parts.append(f"""<h2>Species with this ability ({len(holders)})</h2>
<div class="scroll-x"><table class="data">
<thead><tr><th>Species</th><th>Slot</th></tr></thead>
{rows}</table></div>""")
            else:
                parts.append('<p class="sub">No species in this game '
                             "has this ability yet.</p>")

            prev_ab = shown[i - 1] if i > 0 else None
            next_ab = shown[i + 1] if i + 1 < len(shown) else None
            nav = ['<div class="pagenav">']
            nav.append("<span>&larr; " + self.ability_link(prev_ab["const"], 1)
                       + "</span>" if prev_ab else "<span></span>")
            nav.append("<span>" + self.ability_link(next_ab["const"], 1)
                       + " &rarr;</span>" if next_ab else "<span></span>")
            nav.append("</div>")
            parts.append("".join(nav))

            self.write(f"abilities/{slug(const)}.html",
                       self.page(f"{name} - {self.game} dex", "\n".join(parts),
                            depth=1, active="abilities"))

    def build_items(self):
        rows = []
        for it in self.items_ordered:
            const = it["const"]
            if const == "ITEM_NONE":
                continue
            status = self.item_status[const][0]
            name = it.get("name", pretty(const))
            filt = " ".join([name.lower(),
                             pretty(it["pocket"]).lower() if it.get("pocket") else "",
                             status])
            cells = [
                f"<td>{self.item_link(const, 0)}</td>",
                f"<td>{esc(pretty(it['pocket'])) if it.get('pocket') else ''}</td>",
                f'<td class="num">{it["price"] if it.get("price") is not None else "&mdash;"}</td>',
                f"<td>{status_badge(status)}</td>",
            ]
            rows.append(f'<tr data-status="{status}" data-f="{esc(filt)}">'
                        + "".join(cells) + "</tr>")
        shown = [it for it in self.items_ordered if it["const"] != "ITEM_NONE"]
        n_new = sum(1 for it in shown if self.item_status[it["const"]][0] == "new")
        n_chg = sum(1 for it in shown if self.item_status[it["const"]][0] == "changed")
        body = f"""<h1>Items</h1>
<p class="sub">{len(shown)} items &middot; {n_new} new &middot;
{n_chg} changed vs. stock ({esc(self.engine_ref)}) &middot; an item page lists
the trainers who carry it; items lying on the ground are not in the site yet</p>
<div class="controls">
  <input type="text" id="q" placeholder="Filter by name or pocket&hellip;">
  <label><input type="checkbox" id="only"> Only my changes</label>
</div>
<div class="scroll-x">
<table class="data" id="dex">
<thead><tr>
  <th data-s="t">Name</th><th data-s="t">Pocket</th>
  <th class="num" data-s="n">Price</th><th data-s="t">&Delta;</th>
</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
</div>
<script>
{INDEX_JS}
</script>"""
        self.write("items.html",
                   self.page(f"Items - {self.game} dex", body, active="items"))

    def build_item_pages(self):
        shown = [it for it in self.items_ordered if it["const"] != "ITEM_NONE"]
        for i, it in enumerate(shown):
            const = it["const"]
            status, diffs = self.item_status[const]
            name = it.get("name", pretty(const))
            parts = [f"<h1>{esc(name)} {status_badge(status)}</h1>"]
            if it.get("description"):
                parts.append(f'<p class="desc">{esc(it["description"])}</p>')

            kv = []
            if it.get("price") is not None:
                kv.append(("Price", it["price"]))
            if it.get("pocket"):
                kv.append(("Pocket", esc(pretty(it["pocket"]))))
            if kv:
                parts.append("<h2>Item data</h2><table class=\"data kv\">"
                             + "".join(f"<tr><td>{k}</td><td>{v}</td></tr>"
                                       for k, v in kv) + "</table>")

            if status == "changed":
                rows = "".join(
                    f"<tr><td>{esc(label)}</td>"
                    f'<td>{esc(old) if old is not None else "&mdash;"}</td>'
                    f'<td>{esc(new) if new is not None else "&mdash;"}</td></tr>'
                    for label, old, new in diffs)
                parts.append(f"""<h2>vs. stock ({esc(self.engine_ref)})</h2>
<div class="scroll-x"><table class="data difftable">
<thead><tr><th>Field</th><th>Stock</th><th>This game</th></tr></thead>
{rows}</table></div>""")

            found = self.item_places.get(const) or []
            if found:
                rows = "".join(
                    f"<tr><td>{self.map_link(m, 1)}</td>"
                    f'<td>{"hidden" if hidden else "in plain sight"}</td></tr>'
                    for m, hidden in found)
                parts.append(f"<h2>Found on the ground ({len(found)})</h2>"
                             '<div class="scroll-x"><table class="data">'
                             "<thead><tr><th>Place</th><th>How</th></tr>"
                             "</thead>" + rows + "</table></div>")

            given = sorted(self.gifts.get(const) or (), key=map_label)
            if given:
                parts.append(f"<h2>Given away ({len(given)})</h2>"
                             '<p class="sub">Handed over by a script in '
                             + ", ".join(self.map_link(m, 1) for m in given)
                             + ".</p>")

            carriers = sorted(self.item_trainers.get(const) or (),
                              key=self.trainer_name)
            if carriers:
                chips = "".join(f"<span>{self.trainer_link(t, 1)}</span>"
                                for t in carriers)
                parts.append(f"<h2>Carried by ({len(carriers)})</h2>"
                             '<p class="sub">Trainers who hold this in their '
                             "bag, or whose party carries it.</p>"
                             f'<div class="movechips">{chips}</div>')

            prev_it = shown[i - 1] if i > 0 else None
            next_it = shown[i + 1] if i + 1 < len(shown) else None
            nav = ['<div class="pagenav">']
            nav.append("<span>&larr; " + self.item_link(prev_it["const"], 1)
                       + "</span>" if prev_it else "<span></span>")
            nav.append("<span>" + self.item_link(next_it["const"], 1)
                       + " &rarr;</span>" if next_it else "<span></span>")
            nav.append("</div>")
            parts.append("".join(nav))

            self.write(f"items/{slug(const)}.html",
                       self.page(f"{name} - {self.game} dex", "\n".join(parts),
                            depth=1, active="items"))

    # -- Track A2: trainers and locations ------------------------------------

    def build_trainers(self):
        rows = []
        for tr in self.trainers_ordered:
            const = tr["const"]
            status = self.trainer_status[const][0]
            cls = self.class_label(tr["class"])
            ident = const[len("TRAINER_"):]
            filt = " ".join([self.trainer_name(const).lower(), cls.lower(),
                             ident.lower(), status])
            party = ", ".join(self.link(m["species"], 0) if m["species"]
                              in self.f["species"] else esc(pretty(m["species"]))
                              for m in tr["party"][:6])
            cells = [
                f"<td>{self.trainer_link(const, 0)}</td>",
                f'<td class="ident">{esc(ident)}</td>',
                f"<td>{esc(cls)}</td>",
                f'<td class="num">{len(tr["party"])}</td>',
                f'<td class="num">{tr["maxLevel"] if tr["maxLevel"] else "&mdash;"}</td>',
                f"<td>{party}</td>",
                f"<td>{status_badge(status)}</td>",
            ]
            rows.append(f'<tr data-status="{status}" data-f="{esc(filt)}">'
                        + "".join(cells) + "</tr>")
        n_new = sum(1 for t in self.trainers_ordered
                    if self.trainer_status[t["const"]][0] == "new")
        n_chg = sum(1 for t in self.trainers_ordered
                    if self.trainer_status[t["const"]][0] == "changed")
        body = f"""<h1>Trainers</h1>
<p class="sub">{len(self.trainers_ordered)} trainers with a party &middot;
{n_new} new &middot; {n_chg} changed vs. stock ({esc(self.engine_ref)}) &middot;
read from the game's own trainer table, parties and all</p>
<div class="controls">
  <input type="text" id="q" placeholder="Filter by name, class or ID&hellip;">
  <label><input type="checkbox" id="only"> Only my changes</label>
</div>
<div class="scroll-x">
<table class="data" id="dex">
<thead><tr>
  <th data-s="t">Name</th><th data-s="t">ID</th><th data-s="t">Class</th>
  <th class="num" data-s="n">Party</th><th class="num" data-s="n">Max Lv.</th>
  <th>Team</th><th data-s="t">&Delta;</th>
</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
</div>
<script>
{INDEX_JS}
</script>"""
        self.write("trainers.html",
                   self.page(f"Trainers - {self.game} dex", body, active="trainers"))

    def mon_card(self, mon, depth) -> str:
        """One party member, the way a battle would meet it: what it is, how
        strong, what it is holding, what it knows."""
        sp = mon["species"]
        head = (self.link(sp, depth) if sp in self.f["species"]
                else esc(pretty(sp)))
        bits = [f'<div class="mon-head">{self.sprite_html(sp, "icon", depth)}'
                f"<span>{head}</span>"
                + (f'<span class="lvl">Lv. {mon["lvl"]}</span>'
                   if mon.get("lvl") else "") + "</div>"]
        meta = []
        if mon.get("heldItem") and mon["heldItem"] != "ITEM_NONE":
            meta.append("holding " + self.item_link(mon["heldItem"], depth))
        if mon.get("ability"):
            meta.append(self.ability_link(mon["ability"], depth))
        if mon.get("shiny"):
            meta.append("shiny")
        if meta:
            bits.append('<div class="mon-meta">' + " &middot; ".join(meta)
                        + "</div>")
        if mon.get("moves"):
            bits.append('<div class="movechips">'
                        + "".join(f"<span>{self.move_link(m, depth)}</span>"
                                  for m in mon["moves"]) + "</div>")
        return '<div class="mon">' + "".join(bits) + "</div>"

    def build_trainer_pages(self):
        for i, tr in enumerate(self.trainers_ordered):
            const = tr["const"]
            status, diffs = self.trainer_status[const]
            name = self.trainer_name(const)
            cls = self.class_label(tr["class"])
            head = [f"<h1>{esc(name)} {status_badge(status)}</h1>",
                    f'<p class="sub">{esc(cls)}'
                    + (" &middot; double battle" if tr["double"] else "")
                    + f' &middot; <span class="ident">{esc(const)}</span></p>']
            if tr["items"]:
                counted = []
                for it in dict.fromkeys(tr["items"]):
                    n = tr["items"].count(it)
                    counted.append(self.item_link(it, 1)
                                   + (f" &times;{n}" if n > 1 else ""))
                head.append('<p class="sub">Carries ' + ", ".join(counted)
                            + "</p>")
            pic = self.pic_html(tr.get("pic"), 1, scale=2)
            parts = ['<div class="headrow">'
                     + (f'<div class="tpic-wrap">{pic}</div>' if pic else "")
                     + "<div>" + "".join(head) + "</div></div>"]
            home = self.trainer_home.get(const)
            led = self.gym_of_leader.get(const)
            if led:
                # A leader is usually an ordinary NPC in the map data, so
                # trainer_home does not know where they stand. The gym does.
                gym_map, gym = led
                parts.append(
                    '<p class="sub">Leads the gym at '
                    + self.map_link(gym_map, 1)
                    + f' &middot; awards {esc(self.badge_label(gym))}'
                    f' <span class="muted">({gym["badge"]} of '
                    f"{len(self.gyms)})</span></p>")
            elif home:
                parts.append('<p class="sub">Stands in '
                             + self.map_link(home, 1) + "</p>")
            parts.append(f'<h2>Party ({len(tr["party"])})</h2>')
            parts.append('<div class="party">'
                         + "".join(self.mon_card(m, 1) for m in tr["party"])
                         + "</div>")

            # Track A4: what they actually say. The battle macro names the
            # text; the order it names it in is the order it is shown, with
            # no label invented for which line is which.
            if tr.get("lines"):
                parts.append("<h2>What they say</h2>")
                for para in tr["lines"]:
                    parts.append('<blockquote class="say">'
                                 + "".join(f"<p>{esc(p)}</p>" for p in para)
                                 + "</blockquote>")

            if status == "changed":
                parts.append(self.diff_table(diffs))

            prev_tr = self.trainers_ordered[i - 1] if i > 0 else None
            next_tr = (self.trainers_ordered[i + 1]
                       if i + 1 < len(self.trainers_ordered) else None)
            nav = ['<div class="pagenav">']
            nav.append("<span>&larr; " + self.trainer_link(prev_tr["const"], 1)
                       + "</span>" if prev_tr else "<span></span>")
            nav.append("<span>" + self.trainer_link(next_tr["const"], 1)
                       + " &rarr;</span>" if next_tr else "<span></span>")
            nav.append("</div>")
            parts.append("".join(nav))

            self.write(f"trainers/{slug(const)}.html",
                       self.page(f"{name} - {self.game} dex", "\n".join(parts),
                            depth=1, active="trainers"))

    # -- gyms ----------------------------------------------------------------

    def badge_label(self, gym: dict) -> str:
        """What to call the badge. Its name if the game said it in words,
        and its number otherwise -- never a name assembled from the map's."""
        return gym.get("badge_name") or f'Badge {gym["badge"]}'

    def gym_block(self, map_id: str, gym: dict, depth: int) -> str:
        """The gym, as it appears on its own place's page. Four facts, each
        of them read: which badge, who leads, what beating them sets, and
        the script that hands it over."""
        leader = (self.trainer_link(gym["leader"], depth)
                  if gym.get("leader") in self.trainers else None)
        rows = [f"<dt>Badge</dt><dd>{esc(self.badge_label(gym))} "
                f'<span class="muted">&middot; {gym["badge"]} of '
                f"{len(self.gyms)}</span></dd>"]
        if leader:
            rows.append(f"<dt>Leader</dt><dd>{leader}</dd>")
        if gym.get("defeated_flag"):
            rows.append('<dt>Sets</dt><dd><span class="ident">'
                        f'{esc(gym["defeated_flag"])}</span></dd>')
        return ('<div class="gymcard"><span class="lbl">Gym</span>'
                f"<dl>{''.join(rows)}</dl></div>")

    def check_label(self, flag: str, depth: int) -> str:
        """A progress flag, in words a reader can use. A badge becomes its
        badge; a gym-victory flag becomes the gym it belongs to, when the
        gyms can account for it, and stays a flag name when they cannot."""
        n = badge_number(flag)
        if n is not None:
            match = next((g for _m, g in self.gyms if g["badge"] == n), None)
            return esc(self.badge_label(match)) if match else f"badge {n}"
        owner = next((m for m, g in self.gyms
                      if g.get("defeated_flag") == flag), None)
        if owner:
            return "beating " + self.map_link(owner, depth)
        return f'<span class="ident">{esc(flag)}</span>'

    def checks_block(self, mp: dict, depth: int) -> str:
        """What a place's scripts read about your progress. Stated as a
        check and never as a requirement -- see parse_progress_checks."""
        # A gym reading its own victory flag is the gym working, not a
        # gate, and saying so on its own page would be noise.
        own = (mp.get("gym") or {}).get("defeated_flag")
        flags = [f for f in (mp.get("checks") or []) if f != own]
        if not flags:
            return ""
        return ('<p class="sub">Scripts here check '
                + ", ".join(self.check_label(f, depth) for f in flags)
                + ". A check is not necessarily a door: a place may read a "
                "badge to move a shopkeeper as readily as to bar the way, "
                "and which of the two it is cannot be read from the "
                "scripts.</p>")

    def build_gyms(self):
        """§12.3's first blocked item, unblocked. A gym is not a map type
        and not a trainer class: it is a place whose scripts award a badge,
        which is the only reading that selects the right places (the map
        header's gym battle scene also selects thirteen Battle Pyramid
        rooms, and the leader's trainer class does not exist as data at
        all). Everything on this page is that one fact and what hangs off
        it."""
        parts = ["<h1>Gyms</h1>"]
        if not self.gyms:
            parts.append('<p class="sub">No place in this game awards a '
                         "badge, so it has no gyms. This page is derived "
                         "from the badge flags the scripts set &mdash; it "
                         "does not go looking for rooms that merely look "
                         "like gyms.</p>")
            self.write("gyms.html",
                       self.page(f"Gyms - {self.game}", "\n".join(parts),
                                 active="gyms"))
            return

        named = sum(1 for _m, g in self.gyms if g.get("badge_name"))
        parts.append(f'<p class="sub">{len(self.gyms)} '
                     + ("gym" if len(self.gyms) == 1 else "gyms")
                     + ", in badge order. A gym here is a place whose own "
                     "scripts award a badge &mdash; not a room that uses the "
                     "gym battle scene, which in the stock engine also means "
                     "thirteen Battle Pyramid squares. "
                     + (f"{named} of them say the badge's name in the line "
                        "they hand it over with; any that do not are shown "
                        "by number, because no table in the tree holds badge "
                        "names.</p>" if named < len(self.gyms) else
                        "Each badge's name is lifted from the line the game "
                        "hands it over with.</p>"))
        rows = []
        for map_id, g in self.gyms:
            leader = (self.trainer_link(g["leader"], 0)
                      if g.get("leader") in self.trainers else
                      '<span class="muted">not derived</span>')
            party = (self.trainers.get(g.get("leader")) or {}).get("party") or []
            levels = [m["lvl"] for m in party if m.get("lvl")]
            rows.append(
                f'<tr><td class="num">{g["badge"]}</td>'
                f"<td>{esc(self.badge_label(g))}</td>"
                f"<td>{self.map_link(map_id, 0)}</td>"
                f"<td>{leader}</td>"
                f'<td class="num">{len(party) or "&mdash;"}</td>'
                f'<td class="num">'
                + (f"{min(levels)}&ndash;{max(levels)}" if levels else "&mdash;")
                + "</td></tr>")
        parts.append('<div class="scroll-x"><table class="data">'
                     "<thead><tr><th>#</th><th>Badge</th><th>Place</th>"
                     "<th>Leader</th><th>Party</th><th>Levels</th></tr>"
                     "</thead>" + "".join(rows) + "</table></div>")
        missing = [] if self.publish else [m for m, g in self.gyms
                                          if not g.get("leader")]
        if missing:
            parts.append('<p class="sub">The leader could not be read for '
                         + ", ".join(self.map_link(m, 0) for m in missing)
                         + ": the badge is awarded by a script whose battle "
                         "this parse cannot trace back. Shown as underived "
                         "rather than filled in with the likeliest name.</p>")
        self.write("gyms.html",
                   self.page(f"Gyms - {self.game}", "\n".join(parts),
                             active="gyms"))

    def build_locations(self):
        rows = []
        for mp in self.maps_ordered:
            const = mp["id"]
            status = self.map_status[const][0]
            species = {s["species"] for t in mp["encounters"].values()
                       for s in t["slots"]}
            w, h = mp["size"]
            filt = " ".join([map_label(const).lower(),
                             pretty(mp["type"]).lower(), status])
            rows.append(
                f'<tr data-status="{status}" data-f="{esc(filt)}">'
                f"<td>{self.map_link(const, 0)}</td>"
                f'<td>{esc(pretty(mp["type"]))}</td>'
                f'<td class="num">{f"{w}&times;{h}" if w else "&mdash;"}</td>'
                f'<td class="num">{len(species) or "&mdash;"}</td>'
                f'<td class="num">{len(mp["trainers"]) or "&mdash;"}</td>'
                f'<td class="num">{len(mp["ground"]) or "&mdash;"}</td>'
                f"<td>{status_badge(status)}</td></tr>")
        n_new = sum(1 for m in self.maps_ordered
                    if self.map_status[m["id"]][0] == "new")
        n_chg = sum(1 for m in self.maps_ordered
                    if self.map_status[m["id"]][0] == "changed")
        n_wild = sum(1 for m in self.maps_ordered if m["encounters"])
        body = f"""<h1>Locations</h1>
<p class="sub">{len(self.maps_ordered)} places &middot; {n_wild} with wild
Pok&eacute;mon &middot; {n_new} new &middot; {n_chg} changed vs. stock
({esc(self.engine_ref)})</p>
<p class="sub">Every map the game defines, drawn from its own block data and
tilesets. "Changed" counts a place whose terrain, encounters, trainers, items
or connections differ from stock &mdash; a redrawn map is a change even when
nothing in it moved.</p>
<div class="controls">
  <input type="text" id="q" placeholder="Filter by place or type&hellip;">
  <label><input type="checkbox" id="only"> Only my changes</label>
</div>
<div class="scroll-x">
<table class="data" id="dex">
<thead><tr>
  <th data-s="t">Place</th><th data-s="t">Type</th>
  <th class="num" data-s="t">Size</th><th class="num" data-s="n">Species</th>
  <th class="num" data-s="n">Trainers</th><th class="num" data-s="n">Items</th>
  <th data-s="t">&Delta;</th>
</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
</div>
<script>
{INDEX_JS}
</script>"""
        self.write("locations.html",
                   self.page(f"Locations - {self.game} dex", body, active="locations"))

    def render_maps(self):
        """One PNG per layout, shared by every map that draws it."""
        if not self.maps_ordered or not self.renderer.available():
            return
        dst = self.out / "assets/maps"
        dst.mkdir(parents=True, exist_ok=True)
        done: dict[str, tuple[str, tuple[int, int]] | None] = {}
        for mp in self.maps_ordered:
            lid = mp["layout"]
            if lid not in done:
                layout = self.layouts.get(lid)
                img = self.renderer.render(layout) if layout else None
                if img:
                    name = f"{slug(lid[len('LAYOUT_'):]) if lid.startswith('LAYOUT_') else slug(lid)}.png"
                    img.convert("RGB").save(dst / name, optimize=True)
                    done[lid] = (name, img.size)
                else:
                    done[lid] = None
            if done[lid]:
                self.map_images[mp["id"]] = done[lid]
        missing = len(self.maps_ordered) - len(self.map_images)
        if missing:
            self.warn(f"{missing} of {len(self.maps_ordered)} maps could not "
                      "be drawn; their pages show everything else")

    def encounter_table(self, table, depth) -> str:
        rows = []
        for slot in table["slots"]:
            sp = slot["species"]
            name = (self.link(sp, depth) if sp in self.f["species"]
                    else esc(pretty(sp)))
            lo, hi = slot.get("min"), slot.get("max")
            lvl = (f"{lo}" if lo == hi else f"{lo}&ndash;{hi}") if lo else "&mdash;"
            rows.append(f"<tr><td>{self.sprite_html(sp, 'icon', depth)}</td>"
                        f"<td>{name}</td>"
                        f'<td class="num">{lvl}</td>'
                        f'<td class="num">{slot["pct"]:.0f}%</td></tr>')
        return ('<div class="scroll-x"><table class="data"><thead><tr><th></th>'
                '<th>Pok&eacute;mon</th><th class="num">Levels</th>'
                '<th class="num">Chance</th></tr></thead>'
                + "".join(rows) + "</table></div>")

    def build_location_pages(self):
        for i, mp in enumerate(self.maps_ordered):
            const = mp["id"]
            status, diffs = self.map_status[const]
            name = map_label(const)
            w, h = mp["size"]
            facts = [pretty(mp["type"])] if mp["type"] else []
            if w:
                facts.append(f"{w}&times;{h} blocks")
            if mp["weather"] and not mp["weather"].endswith("NONE"):
                facts.append(pretty(mp["weather"]).lower() + " weather")
            if mp["npcs"]:
                facts.append(f'{mp["npcs"]} other '
                             + ("person" if mp["npcs"] == 1 else "people"))
            parts = [f"<h1>{esc(name)} {status_badge(status)}</h1>",
                     f'<p class="sub">{" &middot; ".join(facts)} &middot; '
                     f'<span class="ident">{esc(const)}</span></p>']
            if mp.get("gym"):
                parts.append(self.gym_block(const, mp["gym"], 1))
            checks = self.checks_block(mp, 1)
            if checks:
                parts.append(checks)

            # C2: the sentence the route order gives this place, shown here
            # as well as on the thread -- written once, read twice, and it
            # says where it was written.
            note = self.place_notes().get(const)
            if note:
                text, beat = note
                parts.append(self.authored_note(
                    esc(text), depth=1,
                    tail=f'<p class="sub"><a href="../thread.html#beat-'
                         f'{esc(beat)}">On the thread, in beat {esc(beat)} '
                         "&rarr;</a></p>"))

            rec = self.map_images.get(const)
            if rec:
                img_name, (iw, ih) = rec
                parts.append(
                    f'<div class="mapshot"><img loading="lazy" '
                    f'src="../assets/maps/{img_name}" width="{iw}" '
                    f'height="{ih}" alt="{esc(name)}, drawn from its own '
                    'block data"></div>')

            # Where its edges lead. Connections are the walkable seams;
            # warps are the doors.
            links = []
            for c in mp["connections"]:
                links.append(f'{esc(str(c.get("direction") or ""))}: '
                             + self.map_link(c["map"], 1))
            doors = sorted({d for d in mp["warps"] if d != const})
            if links or doors:
                parts.append("<h2>Ways out</h2>")
                if links:
                    parts.append('<p class="sub">Walk off the edge: '
                                 + ", ".join(links) + "</p>")
                if doors:
                    parts.append('<p class="sub">Doors and stairs lead to '
                                 + ", ".join(self.map_link(d, 1)
                                             for d in doors) + "</p>")

            for method, table in mp["encounters"].items():
                rate = table.get("rate")
                head = f"<h2>{esc(method)}</h2>"
                if rate:
                    head += (f'<p class="sub">The table\'s own encounter rate '
                             f"is {rate}.</p>")
                parts.append(head + self.encounter_table(table, 1))

            here = [t for t in mp["trainers"] if t.get("trainer")]
            unknown = len(mp["trainers"]) - len(here)
            if mp["trainers"]:
                rows = []
                for spot in here:
                    tr = self.trainers.get(spot["trainer"]) or {}
                    party = ", ".join(
                        (self.link(m["species"], 1)
                         if m["species"] in self.f["species"]
                         else esc(pretty(m["species"])))
                        + (f' {m["lvl"]}' if m.get("lvl") else "")
                        for m in tr.get("party", []))
                    rows.append(
                        f"<tr><td>{self.trainer_link(spot['trainer'], 1)}</td>"
                        f'<td>{esc(self.class_label(tr.get("class")))}</td>'
                        f'<td class="num">{spot["x"]}, {spot["y"]}</td>'
                        f"<td>{party}</td></tr>")
                parts.append(f"<h2>Trainers here ({len(mp['trainers'])})</h2>")
                if rows:
                    parts.append('<div class="scroll-x"><table class="data">'
                                 "<thead><tr><th>Trainer</th><th>Class</th>"
                                 '<th class="num">At</th><th>Team</th></tr>'
                                 "</thead>" + "".join(rows) + "</table></div>")
                if unknown:
                    parts.append(f'<p class="sub">{unknown} more stand here '
                                 "whose script names no trainer &mdash; a "
                                 "rematch or a scripted battle this reader "
                                 "cannot resolve.</p>")

            if mp["ground"]:
                rows = "".join(
                    f"<tr><td>{self.item_link(g['item'], 1)}</td>"
                    f'<td>{"hidden" if g["hidden"] else "in plain sight"}</td>'
                    f'<td class="num">{g["x"]}, {g["y"]}</td></tr>'
                    for g in mp["ground"])
                parts.append(f"<h2>Items here ({len(mp['ground'])})</h2>"
                             '<div class="scroll-x"><table class="data">'
                             "<thead><tr><th>Item</th><th>How</th>"
                             '<th class="num">At</th></tr></thead>'
                             + rows + "</table></div>")

            # Every line this place says, folded away: complete enough to
            # review a hack's writing in one place, quiet enough not to bury
            # the map above it.
            if mp["text"]:
                blocks = "".join(
                    f'<div class="line"><span class="ident">{esc(lab)}</span>'
                    + "".join(f"<p>{esc(p)}</p>" for p in paras) + "</div>"
                    for lab, paras in mp["text"] if paras)
                parts.append(
                    f'<details class="says"><summary>What is said here '
                    f'({len(mp["text"])} passages)</summary>{blocks}</details>')

            if status == "changed":
                parts.append(self.diff_table(diffs))

            prev_mp = self.maps_ordered[i - 1] if i > 0 else None
            next_mp = (self.maps_ordered[i + 1]
                       if i + 1 < len(self.maps_ordered) else None)
            nav = ['<div class="pagenav">']
            nav.append("<span>&larr; " + self.map_link(prev_mp["id"], 1)
                       + "</span>" if prev_mp else "<span></span>")
            nav.append("<span>" + self.map_link(next_mp["id"], 1)
                       + " &rarr;</span>" if next_mp else "<span></span>")
            nav.append("</div>")
            parts.append("".join(nav))

            self.write(f"locations/{slug(const)}.html",
                       self.page(f"{name} - {self.game} dex", "\n".join(parts),
                            depth=1, active="locations"))

    def build_changes(self):
        news = [sp for sp in self.ordered if self.status[sp["const"]][0] == "new"]
        chgs = [sp for sp in self.ordered
                if self.status[sp["const"]][0] == "changed"]
        parts = [f"<h1>Changes</h1><p class=\"sub\">Everything this game adds "
                 f"or alters relative to stock ({esc(self.engine_ref)}), "
                 "derived from the source trees, not from notes.</p>"]

        # dex-site-requirements.md §5, "What's different from vanilla":
        # Odyssey's pattern, a short authored statement of what this hack is
        # FOR, sitting above the exhaustive derived diff rather than instead
        # of it. It is the design doc's own pitch and its own locked
        # decisions -- the two things there that answer the question -- and
        # it wears the same dashed label as the Roadmap so the line between
        # the written half and the read half is never in doubt.
        d = self.design or {}
        pillars = []
        if d.get("pitch"):
            pillars.append(f"<p><strong>{esc(d['pitch'])}</strong></p>")
        if d.get("loop"):
            pillars.append(f'<p class="sub">Core loop: {esc(d["loop"])}</p>')
        # A dated log of what the builder decided and when is the design
        # process, not the game -- internal, and stripped on publish (§7).
        if d.get("decisions") and not self.publish:
            rows = "".join(
                f"<tr><td>{esc(row[1])}</td>"
                f'<td class="muted">{esc(row[0])}</td></tr>'
                for row in d["decisions"] if len(row) > 1)
            pillars.append('<details><summary>The decisions this game locked '
                           f'({len(d["decisions"])})</summary>'
                           '<div class="scroll-x"><table class="data wrap">'
                           "<thead><tr><th>Decision</th><th>When</th></tr>"
                           f"</thead>{rows}</table></div></details>")
        if pillars:
            parts.append('<div class="authored"><span class="lbl">From the '
                         "design doc, not from the game</span>"
                         + "".join(pillars) +
                         '<p class="sub">Written by hand, and true only in '
                         "the sense that someone meant it. Everything below "
                         "this box is read from the source tree.</p></div>")

        parts.append(f"<h2>New species ({len(news)})</h2>")
        if news:
            rows = []
            for sp in news:
                const = sp["const"]
                stats = [sp.get(k) for k in ("baseHP", "baseAttack",
                                             "baseDefense", "baseSpAttack",
                                             "baseSpDefense", "baseSpeed")]
                total = sum(v for v in stats) if all(
                    v is not None for v in stats) else None
                evo = "; ".join(f"{evo_text(m, p)} → {pretty(t)}"
                                for m, p, t in sp.get("evolutions", []))
                rows.append(
                    f"<tr><td>{self.sprite_html(const, 'icon', 0)}</td>"
                    f"<td>{self.link(const, 0)}</td>"
                    "<td>" + " ".join(type_badge(t)
                                      for t in sp.get("types", [])) + "</td>"
                    f'<td class="num">{total if total is not None else "&mdash;"}</td>'
                    f"<td>{esc(evo) if evo else '&mdash;'}</td></tr>")
            parts.append('<table class="data"><thead><tr><th></th><th>Name</th>'
                         '<th>Types</th><th class="num">BST</th><th>Evolves</th>'
                         "</tr></thead>" + "".join(rows) + "</table>")
        else:
            parts.append('<p class="sub">None yet.</p>')

        parts.append(f"<h2>Changed species ({len(chgs)})</h2>")
        if chgs:
            rows = []
            for sp in chgs:
                const = sp["const"]
                _, diffs = self.status[const]
                rows.append(
                    f"<tr><td>{self.sprite_html(const, 'icon', 0)}</td>"
                    f"<td>{self.link(const, 0)}</td>"
                    f"<td>{self.change_summary(diffs)}</td></tr>")
            parts.append('<table class="data"><thead><tr><th></th><th>Name</th>'
                         "<th>What changed</th></tr></thead>"
                         + "".join(rows) + "</table>")
        else:
            parts.append('<p class="sub">No stock species has been altered.</p>')

        # Track A1: moves, abilities, items -- same new/changed shape as
        # species, one category each, so changes.html stays the single
        # place that answers "what has this game actually done."
        move_news = [m for m in self.moves_ordered
                    if self.move_status[m["const"]][0] == "new"]
        move_chgs = [m for m in self.moves_ordered
                    if self.move_status[m["const"]][0] == "changed"]
        parts.append(f"<h2>New moves ({len(move_news)})</h2>")
        if move_news:
            rows = "".join(
                f"<tr><td>{self.move_link(m['const'], 0)}</td>"
                f"<td>{type_badge(m['type']) if m.get('type') else ''}</td>"
                f'<td class="num">{m.get("power", "&mdash;")}</td></tr>'
                for m in move_news)
            parts.append('<table class="data"><thead><tr><th>Name</th>'
                        '<th>Type</th><th class="num">Power</th>'
                        "</tr></thead>" + rows + "</table>")
        else:
            parts.append('<p class="sub">None yet.</p>')
        parts.append(f"<h2>Changed moves ({len(move_chgs)})</h2>")
        if move_chgs:
            rows = "".join(
                f"<tr><td>{self.move_link(m['const'], 0)}</td>"
                f"<td>{self.change_summary(self.move_status[m['const']][1])}</td></tr>"
                for m in move_chgs)
            parts.append('<table class="data"><thead><tr><th>Name</th>'
                        "<th>What changed</th></tr></thead>" + rows + "</table>")
        else:
            parts.append('<p class="sub">No stock move has been altered.</p>')

        shown_ab = [a for a in self.abilities_ordered if a["const"] != "ABILITY_NONE"]
        ab_news = [a for a in shown_ab if self.ability_status[a["const"]][0] == "new"]
        ab_chgs = [a for a in shown_ab if self.ability_status[a["const"]][0] == "changed"]
        parts.append(f"<h2>New abilities ({len(ab_news)})</h2>")
        if ab_news:
            rows = "".join(
                f"<tr><td>{self.ability_link(a['const'], 0)}</td>"
                f'<td class="desc">{esc(a.get("description", ""))}</td></tr>'
                for a in ab_news)
            parts.append('<table class="data"><thead><tr><th>Name</th>'
                        "<th>Effect</th></tr></thead>" + rows + "</table>")
        else:
            parts.append('<p class="sub">None yet.</p>')
        parts.append(f"<h2>Changed abilities ({len(ab_chgs)})</h2>")
        if ab_chgs:
            rows = "".join(
                f"<tr><td>{self.ability_link(a['const'], 0)}</td>"
                f"<td>{self.change_summary(self.ability_status[a['const']][1])}</td></tr>"
                for a in ab_chgs)
            parts.append('<table class="data"><thead><tr><th>Name</th>'
                        "<th>What changed</th></tr></thead>" + rows + "</table>")
        else:
            parts.append('<p class="sub">No stock ability has been altered.</p>')

        shown_it = [it for it in self.items_ordered if it["const"] != "ITEM_NONE"]
        it_news = [it for it in shown_it if self.item_status[it["const"]][0] == "new"]
        it_chgs = [it for it in shown_it if self.item_status[it["const"]][0] == "changed"]
        parts.append(f"<h2>New items ({len(it_news)})</h2>")
        if it_news:
            rows = "".join(
                f"<tr><td>{self.item_link(it['const'], 0)}</td>"
                f'<td class="num">{it.get("price", "&mdash;")}</td></tr>'
                for it in it_news)
            parts.append('<table class="data"><thead><tr><th>Name</th>'
                        '<th class="num">Price</th></tr></thead>' + rows + "</table>")
        else:
            parts.append('<p class="sub">None yet.</p>')
        parts.append(f"<h2>Changed items ({len(it_chgs)})</h2>")
        if it_chgs:
            rows = "".join(
                f"<tr><td>{self.item_link(it['const'], 0)}</td>"
                f"<td>{self.change_summary(self.item_status[it['const']][1])}</td></tr>"
                for it in it_chgs)
            parts.append('<table class="data"><thead><tr><th>Name</th>'
                        "<th>What changed</th></tr></thead>" + rows + "</table>")
        else:
            parts.append('<p class="sub">No stock item has been altered.</p>')

        # Track A2: trainers and encounter tables, same two-category shape.
        tr_news = [t for t in self.trainers_ordered
                   if self.trainer_status[t["const"]][0] == "new"]
        tr_chgs = [t for t in self.trainers_ordered
                   if self.trainer_status[t["const"]][0] == "changed"]
        parts.append(f"<h2>New trainers ({len(tr_news)})</h2>")
        if tr_news:
            rows = "".join(
                f"<tr><td>{self.trainer_link(t['const'], 0)}</td>"
                f"<td>{esc(self.class_label(t['class']))}</td>"
                f'<td class="num">{len(t["party"])}</td>'
                f'<td class="num">{t["maxLevel"] or "&mdash;"}</td></tr>'
                for t in tr_news)
            parts.append('<table class="data"><thead><tr><th>Name</th>'
                         '<th>Class</th><th class="num">Party</th>'
                         '<th class="num">Max Lv.</th></tr></thead>'
                         + rows + "</table>")
        else:
            parts.append('<p class="sub">None yet.</p>')
        parts.append(f"<h2>Changed trainers ({len(tr_chgs)})</h2>")
        if tr_chgs:
            rows = "".join(
                f"<tr><td>{self.trainer_link(t['const'], 0)}</td>"
                f"<td>{self.change_summary(self.trainer_status[t['const']][1])}"
                "</td></tr>" for t in tr_chgs)
            parts.append('<table class="data"><thead><tr><th>Name</th>'
                         "<th>What changed</th></tr></thead>" + rows + "</table>")
        else:
            parts.append('<p class="sub">No stock trainer has been altered.</p>')

        mp_news = [m for m in self.maps_ordered
                   if self.map_status[m["id"]][0] == "new"]
        mp_chgs = [m for m in self.maps_ordered
                   if self.map_status[m["id"]][0] == "changed"]
        parts.append(f"<h2>New places ({len(mp_news)})</h2>")
        if mp_news:
            rows = "".join(
                f"<tr><td>{self.map_link(m['id'], 0)}</td>"
                f'<td>{esc(pretty(m["type"]))}</td>'
                f'<td class="num">{len(m["trainers"]) or "&mdash;"}</td>'
                f'<td class="num">{len(m["ground"]) or "&mdash;"}</td></tr>'
                for m in mp_news)
            parts.append('<table class="data"><thead><tr><th>Place</th>'
                         '<th>Type</th><th class="num">Trainers</th>'
                         '<th class="num">Items</th></tr></thead>'
                         + rows + "</table>")
        else:
            parts.append('<p class="sub">None yet.</p>')
        parts.append(f"<h2>Changed places ({len(mp_chgs)})</h2>")
        if mp_chgs:
            rows = "".join(
                f"<tr><td>{self.map_link(m['id'], 0)}</td>"
                f"<td>{self.change_summary(self.map_status[m['id']][1])}"
                "</td></tr>" for m in mp_chgs)
            parts.append('<table class="data"><thead><tr><th>Place</th>'
                         "<th>What changed</th></tr></thead>" + rows + "</table>")
        else:
            parts.append('<p class="sub">No stock place has been altered.</p>')

        self.write("changes.html",
                   self.page(f"Changes - {self.game} dex", "\n".join(parts), active="changes"))

    # -- Track B2: the dev log ---------------------------------------------

    # Where each kind of thing's page lives, and what still holds one.
    _DEVLOG_PAGES = {"species": "pokemon", "moves": "moves",
                     "abilities": "abilities", "items": "items",
                     "trainers": "trainers", "places": "locations"}

    def devlog_categories(self):
        """(key, label, constants in display order, lookup, status map,
        compared fields) for every kind of thing the log tracks -- the same
        six the Changes page lists, in the same order."""
        return [
            ("species", "Species", [sp["const"] for sp in self.ordered],
             self.f["species"], self.status, COMPARE_FIELDS),
            ("moves", "Moves", [m["const"] for m in self.moves_ordered],
             self.moves, self.move_status, MOVE_COMPARE_FIELDS),
            ("abilities", "Abilities",
             [a["const"] for a in self.abilities_ordered
              if a["const"] != "ABILITY_NONE"],
             self.abilities, self.ability_status, ABILITY_COMPARE_FIELDS),
            ("items", "Items",
             [i["const"] for i in self.items_ordered
              if i["const"] != "ITEM_NONE"],
             self.items, self.item_status, ITEM_COMPARE_FIELDS),
            ("trainers", "Trainers", [t["const"] for t in self.trainers_ordered],
             self.trainers, self.trainer_status, TRAINER_COMPARE_FIELDS),
            ("places", "Places", [m["id"] for m in self.maps_ordered],
             self.maps, self.map_status, MAP_COMPARE_FIELDS),
        ]

    def stock_keys(self, cat) -> set[str]:
        """What the pinned engine has in a category. The half of the diff
        the fork's own tables cannot show, because a thing this game deleted
        leaves nothing behind to iterate."""
        e = self.e or {}
        if cat == "places":
            return set(e.get("maps") or {})
        return set(e.get(cat) or {})

    def devlog_lookup(self, cat) -> dict:
        return {"species": self.f["species"], "moves": self.moves,
                "abilities": self.abilities, "items": self.items,
                "trainers": self.trainers, "places": self.maps}[cat]

    def devlog_name(self, cat, const) -> str:
        if cat == "places":
            return map_label(const)
        here = {"species": lambda: (self.f["species"].get(const) or {}).get("name"),
                "moves": lambda: self.move_name(const),
                "abilities": lambda: self.ability_name(const),
                "items": lambda: self.item_name(const),
                "trainers": lambda: self.trainer_name(const)}[cat]()
        # A thing this game DELETED has no name left in the fork, and the
        # fallbacks above would print its constant. The pin still holds it,
        # and what stock called it is the right name for a line that says
        # stock lost it -- still read, just read from the other tree.
        if not here or here == pretty(const):
            stock = (self.e.get("species" if cat == "species" else cat)
                     or {}).get(const) or {}
            if stock.get("name"):
                return stock["name"]
        return here or pretty(const)

    def devlog_entry(self) -> dict:
        """This run's snapshot: how much of each kind of thing the game has,
        which of them are this game's own doing, and a fingerprint per entry
        so the NEXT build can tell which of them moved."""
        h = self.health or {}
        cats = {}
        for key, _label, keys, lookup, status_map, fields in self.devlog_categories():
            entries, n_new, n_chg = {}, 0, 0
            for const in keys:
                status, diffs = status_map[const]
                if status == "same":
                    continue
                if status == "new":
                    n_new += 1
                else:
                    n_chg += 1
                if len(entries) >= DEVLOG_CAP:
                    continue
                entries[const] = {
                    "name": self.devlog_name(key, const),
                    "status": status,
                    "digest": devlog_digest(lookup[const], fields),
                    "summary": "; ".join(self.change_bits(diffs)),
                }
            # §6.2 item 4, the log's blind spot, closed. A stock entry
            # deleted outright never differed from stock while it existed,
            # so it is in no snapshot's `entries` and only the total ever
            # recorded that it went. The fork's own tables cannot show it
            # either -- a deleted thing leaves nothing to iterate. But the
            # PIN still has it, so "in stock and not here" names it exactly,
            # and it is recorded per snapshot rather than inferred between
            # two, which keeps it true even for the first record.
            removed = sorted(self.stock_keys(key) - set(keys))
            cats[key] = {"total": len(keys), "new": n_new, "changed": n_chg,
                         "capped": n_new + n_chg > len(entries),
                         "removed": removed[:DEVLOG_CAP],
                         "removed_total": len(removed),
                         "entries": entries}
        rom, git = h.get("rom"), h.get("git")
        ch = h.get("checks") or {}
        at = int(h.get("now") or time.time())
        return {
            "version": DEVLOG_VERSION,
            "at": at,
            "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(at)),
            "game": self.game,
            "engine": self.engine_ref,
            "rom": {"size": rom["size"]} if rom else None,
            "git": ({"sha": git.get("sha"), "branch": git.get("branch"),
                     "subject": git.get("subject")} if git else None),
            "checks": {"specs": ch.get("specs", 0),
                       "runnable": ch.get("runnable", 0),
                       "asserts": ch.get("asserts", 0)},
            "categories": cats,
        }

    def devlog_link(self, cat, const, name) -> str:
        """The name as the log RECORDED it, linked to a page only if that
        entry is still in the tree. A species renamed since keeps the name
        the record was written with: the history says what was true then."""
        text = esc(name or pretty(const))
        if const not in self.devlog_lookup(cat):
            return text
        return f'<a href="{self._DEVLOG_PAGES[cat]}/{slug(const)}.html">{text}</a>'

    def log_rows(self, delta, old, new) -> str:
        """One build's movement, one card per category. Names and summaries
        come from the snapshots that recorded them, never from the tree as
        it stands now."""
        cards = []
        for key, label, *_ in self.devlog_categories():
            d = delta.get(key)
            if not d:
                continue
            now = (((new or {}).get("categories") or {}).get(key) or {}).get("entries") or {}
            was = (((old or {}).get("categories") or {}).get(key) or {}).get("entries") or {}
            here = self.devlog_lookup(key)
            rows = []

            def row(badge, const, e, note, absence=True):
                # A name with no page behind it needs saying why, once: the
                # thing it named is not in the tree any more.
                if absence and const not in here:
                    note = (f"{note}, and gone from the tree" if note
                            else "gone from the tree")
                return (f"<li>{badge} "
                        + self.devlog_link(key, const, e.get("name"))
                        + (f' <span class="muted">{esc(note)}</span>'
                           if note else "") + "</li>")

            for const in d["added"]:
                e = now.get(const) or {}
                rows.append(row(status_badge(e.get("status") or "new"), const,
                                e, e.get("summary") or ""))
            for const in d["edited"]:
                e = now.get(const) or {}
                rows.append(row('<span class="badge changed">EDIT</span>',
                                const, e,
                                e.get("summary")
                                or ("reworked" if e.get("status") == "new"
                                    else "changed again")))
            for const in d["gone"]:
                # Two different endings look identical from here: it matches
                # stock again, or it left the tree. Which one is readable --
                # whether the thing still exists -- so it is read, not
                # guessed at.
                e = was.get(const) or {}
                rows.append(row('<span class="badge stock">STOCK</span>',
                                const, e,
                                "back to stock" if const in here
                                else "no longer in the tree", absence=False))
            # A stock entry deleted outright. It has no page (it is not in
            # the tree) and no snapshot name (it never differed from stock
            # while it existed), so the constant IS the name -- prettified,
            # and never linked to a page that cannot exist.
            for const in d.get("deleted") or []:
                rows.append('<li><span class="badge stock">CUT</span> '
                            f"{esc(self.devlog_name(key, const))}"
                            ' <span class="muted">stock entry removed from '
                            "the tree</span></li>")

            n = (len(d["added"]) + len(d["edited"]) + len(d["gone"])
                 + len(d.get("deleted") or []))
            notes = []
            if d.get("from") is not None and d["from"] != d.get("to"):
                notes.append(f'<li><span class="badge stock">TOTAL</span> '
                             f'<span class="muted">{d["from"]} → {d["to"]} '
                             "in the tree</span></li>")
            if d.get("partial"):
                notes.append('<li><span class="muted">One of these two '
                             "snapshots was past its naming cap, so this list "
                             "is short where the counts are not.</span></li>")
            cards.append(f'<div class="logcat"><h3>{esc(label)}'
                         + (f" &middot; {n}" if n else "")
                         + f'</h3><ul class="loglist">{"".join(notes + rows)}'
                         "</ul></div>")
        return f'<div class="logcats">{"".join(cards)}</div>' if cards else ""

    def build_devlog(self):
        """The site becoming its own changelog. One section per recorded
        build, newest first, each saying what moved since the build before
        it -- and, at the top, what has moved since the newest record."""
        hist = self.history or []
        cur = self.entry or self.devlog_entry()
        if self.publish:
            # Track D1: the same history, read as patch notes. What changed
            # between two releases is exactly what a player wants; the ROM's
            # size, the commit it came from and how many assertions guarded
            # it are the builder's half, and go (§7).
            parts = [
                "<h1>Patch notes</h1>",
                '<p class="sub">One entry per build of this game that '
                "passed its checks, newest first, each saying what changed "
                "since the build before it. The list is derived from the "
                "game itself at each of those builds, so it cannot forget "
                "to mention something.</p>",
            ]
        else:
            parts = [
                "<h1>Dev log</h1>",
                '<p class="sub">One entry per green build, written when the '
                "build ritual regenerates this site and kept in the game "
                "repo's own git &mdash; the only part of this site that is "
                "stored rather than re-derived, because a source tree can "
                "only ever show its present state. Every line below is the "
                "arithmetic between two of those records.</p>",
            ]

        # The uncommitted, unbuilt present: work in progress by definition,
        # and nothing a released site should be showing.
        if self.publish:
            if not hist:
                parts.append('<p class="sub">No build of this game has been '
                             "recorded yet, so there is nothing to report "
                             "changed.</p>")
        elif hist:
            newest = hist[-1]
            since = devlog_delta(newest, cur)
            parts.append("<h2>Since the last recorded build</h2>")
            if since:
                parts.append(
                    f'<p class="sub">The tree has moved on from the build '
                    f'recorded {esc(newest.get("date") or "earlier")}. None of '
                    "this is in the history yet; the next green build records "
                    "it.</p>")
                parts.append(self.log_rows(since, newest, cur))
            else:
                parts.append('<p class="sub">The tree says exactly what the '
                             f'build recorded {esc(newest.get("date") or "earlier")} '
                             "said. Nothing has moved since.</p>")
        else:
            parts.append(
                '<p class="sub">No build has been recorded yet. The history '
                "starts at the next green build; it is never back-filled, "
                "because a past reconstructed from a tree that only shows its "
                "present would be a story rather than a record.</p>")

        for i in range(len(hist) - 1, -1, -1):
            e, prev = hist[i], (hist[i - 1] if i else None)
            g = e.get("git") or {}
            meta = []
            # The commit, the byte cost and the assertion count: three
            # numbers about the build rather than about the game, so the
            # publish render leaves the meta strip empty (§7).
            if not self.publish:
                if g.get("sha"):
                    meta.append(
                        f'<span><code>{esc(g["sha"])}</code>'
                        + (f' {esc(g["subject"])}' if g.get("subject") else "")
                        + "</span>")
                rom, prom = e.get("rom") or {}, (prev or {}).get("rom") or {}
                if rom.get("size"):
                    cost = (human_delta(rom["size"] - prom["size"])
                            if prom.get("size") else "")
                    meta.append(f'<span>ROM {esc(human_size(rom["size"]))}'
                                + (f' <span class="muted">{esc(cost)}</span>'
                                   if cost else "") + "</span>")
                ch, pch = e.get("checks") or {}, (prev or {}).get("checks") or {}
                if ch.get("asserts"):
                    d = ch["asserts"] - pch["asserts"] if pch.get("asserts") else 0
                    meta.append(f'<span>{ch["asserts"]} assertions'
                                + (f' <span class="muted">{d:+d}</span>'
                                   if d else "")
                                + f' &middot; {ch.get("specs", 0)} checks</span>')
            body = [f'<section class="build"><h2>{esc(e.get("date") or e.get("file") or "")}'
                    + (f'<span class="when">{human_age(cur["at"] - e["at"])}</span>'
                       if e.get("at") and cur.get("at") else "")
                    + "</h2>"]
            if meta:
                body.append(f'<div class="buildmeta">{"".join(meta)}</div>')
            if prev is None:
                carried = []
                for k, label, *_ in self.devlog_categories():
                    c = e["categories"].get(k) or {}
                    # A zero is not worth a clause: only the halves that
                    # actually carried something are named.
                    half = [f"{c[w]} {w}" for w in ("new", "changed") if c.get(w)]
                    if half:
                        carried.append(" and ".join(half) + f" {label.lower()}")
                counts = ", ".join(carried)
                body.append('<p class="sub">The first recorded build &mdash; the '
                            "baseline everything above is measured from. It "
                            "carried "
                            + (esc(counts) if counts else "nothing of this "
                               "game's own")
                            + f' against stock {esc(e.get("engine") or "")}.</p>')
            else:
                rows = self.log_rows(devlog_delta(prev, e), prev, e)
                body.append(rows or '<p class="sub">A green build that moved '
                                    "none of this game's data.</p>")
            parts.append("".join(body) + "</section>")

        heading = "Patch notes" if self.publish else "Dev log"
        self.write("devlog.html",
                   self.page(f"{heading} - {self.game}", "\n".join(parts),
                             active="devlog"))

    # -- Track B3: the roadmap ---------------------------------------------

    def authored_note(self, text, depth=0, tail="") -> str:
        """The label every authored block on this site wears. It says the
        same thing everywhere, because the reader has to be able to learn it
        once: this part was written, not read off the game."""
        return ('<div class="authored"><span class="lbl">From the design '
                f"doc, not from the game</span><p>{text}</p>{tail}</div>")

    def species_notes(self) -> dict[str, str]:
        """C2, species half: the design doc's own art brief per species,
        matched by the constant its heading names or, failing that, by the
        species' name. A brief naming neither is a brief about something
        this tree does not have, and it is not attached to anything."""
        if self._species_notes is None:
            by_name = {re.sub(r"[^a-z0-9]", "", (sp.get("name") or "").lower()):
                       sp["const"] for sp in self.f["species"].values()}
            out = {}
            for b in (self.design or {}).get("briefs") or []:
                const = b.get("const")
                if const not in self.f["species"]:
                    const = by_name.get(
                        re.sub(r"[^a-z0-9]", "", (b.get("name") or "").lower()))
                if const:
                    out[const] = b["text"]
            self._species_notes = out
        return self._species_notes

    def place_notes(self) -> dict[str, tuple[str, str]]:
        """C2, place half: a place's sentence in the route order, which the
        thread already shows, put on the place's own page as well. One
        sentence, written once, and it says where it was written."""
        if self._place_notes is None:
            idx, out = self.place_index(), {}
            for beat in (self.design or {}).get("route") or []:
                for spot in beat["places"]:
                    mid = idx.get(re.sub(r"[^a-z0-9]", "",
                                         spot["name"].lower()))
                    if mid and spot.get("note") and mid not in out:
                        out[mid] = (spot["note"], beat["n"])
            self._place_notes = out
        return self._place_notes

    def owned_constants(self) -> set[str]:
        """Everything the tree contains that this game put there. What the
        roadmap's third contradiction check is measured against."""
        owned = set()
        for key, _l, keys, _lookup, status, _f in self.devlog_categories():
            owned |= {c for c in keys if status[c][0] == "new"}
        return owned

    def build_whats_next(self):
        """Track D1: the roadmap, for players.

        The builder's roadmap is a ledger -- statuses, dates, contradictions,
        a cut list, a next-actions queue. A player wants one thing from it:
        is there more coming, and roughly what. So this reads the same slice
        plan and prints only the slices not yet marked done, by name and by
        the one sentence the doc writes about what each is FOR. The status is
        used to choose what to show and is never shown; no date reaches this
        page at all. Nothing is invented -- a plan with nothing left in it
        says so rather than promising."""
        d = self.design or {}
        parts = ['<p class="eyebrow">Written by hand, not read from the game</p>',
                 "<h1>What's next</h1>"]
        # "cut" is a decision not to build, and a plan whose status word the
        # doc did not recognise is not evidence of anything -- neither is a
        # promise, so neither is shown. Nor is a slice the doc's own internal
        # evidence says has probably shipped already (doubted_slices).
        doubted = doubted_slices(d, self.owned_constants())
        coming = [s for i, s in enumerate(d.get("slices") or [])
                  if s.get("status") in ("planned", "building")
                  and i not in doubted]
        if not d.get("found") or not coming:
            parts.append(self.authored_note(
                "Nothing here is promised. This page lists whatever the "
                "person building this game has written down as still to "
                "come, and right now that list is empty &mdash; either "
                "because the plan has nothing outstanding in it, or because "
                "it has not been written down. Everything the game already "
                "contains is on the rest of this site."))
            self.write("roadmap.html",
                       self.page(f"What's next - {self.game}",
                                 "\n".join(parts), active="roadmap"))
            return

        parts.append(self.authored_note(
            "Everything below was written by hand in this game's design "
            "notes, and it is the only page here that was. It is intent, not "
            "fact: it can change, it can slip, and it can be dropped "
            "altogether. Every other page on this site is read out of the "
            "game itself and cannot be wrong in that way."))
        cards = []
        for s in coming:
            soul = s.get("soul") or ""
            cards.append('<div class="slice">'
                         f'<h3>{esc(s["title"])}</h3>'
                         + (f"<p>{esc(soul)}</p>" if soul else "")
                         + "</div>")
        parts.append(f'<div class="plan">{"".join(cards)}</div>')
        self.write("roadmap.html",
                   self.page(f"What's next - {self.game}", "\n".join(parts),
                             active="roadmap"))

    def build_roadmap(self):
        if self.publish:
            return self.build_whats_next()
        d = self.design or {}
        parts = ["<h1>Roadmap</h1>"]
        if not d.get("found"):
            parts.append(self.authored_note(
                "This game has no design doc yet, so there is nothing here "
                "to read. Every other page on this site is derived from the "
                "source tree; this one is the exception, and an exception "
                "with no source is simply empty."))
            self.write("roadmap.html",
                       self.page(f"Roadmap - {self.game}", "\n".join(parts),
                            active="roadmap"))
            return

        parts.append(self.authored_note(
            "Everything on this page was written by hand in this game's "
            "design doc and read from there unchanged. It is a statement of "
            "intent: it can be out of date, it can be wrong, and nothing on "
            "it is proved by the source tree the way every other page here "
            "is. That is why it is dashed and everything else is not. Where "
            "the doc stops agreeing with itself, that is said below rather "
            "than tidied away."))

        phase = d.get("phase")
        if phase:
            entered = (f' <span class="muted">since {esc(d["entered"])}</span>'
                       if d.get("entered") else "")
            parts.append(f'<p class="sub">Phase: <strong>{esc(phase)}</strong>'
                         f"{entered}"
                         + (f' &middot; {esc(d["archetype"])}'
                            if d.get("archetype") else "") + "</p>")

        problems = design_contradictions(d, self.owned_constants())
        if problems:
            parts.append("<h2>Where the doc no longer agrees with itself</h2>")
            parts.append('<ul class="flags">'
                         + "".join(f"<li>{esc(p)}</li>" for p in problems)
                         + "</ul>")

        slices = d.get("slices") or []
        if slices:
            parts.append(f"<h2>Slice plan ({len(slices)})</h2>")
            parts.append('<p class="sub">The plan\'s own words. A slice is '
                         "marked done by the person who wrote it &mdash; this "
                         "page reports that mark, it does not check it. What "
                         'the game actually contains is on <a href="index.html">'
                         'Home</a> and <a href="changes.html">Changes</a>.</p>')
            cards = []
            for s in slices:
                status = s["status"] or "unclear"
                chip = (f'<span class="chip {esc(status)}">{esc(status)}</span>'
                        if s["status"] else
                        '<span class="chip unclear">status unclear</span>')
                rows = []
                for label, key in (("Soul", "soul"),
                                   ("Fails if", "failure_condition"),
                                   ("Faking", "fake"),
                                   ("Not faking", "do_not_fake")):
                    if s.get(key):
                        rows.append(f"<dt>{label}</dt><dd>{esc(s[key])}</dd>")
                note = ("" if s["status"] else
                        f'<dd class="muted">{esc(clip(s["status_raw"], 200))}</dd>')
                if note:
                    rows.insert(0, "<dt>Reads</dt>" + note)
                cards.append(
                    f'<div class="slice {esc(status)}">'
                    f'<h3><span class="num">Slice {esc(s["n"])}</span>'
                    f'{esc(s["title"])} {chip}</h3>'
                    + (f"<dl>{''.join(rows)}</dl>" if rows else "")
                    + "</div>")
            parts.append(f'<div class="plan">{"".join(cards)}</div>')

        if d.get("next"):
            parts.append("<h2>Next actions</h2>")
            parts.append("<ol>" + "".join(f"<li>{esc(n)}</li>"
                                          for n in d["next"]) + "</ol>")
        if d.get("questions"):
            parts.append("<h2>Open questions</h2>")
            parts.append("<ul>" + "".join(f"<li>{esc(q)}</li>"
                                          for q in d["questions"]) + "</ul>")
        elif "none" in (d.get("questions_inline") or "").lower():
            parts.append("<h2>Open questions</h2>"
                         '<p class="sub">The doc says none.</p>')

        if d.get("cuts"):
            parts.append(f'<h2>Cut, on purpose ({len(d["cuts"])})</h2>')
            parts.append('<p class="sub">Recorded so they do not creep back '
                         "in unexamined &mdash; the doc's own reason for "
                         "keeping this list.</p>")
            rows = "".join(
                "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row[:4]) + "</tr>"
                for row in d["cuts"])
            parts.append('<div class="scroll-x"><table class="data wrap">'
                         "<thead><tr><th>Date</th><th>What</th><th>Why</th>"
                         "<th>Revisit?</th></tr></thead>" + rows + "</table></div>")

        self.write("roadmap.html",
                   self.page(f"Roadmap - {self.game}", "\n".join(parts), active="roadmap"))

    # -- Track C1/C2: the story thread ---------------------------------------

    def place_index(self) -> dict[str, str]:
        """Every way a human might write a place's name, pointing at the map
        it means: the label the site prints, the raw constant, and both with
        punctuation and spacing thrown away. A name that lands on two maps
        keeps the first and is not resolved twice."""
        idx: dict[str, str] = {}

        def key(s):
            return re.sub(r"[^a-z0-9]", "", s.lower())

        for mp in self.maps_ordered:
            for form in (map_label(mp["id"]), mp["id"],
                         mp["id"].removeprefix("MAP_")):
                idx.setdefault(key(form), mp["id"])
        return idx

    def map_neighbours(self) -> dict[str, set[str]]:
        """The world as a graph: walkable seams and doors, both directions.
        A one-way warp still joins two places for the purpose of asking what
        hangs off the route, which is the only thing this is used for."""
        adj: dict[str, set[str]] = {m["id"]: set() for m in self.maps_ordered}
        for mp in self.maps_ordered:
            near = {c["map"] for c in mp["connections"] if c.get("map")}
            near |= {w for w in mp["warps"] if w}
            for other in near:
                if other == mp["id"]:
                    continue
                adj.setdefault(mp["id"], set()).add(other)
                adj.setdefault(other, set()).add(mp["id"])
        return adj

    def route_thread(self) -> dict:
        """The authored route, resolved against the world.

        The ORDER is never derived -- §11.4, and the reason this page exists
        at all. The graph is walked for two things only: what hangs off the
        route (so nothing in the world silently goes missing), and what the
        route never reaches (so the omission is stated)."""
        route = (self.design or {}).get("route") or []
        idx, adj = self.place_index(), self.map_neighbours()

        def key(s):
            return re.sub(r"[^a-z0-9]", "", s.lower())

        beats, seen_at, named = [], {}, set()
        for beat in route:
            stops = []
            for spot in beat["places"]:
                mid = idx.get(key(spot["name"]))
                first = seen_at.get(mid) if mid else None
                stops.append({"name": spot["name"], "id": mid,
                              "note": spot.get("note", ""),
                              "first": first,
                              "visit": (seen_at.setdefault(mid, beat["n"]) and
                                        None) if mid else None})
                if mid:
                    named.add(mid)
            beats.append(dict(beat, stops=stops))

        # Each unnamed place near the route attaches to the first beat that
        # reaches it, walking THROUGH unnamed places only.
        #
        # Bounded to POCKET_HOPS, and the bound is the whole point. An
        # unbounded fill is technically correct and useless: a connected
        # world with a partial route puts every unvisited place in the first
        # beat's pocket, which is not "the cave off this route" but "the
        # rest of the game". Two hops is a side room and the room behind it.
        # Everything further away is not off the path, it is simply not on
        # the route yet, and the coverage list below is where that belongs.
        pocketed: dict[str, str] = {}
        for beat in beats:
            found: list[str] = []
            frontier = [(s["id"], 0) for s in beat["stops"] if s["id"]]
            seen = {mid for mid, _ in frontier}
            while frontier:
                here, depth = frontier.pop()
                if depth >= POCKET_HOPS:
                    continue
                for nxt in sorted(adj.get(here, ())):
                    if nxt in seen or nxt in named:
                        continue
                    seen.add(nxt)
                    if nxt not in pocketed:
                        pocketed[nxt] = beat["n"]
                        found.append(nxt)
                    frontier.append((nxt, depth + 1))
            beat["pocket"] = sorted(found, key=map_label)

        unreached = []
        for mp in self.maps_ordered:
            if mp["id"] in named or mp["id"] in pocketed:
                continue
            near = sorted(adj.get(mp["id"]) or (), key=map_label)
            # The ones with something in them are the ones worth routing, so
            # they lead -- a list of 400 places is read from the top or not
            # at all.
            weight = (len(mp["trainers"]) + len(mp["ground"])
                      + sum(len(t["slots"]) for t in mp["encounters"].values()))
            unreached.append({"id": mp["id"], "near": near[0] if near else None,
                              "weight": weight})
        unreached.sort(key=lambda u: (-u["weight"], map_label(u["id"])))
        return {"beats": beats, "named": named, "unreached": unreached}

    def census(self, mp) -> str:
        """One mono line per place saying what is under it, so a reader can
        skip every table below and lose nothing. An absence is words, never
        an empty table."""
        n_wild = sum(len(t["slots"]) for t in mp["encounters"].values())
        n_out = len({c["map"] for c in mp["connections"] if c.get("map")}
                    | {w for w in mp["warps"] if w and w != mp["id"]})
        def n(count, one, many, none):
            return f"{count} {one if count == 1 else many}" if count else none

        bits = [n(len(mp["trainers"]), "trainer", "trainers", "no trainers"),
                n(n_wild, "wild species", "wild species", "no wild encounters"),
                n(len(mp["ground"]), "item", "items", "no items"),
                n(n_out, "exit", "exits", "no way out derived")]
        return (f'<div class="census"><span>'
                + " &middot; ".join(esc(b) for b in bits)
                + f'</span><a href="locations/{slug(mp["id"])}.html">'
                "place page &rarr;</a></div>")

    def beat_progress(self, beat) -> str:
        """What a beat does to your progress, read from the game rather than
        from the doc that ordered it.

        The authored gate sitting under this says what the writer INTENDED
        to stand in the player's way. This says what the tree can prove: the
        badges the beat's own places hand out, and the progress flags they
        read. The two are shown separately and never merged -- where they
        disagree, that disagreement is the useful thing on the page."""
        awards, checks = [], []
        for stop in beat["stops"]:
            mp = self.maps.get(stop["id"]) if stop["id"] else None
            if not mp:
                continue
            if mp.get("gym"):
                awards.append((stop["id"], mp["gym"]))
            own = (mp.get("gym") or {}).get("defeated_flag")
            checks += [f for f in (mp.get("checks") or []) if f != own]
        # A badge this beat hands out is not also something it waits on.
        given = {f'FLAG_BADGE0{g["badge"]}_GET' for _m, g in awards}
        checks = [f for f in sorted(set(checks)) if f not in given]
        if not awards and not checks:
            return ""
        bits = []
        if awards:
            bits.append("<strong>Awards</strong> "
                        + ", ".join(f"{esc(self.badge_label(g))} at "
                                    + self.map_link(m, 0) for m, g in awards))
        if checks:
            bits.append("<strong>Checks</strong> "
                        + ", ".join(self.check_label(f, 0) for f in checks))
        return ('<div class="beatprog"><span class="lbl">Read from the game'
                "</span><p>" + " &middot; ".join(bits) + "</p></div>")

    def thread_place(self, stop) -> str:
        """One place on the thread. Authored sentence against the spine;
        everything derived inset and quieter, capped here and exhaustive on
        the place's own page."""
        mid = stop["id"]
        if not mid:
            # Named in the route, not in the tree: B3's dashed language,
            # applied to the world.
            return (
                '<div class="place unbuilt"><span class="dot"></span>'
                f'<div class="authored"><h3>{esc(stop["name"])} '
                '<span class="lbl inline">named in the route &middot; does '
                "not exist in the game yet</span></h3>"
                + (f'<p class="note">{esc(stop["note"])}</p>'
                   if stop.get("note") else "")
                + '<p class="sub">No map, no trainers, no encounters &mdash; '
                  "nothing to derive until the place exists.</p></div></div>")

        mp = self.maps[mid]
        name = map_label(mid)
        head = [f'<h3><a href="locations/{slug(mid)}.html">{esc(name)}</a>']
        if stop.get("first"):
            head.append('<span class="tag">return visit</span>'
                        f'<a class="backlink" href="#beat-{esc(stop["first"])}">'
                        f'&uarr; first seen in beat {esc(stop["first"])}</a>')
        head.append("</h3>")
        parts = [f'<div class="place{" revisit" if stop.get("first") else ""}">'
                 '<span class="dot"></span>' + "".join(head)]
        if stop.get("note"):
            parts.append(f'<p class="note">{esc(stop["note"])}</p>')
        if stop.get("first"):
            # True of this PAGE, not of the game: a story flag can move an
            # NPC, and nothing here would know.
            parts.append('<div class="census"><span>The same place, so there '
                         "is nothing new here to derive for a second visit."
                         "</span>"
                         f'<a href="locations/{slug(mid)}.html">place page '
                         "&rarr;</a></div></div>")
            return "".join(parts)
        parts.append(self.census(mp))
        parts.append('<div class="pbody">')

        rec = self.map_images.get(mid)
        if rec:
            img, (iw, ih) = rec
            size = "wide" if iw >= 560 else ("mid" if iw >= 260 else "small")
            parts.append(f'<div class="pmap {size}"><img loading="lazy" '
                         f'src="assets/maps/{img}" width="{iw}" height="{ih}" '
                         f'alt="{esc(name)}, drawn from its own block data">'
                         "</div>")
        else:
            parts.append('<div class="pmap mid mapfail"><span class="lbl">Map '
                         "not drawn</span><p>Its tileset could not be "
                         "composited on this machine. Everything else about "
                         "this place is unaffected.</p></div>")

        side = []
        here = [t for t in mp["trainers"] if t.get("trainer")]
        if here:
            # Position is derivable; the order a player walks past them is
            # not, so the label says what the sort actually is.
            here.sort(key=lambda s: (s["y"], s["x"]))
            cards = [self.thread_trainer(s) for s in here]
            side.append('<div class="tset"><span class="lbl">Trainers here '
                        f'&middot; {len(here)} &middot; in reading order, '
                        'top-left first</span>'
                        f'<div class="tcards">{"".join(cards[:3])}</div>')
            if len(cards) > 3:
                side.append(f"<details><summary>show the other "
                            f'{len(cards) - 3} &#9662;</summary>'
                            f'<div class="tcards">{"".join(cards[3:])}</div>'
                            "</details>")
            side.append("</div>")
        if side:
            parts.append(f'<div class="pside">{"".join(side)}</div>')
        parts.append("</div>")          # /pbody

        chips = []
        for method, table in mp["encounters"].items():
            for slot in table["slots"]:
                chips.append((slot["pct"], method, slot))
        if chips:
            chips.sort(key=lambda c: -c[0])
            shown = "".join(self.wild_chip(m, s) for _, m, s in chips[:8])
            more = (f'<a href="locations/{slug(mid)}.html">'
                    f"and {len(chips) - 8} more, with the full table "
                    "&rarr;</a>" if len(chips) > 8 else "")
            parts.append('<div class="rollup"><span class="lbl">Wild here '
                         "&middot; rolled up by species</span>"
                         f'<div class="chips">{shown}</div>{more}</div>')

        band = []
        if mp["ground"]:
            rows = "".join(
                f'<li>{self.item_link(g["item"], 0)} '
                f'<span class="muted">{"hidden" if g["hidden"] else "in plain sight"}'
                "</span></li>" for g in mp["ground"])
            band.append('<div><span class="lbl">Items on the ground</span>'
                        f'<ul class="plain">{rows}</ul></div>')
        exits = [(str(c.get("direction") or "edge"), c["map"])
                 for c in mp["connections"] if c.get("map")]
        exits += [("door", w) for w in sorted({w for w in mp["warps"]
                                               if w and w != mid})]
        if exits:
            pills = "".join(
                f'<a class="plink" href="locations/{slug(m)}.html">'
                f'{esc(map_label(m))} <span class="muted">{esc(d)}</span></a>'
                if m in self.maps else
                f'<span class="plink">{esc(map_label(m))}</span>'
                for d, m in exits)
            band.append('<div><span class="lbl">Ways out</span>'
                        f'<div class="chips">{pills}</div></div>')
        if band:
            parts.append(f'<div class="pband">{"".join(band)}</div>')

        lines = sum(len(paras) for _, paras in mp["text"] if paras)
        if lines:
            parts.append(f'<a class="saidhere" href="locations/{slug(mid)}.html">'
                         f"what is said in this place ({lines} passage"
                         f'{"" if lines == 1 else "s"}) &rarr;</a>')
        parts.append("</div>")
        return "".join(parts)

    def thread_trainer(self, spot) -> str:
        const = spot["trainer"]
        tr = self.trainers.get(const) or {}
        party = tr.get("party") or []
        lvls = [m["lvl"] for m in party if m.get("lvl")]
        rng = ("" if not lvls else
               f"Lv {min(lvls)}" + (f"&ndash;{max(lvls)}" if min(lvls) != max(lvls)
                                    else ""))
        icons = "".join(self.sprite_html(m["species"], "icon", 0) for m in party)
        return (f'<div class="tcard"><span class="who">'
                f'{self.trainer_link(const, 0)}'
                f'<span class="muted">{esc(self.class_label(tr.get("class")))}'
                f'</span></span><span class="lv">{rng}</span>'
                f'<div class="team">{icons}</div></div>')

    def wild_chip(self, method, slot) -> str:
        sp = slot["species"]
        lo, hi = slot.get("min"), slot.get("max")
        lvl = (f"{lo}" if lo == hi else f"{lo}&ndash;{hi}") if lo else ""
        name = (self.link(sp, 0) if sp in self.f["species"]
                else esc(pretty(sp)))
        return (f'<span class="wchip">{self.sprite_html(sp, "icon", 0)}{name}'
                f'<span class="muted">{esc(method.lower())} '
                f'{slot["pct"]:.0f}%' + (f" &middot; {lvl}" if lvl else "")
                + "</span></span>")

    def build_thread(self):
        thread = self.route_thread()
        beats = thread["beats"]
        parts = ['<p class="eyebrow">The game in play order</p>',
                 "<h1>Story thread</h1>"]
        if not beats:
            self.write("thread.html",
                       self.page(f"Story thread - {self.game}",
                            "\n".join(parts + [self.thread_empty()]),
                            active="thread"))
            return

        n_places = sum(1 for b in beats for s in b["stops"])
        parts.append(f'<p class="sub">{esc(self.game)} from the first step to '
                     "the last one written down. The order is the one part of "
                     "this site a person wrote; everything under each place is "
                     "read from the game, and every place links to its own page "
                     "where the exhaustive version lives.</p>")
        parts.append(f'<div class="threadhead"><span class="chip">{len(beats)} '
                     f'beats</span><span class="chip">{n_places} places</span>'
                     "</div>")

        rail = []
        for beat in beats:
            rail.append(f'<section class="beat" id="beat-{esc(beat["n"])}">'
                        f'<span class="disc">{esc(beat["n"])}</span>'
                        f'<h2>{esc(beat["title"])}</h2>')
            if beat.get("sentence"):
                rail.append(f'<p class="lead">{esc(beat["sentence"])}</p>')
            derived = self.beat_progress(beat)
            if derived:
                rail.append(derived)
            if beat.get("gate"):
                rail.append('<div class="authored"><span class="lbl">From the '
                            "design doc, not from the game</span>"
                            f'<p><strong>Gate.</strong> {esc(beat["gate"])}</p>'
                            "</div>")
            rail.append("</section>")
            for stop in beat["stops"]:
                rail.append(self.thread_place(stop))
            if beat.get("pocket"):
                pills = "".join(
                    f'<a class="plink" href="locations/{slug(m)}.html">'
                    f"{esc(map_label(m))}</a>" for m in beat["pocket"][:12])
                more = (f' <span class="muted">and {len(beat["pocket"]) - 12} '
                        "more</span>" if len(beat["pocket"]) > 12 else "")
                rail.append('<div class="pocket"><span class="lbl">Off the '
                            "path from here &middot; within two steps of "
                            "somewhere this beat names, and the route never "
                            "sends you</span>"
                            f'<div class="chips">{pills}</div>{more}</div>')
        rail.append('<div class="terminus"><span class="dot"></span>'
                    f"<span>The written route ends here &middot; {len(beats)} "
                    f'beat{"" if len(beats) == 1 else "s"} written</span></div>')
        parts.append(f'<div class="thread">{"".join(rail)}</div>')

        if thread["unreached"]:
            rows = "".join(
                f'<li>{self.map_link(u["id"], 0)}'
                + (f' <span class="muted">reachable from '
                   f'{esc(map_label(u["near"]))}</span>' if u["near"] else
                   ' <span class="muted">no connection derived</span>')
                + "</li>" for u in thread["unreached"][:12])
            more = (f'<p class="sub">and {len(thread["unreached"]) - 12} more.'
                    "</p>" if len(thread["unreached"]) > 12 else "")
            parts.append(f'<h2>Not on the thread ({len(thread["unreached"])})</h2>')
            parts.append('<p class="sub">Places that exist in the game and no '
                         "beat reaches. This is a statement about the route, "
                         "not about the places &mdash; the ones with the most "
                         "in them are listed first.</p>"
                         f'<ul class="unreached">{rows}</ul>{more}')

        self.write("thread.html",
                   self.page(f"Story thread - {self.game}", "\n".join(parts),
                        active="thread"))

    def thread_empty(self) -> str:
        """No route written. Say so, show the shape, count what there is to
        route through, and invent nothing."""
        built = len(self.maps_ordered)
        with_tr = sum(1 for m in self.maps_ordered if m["trainers"])
        joined = sum(1 for m in self.maps_ordered
                     if m["connections"] or m["warps"])
        example = (
            "## Route order\n\n"
            "1. **The parcel** &mdash; the errand that starts it.\n"
            "   - **Gate:** none &mdash; this is the opening\n"
            "   - Littleroot Town &mdash; three houses and a lab.\n"
            "   - Route 101\n"
            "   - Oldale Town\n")
        return (
            '<p class="sub">No route order has been written for '
            f"{esc(self.game)} yet, so this page has nothing to walk. The "
            "route is the one part of this site a person has to author "
            "&mdash; a world with loops has many valid ways through it and "
            "no way to prove which one was meant, so the generator will not "
            "guess.</p>"
            '<div class="authored"><span class="lbl">How the route gets '
            "written &middot; a Route order section in the game's narrative "
            f"design doc</span><pre>{example}</pre>"
            '<p class="sub">A place\'s own sentence, after the dash, is also '
            "the note that appears on that place's page. Places you name that "
            "do not exist yet are shown as planned, not built.</p></div>"
            '<h2>What there is to route through, meanwhile</h2>'
            '<div class="tiles">'
            + self.tile("Places built", built, "drawn from their own data")
            + self.tile("With trainers", with_tr, "someone stands in them")
            + self.tile("Connected", joined, "have an exit or a door")
            + "</div>"
            '<p class="sub"><a href="locations.html">Browse the places '
            "instead &rarr;</a></p>")

    def build_types(self):
        ts = self.types_shown
        head = "".join(f"<th>{type_badge(t)}</th>" for t in ts)
        rows = []
        for atk in ts:
            cells = "".join(
                f"<td>{eff_cell(self.chart.get((atk, d), 1.0))}</td>" for d in ts)
            rows.append(f'<tr><th class="atk">{type_badge(atk)}</th>{cells}</tr>')
        body = (f"<h1>Type chart</h1><p class=\"sub\">Rows attack, columns "
                "defend. Parsed from the game's own effectiveness table.</p>"
                '<div class="scroll-x"><table class="chart">'
                f"<thead><tr><th></th>{head}</tr></thead>{''.join(rows)}"
                "</table></div>")
        self.write("types.html",
                   self.page(f"Type chart - {self.game} dex", body, active="types"))


# ------------------------------------------------------------ entry

def die(msg: str, code: int = 2):
    sys.exit(f"make_dex.py: {msg}")


def resolve_roots(game_arg: str | None):
    workspace = (Path(game_arg).resolve() if game_arg
                 else hx.find_workspace())
    cfg = hx.load_config(workspace)
    game = cfg.get("game")
    hacks = workspace / "hacks"
    if not game:
        candidates = [d.name for d in hacks.iterdir()
                      if d.is_dir()] if hacks.is_dir() else []
        if len(candidates) == 1:
            game = candidates[0]
        else:
            die(f"{workspace}/harness.json names no game and {hacks} is not "
                "a single fork; pass --game a game repo")
    fork = hacks / game
    if not (fork / "src/data/pokemon").is_dir():
        die(f"{fork} is not a pokeemerald fork (no src/data/pokemon)")
    eng_cfg = cfg.get("engine") or {}
    cache = eng_cfg.get("cache")
    if cache:
        engine = Path(os.path.expanduser(cache)).resolve()
    elif (workspace / "engine").exists():
        engine = workspace / "engine"
    else:
        ref = eng_cfg.get("ref", hx.DEFAULT_ENGINE_REF)
        engine = hx.DEFAULT_CACHE_ROOT / ref.replace("/", "-")
    if not (engine / "src/data/pokemon").is_dir():
        die(f"engine clone missing at {engine} -- the stock baseline is what "
            "'new' and 'changed' are measured against")
    return workspace, game, fork, engine, eng_cfg.get("ref", hx.DEFAULT_ENGINE_REF)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default=None,
                    help="game repo (workspace); default: walk up for harness.json")
    ap.add_argument("--out", default=None, help="output dir (default <workspace>/dex)")
    ap.add_argument("--open", action="store_true", dest="open_site",
                    help="open the site's dashboard when done")
    ap.add_argument("--record", action="store_true",
                    help="append this build to the game's dev log (devlog/, "
                         "git-tracked). The build ritual passes it AFTER a "
                         "green build; a plain run only reads the history")
    ap.add_argument("--publish", action="store_true",
                    help="render the player-facing tree instead of the "
                         "builder's one (default <workspace>/publish): no "
                         "build health, no byte costs, no staleness, and the "
                         "roadmap reduced to a teaser. Never run "
                         "automatically -- publishing is a decision")
    args = ap.parse_args()

    if args.publish and args.record:
        die("--publish and --record together would write a dev-log entry for "
            "a render nobody built; record from the build ritual, publish on "
            "purpose")

    workspace, game, fork, engine, engine_ref = resolve_roots(args.game)
    out = (Path(args.out).resolve() if args.out
           else workspace / ("publish" if args.publish else "dex"))

    warnings: list[str] = []
    warn = warnings.append

    fork_model = load_tree(fork, warn)
    engine_model = load_tree(engine, lambda m: warn(f"(engine) {m}"))
    if not fork_model["species"]:
        die(f"zero species parsed from {fork} -- nothing to generate", 1)

    health = collect_health(workspace, fork, engine, game, time.time())
    health["title"] = hx.load_config(workspace).get("title") or game
    site = Site(fork_model, engine_model, fork, out, game, warn, engine_ref,
                health=health, publish=args.publish)

    # Track B2: read the history, then take this run's snapshot -- and only
    # WRITE it when asked, because a generator that recorded a build every
    # time someone regenerated the site would be keeping a log of itself.
    site.history = read_devlog(workspace)
    site.entry = site.devlog_entry()
    site.design = load_design(workspace)
    if args.record:
        written, note = record_devlog(workspace, site.entry, site.history)
        print(f"dev log: {note}")
        if written:
            site.history = site.history + [site.entry]

    (out / "assets").mkdir(parents=True, exist_ok=True)
    theme = load_theme(workspace)
    # The site embeds sprites copied from a Nintendo-derived tree, so the
    # output directory excludes itself from git wherever it lands -- same
    # policy as engine/ and hacks/ in a game repo's own .gitignore.
    (out / ".gitignore").write_text(
        "# Generated by make_dex.py; contains Nintendo-derived sprite art.\n"
        "# Regenerate with: python3 tools/make_dex.py"
        + (" --publish\n" if args.publish else "\n") + "*\n", encoding="utf-8")
    (out / "assets/style.css").write_text(build_css(theme), encoding="utf-8")
    copy_fonts(out)
    site.copy_sprites()
    site.copy_trainer_pics()
    site.render_maps()
    site.build_dashboard()          # index.html -- must follow the art above
    site.build_pokedex()
    site.build_species_pages()
    site.build_moves()
    site.build_move_pages()
    site.build_abilities()
    site.build_ability_pages()
    site.build_items()
    site.build_item_pages()
    site.build_trainers()
    site.build_trainer_pages()
    site.build_locations()
    site.build_location_pages()
    site.build_gyms()
    site.build_changes()
    site.build_devlog()
    site.build_roadmap()
    site.build_thread()
    site.build_types()

    for w in warnings[:30]:
        print(f"warning: {w}")
    if len(warnings) > 30:
        print(f"warning: ...and {len(warnings) - 30} more")

    n_new = sum(1 for s in site.status.values() if s[0] == "new")
    n_chg = sum(1 for s in site.status.values() if s[0] == "changed")
    if args.publish:
        print("publish: build health, byte costs, staleness, the roadmap's "
              "statuses and the design decisions are not in this tree")
    print(f"dex: {len(fork_model['species'])} species ({n_new} new, {n_chg} "
          f"changed vs stock {engine_ref}), {len(site.trainers_ordered)} "
          f"trainers, {len(site.maps_ordered)} places "
          f"({len(site.map_images)} drawn), "
          f"{site.pages_written} pages, {len(site.sprites)} sprite sets "
          f"-> {out} [{len(warnings)} warning(s)]")

    if args.open_site:
        subprocess.run(["open", str(out / "index.html")], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
