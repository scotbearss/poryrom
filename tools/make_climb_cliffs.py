#!/usr/bin/env python3
"""The two cliffs docs 77 §5 reasoned about, built so they can be photographed.

Doc `77` found two silent walls and then *argued* about what falls off them.
Doc `68`'s standard is higher: a wall this corpus claims is real gets walked off
on purpose, with its own control, and the fall gets a picture. This is that
fixture, in a throwaway fork (`hacks/climbcliffs/`) that never ships and
needs no tracked patch, because this file rebuilds it from the pin.

CLIFF 1 -- THE FIELD-MOVE / BADGE-FLAG WELD (docs 77 §2.2).
`CursorCb_FieldMove` gates HMs with `FlagGet(FLAG_BADGE01_GET + fieldMove)`, so
the first eight enumerators ARE the eight badge flags by position. Insert a
field move into that range and every later HM silently demands the next gym's
badge. That is a COMPILE-TIME shape, so it needs two builds of one tree rather
than two boot keys -- doc `73`'s structure for the save layout:

    CLIFF_INSERT_FIELD_MOVE 0   control: appended past FIELD_MOVE_SWEET_SCENT
    CLIFF_INSERT_FIELD_MOVE 1   cliff:   inserted ahead of FIELD_MOVE_CUT

Both builds hand the player the Stone Badge and a lead that knows CUT, so the
only difference is where the enumerator sits. The control gates CUT on the badge
the player holds; the cliff gates it on the NEXT one -- a correctly typeset
refusal, naming a real requirement, for a badge already in the case.

CLIFF 2 -- THE UNCHECKED movementActionId (docs 77 §2.3, doc `47` §7.3).
`gMovementActionFuncs[objectEvent->movementActionId][...]` is dereferenced at two
sites with no range test. That is a RUNTIME shape, so it is boot-key selected
inside the same build:

    A held   CONTROL -- a valid movement action on the player (they step)
    no key   CLIFF   -- the same call, one id PAST the end of the table

The control matters more than usual: "the game froze" is also what a broken
fixture looks like, and only the pair separates the wall from the scaffolding
(doc `61` §4).

USAGE
    python3 tools/make_climb_cliffs.py            # control build
    python3 tools/make_climb_cliffs.py --insert   # cliff build
    python3 tools/make_climb_cliffs.py --specs    # emit verify/*.json

Exit 0 = the fork is in the wanted state. 2 = cannot run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import hx  # noqa: E402
REPO = hx.HARNESS_ROOT
HACK = hx.HACKS / "climbcliffs"
VERIFY = hx.SPEC_DIR
MARKER = "climbcliffs fixture"


def die(msg: str):
    sys.exit(f"cannot run: {msg}")


def read_define(rel: str, name: str) -> int:
    path = HACK / rel
    if not path.is_file():
        die(f"missing {rel}")
    m = re.search(rf"^#define\s+{name}\s+(0x[0-9A-Fa-f]+|\d+)", path.read_text(), re.M)
    if not m:
        die(f"#define {name} not found in {rel}")
    return int(m.group(1), 0)


def edit(rel: str, find: str, repl: str, must: str, what: str) -> None:
    """One replacement, asserted on its own, idempotent.

    An edit script that asserts only "the file changed" after several
    replacements reports success when one silently fails to match. This project
    has been bitten by that twice (root CLAUDE.md, 2026-07-30).
    """
    path = HACK / rel
    if not path.is_file():
        die(f"missing {rel}")
    t = path.read_text()
    if must in t:
        return
    new = re.sub(find, repl, t, count=1)
    if new == t:
        die(f"{what}: anchor did not match in {rel}")
    path.write_text(new)
    if must not in path.read_text():
        die(f"{what}: replacement did not land in {rel}")
    print(f"  edit  {rel:<45} {what}")


def write_config(insert: bool) -> None:
    path = HACK / "include/config/climbcliffs.h"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#ifndef GUARD_CONFIG_CLIMBCLIFFS_H\n"
        "#define GUARD_CONFIG_CLIMBCLIFFS_H\n\n"
        "// docs 77 §5 cliff 1. 0 = control (field move APPENDED past the badge-mapped\n"
        "// range), 1 = cliff (INSERTED ahead of FIELD_MOVE_CUT). Everything else about\n"
        "// the two builds is identical, so any difference is this line and nothing else.\n"
        f"#define CLIFF_INSERT_FIELD_MOVE {1 if insert else 0}\n\n"
        "#endif // GUARD_CONFIG_CLIMBCLIFFS_H\n")
    print(f"  wrote include/config/climbcliffs.h                 "
          f"CLIFF_INSERT_FIELD_MOVE {1 if insert else 0}")


def write_header() -> None:
    path = HACK / "include/climbcliffs.h"
    path.write_text('''#ifndef GUARD_CLIMBCLIFFS_H
#define GUARD_CLIMBCLIFFS_H

// docs 77 §5 -- the throwaway two-cliff fixture. Nothing here ships.
//
// HARNESS SURFACE: every gCliffProbe* is read by name out of pokeemerald.sym.
// Counters are monotone and never cleared; the rest are last-writes that
// persist, so no sampling rate can miss them (doc 66's storage rule).

extern u32 gCliffProbeArm;            // 0 control, 1 movement cliff
extern u32 gCliffProbeLastActionId;   // last id handed to the movement VM
extern u32 gCliffProbeOutOfRange;     // of which past the end of the table
extern u32 gCliffProbeBadgeGate;      // the flag id CUT is actually gated on
extern u32 gCliffProbeCutIndex;       // FIELD_MOVE_CUT's enum value
extern u32 gCliffProbeTicks;          // monotone: is the game still running

void CliffsApplyState(void);
void CliffsTick(void);
void CliffNoteMovementAction(u8 animId);

// FIELD_MOVE_CUT lives in an anonymous enum inside src/party_menu.c, so the
// fixture cannot see it. Published through a function rather than duplicated,
// because a second copy of an index is exactly what this cliff is about.
u32 CliffGetCutFieldMoveIndex(void);

#endif // GUARD_CLIMBCLIFFS_H
''')
    print("  wrote include/climbcliffs.h")


def write_fixture(bad_action_id: int) -> None:
    (HACK / "src/climbcliffs_start.c").write_text(f'''#include "global.h"
#include "climbcliffs.h"
#include "event_data.h"
#include "event_object_movement.h"
#include "field_player_avatar.h"
#include "main.h"
#include "main_menu.h"   // NewGameBirchSpeech_SetDefaultPlayerName
#include "new_game.h"
#include "overworld.h"
#include "pokemon.h"
#include "constants/flags.h"
#include "constants/moves.h"
#include "constants/species.h"

// ---------------------------------------------------------------------------
// docs 77 §5 -- the two cliffs, and the state they need.
//
// THE ARM IS PICKED BY A KEY HELD AT BOOT (doc 68's routing): REG_KEYINPUT is
// read once during new-game init, so each arm is a cold boot with one key held
// for the whole run. No walking, no frame counts, nothing to drift.
//
//   A held   CONTROL -- a valid movement action
//   no key   CLIFF   -- one id PAST the end of gMovementActionFuncs
//
// Cliff 1 is not here: it is a compile-time enum order, i.e. the other build of
// this same tree (CLIFF_INSERT_FIELD_MOVE).
// ---------------------------------------------------------------------------

EWRAM_DATA u32 gCliffProbeArm = 0;
EWRAM_DATA u32 gCliffProbeLastActionId = 0;
EWRAM_DATA u32 gCliffProbeOutOfRange = 0;
EWRAM_DATA u32 gCliffProbeBadgeGate = 0;
EWRAM_DATA u32 gCliffProbeCutIndex = 0;
EWRAM_DATA u32 gCliffProbeTicks = 0;

// One past the last real entry in gMovementActionFuncs, derived from the
// engine's own last action constant rather than written as a number.
#define CLIFF_BAD_ACTION_ID {bad_action_id}

void CliffNoteMovementAction(u8 animId)
{{
    gCliffProbeLastActionId = animId;
    if (animId > MOVEMENT_ACTION_ENTER_POKEBALL && animId != MOVEMENT_ACTION_NONE
        && animId != MOVEMENT_ACTION_STEP_END)
        gCliffProbeOutOfRange++;
}}

void CliffsApplyState(void)
{{
    struct Pokemon mon;
    u16 move = MOVE_CUT;
    u8 pp = 30;

    // GBA keys are ACTIVE LOW: a held button reads 0.
    gCliffProbeArm = (REG_KEYINPUT & A_BUTTON) ? 0 : 1;

    // Doc 68 §6.2: this fixture skips the naming screen, and an unset player
    // name is not empty -- it is UNTERMINATED, and it crashes the trainer card.
    NewGameBirchSpeech_SetDefaultPlayerName(0);

    // The player holds the Stone Badge. This is what makes the cliff arm a
    // finding rather than a tautology: the refusal names a badge requirement
    // for a badge that is already in the case.
    FlagSet(FLAG_BADGE01_GET);

    // A party member that knows CUT, so the field-move list has a row to gate.
    CreateMon(&mon, SPECIES_TREECKO, 5, USE_RANDOM_IVS, FALSE, 0, OT_ID_PLAYER_ID, 0);
    SetMonData(&mon, MON_DATA_MOVE2, &move);
    SetMonData(&mon, MON_DATA_PP2, &pp);
    CalculateMonStats(&mon);
    GiveMonToPlayer(&mon);

    // Published so a spec reads the WELD rather than restating its arithmetic:
    // whichever flag CUT is actually gated on, and where CUT sits in the enum.
    gCliffProbeCutIndex = CliffGetCutFieldMoveIndex();
    gCliffProbeBadgeGate = FLAG_BADGE01_GET + gCliffProbeCutIndex;
}}

// Every frame from the overworld. The movement cliff fires once, on the arm
// that asked for it; the tick counter is how a spec tells a frozen game from a
// slow one, and it is the probe the cliff arm is most likely to stop.
void CliffsTick(void)
{{
    static bool8 fired = FALSE;

    gCliffProbeTicks++;

    if (fired || gCliffProbeTicks < 240)
        return;
    fired = TRUE;

    // Doc 47 §7.3: gMovementActionFuncs is dereferenced with NO range test at
    // either site, so the cliff arm is a jump through whatever the linker put
    // after the table. The control arm hands over a perfectly ordinary walk.
    // ObjectEventForceSetHeldMovement, NOT ObjectEventSetHeldMovement. The
    // plain setter returns early when ObjectEventIsMovementOverridden is true
    // and never stores the id -- so the first version of this fixture counted
    // the ATTEMPT while the commit never happened, the two arms rendered
    // identically, and the cliff looked like a wall that is not there.
    // A probe on a call site is not a probe on the effect.
    ObjectEventForceSetHeldMovement(&gObjectEvents[gPlayerAvatar.objectEventId],
                                    gCliffProbeArm ? MOVEMENT_ACTION_WALK_SLOW_DOWN
                                                   : CLIFF_BAD_ACTION_ID);
}}
''')
    print(f"  wrote src/climbcliffs_start.c                      "
          f"bad action id {bad_action_id}")


def patch_tree() -> None:
    # --- cliff 1: the enumerator, on whichever side the switch says ----------
    edit("src/party_menu.c", r'(#include "global\.h"\n)',
         r'\1#include "config/climbcliffs.h"\n#include "climbcliffs.h"\n',
         '#include "config/climbcliffs.h"', "cliff config include")
    edit("src/party_menu.c", r"(enum \{\n)(    FIELD_MOVE_CUT,)",
         "\\1#if CLIFF_INSERT_FIELD_MOVE\n"
         "    FIELD_MOVE_CLIFF,   // docs 77 §5: INSIDE the badge-mapped range\n"
         "#endif\n\\2",
         "INSIDE the badge-mapped range", "cliff enumerator (inserted)")
    edit("src/party_menu.c", r"(    FIELD_MOVE_SWEET_SCENT,\n)(    FIELD_MOVES_COUNT)",
         "\\1#if !CLIFF_INSERT_FIELD_MOVE\n"
         "    FIELD_MOVE_CLIFF,   // docs 77 §5: OUTSIDE it, the safe append\n"
         "#endif\n\\2",
         "OUTSIDE it, the safe append", "cliff enumerator (appended)")
    edit("src/party_menu.c", r"(static bool8 SetUpFieldMove_Waterfall\(void\);\n)",
         r"\1static bool8 SetUpFieldMove_Cliff(void);\n",
         "static bool8 SetUpFieldMove_Cliff(void);", "cliff callback decl")
    edit("src/party_menu.c", r"(static bool8 SetUpFieldMove_Waterfall\(void\)\n\{)",
         "static bool8 SetUpFieldMove_Cliff(void)\n{\n"
         "    // Never usable: the fixture is about WHICH REFUSAL you get for a move\n"
         "    // you hold the badge for, not about this one working.\n"
         "    return FALSE;\n}\n\n"
         "u32 CliffGetCutFieldMoveIndex(void)\n{\n    return FIELD_MOVE_CUT;\n}\n\n"
         r"\1",
         "u32 CliffGetCutFieldMoveIndex(void)", "cliff callback body + index getter")

    # Both parallel tables need the row wherever the enumerator ended up. An
    # unfilled sFieldMoves row reads MOVE_NONE, which matches every EMPTY move
    # slot a party Pokemon has -- so a missing row is not a blank menu entry,
    # it is a phantom field move on every mon.
    edit("src/data/party_menu.h", r"(\[FIELD_MOVE_SWEET_SCENT\]\s*= MOVE_SWEET_SCENT,\n)",
         r"\1    [FIELD_MOVE_CLIFF]        = MOVE_SPLASH,\n",
         "[FIELD_MOVE_CLIFF]        = MOVE_SPLASH", "cliff sFieldMoves row")
    edit("src/data/party_menu.h",
         r"(\[FIELD_MOVE_SWEET_SCENT\]\s*= \{SetUpFieldMove_SweetScent,\s*PARTY_MSG_CANT_USE_HERE\},\n)",
         r"\1    [FIELD_MOVE_CLIFF]       = {SetUpFieldMove_Cliff,      PARTY_MSG_CANT_USE_HERE},\n",
         "{SetUpFieldMove_Cliff,", "cliff callback row")

    # --- cliff 2: record every id the movement VM is handed -----------------
    edit("src/event_object_movement.c", r'(#include "global\.h"\n)',
         r'\1#include "climbcliffs.h"\n',
         '#include "climbcliffs.h"', "movement probe include")
    # BOTH setters, because doc 47 §7.3 names two dereference sites and the
    # first version of this fixture instrumented only the single-movement one
    # while driving the HELD one -- so the cliff fired and the counter stayed
    # at zero, which reads exactly like a wall that is not there.
    edit("src/event_object_movement.c",
         r"(static void ObjectEventSetSingleMovement\(struct ObjectEvent \*objectEvent, struct Sprite \*sprite, u8 animId\)\n\{\n)",
         "\\1    CliffNoteMovementAction(animId);\n",
         "CliffNoteMovementAction(animId);", "movement probe (single)")
    edit("src/event_object_movement.c",
         r"(bool8 ObjectEventSetHeldMovement\(struct ObjectEvent \*objectEvent, u8 movementActionId\)\n\{\n)",
         "\\1    CliffNoteMovementAction(movementActionId);\n",
         "CliffNoteMovementAction(movementActionId);", "movement probe (held)")

    # --- boot: straight into a new game, no intro and no title screen -------
    # Without this the ROM sits on the title waiting for input, and an arm
    # selected by "no key held" can never be reached -- which is exactly how the
    # first run of this fixture read zero on every probe, INCLUDING a tick
    # counter that increments unconditionally. A counter that cannot be zero
    # reading zero means the code never ran at all; it is the cheapest
    # "did we even boot" probe there is, and it pointed straight at the title.
    # CB2_NewGame is declared in overworld.h, not new_game.h -- checked, not
    # assumed, because "the obvious header" was wrong here.
    edit("src/intro.c", r'(#include "intro\.h"\n)',
         r'\1#include "overworld.h"   // ' + MARKER + r'\n',
         '#include "overworld.h"   // ' + MARKER, "intro include")
    edit("src/intro.c",
         r"(#if EXPANSION_INTRO == TRUE\n        SetMainCallback2\(CB2_ExpansionIntro\);)",
         r"#if 0   // " + MARKER + r"\n        SetMainCallback2(CB2_ExpansionIntro);",
         "#if 0   // " + MARKER, "disable the expansion intro")
    edit("src/intro.c",
         r"(        CreateTask\(Task_Scene1_Load, 0\);\n        SetMainCallback2\(MainCB2_Intro\);)",
         r"        SetMainCallback2(CB2_NewGame);   // " + MARKER,
         "SetMainCallback2(CB2_NewGame);", "boot straight into a new game")

    # --- boot: skip the truck, land in a normal map, apply the state --------
    edit("src/new_game.c", r'(#include "new_game\.h"\n)',
         r'\1#include "climbcliffs.h"\n',
         '#include "climbcliffs.h"', "new_game include")
    edit("src/new_game.c",
         r"(    SetWarpDestination\(MAP_GROUP\(INSIDE_OF_TRUCK\), MAP_NUM\(INSIDE_OF_TRUCK\), WARP_ID_NONE, -1, -1\);)",
         "    SetWarpDestination(MAP_GROUP(LITTLEROOT_TOWN), MAP_NUM(LITTLEROOT_TOWN),\n"
         "                       WARP_ID_NONE, 10, 9);   // " + MARKER + "\n"
         "    CliffsApplyState();",
         "CliffsApplyState();", "boot warp + state")
    edit("src/overworld.c", r'(#include "overworld\.h"\n)',
         r'\1#include "climbcliffs.h"\n',
         '#include "climbcliffs.h"', "overworld include")
    edit("src/overworld.c", r"(    gFieldCallback = ExecuteTruckSequence;)",
         "    gFieldCallback = NULL;   // " + MARKER,
         "gFieldCallback = NULL;   // " + MARKER, "no truck cutscene")
    edit("src/overworld.c", r"(static void OverworldBasic\(void\)\n\{\n)",
         r"\1    CliffsTick();\n",
         "CliffsTick();", "per-frame tick")


def emit_specs() -> None:
    # FLAG_BADGE01_GET is (SYSTEM_FLAGS + 0x7), an expression rather than a
    # literal, and resolving that chain here would put a second copy of the
    # engine's arithmetic in the harness -- which is the exact fault this whole
    # fixture is about. So the DISCRIMINATOR is cut_index, which the ROM
    # publishes directly, and badge_gate rides along as a printed observation.

    probes = [
        {"id": "arm", "why": "which arm the boot key selected. Assert that the thing under test "
                             "happened, or a green run may be a run of something else.",
         "symbol": "gCliffProbeArm", "type": "u32", "sample": {"every": 60}},
        {"id": "cut_index", "why": "FIELD_MOVE_CUT's value, read out of the ROM through "
                                   "CliffGetCutFieldMoveIndex rather than restated here.",
         "symbol": "gCliffProbeCutIndex", "type": "u32", "sample": {"every": 60}},
        {"id": "badge_gate", "why": "THE WELD AS A NUMBER: FLAG_BADGE01_GET + FIELD_MOVE_CUT, "
                                    "which is the flag CursorCb_FieldMove will actually test.",
         "symbol": "gCliffProbeBadgeGate", "type": "u32", "sample": {"every": 60}},
        {"id": "last_action", "why": "the last movement action id handed to the VM.",
         "symbol": "gCliffProbeLastActionId", "type": "u32", "sample": {"every": 30}},
        {"id": "out_of_range", "why": "how many of those were past the end of the table.",
         "symbol": "gCliffProbeOutOfRange", "type": "u32", "sample": {"every": 30}},
        {"id": "ticks", "why": "monotone frame counter. THE probe that separates 'the cliff did "
                               "something' from 'the ROM never ran'.",
         "symbol": "gCliffProbeTicks", "type": "u32", "sample": {"every": 30}},
    ]
    boot_cliff = [{"name": "boot", "frames": 1200, "keys": []},
                  {"name": "settle", "frames": 600, "keys": []}]
    boot_ctrl = [{"name": "boot", "frames": 1200, "keys": ["A"]},
                 {"name": "settle", "frames": 600, "keys": []}]

    specs = {
        "climbcliff-move-control": dict(
            description="docs 77 §5 cliff 2, CONTROL arm: an ordinary movement action. The pair's "
                        "clean half -- without it a frozen cliff arm is equally consistent with a "
                        "broken fixture (doc 61 §4).",
            timeline=boot_ctrl,
            assert_=[
                {"probe": "arm", "check": "compare", "at": "last", "op": "==", "value": 1,
                 "why": "the control arm was selected."},
                {"probe": "out_of_range", "check": "compare", "at": "last", "op": "==", "value": 0,
                 "why": "SUPPORTING, weak under a shift: nothing out of range was handed over."},
                {"probe": "ticks", "check": "compare", "at": "last", "op": ">=", "value": 1000,
                 "why": "the game is alive at the end -- the half the cliff arm is compared to. "
                        "NOT strictly_increases: OverworldBasic does not run every frame, so the "
                        "counter legitimately plateaus between samples and the strict form fails "
                        "on a perfectly healthy run."},
            ]),
        "climbcliff-move": dict(
            description="docs 77 §5 cliff 2, CLIFF arm: movementActionId one past the end of "
                        "gMovementActionFuncs, dereferenced with no range test at either site "
                        "(doc 47 §7.3). Same build, same frames, one boot key.",
            timeline=boot_cliff,
            assert_=[
                {"probe": "arm", "check": "compare", "at": "last", "op": "==", "value": 0,
                 "why": "the cliff arm was selected."},
                {"probe": "out_of_range", "check": "compare", "at": "last", "op": ">=", "value": 1,
                 "why": "an out-of-range id really reached the VM, so whatever the screenshot "
                        "shows is a consequence of that and not of the boot."},
            ]),
        "climbcliff-badge-control": dict(
            description="docs 77 §5 cliff 1, CONTROL build: the field move APPENDED past the "
                        "badge-mapped range, so CUT keeps enum 0 and is gated on the badge the "
                        "player is holding.",
            timeline=boot_ctrl,
            assert_=[
                {"probe": "cut_index", "check": "compare", "at": "last", "op": "==", "value": 0,
                 "why": "CUT is where it has always been."},
                {"probe": "badge_gate", "check": "compare", "at": "last", "op": ">=", "value": 1,
                 "why": "SUPPORTING and deliberately weak: the flag id itself is printed for the "
                        "record, but the claim lives in cut_index, which needs no copy of "
                        "FLAG_BADGE01_GET's expression to check."},
            ]),
        "climbcliff-badge": dict(
            description="docs 77 §5 cliff 1, CLIFF build: the same field move INSERTED ahead of "
                        "FIELD_MOVE_CUT. CUT becomes enum 1 and is silently gated on the SECOND "
                        "badge, so a player holding the Stone Badge is refused -- in a correctly "
                        "typeset sentence naming a real requirement.",
            timeline=boot_ctrl,
            assert_=[
                {"probe": "cut_index", "check": "compare", "at": "last", "op": "==", "value": 1,
                 "why": "CUT moved, and nothing in the engine said so."},
                {"probe": "badge_gate", "check": "compare", "at": "last", "op": ">=", "value": 1,
                 "why": "SUPPORTING: printed so the two builds' flag ids can be diffed by eye. "
                        "THE FINDING is cut_index above -- CUT is gated one badge higher than "
                        "the player holds, and every later HM shifted with it."},
            ]),
    }
    VERIFY.mkdir(exist_ok=True)
    for name, body in specs.items():
        spec = {"name": name, "symbols_from": "climbcliffs", "screenshot": True,
                "description": body["description"], "timeline": body["timeline"],
                "probes": probes, "assert": body["assert_"]}
        (VERIFY / f"{name}.json").write_text(json.dumps(spec, indent=1) + "\n")
        print(f"  spec  verify/{name}.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--insert", action="store_true",
                    help="build the CLIFF side of cliff 1 (field move inserted, not appended)")
    ap.add_argument("--specs", action="store_true", help="emit the verify specs and exit")
    args = ap.parse_args()

    if not HACK.is_dir():
        die(f"no fork at {HACK} -- run: python3 tools/new_hack.py climbcliffs")
    if args.specs:
        emit_specs()
        return 0

    bad = read_define("include/constants/event_object_movement.h",
                      "MOVEMENT_ACTION_ENTER_POKEBALL") + 1
    print(f"climb cliffs -> {HACK}")
    write_config(args.insert)
    write_header()
    write_fixture(bad)
    patch_tree()
    print("  done -- now build the fork")
    return 0


if __name__ == "__main__":
    sys.exit(main())
