#!/usr/bin/env python3
"""Build the OBJ-PALETTE FIXTURE: a ROM that runs a crowd past the sprite
palette budget on purpose, so the failure can be photographed.

Doc 67 slate item E. That item was written from doc 47 sec.13.2, which quotes
the engine's own comment:

    // The same standard set of palettes for overworld objects are normally
    // always loaded at the same time while walking around the overworld. The
    // only exceptions are the palettes for the player and the "special" NPC,
    // which can be swapped out. This also means that e.g. two "special" NPCs
    // with competing palettes cannot be properly loaded at the same time.

THAT COMMENT DESCRIBES A SYSTEM THAT IS NOT RUNNING AT THIS PIN. Reading the
fork before building anything:

  * `InitObjectEventPalettes` -- the function that installs the fixed slot
    assignment -- HAS NO CALLERS. Nothing in src/ calls it.
  * `sObjectPaletteTagSets` and `gReflectionEffectPaletteMap` are read only
    from inside that dead function and from two other functions
    (`LoadPlayerObjectReflectionPalette`, `LoadSpecialObjectReflectionPalette`)
    that also have no callers.
  * `struct ObjectEventGraphicsInfo.paletteSlot` -- the field that would say
    WHICH fixed slot a graphic belongs in, and the field the whole PALSLOT_*
    enum exists to populate -- is written in 36 data rows and READ NOWHERE.

What actually runs is dynamic, tag-keyed, first-fit allocation:
`LoadObjectEventPalette` -> `LoadSpritePaletteIfTagExists` -> `LoadSpritePalette`,
which calls `IndexOfSpritePaletteTag` and scans slots
`gReservedSpritePaletteCount .. 15` for a free one. So there is no "special"
slot to collide over, and two "special" NPCs coexist fine.

THE WALL UNDERNEATH IS REAL, AND IT IS WORSE, BECAUSE IT IS SILENT AND
MIS-COLOURS RATHER THAN OMITS:

    LoadSpritePalette returns 0xFF when all 16 slots are taken (sprite.c).
    CreateSprite then does
        sprite->oam.paletteNum = IndexOfSpritePaletteTag(template->paletteTag);
    which is also 0xFF -- and `oam.paletteNum` is a FOUR-BIT bitfield
    (include/gba/types.h). 0xFF truncates to 15.

An NPC past the budget therefore does not vanish (that is the OBJECT-EVENT
budget, doc 68) and does not error. It is drawn, in full, in the correct place,
animating correctly, wearing WHATEVER PALETTE 15 HAPPENS TO HOLD. Nothing about
the picture says "error" -- doc 68's plausible-artifact class, and the reason
item E was filed as screenshot-class in the first place.

MEASURED BASELINE, before this fixture existed (verify/palette-baseline.json,
run against the STOCK engine on emerald_overworld.ss1 -- no fork, no build,
because every probe named an engine global):

    gReservedSpritePaletteCount = 0        (not 12: nothing reserves in the field)
    slot 0  0x1200  TAG_WEATHER_START
    slot 1  0x1201  weather+1
    slot 2  0x1100  OBJ_EVENT_PAL_TAG_BRENDAN   (the player)
    slot 3  0x1104  OBJ_EVENT_PAL_TAG_NPC_2     (freed when that NPC left)
    slot 4  0x1103  OBJ_EVENT_PAL_TAG_NPC_1
    slots 5-15      free

Five of sixteen. Doc 67's table says "12 of 16 pre-committed; 4 NPC + 1 special"
and that every NPC palette costs a second bank for its reflection whether or not
it ever goes near water. Both are stale: reflections allocate ON DEMAND, through
the same tag allocator, only when SetUpReflection runs.

WHAT IT MAKES -- two maps in one ROM, identical in every respect except which
graphics the fifteen NPCs use, so the only variable is the number of DISTINCT
palettes demanded:

  PalControl   15 NPCs drawn from the four stock NPC palettes (NPC_1..NPC_4).
               This is what a real Emerald crowd looks like, and it is the
               control: same count, same coordinates, same order, same map.
  PalCliff     THE SAME 15 POSITIONS IN THE SAME ORDER, each NPC a graphic with
               a DISTINCT palette tag. 15 tags + the player + two weather
               sprites = 18 claims on 16 slots.

The pair is the point, not the cliff arm (doc 61 sec.4): a single crowded map
mis-colouring is equally consistent with "that graphic is broken". Two arms
that differ only in palette DIVERSITY, at identical positions, are not.

Fifteen is not a round number, it is the OTHER wall: gObjectEvents has 16 slots
and the player holds one (doc 68 sec.4), so 15 NPCs is the most a map can show.
Which means the two budgets very nearly protect each other -- indoors, with no
weather, 15 distinct NPCs plus the player is exactly 16 and NOTHING OVERFLOWS.
These maps are OUTDOOR on purpose: weather is the claimant that tips it over,
and a town square is where a crowd would actually be.

HOW YOU GET TO EACH ONE -- the same boot-key selector make_cliffs.py used, for
the same reason: every spec is then a cold boot with one key held for the whole
run, with no walking and no frame counts to drift.

    (nothing held) -> PalControl        A held -> PalCliff

Keys picked against the mGBA keymap this actually gets played on
(~/.config/mgba/config.ini, section gba.input.QT_K), not mGBA's defaults.

WHY A GENERATOR RATHER THAN EDITS IN THE FORK. `hacks/` is gitignored,
so a fork is disposable and source edits inside one are not durable. This file
is the artifact; the fork can be deleted and rebuilt at any time. Doc 68's rule:
until you have replayed it, "the tool can rebuild this" is a hope -- so run
`--verify-replay` and get a byte-identical ROM sha before believing it.

Usage:
    python3 tools/make_palettes.py                 # fork + generate + patch
    python3 tools/make_palettes.py --check         # dry run, changes nothing
    python3 tools/make_palettes.py --specs         # emit verify/palette-*.json
"""

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import hx  # noqa: E402
REPO_ROOT = hx.HARNESS_ROOT
TOOLS = hx.TOOLS
ENGINE = hx.ENGINE
DEFAULT_HACK = hx.HACKS / "palettes"
SPEC_DIR = hx.SPEC_DIR

MARKER = "PALETTES_FIXTURE"

GROUP = "gMapGroup_TownsAndRoutes"

# Tilesets and blocks come from LAYOUT_ROUTE101 via `new_map.py --dump-layout`.
# Derive, don't guess: a metatile id is meaningless outside its tileset pair,
# and a wrong one is a wall where you wanted grass, not an error (doc 65).
PRIMARY, SECONDARY = "gTileset_General", "gTileset_Petalburg"
BORDER = [468, 469, 476, 477]
GRASS = [1, 0, 3]        # walkable, elevation 3
FENCE = [468, 1, 0]      # solid

MAP_W, MAP_H = 20, 18
PLAYER_START = (8, 15)

# The fifteen NPC positions, shared by both arms verbatim. Spaced two tiles
# apart so a 32x32 graphic does not visually overlap its neighbour -- the
# finding is a COLOUR and overlapping sprites would muddy the photograph.
SLOTS = [(x, y) for y in (8, 10, 12) for x in (4, 6, 8, 10, 12)]
assert len(SLOTS) == 15

# THE CONTROL ARM: fifteen NPCs, four palettes. What Emerald actually does.
CONTROL_GFX = [
    "OBJ_EVENT_GFX_BOY_2",     "OBJ_EVENT_GFX_TWIN",      "OBJ_EVENT_GFX_BOY_1",
    "OBJ_EVENT_GFX_BOY_3",     "OBJ_EVENT_GFX_WOMAN_1",   "OBJ_EVENT_GFX_GIRL_1",
    "OBJ_EVENT_GFX_GIRL_2",    "OBJ_EVENT_GFX_EXPERT_M",  "OBJ_EVENT_GFX_FAT_MAN",
    "OBJ_EVENT_GFX_GIRL_3",    "OBJ_EVENT_GFX_RICH_BOY",  "OBJ_EVENT_GFX_EXPERT_F",
    "OBJ_EVENT_GFX_WOMAN_4",   "OBJ_EVENT_GFX_POKEFAN_F", "OBJ_EVENT_GFX_MAN_1",
]
CONTROL_EXPECTED_TAGS = 4

# THE CLIFF ARM: fifteen NPCs, fifteen palettes. Each entry is (graphics id,
# the palette tag it MUST have) and the generator proves the pairing against
# the fork's own data rather than trusting this list -- doc 69's rule, after a
# hand-written list of ball tables missed three of nine.
CLIFF_GFX = [
    ("OBJ_EVENT_GFX_BOY_2",                "OBJ_EVENT_PAL_TAG_NPC_1"),
    ("OBJ_EVENT_GFX_TWIN",                 "OBJ_EVENT_PAL_TAG_NPC_2"),
    ("OBJ_EVENT_GFX_BOY_1",                "OBJ_EVENT_PAL_TAG_NPC_3"),
    ("OBJ_EVENT_GFX_BOY_3",                "OBJ_EVENT_PAL_TAG_NPC_4"),
    ("OBJ_EVENT_GFX_LINK_BRENDAN",         "OBJ_EVENT_PAL_TAG_MAY"),
    ("OBJ_EVENT_GFX_LINK_RS_BRENDAN",      "OBJ_EVENT_PAL_TAG_RS_BRENDAN"),
    ("OBJ_EVENT_GFX_LINK_RS_MAY",          "OBJ_EVENT_PAL_TAG_RS_MAY"),
    ("OBJ_EVENT_GFX_LEAF",                 "OBJ_EVENT_PAL_TAG_RED_LEAF"),
    ("OBJ_EVENT_GFX_MOVING_BOX",           "OBJ_EVENT_PAL_TAG_MOVING_BOX"),
    ("OBJ_EVENT_GFX_QUINTY_PLUMP",         "OBJ_EVENT_PAL_TAG_QUINTY_PLUMP"),
    ("OBJ_EVENT_GFX_VIGOROTH_CARRYING_BOX","OBJ_EVENT_PAL_TAG_VIGOROTH"),
    ("OBJ_EVENT_GFX_ZIGZAGOON_1",          "OBJ_EVENT_PAL_TAG_ZIGZAGOON"),
    ("OBJ_EVENT_GFX_POOCHYENA",            "OBJ_EVENT_PAL_TAG_POOCHYENA"),
    ("OBJ_EVENT_GFX_DEOXYS",               "OBJ_EVENT_PAL_TAG_DEOXYS"),
    ("OBJ_EVENT_GFX_LUGIA",                "OBJ_EVENT_PAL_TAG_LUGIA"),
]
assert len(CLIFF_GFX) == len(SLOTS)
assert len({t for _, t in CLIFF_GFX}) == len(CLIFF_GFX), "cliff tags must be distinct"


def fail(msg):
    print(f"make_palettes.py: {msg}", file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------
# Maps
# --------------------------------------------------------------------------

def rect_plan(w: int, h: int) -> list[str]:
    """A fenced field of plain grass. No marker block: unlike make_cliffs.py
    this fixture asserts nothing about map DATA, only about who is standing on
    it, so the map wants to be as boring as possible."""
    top = "#" * w
    middle = "#" + "e" * (w - 2) + "#"
    return [top] + [middle] * (h - 2) + [top]


def layout() -> dict:
    return {
        "primary_tileset": PRIMARY,
        "secondary_tileset": SECONDARY,
        "border": list(BORDER),
        "palette": {"e": list(GRASS), "#": list(FENCE)},
        "plan": rect_plan(MAP_W, MAP_H),
    }


HEADER = {"music": "MUS_NONE", "region_map_section": "MAPSEC_ROUTE_101",
          "map_type": "MAP_TYPE_TOWN"}


def scripts_for(name: str) -> str:
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
        "flag": "0",
    }


# How many NPCs get refused, and therefore how many entries at the tail of the
# template list are the victims. Measured, not assumed: the first cliff run
# came back load_fails 2.
VICTIMS = 2


def build_specs() -> list[dict]:
    control = [object_event("PalControl", g, x, y)
               for g, (x, y) in zip(CONTROL_GFX, SLOTS)]
    cliff = [object_event("PalCliff", g, x, y)
             for (g, _tag), (x, y) in zip(CLIFF_GFX, SLOTS)]

    # THE REORDERED ARM. Identical map, identical fifteen graphics, identical
    # fifteen COORDINATES -- only the order of the entries in the template list
    # differs, with the two that were refused moved to the FRONT.
    #
    # It exists because the cliff arm alone cannot distinguish the two readings
    # of its own picture: "the palette budget ran out and the last two NPCs in
    # the list were served somebody else's colours" and "those two particular
    # graphics are broken". Doc 68 used exactly this move on the object-event
    # slot budget; the same argument applies one resource over. If the same two
    # graphics now render correctly and two DIFFERENT ones are wrong, the loss
    # is a budget and the victim is decided by position in the list.
    reordered_gfx = CLIFF_GFX[-VICTIMS:] + CLIFF_GFX[:-VICTIMS]
    reordered_pos = SLOTS[-VICTIMS:] + SLOTS[:-VICTIMS]
    reordered = [object_event("PalCliffReordered", g, x, y)
                 for (g, _tag), (x, y) in zip(reordered_gfx, reordered_pos)]

    return [
        {"name": "PalControl", "group": GROUP, "layout": layout(),
         "header": dict(HEADER), "scripts": scripts_for("PalControl"),
         "object_events": control},
        {"name": "PalCliff", "group": GROUP, "layout": layout(),
         "header": dict(HEADER), "scripts": scripts_for("PalCliff"),
         "object_events": cliff},
        {"name": "PalCliffReordered", "group": GROUP, "layout": layout(),
         "header": dict(HEADER), "scripts": scripts_for("PalCliffReordered"),
         "object_events": reordered},
    ]


# --------------------------------------------------------------------------
# The fork's own source: a boot-key selector and a probe
# --------------------------------------------------------------------------

CONFIG_HEADER = f"""// {MARKER}: written by tools/make_palettes.py
#ifndef GUARD_CONFIG_PALETTES_H
#define GUARD_CONFIG_PALETTES_H

// One switch, so every fixture change in this fork is greppable.
#define PALETTES_MODE TRUE

#endif // GUARD_CONFIG_PALETTES_H
"""

PROBE_HEADER = f"""// {MARKER}: written by tools/make_palettes.py
#ifndef GUARD_PALETTES_PROBE_H
#define GUARD_PALETTES_PROBE_H

#include "global.fieldmap.h"

void PalettesSetStartWarp(void);
void PalettesProbeSample(void);

extern u8  gPalProbePaletteNum[OBJECT_EVENTS_COUNT];
extern u16 gPalProbeGfxId[OBJECT_EVENTS_COUNT];
extern u16 gPalProbeWantTag[OBJECT_EVENTS_COUNT];
extern u16 gPalProbeGotTag[OBJECT_EVENTS_COUNT];
extern u8  gPalProbeActive;
extern u8  gPalProbeSlotsUsed;
extern u8  gPalProbeMismatch;
extern u8  gPalProbeOnSlot15;
extern u16 gPalProbeLoadFails;
extern u16 gPalProbeLastFailTag;

#endif // GUARD_PALETTES_PROBE_H
"""

PROBE_SOURCE = f"""// {MARKER}: written by tools/make_palettes.py
//
// THE ONE ASSERTION THIS FIXTURE IS BUILT AROUND, stated as data rather than
// as a boolean, because the harness judges and this file must not:
//
//     for every ACTIVE object event, is the palette the hardware will draw it
//     with actually ITS OWN palette?
//
//   gPalProbeWantTag[i]  the tag its ObjectEventGraphicsInfo asks for
//   gPalProbeGotTag[i]   the tag sitting in the slot its sprite points at
//
// Those two disagreeing IS the failure. It is not "a wrong number" in any
// sense a normal probe would recognise -- the sprite is present, in the right
// place, correctly animated, and every other value about it is right. Only the
// colours are somebody else's. Hence doc 62's class, hence a screenshot.
//
// gPalProbeMismatch counts the disagreements and gPalProbeOnSlot15 counts how
// many landed specifically on slot 15, which is where the 0xFF -> 4-bit
// truncation in CreateSprite deposits everything it could not place.
//
// gPalProbeLoadFails is incremented inside LoadSpritePalette itself (a second
// patch, in src/sprite.c) and is NEVER CLEARED -- doc 66's storage rule. The
// failure it records happens once, during the map's spawn burst, and a probe
// that can be overwritten a frame later is a probe that will read zero forever
// and be asserted with a weak `!= 0` by every spec that touches it.

#include "global.h"
#include "event_object_movement.h"
#include "overworld.h"
#include "main_menu.h"
#include "new_game.h"
#include "sprite.h"
#include "constants/maps.h"
#include "config/palettes.h"
#include "palettes_probe.h"

EWRAM_DATA u8  gPalProbePaletteNum[OBJECT_EVENTS_COUNT] = {{0}};
EWRAM_DATA u16 gPalProbeGfxId[OBJECT_EVENTS_COUNT] = {{0}};
EWRAM_DATA u16 gPalProbeWantTag[OBJECT_EVENTS_COUNT] = {{0}};
EWRAM_DATA u16 gPalProbeGotTag[OBJECT_EVENTS_COUNT] = {{0}};
EWRAM_DATA u8  gPalProbeActive = 0;
EWRAM_DATA u8  gPalProbeSlotsUsed = 0;
EWRAM_DATA u8  gPalProbeMismatch = 0;
EWRAM_DATA u8  gPalProbeOnSlot15 = 0;
EWRAM_DATA u16 gPalProbeLoadFails = 0;
EWRAM_DATA u16 gPalProbeLastFailTag = 0;

void PalettesProbeSample(void)
{{
    u32 i;
    u8 active = 0, mismatch = 0, onSlot15 = 0, used = 0;

    for (i = 0; i < OBJECT_EVENTS_COUNT; i++)
    {{
        struct ObjectEvent *oe = &gObjectEvents[i];
        const struct ObjectEventGraphicsInfo *info;
        u8 palNum;

        if (!oe->active)
        {{
            gPalProbePaletteNum[i] = 0xFF;
            gPalProbeGfxId[i] = 0xFFFF;
            gPalProbeWantTag[i] = 0xFFFF;
            gPalProbeGotTag[i] = 0xFFFF;
            continue;
        }}

        active++;
        info = GetObjectEventGraphicsInfo(oe->graphicsId);
        palNum = gSprites[oe->spriteId].oam.paletteNum;

        gPalProbePaletteNum[i] = palNum;
        gPalProbeGfxId[i] = oe->graphicsId;
        gPalProbeWantTag[i] = info->paletteTag;
        gPalProbeGotTag[i] = GetSpritePaletteTagByPaletteNum(palNum);

        // TAG_NONE graphics ask for nothing and cannot be mis-served.
        if (info->paletteTag != TAG_NONE
            && gPalProbeGotTag[i] != info->paletteTag)
            mismatch++;
        if (palNum == 15)
            onSlot15++;
    }}

    for (i = 0; i < 16; i++)
    {{
        if (GetSpritePaletteTagByPaletteNum(i) != TAG_NONE)
            used++;
    }}

    gPalProbeActive = active;
    gPalProbeMismatch = mismatch;
    gPalProbeOnSlot15 = onSlot15;
    gPalProbeSlotsUsed = used;
}}

// Which arm a new game starts in, chosen by what is held at boot.
//
// REG_KEYINPUT is read directly and is ACTIVE LOW -- a 0 bit means the key is
// down. gMain.heldKeys is not used on purpose: new-game init does not run at a
// fixed point in the input cycle, and a stale read would silently select the
// wrong map, which looks exactly like a broken fixture rather than a wrong
// button.
//
// NewGameBirchSpeech_SetDefaultPlayerName IS NOT OPTIONAL. This shortcut skips
// the naming screen, and nothing else writes gSaveBlock2Ptr->playerName -- it
// stays eight zero bytes, which in this charmap is eight SPACE glyphs with NO
// TERMINATOR. The Start menu's PLAYER row looks merely blank and selecting it
// clobbers gMain (doc 68 sec.6.2, found by a person playing a different ROM
// built from the same shortcut). A shortcut that skips a setup step inherits
// every default that step would have set, and the ones that bite are the
// defaults that are zero-VALID.
void PalettesSetStartWarp(void)
{{
    u16 keys = (u16)(~REG_KEYINPUT) & KEYS_MASK;

    NewGameBirchSpeech_SetDefaultPlayerName(0);

    if (keys & A_BUTTON)
        SetWarpDestination(MAP_GROUP(PAL_CLIFF), MAP_NUM(PAL_CLIFF),
                           WARP_ID_NONE, {PLAYER_START[0]}, {PLAYER_START[1]});
    else if (keys & B_BUTTON)
        SetWarpDestination(MAP_GROUP(PAL_CLIFF_REORDERED),
                           MAP_NUM(PAL_CLIFF_REORDERED),
                           WARP_ID_NONE, {PLAYER_START[0]}, {PLAYER_START[1]});
    else
        SetWarpDestination(MAP_GROUP(PAL_CONTROL), MAP_NUM(PAL_CONTROL),
                           WARP_ID_NONE, {PLAYER_START[0]}, {PLAYER_START[1]});
}}
"""

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
        f"""#if PALETTES_MODE == TRUE // {MARKER}
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
        f'#include "intro.h"\n#include "overworld.h"        // {MARKER}\n'
        f'#include "config/palettes.h" // {MARKER}',
    ),
    # 2. Start in a fixture map, not in the moving truck.
    (
        "src/new_game.c",
        "    SetWarpDestination(MAP_GROUP(INSIDE_OF_TRUCK), MAP_NUM(INSIDE_OF_TRUCK), WARP_ID_NONE, -1, -1);",
        f"""#if PALETTES_MODE == TRUE // {MARKER}
    PalettesSetStartWarp();
#else
    SetWarpDestination(MAP_GROUP(INSIDE_OF_TRUCK), MAP_NUM(INSIDE_OF_TRUCK), WARP_ID_NONE, -1, -1);
#endif""",
    ),
    (
        "src/new_game.c",
        '#include "new_game.h"',
        f'#include "new_game.h"\n#include "config/palettes.h" // {MARKER}\n'
        f'#include "palettes_probe.h"   // {MARKER}',
    ),
    # 3. No truck cutscene.
    (
        "src/overworld.c",
        "    gFieldCallback = ExecuteTruckSequence;",
        f"""#if PALETTES_MODE == TRUE // {MARKER}
    gFieldCallback = NULL;
#else
    gFieldCallback = ExecuteTruckSequence;
#endif""",
    ),
    # 4. Sample the probe every field frame.
    (
        "src/overworld.c",
        """    UpdateTilesetAnimations();
    DoScheduledBgTilemapCopiesToVram();
}""",
        "    UpdateTilesetAnimations();\n"
        "    DoScheduledBgTilemapCopiesToVram();\n"
        f"#if PALETTES_MODE == TRUE // {MARKER}\n"
        "    PalettesProbeSample();\n"
        "#endif\n"
        "}",
    ),
    (
        "src/overworld.c",
        '#include "overworld.h"',
        f'#include "overworld.h"\n#include "config/palettes.h" // {MARKER}\n'
        f'#include "palettes_probe.h"   // {MARKER}',
    ),
    # 5. Count the allocator's refusals AT THE POINT OF REFUSAL. Without this
    #    the only evidence is the consequence, and "an NPC is wearing the wrong
    #    palette" has more than one possible cause.
    (
        "src/sprite.c",
        """    index = IndexOfSpritePaletteTag(TAG_NONE);

    if (index == 0xFF)
    {
        return 0xFF;
    }""",
        f"""    index = IndexOfSpritePaletteTag(TAG_NONE);

    if (index == 0xFF)
    {{
#if PALETTES_MODE == TRUE // {MARKER}
        gPalProbeLoadFails++;          // never cleared -- doc 66's storage rule
        gPalProbeLastFailTag = palette->tag;
#endif
        return 0xFF;
    }}""",
    ),
    (
        "src/sprite.c",
        '#include "sprite.h"',
        f'#include "sprite.h"\n#include "config/palettes.h" // {MARKER}\n'
        f'#include "palettes_probe.h"   // {MARKER}',
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
# Proving the graphics/tag pairings against the fork, not against this file
# --------------------------------------------------------------------------

def read_gfx_tags(hack: pathlib.Path) -> dict[str, str]:
    """OBJ_EVENT_GFX_* -> its ObjectEventGraphicsInfo's paletteTag, parsed out
    of the fork. Doc 69's rule: a hand-written list of engine tables missed
    three of nine, so the list in this file is a REQUEST and this is the check.
    """
    info = (hack / "src/data/object_events/object_event_graphics_info.h").read_text()
    ptrs = (hack / "src/data/object_events/object_event_graphics_info_pointers.h").read_text()
    tags = {}
    for m in re.finditer(
            r'const struct ObjectEventGraphicsInfo (gObjectEventGraphicsInfo_\w+)\s*=\s*\{(.*?)\n\};',
            info, re.S):
        t = re.search(r'\.paletteTag\s*=\s*(\w+)', m.group(2))
        if t:
            tags[m.group(1)] = t.group(1)
    out = {}
    for m in re.finditer(r'\[(OBJ_EVENT_GFX_\w+)\]\s*=\s*&(gObjectEventGraphicsInfo_\w+)', ptrs):
        if m.group(2) in tags:
            out[m.group(1)] = tags[m.group(2)]
    return out


def check_pairings(hack: pathlib.Path) -> None:
    tags = read_gfx_tags(hack)
    bad = []
    for gfx, want in CLIFF_GFX:
        got = tags.get(gfx)
        if got != want:
            bad.append(f"    {gfx}: this file says {want}, the fork says {got}")
    if bad:
        fail("the cliff arm's graphics/tag pairings disagree with the fork:\n"
             + "\n".join(bad))
    distinct = {tags[g] for g, _ in CLIFF_GFX}
    if len(distinct) != len(CLIFF_GFX):
        fail(f"cliff arm is not palette-distinct: {len(distinct)} tags "
             f"for {len(CLIFF_GFX)} NPCs")
    ctrl = {tags.get(g) for g in CONTROL_GFX}
    if None in ctrl:
        fail("a control-arm graphic is not in the fork's pointer table")
    if len(ctrl) != CONTROL_EXPECTED_TAGS:
        fail(f"control arm should demand exactly {CONTROL_EXPECTED_TAGS} "
             f"palettes, the fork says {len(ctrl)}: {sorted(ctrl)}")
    print(f"  pairings: cliff {len(distinct)} distinct tags, "
          f"control {len(ctrl)} distinct tags  [checked against the fork]")


def check_budgets(hack: pathlib.Path) -> None:
    """The two walls this fixture sits between, read out of the fork rather
    than remembered. A fixture whose premise has rotted is worse than none."""
    g = (hack / "include/constants/global.h").read_text()
    m = re.search(r'#define\s+OBJECT_EVENTS_COUNT\s+(\d+)', g)
    if not m:
        m = re.search(r'#define\s+OBJECT_EVENTS_COUNT\s+(\d+)',
                      (hack / "include/global.fieldmap.h").read_text())
    if not m:
        fail("cannot find OBJECT_EVENTS_COUNT in the fork")
    oes = int(m.group(1))
    if len(SLOTS) != oes - 1:
        fail(f"this fixture places {len(SLOTS)} NPCs, but the fork's object "
             f"event budget is {oes} minus the player = {oes - 1}. Placing "
             f"fewer would leave the palette table unexhausted; placing more "
             f"would silently drop NPCs (doc 68) and confound the two walls.")
    w, h = MAP_W, MAP_H
    cells = (w + 15) * (h + 14)
    if cells > 10240:
        fail(f"map is {cells} of 10240 -- it would load as a solid void (doc 68)")
    print(f"  budgets: {len(SLOTS)} NPCs against OBJECT_EVENTS_COUNT {oes}; "
          f"map {cells}/10240 cells")


# --------------------------------------------------------------------------
# Specs
# --------------------------------------------------------------------------
#
# TWO-PASS ON PURPOSE. The counts below are what the RUN measured, not what
# this file predicted, and until a run has happened they are None and --specs
# emits OBSERVATION specs that assert only the frame (which arm, which screen)
# and nothing about the outcome.
#
# The predictions this fixture was built on, written down BEFORE the first run
# so the measurement can contradict them rather than be shaped by them:
#
#   control  slots_used 7   (2 weather + player + NPC_1..4)
#            mismatch 0, on_slot15 0, load_fails 0
#   cliff    slots_used 16  (full)
#            15 NPC tags + player + 2 weather = 18 claims on 16 slots
#            -> load_fails 2, mismatch 2, on_slot15 2
#
# The weather term is the soft one: nothing has yet measured how many sprite
# palettes a MAP_TYPE_TOWN with no weather script actually allocates, and the
# baseline's two came off Route 101. If the cliff arm comes back with mismatch
# 0 the answer is "weather is not a claimant here", which is a real result and
# the fixture then wants a 16th claimant rather than a bigger crowd.

# MEASURED 2026-08-05. Four of the five predictions above held exactly; the one
# that did not is on_slot15, predicted 2 and measured 3 -- because slot 15's
# RIGHTFUL OWNER is standing on it too and the probe counts occupancy, not
# victims. Kept as measured rather than redefined: reshaping an instrument to
# match a prediction after seeing the answer is how you stop being able to be
# wrong. `mismatch` is the discriminator; `on_slot15` is a supporting detail
# about where the refused ones went.
EXPECT = {
    "PalControl": {
        "slots_used": 7, "mismatch": 0, "on_slot15": 0, "load_fails": 0,
        "want_last": 0x1105, "got_last": 0x1105,          # NPC_3, correctly served
    },
    "PalCliff": {
        "slots_used": 16, "mismatch": 2, "on_slot15": 3, "load_fails": 2,
        "last_fail_tag": 0x1121,                          # LUGIA was refused
        "want_last": 0x1121, "got_last": 0x111c,          # wants LUGIA, wears POOCHYENA
    },
    "PalCliffReordered": {
        "slots_used": 16, "mismatch": 2, "on_slot15": 3, "load_fails": 2,
        "last_fail_tag": 0x111c,                          # POOCHYENA was refused
        "want_last": 0x111c, "got_last": 0x110e,          # wants POOCHYENA, wears VIGOROTH
    },
}

# PREDICTED ADDRESS-SHIFT SURVIVORS, written before running --counterfactual,
# because doc 72 established that a matching survivor COUNT can hide a wrong
# composition and only the list finds it:
#   PalControl          3 -- mismatch, on_slot15 and load_fails are all exact
#                            compares against ZERO, weak since doc 58 and
#                            confirmed nine times since. They are unavoidable
#                            here: zero mis-served NPCs is what correct MEANS.
#   PalCliff            0 -- a clean sweep. Every assertion in it is an exact
#   PalCliffReordered   0    compare against a non-zero value or a symbol_at.

ARM_KEYS = {"PalControl": [], "PalCliff": ["A"], "PalCliffReordered": ["B"]}


def _sample(steps):
    return {"at_step_end": list(steps), "every": 240}


def _probe(pid, why, symbol, ptype, offset=0, sample=None):
    p = {"id": pid, "why": why, "symbol": symbol, "type": ptype,
         "sample": sample or _sample(["settle"])}
    if offset:
        p["offset"] = offset
    return p


def _layout_ids(hack: pathlib.Path) -> dict[str, int]:
    """LAYOUT_* -> its index in layouts.json, which is what gMapHeader holds."""
    data = json.loads((hack / "data/layouts/layouts.json").read_text())
    return {l["id"]: i + 1 for i, l in enumerate(data["layouts"])}


SLUG = {"PalControl": "palette-control", "PalCliff": "palette-cliff",
        "PalCliffReordered": "palette-cliff-reordered"}


def _spec_for(arm: str, hack: pathlib.Path) -> dict:
    keys = ARM_KEYS[arm]
    lid = _layout_ids(hack)[f"LAYOUT_{re.sub(r'(?<!^)(?=[A-Z])', '_', arm).upper()}"]
    exp = EXPECT[arm]
    cliff = arm != "PalControl"

    probes = [
        _probe("cb2", "Doc 66's rule -- assert the thing under test actually "
                      "happened. A palette table read on the wrong screen is a "
                      "measurement of a different screen.",
               "gMain", "ptr", 4),
        _probe("layout_id", "gMapHeader.mapLayoutId. WHICH ARM the boot-key "
                            "selector chose. Without this a green run on the "
                            "control map would be reported as a green run on "
                            "the cliff map.",
               "gMapHeader", "u16", 18),
        _probe("active", "gPalProbeActive -- live object events including the "
                         "player. 16 means the object-event budget is exactly "
                         "full, which is what makes 15 the most NPCs a map can "
                         "show and therefore what bounds this experiment.",
               "gPalProbeActive", "u8"),
        _probe("slots_used", "gPalProbeSlotsUsed -- how many of the 16 sprite "
                             "palette slots hold a tag.",
               "gPalProbeSlotsUsed", "u8"),
        _probe("mismatch", "gPalProbeMismatch -- THE DELIVERABLE. Active object "
                           "events whose sprite points at a palette slot holding "
                           "a tag that is not their own. This is the failure "
                           "stated as a number; the picture is what shows it is "
                           "not merely a number.",
               "gPalProbeMismatch", "u8"),
        _probe("on_slot15", "gPalProbeOnSlot15 -- how many landed specifically "
                            "on slot 15, where CreateSprite's 0xFF truncates to "
                            "in a 4-bit bitfield.",
               "gPalProbeOnSlot15", "u8"),
        _probe("load_fails", "gPalProbeLoadFails, latched inside LoadSpritePalette "
                             "itself. The CAUSE, recorded at the point of refusal, "
                             "independently of the consequence -- 'an NPC is "
                             "wearing the wrong colours' has more than one "
                             "possible cause and this rules the others out.",
               "gPalProbeLoadFails", "u16"),
        _probe("last_fail_tag", "gPalProbeLastFailTag -- WHICH palette was "
                                "refused. Names the victim instead of counting "
                                "victims.",
               "gPalProbeLastFailTag", "u16"),
        _probe("tag15", "sSpritePaletteTags[15]. What the mis-coloured NPCs are "
                        "actually wearing.",
               "sSpritePaletteTags", "u16", 30),
        _probe("want_last", "gPalProbeWantTag[15] -- the palette the LAST object "
                            "event slot's graphic asks for. Object events are "
                            "first-fit from slot 0 with the player in slot 0, so "
                            "this is the last template on the map: the one at the "
                            "back of the queue when the allocator runs dry.",
               "gPalProbeWantTag", "u16", 30),
        _probe("got_last", "gPalProbeGotTag[15] -- the palette it is actually "
                           "being drawn with. want_last and got_last disagreeing "
                           "IS the finding, named rather than counted: not 'two "
                           "sprites are wrong' but 'this one wanted X and is "
                           "wearing Y'.",
               "gPalProbeGotTag", "u16", 30),
    ]

    asserts = [
        {"probe": "cb2", "check": "symbol_at", "at": "all", "op": "==",
         "value": "CB2_Overworld",
         "why": "CONTROL. Shared by both arms; must be green in both, which is "
                "what aims a failure at the palettes rather than at the boot."},
        {"probe": "layout_id", "check": "compare", "at": "all", "op": "==",
         "value": lid,
         "why": f"CONTROL. This run is on {arm}, layout id {lid}."},
        {"probe": "active", "check": "compare", "at": "last", "op": "==",
         "value": len(SLOTS) + 1,
         "why": "CONTROL. 15 NPCs + the player. Shared by both arms: if this "
                "differs between them the crowd is not identical and nothing "
                "downstream compares."},
    ]

    if exp is None:
        description = (
            f"Doc 67 slate item E, OBSERVATION PASS for the {arm} arm. Emitted "
            f"by tools/make_palettes.py --specs before any run had "
            f"happened, so it asserts only WHICH ARM and WHICH SCREEN and "
            f"nothing about the outcome -- the outcome is what it is here to "
            f"measure. Re-run --specs after filling EXPECT in the generator to "
            f"get the real spec. Do not hand-edit.")
        asserts += [
            {"probe": "mismatch", "check": "always_valid", "why": "SUPPORTING. Observation pass."},
            {"probe": "load_fails", "check": "always_valid", "why": "SUPPORTING. Observation pass."},
            {"probe": "slots_used", "check": "always_valid", "why": "SUPPORTING. Observation pass."},
        ]
    else:
        description = _describe(arm, exp, lid)
        asserts += [
            {"probe": "slots_used", "check": "compare", "at": "last", "op": "==",
             "value": exp["slots_used"],
             "why": "How full the palette table got. Exact, not a threshold: "
                    "doc 55 sec.9.4's list makes in_range and >= weak under an "
                    "address shift."},
            {"probe": "mismatch", "check": "compare", "at": "last", "op": "==",
             "value": exp["mismatch"],
             "why": ("THE DISCRIMINATOR. This is the assertion the control arm "
                     "and the cliff arm disagree on, and the only one that "
                     "does." if cliff else
                     "THE DISCRIMINATOR, from the control side. Zero here and "
                     "non-zero on the cliff arm is what makes the finding a "
                     "property of palette DIVERSITY rather than of crowding.")},
            {"probe": "on_slot15", "check": "compare", "at": "last", "op": "==",
             "value": exp["on_slot15"],
             "why": "Where the refused sprites landed. Names the mechanism "
                    "(a 4-bit truncation of 0xFF) rather than just its size."},
            {"probe": "load_fails", "check": "compare", "at": "last", "op": "==",
             "value": exp["load_fails"],
             "why": "The cause, counted at the point of refusal."},
        ]
        asserts += [
            {"probe": "want_last", "check": "compare", "at": "last", "op": "==",
             "value": exp["want_last"],
             "why": "The palette the last-spawned NPC's graphic asks for."},
            {"probe": "got_last", "check": "compare", "at": "last", "op": "==",
             "value": exp["got_last"],
             "why": ("THE NAMED FINDING. It asks for want_last and is drawn "
                     "with this instead." if exp["want_last"] != exp["got_last"]
                     else "It gets what it asked for. Equal to want_last, which "
                          "is what a correct run looks like.")},
        ]
        if cliff:
            asserts.append(
                {"probe": "last_fail_tag", "check": "compare", "at": "last",
                 "op": "==", "value": exp["last_fail_tag"],
                 "why": "WHICH palette was refused, by tag. A non-zero exact "
                        "value on purpose -- doc 58's rule that a compare "
                        "against zero survives an address shift."})

    return {
        "name": SLUG[arm],
        "description": description,
        "symbols_from": hack.name,
        "symbols_from_why": (
            "gPalProbe* exist only in this fork; a run against the pinned "
            "engine would fail to resolve them. The maps exist only here too."),
        "screenshot": True,
        "timeline": [
            {"name": "boot", "frames": 900, "keys": keys},
            {"name": "settle", "frames": 600, "keys": keys},
        ],
        "probes": probes,
        "assert": asserts,
    }


def _describe(arm: str, exp: dict, lid: int) -> str:
    if arm == "PalCliffReordered":
        return (
            f"Doc 67 slate item E. THE REORDER ARM, and it is what makes the "
            f"cliff arm's picture mean something. Same map, same fifteen "
            f"palette-distinct graphics, same fifteen coordinates -- the ONLY "
            f"difference is that the {VICTIMS} entries that were refused on "
            f"palette-cliff.json are moved to the FRONT of the template list. "
            f"Booted by holding B. If those two now render correctly and a "
            f"different pair does not, the loss is a BUDGET and the victim is "
            f"chosen by position in the list; without this arm, 'Lugia looks "
            f"wrong' stays equally consistent with 'Lugia's palette is broken'. "
            f"Doc 68 made exactly this move against the object-event slot "
            f"budget. Measured: {exp['slots_used']}/16 slots, "
            f"{exp['load_fails']} refusals, {exp['mismatch']} mis-served. "
            f"Generated by make_palettes.py --specs; do not hand-edit.")
    if arm == "PalCliff":
        return (
            f"Doc 67 slate item E. THE CLIFF ARM: fifteen NPCs on one screen, "
            f"each demanding a DISTINCT sprite palette, plus the player and the "
            f"weather. Booted by holding A (hacks/palettes' new-game "
            f"hook reads REG_KEYINPUT). Its pair is palette-control.json -- the "
            f"same fifteen positions in the same order on the same map, with the "
            f"NPCs drawn from the four stock palettes instead. The two differ in "
            f"NOTHING but palette diversity, which is what makes a difference "
            f"between them a fact about the allocator rather than about a "
            f"graphic. Measured: {exp['slots_used']}/16 slots used, "
            f"{exp['load_fails']} refusals by LoadSpritePalette, "
            f"{exp['mismatch']} object events drawn in a palette that is not "
            f"theirs, {exp['on_slot15']} of them on slot 15. Generated by "
            f"make_palettes.py --specs; do not hand-edit.")
    return (
        f"Doc 67 slate item E. THE CONTROL ARM for palette-cliff.json: the same "
        f"fifteen NPC positions in the same order on the same map, but drawn "
        f"from the four stock NPC palettes -- which is what a real Emerald crowd "
        f"looks like. Cold boot with nothing held. Measured: "
        f"{exp['slots_used']}/16 slots used, {exp['mismatch']} mis-served "
        f"object events. A single crowded map coming back mis-coloured would be "
        f"equally consistent with 'one of those graphics is broken'; this arm is "
        f"what rules that out (doc 61 sec.4). Generated by make_palettes.py "
        f"--specs; do not hand-edit.")


def emit_specs(hack: pathlib.Path, out_dir: pathlib.Path, check_only: bool) -> None:
    if not (hack / "data/layouts/layouts.json").exists():
        fail(f"{hack} has no generated maps yet -- run without --specs first")
    for arm in ("PalControl", "PalCliff", "PalCliffReordered"):
        spec = _spec_for(arm, hack)
        path = out_dir / f"{spec['name']}.json"
        text = json.dumps(spec, indent=2) + "\n"
        if path.exists() and path.read_text() == text:
            print(f"  {path.name}: unchanged")
        elif check_only:
            print(f"  {path.name}: WOULD WRITE")
        else:
            path.write_text(text)
            print(f"  {path.name}: written"
                  + ("  [OBSERVATION PASS -- outcome not asserted]"
                     if EXPECT[arm] is None else ""))


# --------------------------------------------------------------------------
# Driving new_hack.py / new_map.py
# --------------------------------------------------------------------------

def run(argv, **kw):
    r = subprocess.run(argv, **kw)
    if r.returncode != 0:
        fail(f"command failed ({r.returncode}): {' '.join(str(a) for a in argv)}")
    return r


def fork(hack: pathlib.Path, check_only: bool) -> None:
    if hack.exists():
        print(f"  fork: {hack} already exists, reusing")
        return
    if check_only:
        print(f"  fork: WOULD create {hack}")
        return
    run([sys.executable, str(TOOLS / "new_hack.py"), hack.name])


def run_new_map(hack: pathlib.Path, spec: dict, scratch: pathlib.Path) -> str:
    """new_map.py is append-only and exits 1 on a map that already exists --
    which is the right behaviour for it and the wrong one to propagate here,
    because re-running this generator must be a no-op. Check the END STATE
    (is the layout in layouts.json?) rather than treating the tool's exit code
    as the answer. Doc 73: an idempotent edit needs an end-state assertion, not
    a change assertion -- the first draft of this aborted the whole loop on the
    first already-present map and never reached the third one."""
    lid = f"LAYOUT_{re.sub(r'(?<!^)(?=[A-Z])', '_', spec['name']).upper()}"
    if lid in _layout_ids(hack):
        return "already present"
    path = scratch / f"{spec['name']}.json"
    path.write_text(json.dumps(spec, indent=2) + "\n")
    run([sys.executable, str(TOOLS / "new_map.py"), "--hack", str(hack), str(path)])
    if lid not in _layout_ids(hack):
        fail(f"{spec['name']}: new_map.py exited 0 but {lid} is not in "
             f"layouts.json -- the map was not written")
    return "generated"


def write_if_changed(path: pathlib.Path, text: str, check_only: bool) -> str:
    if path.exists() and path.read_text() == text:
        return "unchanged"
    if check_only:
        return "WOULD WRITE"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return "written"


def register_source(hack: pathlib.Path, check_only: bool) -> str:
    """Add src/palettes_probe.o to the link. The build's object list is
    generated from src/*.c by the Makefile at this pin, so this is a no-op --
    but ASSERT it rather than assume it, because a source file that silently
    never links produces a fork whose feature is simply absent (doc 73's sed)."""
    mk = (hack / "Makefile").read_text()
    if "$(wildcard $(C_SUBDIR)/*.c)" not in mk and "wildcard" not in mk:
        fail("the fork's Makefile does not glob src/*.c -- palettes_probe.c "
             "would never be compiled. Add it to the object list explicitly.")
    return "globbed by the Makefile"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hack", type=pathlib.Path, default=DEFAULT_HACK)
    ap.add_argument("--check", action="store_true",
                    help="dry run: report what would change, write nothing")
    ap.add_argument("--specs", action="store_true",
                    help="emit verify/palette-*.json from the built fork")
    args = ap.parse_args()

    hack = args.hack.resolve()

    if args.specs:
        emit_specs(hack, SPEC_DIR, args.check)
        return

    print(f"make_palettes.py -> {hack}")
    fork(hack, args.check)
    if not hack.exists():
        return

    check_budgets(hack)
    check_pairings(hack)

    print("  sources:")
    for rel, text in (
        ("include/config/palettes.h", CONFIG_HEADER),
        ("include/palettes_probe.h", PROBE_HEADER),
        ("src/palettes_probe.c", PROBE_SOURCE),
    ):
        print(f"    {rel}: {write_if_changed(hack / rel, text, args.check)}")
    print(f"    link: {register_source(hack, args.check)}")

    print("  patches:")
    for rel, anchor, repl in PATCHES:
        print(f"    {rel}: {apply_patch(hack / rel, anchor, repl, args.check)}")

    print("  maps:")
    with tempfile.TemporaryDirectory() as td:
        for spec in build_specs():
            name = spec["name"]
            if args.check:
                print(f"    {name}: WOULD GENERATE")
                continue
            print(f"    {name}: {run_new_map(hack, spec, pathlib.Path(td))}")

    print("\nNext:")
    print(f"  cd {hack} && make -j10 CPP='arm-none-eabi-cpp -std=gnu17' && make syms")
    print(f"  python3 {__file__} --specs")


if __name__ == "__main__":
    main()
