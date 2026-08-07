#!/usr/bin/env python3
"""make_dex.py -- a static, pokemondb-style dex site generated from the game's
OWN source data, so it can never drift from the game.

WHAT IT READS. The fork's `src/data/pokemon/species_info/*.h` (designated
initializers), `level_up_learnsets/`, `teachable_learnsets.h`, `moves_info.h`
and `types_info.h`, plus `include/constants/pokedex.h` for national dex order
-- and then the SAME files from the pinned engine clone, parsed by the same
code, so that "new" and "changed" are computed against the stock baseline
rather than asserted. Sprites come from `graphics/pokemon/<species>/` and are
copied into the site, which is fully self-contained: no external requests, no
frameworks, works from file:// in any browser.

WHAT IT WRITES, under <workspace>/dex/:
    index.html          every species, sortable/filterable, NEW/CHANGED badges
    changes.html        the progress tracker: what this game added and altered
    types.html          the game's own type chart
    pokemon/<key>.html  one page per species (stats, defenses, evos, learnsets)
    assets/             style.css + copied sprite PNGs

KNOWN LIMITATIONS, all deliberate (this is a regex parser, not a C compiler):
  * Preprocessor conditionals are NOT evaluated. `#if P_FAMILY_X` guards are
    ignored and every entry inside them is parsed; a game that compiles with
    families disabled will show species its ROM does not contain.
  * Config-dependent values (`(P_UPDATED_EXP_YIELDS >= GEN_5) ? 142 : 141`,
    `B_UPDATED_MOVE_DATA` move power blocks, the `*_RS` type-chart macros,
    `HANDLE_EXPANDED_SPECIES_NAME(short, long)`) take the FIRST/modern branch,
    which matches pokeemerald-expansion's default configuration.
  * File-local #define macros (BEEDRILL_ATTACK, VIVILLON_MISC_INFO(...),
    ARCEUS_SPECIES_INFO(...)) are expanded textually, one family file's worth
    at a time, with `##` pasting honored -- but `#param` stringizing is not,
    and a macro defined outside src/data/pokemon/species_info/ is not seen.
  * If the type chart cannot be parsed, a built-in standard Gen-6+ 18-type
    chart is used and a warning is printed.
  * Two-frame sprite sheets (anim_front.png, icon.png) are detected by the
    height == 2*width heuristic and cropped to their first frame with CSS.

USAGE
    python3 tools/make_dex.py                       # workspace found via hx
    python3 tools/make_dex.py --game ~/src/reps     # explicit game repo
    python3 tools/make_dex.py --out /tmp/dex --open

Exit 0 on success, 1 if zero species parsed, 2 if the trees cannot be found.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

import hx

# ------------------------------------------------------------ C-ish parsing

_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
# A directive plus its backslash continuations, so a multi-line #define
# vanishes whole instead of leaking its body into the token stream.
_PREPROC_RE = re.compile(r"^[ \t]*#[^\n]*(?:\\\n[^\n]*)*", re.M)
_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_SPECIES_RE = re.compile(r"\[(SPECIES_\w+)\]\s*=\s*\{")
_MOVE_ENTRY_RE = re.compile(r"\[(MOVE_\w+)\]\s*=\s*\{")


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
            lits = _STRING_RE.findall(f["speciesName"])
            if lits:                # HANDLE_EXPANDED_SPECIES_NAME: take long
                sp["name"] = lits[-1]
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
    """Move name/type/power/accuracy/pp/category per MOVE_X. First branch of
    any #if ladder wins (see module docstring)."""
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
            nm = join_strings(f["name"])
            if nm:
                mv["name"] = nm
        t = re.search(r"TYPE_\w+", f.get("type", ""))
        if t:
            mv["type"] = t.group()
        c = re.search(r"DAMAGE_CATEGORY_(\w+)", f.get("category", ""))
        if c:
            mv["category"] = c.group(1).title()
        for k in ("power", "accuracy", "pp"):
            v = first_int(f.get(k))
            if v is not None:
                mv[k] = v
        out.setdefault(m.group(1), mv)
    return out


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

# Fields compared against the stock engine, with display labels.
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


def classify(ours: dict, stock: dict | None):
    """-> ("new"|"changed"|"same", [(label, old, new), ...]).

    A field absent on BOTH sides is not a difference; absent on one side is.
    """
    if stock is None:
        return "new", []
    diffs = []
    for key, label in COMPARE_FIELDS:
        a, b = stock.get(key), ours.get(key)
        if a != b:
            diffs.append((label, a, b))
    return ("changed", diffs) if diffs else ("same", [])


# ------------------------------------------------------------ prettifying

_PREFIXES = ("SPECIES_", "MOVE_", "ABILITY_", "ITEM_", "TYPE_", "EGG_GROUP_",
             "NATIONAL_DEX_", "EVO_", "TRAINING_CATEGORY_", "TRAINING_EVO_",
             "MAP_", "FLAG_")


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

    order, chart = parse_type_chart(read(data / "types_info.h"))
    if not chart:
        warn("types_info.h chart not parsed; using the built-in Gen-6+ chart")
        order = ["TYPE_" + t for t in FALLBACK_ORDER]
        chart = dict(FALLBACK_CHART)

    dex = parse_dex_order(read(root / "include/constants/pokedex.h"))
    sprite_dirs = parse_sprite_dirs(read(data / "graphics/pokemon.h"))

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
            "type_order": order, "dex": dex, "sprite_dirs": sprite_dirs}


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


# ------------------------------------------------------------ HTML

CSS = """\
:root {
  --bg: #fff; --fg: #1f2428; --muted: #667; --line: #dde2e6;
  --card: #f6f8fa; --accent: #2563ab; --new: #1a7f37; --chg: #b35c00;
  color-scheme: light dark;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #14171a; --fg: #dfe4e8; --muted: #9aa4ad; --line: #33393f;
          --card: #1d2126; --accent: #6ab0f3; --new: #4ac26b; --chg: #e0a24a; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header.site { border-bottom: 1px solid var(--line); padding: 10px 20px;
  display: flex; gap: 18px; align-items: baseline; flex-wrap: wrap; }
header.site .brand { font-weight: 700; font-size: 17px; color: var(--fg); }
main { max-width: 1080px; margin: 0 auto; padding: 18px 20px 60px; }
h1 { font-size: 26px; margin: 12px 0 4px; }
h2 { font-size: 19px; margin: 28px 0 8px; border-bottom: 1px solid var(--line);
     padding-bottom: 4px; }
.sub { color: var(--muted); margin: 0 0 14px; }
table.data { border-collapse: collapse; width: 100%; }
table.data th, table.data td { padding: 4px 8px; border-bottom: 1px solid var(--line);
  text-align: left; white-space: nowrap; }
table.data th { font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--muted); cursor: default; }
table.data th[data-s] { cursor: pointer; }
table.data th[data-s]:hover { color: var(--fg); }
table.data td.num, table.data th.num { text-align: right; }
table.data tr:hover td { background: var(--card); }
.controls { display: flex; gap: 16px; align-items: center; margin: 12px 0;
  flex-wrap: wrap; }
.controls input[type=text] { padding: 6px 10px; border: 1px solid var(--line);
  border-radius: 6px; background: var(--bg); color: var(--fg); min-width: 220px; }
.only-changes tr[data-status="same"] { display: none; }
.spr { display: inline-block; overflow: hidden; vertical-align: middle; }
.spr img { image-rendering: pixelated; display: block; }
.type-badge { display: inline-block; padding: 1px 8px; border-radius: 4px;
  color: #fff; font-size: 12px; font-weight: 600; text-shadow: 0 1px 1px rgba(0,0,0,.4);
  margin-right: 3px; }
.t-normal{background:#A8A878}.t-fire{background:#F08030}.t-water{background:#6890F0}
.t-electric{background:#F8D030}.t-grass{background:#78C850}.t-ice{background:#98D8D8}
.t-fighting{background:#C03028}.t-poison{background:#A040A0}.t-ground{background:#E0C068}
.t-flying{background:#A890F0}.t-psychic{background:#F85888}.t-bug{background:#A8B820}
.t-rock{background:#B8A038}.t-ghost{background:#705898}.t-dragon{background:#7038F8}
.t-dark{background:#705848}.t-steel{background:#B8B8D0}.t-fairy{background:#EE99AC}
.t-mystery{background:#68A090}.t-stellar{background:#40B5A5}.t-none{background:#9aa}
.badge { display: inline-block; padding: 1px 8px; border-radius: 10px;
  font-size: 11px; font-weight: 700; letter-spacing: .05em; }
.badge.new { background: var(--new); color: #fff; }
.badge.changed { background: var(--chg); color: #fff; }
.statbar { background: var(--card); border-radius: 3px; height: 12px;
  min-width: 180px; width: 100%; }
.statbar div { height: 12px; border-radius: 3px; }
table.stats td { border-bottom: none; padding: 2px 8px; }
table.stats { width: auto; min-width: 420px; }
table.kv td:first-child { color: var(--muted); padding-right: 18px; }
.typedef { display: grid; grid-template-columns: repeat(9, minmax(52px, 1fr));
  gap: 4px; max-width: 640px; }
.typedef .cell { text-align: center; border: 1px solid var(--line);
  border-radius: 4px; padding: 2px 0 4px; font-size: 13px; }
.eff { display: inline-block; min-width: 26px; border-radius: 3px;
  font-weight: 700; font-size: 12px; padding: 0 3px; }
.eff-0 { background: #444; color: #fff; }
.eff-25, .eff-50 { background: #a33; color: #fff; }
.eff-200, .eff-400 { background: #2a7f2a; color: #fff; }
.eff-100 { color: var(--muted); }
.chart { border-collapse: collapse; font-size: 12px; }
.chart th, .chart td { border: 1px solid var(--line); padding: 2px;
  text-align: center; min-width: 30px; }
.chart th.atk { text-align: right; padding-right: 6px; }
.evo-step { display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin: 6px 0; }
.evo-cond { color: var(--muted); font-size: 13px; }
.evo-card { text-align: center; padding: 6px 10px; background: var(--card);
  border-radius: 8px; }
.evo-children { display: flex; flex-direction: column; }
.movechips { display: flex; flex-wrap: wrap; gap: 4px; max-width: 900px; }
.movechips span { background: var(--card); border: 1px solid var(--line);
  border-radius: 4px; padding: 1px 7px; font-size: 13px; }
.difftable td { white-space: normal; }
.pagenav { display: flex; justify-content: space-between; margin: 10px 0; }
.desc { max-width: 640px; }
.headrow { display: flex; gap: 24px; align-items: center; flex-wrap: wrap; }
.warn { color: var(--chg); }
.scroll-x { overflow-x: auto; }
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


def page(title: str, body: str, game: str, depth: int = 0) -> str:
    up = "../" * depth
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{up}assets/style.css">
</head>
<body>
<header class="site">
  <span class="brand">{esc(game)} dex</span>
  <a href="{up}index.html">Pokédex</a>
  <a href="{up}changes.html">Changes</a>
  <a href="{up}types.html">Type chart</a>
</header>
<main>
{body}
</main>
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
        return '<span class="badge changed">CHANGED</span>'
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
                 engine_ref=hx.DEFAULT_ENGINE_REF):
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

        self.sprites: dict[str, dict] = {}
        self.pages_written = 0

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
            return esc(", ".join(pretty(a) for a in value if a != "ABILITY_NONE"))
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
            return esc(", ".join(
                f"{lvl}: {self.move_name(mv)}" for lvl, mv in value))
        if field == "Teachable moves":
            if not isinstance(value, list):
                return "&mdash;"
            return esc(", ".join(self.move_name(m) for m in value))
        return esc(value)

    def move_name(self, const) -> str:
        mv = self.moves.get(const)
        return mv["name"] if mv and "name" in mv else pretty(const)

    def change_summary(self, diffs, limit=4) -> str:
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
            elif isinstance(old, int) and isinstance(new, int):
                bits.append(f"{label} {old}→{new}")
            else:
                bits.append(f"{label.lower()} changed")
        shown = bits[:limit]
        if len(bits) > limit:
            shown.append(f"+{len(bits) - limit} more")
        return esc("; ".join(shown))

    # -- pages -------------------------------------------------------------

    def write(self, rel: str, content: str):
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self.pages_written += 1

    def build_index(self):
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
        self.write("index.html", page(f"{self.game} dex", body, self.game))

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
                labels = [pretty(a) for a in ab[:2]]
                if len(sp.get("abilities", [])) >= 3 \
                        and sp["abilities"][2] != "ABILITY_NONE":
                    labels = [pretty(a) for a in sp["abilities"][:2]
                              if a != "ABILITY_NONE"]
                    labels.append(pretty(sp["abilities"][2]) + " (hidden)")
                kv.append(("Abilities", esc(", ".join(labels))))
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
                        f"<td>{esc(self.move_name(mv))}</td>"
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
                chips = "".join(f"<span>{esc(self.move_name(m))}</span>"
                                for m in sorted(tm, key=self.move_name))
                parts.append(f"<h2>Teachable moves</h2>"
                             f'<div class="movechips">{chips}</div>')

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
                       page(f"{name} - {self.game} dex",
                            "\n".join(parts), self.game, depth=1))

    def build_changes(self):
        news = [sp for sp in self.ordered if self.status[sp["const"]][0] == "new"]
        chgs = [sp for sp in self.ordered
                if self.status[sp["const"]][0] == "changed"]
        parts = [f"<h1>Changes</h1><p class=\"sub\">Everything this game adds "
                 f"or alters relative to stock ({esc(self.engine_ref)}), "
                 "derived from the source trees, not from notes.</p>"]

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

        self.write("changes.html",
                   page(f"Changes - {self.game} dex", "\n".join(parts), self.game))

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
                   page(f"Type chart - {self.game} dex", body, self.game))


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
                    help="open index.html when done")
    args = ap.parse_args()

    workspace, game, fork, engine, engine_ref = resolve_roots(args.game)
    out = Path(args.out).resolve() if args.out else workspace / "dex"

    warnings: list[str] = []
    warn = warnings.append

    fork_model = load_tree(fork, warn)
    engine_model = load_tree(engine, lambda m: warn(f"(engine) {m}"))
    if not fork_model["species"]:
        die(f"zero species parsed from {fork} -- nothing to generate", 1)

    site = Site(fork_model, engine_model, fork, out, game, warn, engine_ref)
    (out / "assets").mkdir(parents=True, exist_ok=True)
    # The site embeds sprites copied from a Nintendo-derived tree, so the
    # output directory excludes itself from git wherever it lands -- same
    # policy as engine/ and hacks/ in a game repo's own .gitignore.
    (out / ".gitignore").write_text(
        "# Generated by make_dex.py; contains Nintendo-derived sprite art.\n"
        "# Regenerate with: python3 tools/make_dex.py\n*\n", encoding="utf-8")
    (out / "assets/style.css").write_text(CSS, encoding="utf-8")
    site.copy_sprites()
    site.build_index()
    site.build_species_pages()
    site.build_changes()
    site.build_types()

    for w in warnings[:30]:
        print(f"warning: {w}")
    if len(warnings) > 30:
        print(f"warning: ...and {len(warnings) - 30} more")

    n_new = sum(1 for s in site.status.values() if s[0] == "new")
    n_chg = sum(1 for s in site.status.values() if s[0] == "changed")
    print(f"dex: {len(fork_model['species'])} species ({n_new} new, {n_chg} "
          f"changed vs stock {engine_ref}), {site.pages_written} pages, "
          f"{len(site.sprites)} sprite sets -> {out} "
          f"[{len(warnings)} warning(s)]")

    if args.open_site:
        subprocess.run(["open", str(out / "index.html")], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
