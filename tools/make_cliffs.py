#!/usr/bin/env python3
"""Build the TWO-CLIFF FIXTURE: a ROM that walks off two documented silent
failures of the field engine on purpose, so they can be photographed.

Doc 67 item C. The corpus records both faults from source-reading and neither
has ever been SEEN:

  1. THE MAP-SIZE CEILING. InitMapLayoutData (src/fieldmap.c) copies the layout
     into sBackupMapData only `if (width * height <= MAX_MAP_DATA_SIZE)`, where
     width/height are already padded by MAP_OFFSET_W/H. Past the ceiling the
     `if` simply does not run -- no assert, no log, no crash.
  2. THE SPAWN-WINDOW SLOT BUDGET. gObjectEvents has OBJECT_EVENTS_COUNT live
     slots, the player holds one, and TrySpawnObjectEvents walks the map's
     templates in order spawning those inside a 20x17-tile window. Past the
     budget, GetAvailableObjectEventId returns the same TRUE it returns for
     "already loaded", so the extra objects just are not there.

WHY A GENERATOR RATHER THAN EDITS IN THE FORK. `hacks/` is gitignored,
so a fork is disposable and source edits inside one are not durable
(make_studio.py's argument, and the same one that produced new_map.py). This
file is the artifact; the fork can be deleted and rebuilt at any time.

WHAT IT MAKES -- four maps in one ROM, chosen so every observation has its own
control rather than standing alone:

  CliffLegal            50x143 -> (50+15)*(143+14) = 10205 of 10240. The
                        LARGEST LEGAL MAP at this width. It is the control:
                        same generator, same tilesets, same everything, one
                        row shorter.
  CliffVoid             50x144 -> 10270. ONE ROW past the ceiling.
  CliffCrowd            17 always-visible object events inside one spawn
                        window: 15 kids in a 5x3 grid, then two scientists.
                        The scientists are last in template order.
  CliffCrowdReordered   THE SAME 17 TEMPLATES at THE SAME COORDINATES, with the
                        two scientists moved to the FRONT of the list. Nothing
                        else differs. If the scientists now appear and two kids
                        do not, the loss is a slot budget and not a broken
                        template -- which is the only reading a single crowd
                        map could not rule out (doc 61 section 4's pair rule).

HOW YOU GET TO EACH ONE. There are no warps: on the void map the player cannot
take a step, so a door out of it would be decoration. Instead the map is chosen
by WHAT YOU HOLD AT BOOT, read straight off REG_KEYINPUT during new-game init:

    (nothing) -> CliffLegal        A -> CliffVoid
    B         -> CliffCrowd  SELECT/R -> CliffCrowdReordered

That makes every spec a cold boot with one key held for the whole run: no
walking, no frame counts, nothing to drift.

The keys were picked against the ACTUAL mGBA keymap on the machine this gets
played on (`~/.config/mgba/config.ini`, section `gba.input.QT_K`), not against
mGBA's defaults: A=A, B=B, L=L, R=R, Start=Return, **Select=CAPS LOCK**. Caps
Lock is a toggle and does not reliably read as held, which is why the fourth arm
accepts R as well. (Doc 63 recorded GBA L and GBA A bound to the same host key;
that is STALE -- re-read 2026-08-03, keyL=76 and keyA=65, so they are distinct.)

VERIFICATION COSTS NOTHING IN RAM. Every probe the specs need reads a global
the engine already has: gBackupMapLayout (width/height/map), sBackupMapData,
gObjectEvents, gMapHeader. This fixture adds no probe variables at all, which
is worth knowing on its own -- doc 54 section 4's RAM warning does not apply to
an experiment that only reads.

USAGE
    python3 tools/new_hack.py cliffs
    python3 tools/make_cliffs.py
    python3 tools/check_map.py --hack hacks/cliffs
    # then build the fork, then run verify/cliff-*.json

    python3 tools/make_cliffs.py --check     # report, write nothing

Exit 0 on success, 2 on any failed precondition or assertion.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

import hx  # noqa: E402
REPO_ROOT = hx.HARNESS_ROOT
TOOLS = hx.TOOLS
DEFAULT_HACK = hx.HACKS / "cliffs"

# Every generated file and every patch carries this, which is what makes
# re-running a no-op and what makes the changes greppable in a 23,000-file fork.
MARKER = "CLIFFS_FIXTURE"

GROUP = "gMapGroup_IndoorLittleroot"

# The tileset pair and the blocks all come from LAYOUT_RUSTBORO_CITY_POKEMON_SCHOOL,
# via `new_map.py --dump-layout`. Derive, don't guess: a metatile id is
# meaningless outside its tileset pair and a wrong one is a wall where you
# wanted a floor, not an error (doc 65).
PRIMARY, SECONDARY = "gTileset_Building", "gTileset_PokemonSchool"
BORDER = [519, 519, 519, 519]
FLOOR = [513, 0, 3]     # walkable, elevation 3
WALL = [521, 1, 0]
# plan[0][0] gets its own block with ALL THREE FIELDS non-zero, so the word the
# harness reads back out of sBackupMapData is 0x3601 -- unmistakable against
# both 0x0000 (shifted/garbage memory) and 0x03FF (MAPGRID_UNDEFINED). Doc 58's
# rule: never let an exact compare land on zero.
MARK_BLOCK = [513, 1, 3]
MARK_WORD = 513 | (1 << 10) | (3 << 12)   # 0x3601

# CliffLegal is the largest legal map at width 50: (50+15)*(143+14) = 10205.
# CliffVoid is that map plus one row: (50+15)*(144+14) = 10270 > 10240.
WIDE_W, LEGAL_H, VOID_H = 50, 143, 144
WIDE_START = (5, 5)

# The crowd maps. 15 kids in a 5x3 grid, then 2 scientists on their own row.
# The player stands below all of them. In TEMPLATE coordinates the spawn window
# is [px-9, px+10] x [py-7, py+9] (TrySpawnObjectEvents compares template->x+7
# against gSaveBlock1Ptr->pos.x-2 .. pos.x+17), so every object below is inside
# it with room to spare -- the experiment is about the slot budget, and a
# borderline window position would confound it.
CROWD_W, CROWD_H = 20, 18
CROWD_START = (8, 12)
KID_GFX = "OBJ_EVENT_GFX_GAMEBOY_KID"
EXTRA_GFX = "OBJ_EVENT_GFX_SCIENTIST_1"
KIDS = [(x, y) for y in (6, 7, 8) for x in (6, 7, 8, 9, 10)]   # 15
EXTRAS = [(7, 10), (10, 10)]                                    # 2 -> 17 total

MAP_OFFSET = 7   # asserted against the fork's own header in build_specs()


def fail(msg):
    print(f"make_cliffs.py: {msg}", file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------
# The map specs
# --------------------------------------------------------------------------

def rect_plan(w: int, h: int) -> list[str]:
    """A walled room with a marker block in the top-left corner.

    The marker is what the harness reads: InitBackupMapLayoutData writes the
    layout starting at sBackupMapData[width*7 + MAP_OFFSET], so plan[0][0] is
    the FIRST word the copy produces. If the copy never runs, that slot still
    holds the MAPGRID_UNDEFINED the unconditional CpuFastFill16 left there.
    """
    if w < 3 or h < 3:
        fail(f"a {w}x{h} room has no interior")
    top = "M" + "#" * (w - 1)
    middle = "#" + "w" * (w - 2) + "#"
    bottom = "#" * w
    return [top] + [middle] * (h - 2) + [bottom]


def layout(w: int, h: int) -> dict:
    return {
        "primary_tileset": PRIMARY,
        "secondary_tileset": SECONDARY,
        "border": list(BORDER),
        "palette": {"w": list(FLOOR), "#": list(WALL), "M": list(MARK_BLOCK)},
        "plan": rect_plan(w, h),
    }


HEADER = {"music": "MUS_NONE", "region_map_section": "MAPSEC_LITTLEROOT_TOWN",
          "map_type": "MAP_TYPE_INDOOR"}


def scripts_for(name: str) -> str:
    """One no-op script, shared by every object event on the map.

    The objects need a script pointer that resolves; what it does is irrelevant
    to both cliffs, and giving them all the same one keeps the templates
    identical in every respect except position and graphics.
    """
    return (f"{name}_MapScripts::\n"
            f"\t.byte 0\n"
            f"\n"
            f"{name}_EventScript_Nothing::\n"
            f"\tend\n")


def object_event(name: str, gfx: str, x: int, y: int) -> dict:
    return {
        "graphics_id": gfx,
        "x": x, "y": y, "elevation": 3,
        "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
        "movement_range_x": 0, "movement_range_y": 0,
        "trainer_type": "TRAINER_TYPE_NONE",
        "trainer_sight_or_berry_tree_id": "0",
        "script": f"{name}_EventScript_Nothing",
        "flag": "0",     # always visible: a flag-gated object is not in the
    }                    #   budget check's FAIL set, only its WARN set


def crowd_objects(name: str, extras_first: bool) -> list[dict]:
    kids = [object_event(name, KID_GFX, x, y) for x, y in KIDS]
    extras = [object_event(name, EXTRA_GFX, x, y) for x, y in EXTRAS]
    return extras + kids if extras_first else kids + extras


def build_specs() -> list[dict]:
    return [
        {"name": "CliffLegal", "group": GROUP, "layout": layout(WIDE_W, LEGAL_H),
         "header": dict(HEADER), "scripts": scripts_for("CliffLegal"),
         "_oversize": False},
        {"name": "CliffVoid", "group": GROUP, "layout": layout(WIDE_W, VOID_H),
         "header": dict(HEADER), "scripts": scripts_for("CliffVoid"),
         "_oversize": True},
        {"name": "CliffCrowd", "group": GROUP, "layout": layout(CROWD_W, CROWD_H),
         "header": dict(HEADER), "scripts": scripts_for("CliffCrowd"),
         "object_events": crowd_objects("CliffCrowd", extras_first=False),
         "_oversize": False},
        {"name": "CliffCrowdReordered", "group": GROUP,
         "layout": layout(CROWD_W, CROWD_H),
         "header": dict(HEADER),
         "scripts": scripts_for("CliffCrowdReordered"),
         "object_events": crowd_objects("CliffCrowdReordered", extras_first=True),
         "_oversize": False},
    ]


# --------------------------------------------------------------------------
# The boot-key start selector
# --------------------------------------------------------------------------

CONFIG_HEADER = f"""// {MARKER}: written by tools/make_cliffs.py
#ifndef GUARD_CONFIG_CLIFFS_H
#define GUARD_CONFIG_CLIFFS_H

// One switch, so every fixture change in this fork is greppable.
#define CLIFFS_MODE TRUE

#endif // GUARD_CONFIG_CLIFFS_H
"""

START_HEADER = f"""// {MARKER}: written by tools/make_cliffs.py
#ifndef GUARD_CLIFFS_START_H
#define GUARD_CLIFFS_START_H

void CliffsSetStartWarp(void);

#endif // GUARD_CLIFFS_START_H
"""

START_SOURCE = f"""// {MARKER}: written by tools/make_cliffs.py
//
// Which of the four fixture maps a new game starts in, chosen by what is held
// at boot. This is the whole navigation system: there are no warps between the
// maps, because on CliffVoid the player cannot take a single step and a door
// out of it would be decoration.
//
// REG_KEYINPUT is read directly, and is ACTIVE LOW -- a 0 bit means the key is
// down. gMain.heldKeys is not used on purpose: new-game init does not run at a
// fixed point in the input cycle, and a stale read would silently select the
// wrong map, which looks exactly like a broken fixture rather than a wrong
// button.

#include "global.h"
#include "overworld.h"
#include "main_menu.h"
#include "constants/maps.h"
#include "config/cliffs.h"
#include "cliffs_start.h"

// Despite the name this does TWO things, and the second one is a bug fix found
// by a person playing (2026-08-03), not by any probe.
//
// SKIPPING THE INTRO SKIPS THE NAMING SCREEN, AND THE PLAYER NAME IS LEFT AS
// EIGHT ZERO BYTES WITH NO EOS. In this charmap 0x00 is the SPACE glyph and
// 0xFF is the terminator, so the name renders as blanks -- the Start menu's
// PLAYER row simply looks empty -- and the string is UNTERMINATED. Selecting
// that row clobbers gMain: callback2 goes to an address that is not a symbol
// and the vblank counter stops. It is the read-past-end-of-string surface doc
// 45 recorded as engine defect E2, reached by a boot shortcut rather than by a
// bad string constant.
//
// The engine's own helper is the fix, and it is what the naming screen calls:
// it copies a preset and writes EOS at PLAYER_NAME_LENGTH. Called HERE, at the
// tail of NewGameInitData, because everything upstream (ClearSav1/ClearSav3/
// ResetPokedex/...) has already run by this point and cannot undo it.
//
// NOTE FOR make_studio.py, WHICH USES THE SAME BOOT SHORTCUT: measured on the
// studio ROM built 2026-07-26, gSaveBlock2Ptr->playerName is 0000000000000000
// there too. Same hole, same one-line fix, APPLIED AND VERIFIED there the same
// day -- see ApplyStudioState() in make_studio.py.
void CliffsSetStartWarp(void)
{{
    u16 keys = (u16)(~REG_KEYINPUT) & KEYS_MASK;

    NewGameBirchSpeech_SetDefaultPlayerName(0);

    if (keys & A_BUTTON)
        SetWarpDestination(MAP_GROUP(CLIFF_VOID), MAP_NUM(CLIFF_VOID),
                           WARP_ID_NONE, {WIDE_START[0]}, {WIDE_START[1]});
    else if (keys & B_BUTTON)
        SetWarpDestination(MAP_GROUP(CLIFF_CROWD), MAP_NUM(CLIFF_CROWD),
                           WARP_ID_NONE, {CROWD_START[0]}, {CROWD_START[1]});
    // SELECT *or* R, and the alias is not decoration: on the machine this gets
    // played on, mGBA binds GBA Select to Caps Lock, which is a toggle and does
    // not reliably read as HELD. R is bound to the R key there and is otherwise
    // unused by this fixture. The specs still hold Select, so they are unchanged.
    else if (keys & (SELECT_BUTTON | R_BUTTON))
        SetWarpDestination(MAP_GROUP(CLIFF_CROWD_REORDERED),
                           MAP_NUM(CLIFF_CROWD_REORDERED),
                           WARP_ID_NONE, {CROWD_START[0]}, {CROWD_START[1]});
    else
        SetWarpDestination(MAP_GROUP(CLIFF_LEGAL), MAP_NUM(CLIFF_LEGAL),
                           WARP_ID_NONE, {WIDE_START[0]}, {WIDE_START[1]});
}}
"""

# (relative path, anchor, replacement). Same shape and the same idempotence
# argument as make_studio.py's PATCHES -- a patch tool that quietly no-ops is
# how you end up verifying a build that was never modified.
PATCHES = [
    # 1. Boot straight into the world: no intro, no title screen.
    (
        "src/intro.c",
        """#if EXPANSION_INTRO == TRUE
        SetMainCallback2(CB2_ExpansionIntro);
        CreateTask(Task_HandleExpansionIntro, 0);
#else
        CreateTask(Task_Scene1_Load, 0);
        SetMainCallback2(MainCB2_Intro);
#endif""",
        f"""#if CLIFFS_MODE == TRUE // {MARKER}
        SetMainCallback2(CB2_NewGame);
#elif EXPANSION_INTRO == TRUE
        SetMainCallback2(CB2_ExpansionIntro);
        CreateTask(Task_HandleExpansionIntro, 0);
#else
        CreateTask(Task_Scene1_Load, 0);
        SetMainCallback2(MainCB2_Intro);
#endif""",
    ),
    (
        "src/intro.c",
        '#include "intro.h"',
        f'#include "intro.h"\n#include "overworld.h"      // {MARKER}\n'
        f'#include "config/cliffs.h" // {MARKER}',
    ),
    # 2. Start in a fixture map, not in the moving truck.
    (
        "src/new_game.c",
        "    SetWarpDestination(MAP_GROUP(INSIDE_OF_TRUCK), MAP_NUM(INSIDE_OF_TRUCK), WARP_ID_NONE, -1, -1);",
        f"""#if CLIFFS_MODE == TRUE // {MARKER}
    CliffsSetStartWarp();
#else
    SetWarpDestination(MAP_GROUP(INSIDE_OF_TRUCK), MAP_NUM(INSIDE_OF_TRUCK), WARP_ID_NONE, -1, -1);
#endif""",
    ),
    (
        "src/new_game.c",
        '#include "new_game.h"',
        f'#include "new_game.h"\n#include "config/cliffs.h" // {MARKER}\n'
        f'#include "cliffs_start.h"  // {MARKER}',
    ),
    # 3. No truck cutscene.
    (
        "src/overworld.c",
        "    gFieldCallback = ExecuteTruckSequence;",
        f"""#if CLIFFS_MODE == TRUE // {MARKER}
    gFieldCallback = NULL;
#else
    gFieldCallback = ExecuteTruckSequence;
#endif""",
    ),
    (
        "src/overworld.c",
        '#include "overworld.h"',
        f'#include "overworld.h"\n#include "config/cliffs.h" // {MARKER}',
    ),
]


def apply_patch(path: pathlib.Path, anchor: str, replacement: str, check_only: bool) -> str:
    text = path.read_text()
    if replacement in text:
        return "already applied"
    if anchor not in text:
        fail(f"{path.name}: anchor not found -- the engine source has moved.\n"
             f"  looking for: {anchor.splitlines()[0][:70]}...")
    if text.count(anchor) != 1:
        fail(f"{path.name}: anchor is ambiguous ({text.count(anchor)} matches)")
    if check_only:
        return "WOULD APPLY"
    path.write_text(text.replace(anchor, replacement, 1))
    if replacement not in path.read_text():
        fail(f"{path.name}: patch did not read back")
    return "applied"


# --------------------------------------------------------------------------

def run_new_map(hack: pathlib.Path, spec: dict, scratch: pathlib.Path) -> None:
    oversize = spec.pop("_oversize")
    path = scratch / f"{spec['name']}.json"
    path.write_text(json.dumps(spec, indent=2) + "\n")
    argv = [sys.executable, str(TOOLS / "new_map.py"), "--hack", str(hack)]
    if oversize:
        argv.append("--allow-oversize")
    argv.append(str(path))
    proc = subprocess.run(argv, capture_output=True, text=True)
    sys.stdout.write("".join(f"    {line}\n" for line in proc.stdout.splitlines()))
    if proc.returncode != 0:
        fail(f"new_map.py failed for {spec['name']}:\n{proc.stderr.strip()}")


def assert_engine_agrees(hack: pathlib.Path) -> None:
    """Re-derive the two ceilings from the fork before trusting our arithmetic.

    Doc 59's rule: a design doc's derived numbers rot. WIDE_W/LEGAL_H/VOID_H and
    the 20x17 window are only meaningful against the constants this fork was
    actually built with, so read them back rather than remembering them.
    """
    fieldmap = (hack / "include/fieldmap.h").read_text()
    glob = (hack / "include/constants/global.h").read_text()
    import re

    def one(text, name):
        m = re.search(rf"#define\s+{name}\s+(\d+)", text)
        if not m:
            fail(f"{name} not found -- the engine's constants have moved")
        return int(m.group(1))

    ceiling = one(fieldmap, "MAX_MAP_DATA_SIZE")
    offset = one(fieldmap, "MAP_OFFSET")
    slots = one(glob, "OBJECT_EVENTS_COUNT")
    if offset != MAP_OFFSET:
        fail(f"MAP_OFFSET is {offset}, this fixture is built around {MAP_OFFSET}")
    ow, oh = offset * 2 + 1, offset * 2

    legal = (WIDE_W + ow) * (LEGAL_H + oh)
    void = (WIDE_W + ow) * (VOID_H + oh)
    if legal > ceiling:
        fail(f"CliffLegal is {legal} > {ceiling}: it is meant to be the CONTROL")
    if void <= ceiling:
        fail(f"CliffVoid is {void} <= {ceiling}: it is meant to be over the cliff")
    if (WIDE_W + ow) * (LEGAL_H + 1 + oh) != void:
        fail("CliffVoid is not CliffLegal plus exactly one row")

    n_objects = len(KIDS) + len(EXTRAS)
    budget = slots - 1     # the player holds one
    if n_objects <= budget:
        fail(f"{n_objects} objects is within the {budget} budget -- no cliff")
    print(f"==> ceilings re-read from the fork")
    print(f"    map size:  {legal} legal / {void} void, of {ceiling} "
          f"(margins {ow}x{oh} from MAP_OFFSET {offset})")
    print(f"    slots:     {n_objects} objects against {slots} slots minus the "
          f"player = {budget}; {n_objects - budget} must vanish")


# --------------------------------------------------------------------------
# The verification specs
# --------------------------------------------------------------------------
#
# Emitted from the fork AFTER it is built, never from the Python constants
# above, so what a spec expects is derived from the map data the ROM was
# actually made from plus the engine's documented rule -- not from the same
# variables that authored the map. The rule being asserted, stated once:
#
#   * InitBackupMapLayoutData writes the layout starting at
#     sBackupMapData[width*MAP_OFFSET + MAP_OFFSET], so plan[0][0] lands there.
#     If the copy is skipped that word is still the MAPGRID_UNDEFINED that the
#     unconditional CpuFastFill16 put there.
#   * TrySpawnObjectEvents walks templates IN ORDER and each spawned object
#     takes the first free gObjectEvents slot, with the player already holding
#     slot 0. So slot i holds template i, and templates past the budget hold
#     nothing.
#   * currentCoords = template coords + MAP_OFFSET.
#
# Every probe reads a stock engine global. This fixture adds no RAM.

OBJECT_EVENT_COORDS_OFFSET = 0x10    # asserted against the header's own comment
MAP_HEADER_LAYOUT_ID_OFFSET = 0x12
COORDS_DECL = "/*0x10*/ struct Coords16 currentCoords;"
LAYOUT_ID_DECL = "/* 0x12 */ u16 mapLayoutId;"

ARMS = {
    "CliffLegal": [],
    "CliffVoid": ["A"],
    "CliffCrowd": ["B"],
    "CliffCrowdReordered": ["Select"],
}
SPEC_NAMES = {
    "CliffLegal": "cliff-legal",
    "CliffVoid": "cliff-void",
    "CliffCrowd": "cliff-crowd",
    "CliffCrowdReordered": "cliff-crowd-reordered",
}


def _sym_size(hack: pathlib.Path, name: str) -> int:
    sym = hack / "pokeemerald.sym"
    if not sym.is_file():
        fail(f"{sym} does not exist -- build the fork before emitting specs")
    for line in sym.read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[3] == name:
            return int(parts[2], 16)
    fail(f"{name} not in {sym}")


def _layout_ids(hack: pathlib.Path) -> dict[str, int]:
    import re
    path = hack / "include/constants/layouts.h"
    if not path.is_file():
        fail(f"{path} is generated by the build -- build the fork first")
    return {m.group(1): int(m.group(2))
            for m in re.finditer(r"#define\s+(LAYOUT_\w+)\s+(\d+)", path.read_text())}


def _sizes(hack: pathlib.Path) -> dict:
    """Everything the specs are computed from, taken from the fork itself."""
    fieldmap = (hack / "include/global.fieldmap.h").read_text()
    for decl in (COORDS_DECL, LAYOUT_ID_DECL):
        if decl not in " ".join(fieldmap.split()).replace("/*", " /*").replace("*/", "*/ ") \
                and decl.replace(" ", "") not in fieldmap.replace(" ", ""):
            fail(f"global.fieldmap.h no longer declares {decl!r} -- re-derive the "
                 f"offsets these specs read")
    slots = int(__import__("re").search(
        r"#define\s+OBJECT_EVENTS_COUNT\s+(\d+)",
        (hack / "include/constants/global.h").read_text()).group(1))
    total = _sym_size(hack, "gObjectEvents")
    if total % slots:
        fail(f"gObjectEvents is {total} B over {slots} slots -- not a whole stride")
    return {"slots": slots, "stride": total // slots,
            "layouts": _layout_ids(hack),
            "grid_words": _sym_size(hack, "sBackupMapData") // 2}


def _probe(pid, why, symbol, offset, ptype, sample):
    p = {"id": pid, "why": why, "symbol": symbol, "type": ptype, "sample": sample}
    if offset:
        p["offset"] = offset
    return p


def _map_facts(hack: pathlib.Path, name: str) -> dict:
    layouts = {r["id"]: r for r in json.loads(
        (hack / "data/layouts/layouts.json").read_text())["layouts"]}
    mapd = json.loads((hack / "data/maps" / name / "map.json").read_text())
    lay = layouts[mapd["layout"]]
    return {"map": mapd, "w": lay["width"], "h": lay["height"],
            "layout_id": mapd["layout"]}


def emit_specs(hack: pathlib.Path, out_dir: pathlib.Path, check_only: bool) -> None:
    sizes = _sizes(hack)
    ow, oh = MAP_OFFSET * 2 + 1, MAP_OFFSET * 2
    undefined = 0x3FF          # MAPGRID_UNDEFINED == MAPGRID_METATILE_ID_MASK

    written, specs = [], {}
    for name, keys in ARMS.items():
        facts = _map_facts(hack, name)
        gw, gh = facts["w"] + ow, facts["h"] + oh
        void = gw * gh > sizes["grid_words"]
        first_word_index = gw * MAP_OFFSET + MAP_OFFSET
        if first_word_index * 2 + 2 > sizes["grid_words"] * 2:
            fail(f"{name}: the first copied word is off the end of sBackupMapData")

        walk = name in ("CliffLegal", "CliffVoid")
        timeline = [{"name": "boot", "frames": 900, "keys": list(keys)}]
        if walk:
            timeline.append({"name": "walk", "frames": 420,
                             "keys": sorted(set(keys) | {"Down"})})
        else:
            timeline.append({"name": "settle",
                             "frames": {"random_range": [30, 90]},
                             "keys": list(keys)})
        endstep = "walk" if walk else "settle"
        # Sampling starts at the second step and never before it. A plain
        # `every` counts from frame 0, so `at: "all"` would include samples
        # taken before the map is loaded, where every one of these globals
        # honestly reads zero -- a FAIL about the boot sequence wearing the
        # costume of a FAIL about the map.
        sample = {"at_step_start": [endstep], "at_step_end": [endstep],
                  "at": [960, 1080, 1200] if walk else [910, 925]}

        probes, asserts = [], []
        probes.append(_probe(
            "layout_id",
            f"gMapHeader.mapLayoutId. Which of the four fixture maps the boot-key "
            f"selector actually chose. Doc 66's rule: assert that the thing under "
            f"test happened, or a green run may be a run of something else.",
            "gMapHeader", MAP_HEADER_LAYOUT_ID_OFFSET, "u16", sample))
        asserts.append({"probe": "layout_id", "check": "compare", "at": "all",
                        "op": "==", "value": sizes["layouts"][facts["layout_id"]],
                        "why": f"{facts['layout_id']}"})

        probes.append(_probe(
            "grid_w",
            "gBackupMapLayout.width. InitMapLayoutData sets width and height "
            "BEFORE the ceiling test, so these are correct on both sides of the "
            "cliff -- which is exactly why the failure is invisible.",
            "gBackupMapLayout", 0, "s32", sample))
        probes.append(_probe(
            "grid_h", "gBackupMapLayout.height, same reasoning as grid_w.",
            "gBackupMapLayout", 4, "s32", sample))
        asserts += [
            {"probe": "grid_w", "check": "compare", "at": "all", "op": "==",
             "value": gw, "why": f"{facts['w']} + MAP_OFFSET_W {ow}"},
            {"probe": "grid_h", "check": "compare", "at": "all", "op": "==",
             "value": gh, "why": f"{facts['h']} + MAP_OFFSET_H {oh}"},
        ]

        probes.append(_probe(
            "first_block",
            f"sBackupMapData[{first_word_index}] -- gBackupMapLayout.width * "
            f"MAP_OFFSET + MAP_OFFSET, the FIRST word InitBackupMapLayoutData "
            f"writes. It holds plan[0][0], a block whose metatile, collision and "
            f"elevation are all non-zero on purpose ({MARK_WORD:#06x}), so an "
            f"exact compare here lands on neither 0 nor {undefined:#06x} "
            f"(doc 58: never let an exact compare rest on zero).",
            "sBackupMapData", first_word_index * 2, "u16", sample))
        asserts.append({
            "probe": "first_block", "check": "compare", "at": "all", "op": "==",
            "value": undefined if void else MARK_WORD,
            "why": ("THE CLIFF. The layout was never copied, so this is still the "
                    "MAPGRID_UNDEFINED that the unconditional CpuFastFill16 left. "
                    "SUPPORTING, AND WEAK ON ITS OWN -- measured: it SURVIVES "
                    "--counterfactual's address shift, because the fill covers the "
                    "whole 20 KB buffer, so a shifted address inside sBackupMapData "
                    "reads the same 0x3FF. Doc 58's `an exact compare against ZERO "
                    "is weak' generalised: an exact compare against the value a "
                    "buffer is BULK-INITIALISED to is weak for the same reason. "
                    "What discriminates is the PAIR -- cliff-legal's half of this "
                    "same assertion expects 0x3601 and does FAIL under the shift."
                    if void else
                    "The layout was copied: this is the marker block from the plan. "
                    "STRONG: an exact compare against a value with all three block "
                    "fields non-zero, and it FAILs under --counterfactual as it "
                    "must.")})

        if walk:
            for axis, off in (("x", OBJECT_EVENT_COORDS_OFFSET),
                              ("y", OBJECT_EVENT_COORDS_OFFSET + 2)):
                probes.append(_probe(
                    f"player_{axis}",
                    f"gObjectEvents[0].currentCoords.{axis}. Slot 0 is the player: "
                    f"InitObjectEventsLocal calls ResetObjectEvents, then "
                    f"InitPlayerAvatar, then TrySpawnObjectEvents.",
                    "gObjectEvents", off, "u16", sample))
            start_x, start_y = WIDE_START
            asserts += [
                {"probe": "player_x", "check": "compare", "at": "all", "op": "==",
                 "value": start_x + MAP_OFFSET,
                 "why": "walking Down never changes x on either map"},
                {"probe": "player_y", "check": "compare", "at": "first", "op": "==",
                 "value": start_y + MAP_OFFSET, "why": "the warp destination"},
                {"probe": "player_y", "check": "compare", "at": "last",
                 "op": "==" if void else ">",
                 "value": start_y + MAP_OFFSET,
                 "why": ("THE CLIFF'S CONSEQUENCE. MapGridGetCollisionAt returns "
                         "TRUE for MAPGRID_UNDEFINED, so every tile of a void map "
                         "is a wall: 420 frames of Down move the player nowhere."
                         if void else
                         "the control: the same 420 frames of Down do move him")},
                {"probe": "player_y", "check": "constant" if void else
                    "non_decreasing",
                 "why": ("he cannot take a single step" if void else
                         "he only ever walks Down")},
            ]
        else:
            objs = facts["map"]["object_events"]
            budget = sizes["slots"] - 1
            spawned = objs[:budget]
            lost = objs[budget:]
            for slot in range(sizes["slots"]):
                for axis, off in (("x", OBJECT_EVENT_COORDS_OFFSET),
                                  ("y", OBJECT_EVENT_COORDS_OFFSET + 2)):
                    pid = f"slot{slot}_{axis}"
                    probes.append(_probe(
                        pid,
                        f"gObjectEvents[{slot}].currentCoords.{axis}",
                        "gObjectEvents", slot * sizes["stride"] + off, "u16", sample))
                    if slot == 0:
                        want, why = CROWD_START["xy".index(axis)] + MAP_OFFSET, "the player"
                    else:
                        t = spawned[slot - 1]
                        want = t[axis] + MAP_OFFSET
                        why = (f"template {slot} ({t['graphics_id']}) authored at "
                               f"({t['x']},{t['y']})")
                    asserts.append({"probe": pid, "check": "compare", "at": "all",
                                    "op": "==", "value": want, "why": why})
            # NO per-lost-template assertion. The first draft added one -- a
            # `!=` against the lost object's x on the last slot -- and it FAILED
            # on a correct run, because a coordinate is not an identifier: a kid
            # at x=10 and a scientist at x=10 give the same 17. The absence is
            # proved by EXHAUSTION instead: all 16 slots above are pinned to
            # other templates by exact compares, so there is nowhere left for
            # these to be. Recorded in the description rather than faked as an
            # assertion.
            del lost

        spec = {
            "name": SPEC_NAMES[name],
            "description": _describe(name, facts, gw, gh, void, sizes),
            "symbols_from": "cliffs",
            "symbols_from_why":
                "Every probe here names a STOCK engine global (gMapHeader, "
                "gBackupMapLayout, sBackupMapData, gObjectEvents) -- this fixture "
                "adds no RAM at all. The key is still declared because the MAP the "
                "spec is about exists only in this fork, and a run against the "
                "pinned engine would resolve every symbol and assert nonsense.",
            "screenshot": True,
            "timeline": timeline,
            "probes": probes,
            "assert": asserts,
        }
        specs[name] = spec
        written.append(_write(out_dir, spec, check_only))

    # The mirror counterfactuals. Each takes one arm's TIMELINE and the other
    # arm's EXPECTATIONS: same ROM, same probes, same addresses, deliberately
    # wrong values. Unlike --counterfactual (which shifts every address into
    # unrelated memory and so breaks everything indiscriminately), a mirror
    # fails on EXACTLY the discriminators while the shared controls stay green
    # -- and that split is what aims the failure at the cliff rather than at
    # "a different run" (docs 57, 59, 63).
    for src, expectations in (("CliffVoid", "CliffLegal"),
                              ("CliffCrowd", "CliffCrowdReordered")):
        mirror = json.loads(json.dumps(specs[expectations]))
        mirror["name"] = f"{SPEC_NAMES[src]}-counterfactual"
        mirror["timeline"] = json.loads(json.dumps(specs[src]["timeline"]))
        mirror["screenshot"] = False
        mirror["description"] = (
            f"MUST FAIL -- run it with --expect-fail. The {SPEC_NAMES[src]} "
            f"timeline (so the ROM really is on {src}) judged against "
            f"{SPEC_NAMES[expectations]}'s expected values. The assertions the two "
            f"maps SHARE must still PASS; only the ones the cliff changes may go "
            f"red, and that split is the proof that the failure is aimed at the "
            f"cliff and not at the run. Generated by make_cliffs.py --specs.")
        written.append(_write(out_dir, mirror, check_only))

    for name, np, na in written:
        print(f"    {name}: {np} probes, {na} assertions")


def _write(out_dir: pathlib.Path, spec: dict, check_only: bool):
    path = out_dir / f"{spec['name']}.json"
    text = json.dumps(spec, indent=2) + "\n"
    if check_only:
        same = path.exists() and path.read_text() == text
        return (f"{path.name} ({'unchanged' if same else 'WOULD WRITE'})",
                len(spec["probes"]), len(spec["assert"]))
    path.write_text(text)
    if path.read_text() != text:
        fail(f"{path} did not read back")
    return (path.name, len(spec["probes"]), len(spec["assert"]))


def _describe(name, facts, gw, gh, void, sizes) -> str:
    keys = ARMS[name] or ["nothing"]
    common = (f"Doc 67 item C -- the two-cliff fixture. Cold boot with "
              f"{'+'.join(keys)} held, which is how hacks/cliffs' "
              f"new-game hook picks a start map (src/cliffs_start.c reads "
              f"REG_KEYINPUT). Generated by tools/make_cliffs.py --specs "
              f"from the fork's own map data; do not hand-edit. ")
    if void:
        return common + (
            f"{name} is {facts['w']}x{facts['h']}, so InitMapLayoutData computes "
            f"{gw}x{gh} = {gw * gh} against MAX_MAP_DATA_SIZE {sizes['grid_words']} "
            f"and SKIPS the copy. Nothing errors. The proof is a pair with "
            f"cliff-legal.json, which is the SAME map one row shorter and "
            f"must read a real block where this one reads MAPGRID_UNDEFINED -- a "
            f"void screenshot on its own is equally consistent with a generator "
            f"that wrote a broken map (doc 61 sec.4).")
    if name == "CliffLegal":
        return common + (
            f"{name} is {facts['w']}x{facts['h']} -> {gw * gh} of "
            f"{sizes['grid_words']}: THE LARGEST LEGAL MAP at this width, and the "
            f"control for cliff-cliffvoid.json.")
    objs = facts["map"]["object_events"]
    n = len(objs)
    budget = sizes["slots"] - 1
    order = ("scientists LAST" if name == "CliffCrowd" else "scientists FIRST")
    lost = ", ".join(f"{t['graphics_id']} at ({t['x']},{t['y']})"
                     for t in objs[budget:])
    return common + (
        f"{name} carries {n} always-visible object events inside one spawn window "
        f"against {sizes['slots']} gObjectEvents slots minus the player = {budget}, "
        f"with the two {order} in template order. Its pair is the other crowd map: "
        f"THE SAME {n} TEMPLATES AT THE SAME COORDINATES in a different list order. "
        f"If a different pair goes missing there, the loss is a slot budget and not "
        f"a malformed template -- which is the reading a single crowd map cannot "
        f"rule out. WHAT MUST BE MISSING HERE: {lost}. That absence is asserted by "
        f"EXHAUSTION, not by an inequality -- all {sizes['slots']} slots are pinned "
        f"to other templates by exact compares, so there is nowhere left for these "
        f"two to be. (A `!= that x` assertion was tried first and is simply wrong: "
        f"a coordinate is not an identifier, and two different templates share an "
        f"x all the time.)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hack", default=str(DEFAULT_HACK), help="fork to convert")
    ap.add_argument("--check", action="store_true",
                    help="report what would change; write nothing")
    ap.add_argument("--specs", action="store_true",
                    help="emit verify/cliff-*.json from the BUILT fork "
                         "and exit (needs pokeemerald.sym and the generated "
                         "include/constants/layouts.h)")
    args = ap.parse_args()

    hack = pathlib.Path(args.hack)
    if not (hack / "src" / "new_game.c").exists():
        fail(f"{hack} is not a pokeemerald fork "
             f"(run: python3 tools/new_hack.py cliffs)")

    if args.specs:
        out = hx.SPEC_DIR
        print(f"==> {'checking' if args.check else 'emitting'} specs into {out}")
        emit_specs(hack, out, args.check)
        return

    assert_engine_agrees(hack)

    files = {
        "include/config/cliffs.h": CONFIG_HEADER,
        "include/cliffs_start.h": START_HEADER,
        "src/cliffs_start.c": START_SOURCE,
    }
    print(f"==> {'checking' if args.check else 'writing'} fixture files")
    for rel, content in files.items():
        target = hack / rel
        same = target.exists() and target.read_text() == content
        if args.check:
            print(f"    {rel}: {'unchanged' if same else 'WOULD WRITE'}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            if target.read_text() != content:
                fail(f"{rel} did not read back")
            print(f"    {rel}: {'unchanged' if same else 'written'}")

    print(f"==> {'checking' if args.check else 'applying'} engine patches")
    for rel, anchor, replacement in PATCHES:
        print(f"    {rel}: {apply_patch(hack / rel, anchor, replacement, args.check)}")

    print(f"==> {'checking' if args.check else 'writing'} four maps")
    groups = json.loads((hack / "data/maps/map_groups.json").read_text())
    scratch = hack / ".cliffs_specs"
    if not args.check:
        scratch.mkdir(exist_ok=True)
    for spec in build_specs():
        if spec["name"] in groups.get(GROUP, []):
            print(f"    {spec['name']}: already present")
            continue
        if args.check:
            print(f"    {spec['name']}: WOULD WRITE")
            continue
        print(f"    {spec['name']}:")
        run_new_map(hack, spec, scratch)

    if not args.check:
        print(f"\nNext:\n"
              f"  python3 tools/check_map.py --hack {hack} "
              f"CliffLegal CliffVoid CliffCrowd CliffCrowdReordered\n"
              f"  build the fork, then run the cliff-* specs in verify/")


if __name__ == "__main__":
    main()
