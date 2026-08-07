#!/usr/bin/env python3
"""Turn a fresh pokeemerald-expansion fork into the STUDIO ROM: a playable game
whose Pokedex, bag and badge case are a picture of how far along a ROM hack is.

WHY THIS EXISTS
---------------
`hacks/` is gitignored on purpose (.gitignore: the forks are
Nintendo-derived and stay out of this repo's history). So source edits made
directly inside a fork are NOT durable -- they survive exactly as long as the
directory does, and nothing records how to reproduce them.

The durable artifact is therefore this generator, not the fork. Everything the
studio ROM needs is either written by this script or derived from a manifest
that lives in tracked space (`studio/`). A fork can be deleted and
rebuilt from scratch at any time:

    python3 tools/new_hack.py studio --force
    python3 tools/make_studio.py

WHAT IT DOES
------------
1. Writes four NEW files into the fork. New files are safe -- they cannot
   conflict with the engine, and the Makefile globs `src/*.c`.

       include/config/studio.h     toggles, so every studio change is greppable
       include/studio_state.h      one declaration
       include/studio_generated.h  GENERATED from the manifest -- the data
       src/studio_state.c          applies the data using the ENGINE's own APIs

2. Applies three small patches to existing engine files. Each patch is
   idempotent: it checks for its own marker first and does nothing if already
   applied, so re-running is always safe.

       src/intro.c      boot straight into the world, no intro, no title screen
       src/new_game.c   start outdoors instead of in the moving truck, and
                        apply the studio state as the LAST thing a new game does
       src/overworld.c  don't run the truck cutscene

WHY THE STATE IS BAKED INTO THE ROM RATHER THAN WRITTEN INTO A SAVE FILE
------------------------------------------------------------------------
The obvious design is "generate a .sav and let the ROM read it", which would
make a refresh a file write instead of a rebuild. It was rejected:

  * Gen-3 saves are 128KB of flash split into checksummed sections (doc 41).
    Synthesizing one by hand means reimplementing that layout, and a save the
    game judges malformed is simply refused -- a silent, confusing failure.
  * `make_savestate.py` looks like it could help but cannot: it drives the ROM
    with scripted input and snapshots the result. It deliberately never writes
    state, because the harness rule (docs/research/06) is that nothing inside
    the emulator gets to declare state valid.

Baking it in instead means the state is produced by the engine's own
`GetSetPokedexFlag` / `AddBagItem` / `FlagSet` -- so it is valid by
construction, and a wrong manifest produces a wrong-looking game rather than a
game that refuses to boot. The cost is that a refresh is an incremental `make`.
Whether that cost is acceptable is an empirical question about build latency,
and is the thing to measure first.

USAGE
-----
    python3 tools/make_studio.py                     # default manifest
    python3 tools/make_studio.py --manifest X.json
    python3 tools/make_studio.py --check             # report, change nothing
"""

import argparse
import json
import pathlib
import sys

import hx  # noqa: E402
REPO_ROOT = hx.HARNESS_ROOT
HACK = hx.HACKS / "studio"
STUDIO_DIR = hx.STUDIO
DEFAULT_MANIFEST = STUDIO_DIR / "manifest.json"

# Every generated file and every patch carries this marker. It is what makes
# re-running idempotent, and what makes the studio changes greppable inside a
# 23000-file engine fork.
MARKER = "STUDIO_ROM"

# Where the player stands on boot. One tile below Brendan's front door in
# Littleroot Town -- guaranteed walkable, because that is where you land when
# you walk out of it. (Door warp is at 5,8 in data/maps/LittlerootTown/map.json.)
START_MAP = "LITTLEROOT_TOWN"
START_X, START_Y = 5, 9


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------
# The generated data header
# --------------------------------------------------------------------------

def render_generated_header(manifest):
    """Manifest -> C arrays. Species and items are named by their engine
    constants (SPECIES_TREECKO, ITEM_POTION), so a typo is a COMPILE error
    rather than a silently wrong dex entry. That is deliberate: this file is
    machine-written and never reviewed by eye, so the compiler has to be the
    thing that catches mistakes."""
    seen = [s for s in manifest.get("species", []) if s.get("state") == "seen"]
    caught = [s for s in manifest.get("species", []) if s.get("state") == "caught"]
    items = manifest.get("items", [])
    badges = int(manifest.get("badges", 0))

    def species_array(name, count_macro, rows):
        # The array is never empty: a zero-length array is not valid C here, and
        # the count macro is what actually stops the loop, so a lone SPECIES_NONE
        # placeholder is harmless.
        if not rows:
            return (f"#define {count_macro} 0\n"
                    f"static const u16 {name}[] = {{ SPECIES_NONE }};\n")
        body = "\n".join(f"    {r['id']}," for r in rows)
        return (f"#define {count_macro} {len(rows)}\n"
                f"static const u16 {name}[] = {{\n{body}\n}};\n")

    if items:
        item_body = "\n".join(f"    {{ {i['id']}, {int(i.get('qty', 1))} }}," for i in items)
        item_block = (f"#define STUDIO_ITEM_COUNT {len(items)}\n"
                      f"static const struct StudioItem sStudioItems[] = {{\n{item_body}\n}};\n")
    else:
        item_block = ("#define STUDIO_ITEM_COUNT 0\n"
                      "static const struct StudioItem sStudioItems[] = {{ ITEM_NONE, 0 }};\n")

    return f"""// {MARKER}: GENERATED FILE -- DO NOT EDIT.
// Written by tools/make_studio.py from the studio manifest.
// Every edit here is lost on the next run; change the manifest instead.
#ifndef GUARD_STUDIO_GENERATED_H
#define GUARD_STUDIO_GENERATED_H

#include "constants/species.h"
#include "constants/items.h"

struct StudioItem {{
    u16 item;
    u16 qty;
}};

// Species that are DESIGNED but not yet implemented -> dex shows them as seen.
{species_array("sStudioSeen", "STUDIO_SEEN_COUNT", seen)}
// Species that are fully IMPLEMENTED -> dex shows them as caught.
{species_array("sStudioCaught", "STUDIO_CAUGHT_COUNT", caught)}
// Items that exist in the hack -> they appear in the bag.
{item_block}
// Build milestones that have landed AND passed their verify spec.
#define STUDIO_BADGES {badges}

#endif // GUARD_STUDIO_GENERATED_H
"""


STATE_HEADER = f"""// {MARKER}: written by tools/make_studio.py
#ifndef GUARD_STUDIO_STATE_H
#define GUARD_STUDIO_STATE_H

// Applies the generated studio state to a brand-new game. Must be the LAST
// thing NewGameInitData does -- the map-flag reset that runs partway through it
// would otherwise clear the badge flags straight back off again.
void ApplyStudioState(void);

#endif // GUARD_STUDIO_STATE_H
"""


CONFIG_HEADER = f"""// {MARKER}: written by tools/make_studio.py
// Every studio change in the engine sits behind one of these, so the whole
// diff against stock pokeemerald-expansion is greppable by this marker.
#ifndef GUARD_CONFIG_STUDIO_H
#define GUARD_CONFIG_STUDIO_H

#define STUDIO_MODE        TRUE  // master switch for all studio behaviour
#define STUDIO_SKIP_INTRO  TRUE  // boot straight into the world

// The start location is NOT a macro. MAP_GROUP(x) pastes its argument onto
// MAP_, so handing it a macro yields MAP_STUDIO_START_MAP and fails to compile.
// It is substituted into src/new_game.c by make_studio.py instead.
// Currently: {START_MAP} at ({START_X}, {START_Y}).

#endif // GUARD_CONFIG_STUDIO_H
"""


STATE_SOURCE = f"""// {MARKER}: written by tools/make_studio.py
//
// Applies the studio state using the ENGINE's own APIs rather than writing save
// memory directly. That is the whole reason this approach is safe: whatever the
// manifest says, the resulting game state is one the engine itself produced, so
// it cannot be structurally invalid.

#include "global.h"
#include "event_data.h"
#include "item.h"
#include "main_menu.h"
#include "pokedex.h"
#include "pokemon.h"
#include "constants/flags.h"
#include "config/studio.h"
#include "studio_state.h"
#include "studio_generated.h"

// Struct offsets, published so the VERIFICATION HARNESS can find these fields
// without guessing. include/global.h annotates bagPocket_Items (0x560) and
// flags (0x1270) with exact offsets but leaves dexSeen/dexCaught as "0x3???",
// and a hand-computed offset into a struct full of #ifdefs is exactly the kind
// of number that goes silently wrong. This array makes the COMPILER state them.
//
// It is deliberately not a claim about whether the studio state is correct --
// it says only "the fields are here". The harness still reads the actual save
// memory itself and decides for itself what it found.
const u32 gStudioSaveOffsets[4] = {{
    __builtin_offsetof(struct SaveBlock1, dexSeen),
    __builtin_offsetof(struct SaveBlock1, dexCaught),
    __builtin_offsetof(struct SaveBlock1, flags),
    __builtin_offsetof(struct SaveBlock1, bagPocket_Items),
}};

void ApplyStudioState(void)
{{
    u32 i;

    // FIRST, and it is a bug fix rather than studio state (found 2026-08-03 by
    // PLAYING hacks/cliffs, which uses this same boot shortcut; full
    // record docs/68 sec.6.2).
    //
    // Booting straight to CB2_NewGame skips the NAMING SCREEN, and nothing else
    // ever writes the player name -- so gSaveBlock2Ptr->playerName is left as
    // eight ZERO bytes. In this charmap 0x00 is the SPACE glyph and 0xFF is the
    // terminator, so the name draws as blanks (the Start menu's PLAYER row just
    // looks EMPTY) and the string is UNTERMINATED. Selecting that row takes it
    // into the trainer card and clobbers gMain: callback2 lands on an address
    // that is not a symbol and the vblank counter stops.
    //
    // Measured on the studio ROM built 2026-07-26 before this line existed:
    // playerName == 0000000000000000. The studio ROM is a build-progress view
    // you are meant to WALK AROUND OPENING MENUS IN, so this was a crash sitting
    // in a shipped feature that nobody had happened to press.
    //
    // The fix is the engine's own helper -- exactly what the naming screen
    // calls. It copies a preset and writes EOS at PLAYER_NAME_LENGTH. Safe here
    // because ApplyStudioState is the LAST thing NewGameInitData does, so
    // nothing upstream can undo it.
    NewGameBirchSpeech_SetDefaultPlayerName(0);

    // Caught implies seen. The dex needs the seen flag set too, or a caught
    // entry does not render the way it should.
    for (i = 0; i < STUDIO_CAUGHT_COUNT; i++)
    {{
        u16 dexNum = SpeciesToNationalPokedexNum(sStudioCaught[i]);
        GetSetPokedexFlag(dexNum, FLAG_SET_SEEN);
        GetSetPokedexFlag(dexNum, FLAG_SET_CAUGHT);
    }}

    for (i = 0; i < STUDIO_SEEN_COUNT; i++)
        GetSetPokedexFlag(SpeciesToNationalPokedexNum(sStudioSeen[i]), FLAG_SET_SEEN);

    for (i = 0; i < STUDIO_ITEM_COUNT; i++)
        AddBagItem(sStudioItems[i].item, sStudioItems[i].qty);

    for (i = 0; i < STUDIO_BADGES && i < NUM_BADGES; i++)
        FlagSet(FLAG_BADGE01_GET + i);
}}
"""


# --------------------------------------------------------------------------
# Patches to existing engine files
# --------------------------------------------------------------------------
# Each entry: (relative path, anchor that must be found, replacement).
# The marker in every replacement is what makes re-running a no-op.

PATCHES = [
    # 1. Boot straight into the world. The save/heap init that normally happens
    #    after this point still runs -- SetUpCopyrightScreen returns 0 here, and
    #    its caller does the init before our new callback ever executes.
    (
        "src/intro.c",
        """#if EXPANSION_INTRO == TRUE
        SetMainCallback2(CB2_ExpansionIntro);
        CreateTask(Task_HandleExpansionIntro, 0);
#else
        CreateTask(Task_Scene1_Load, 0);
        SetMainCallback2(MainCB2_Intro);
#endif""",
        f"""#if STUDIO_SKIP_INTRO == TRUE // {MARKER}
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
        f'#include "intro.h"\n#include "overworld.h"      // {MARKER}\n#include "config/studio.h" // {MARKER}',
    ),
    # 2. Start outdoors, not in the truck.
    (
        "src/new_game.c",
        """    SetWarpDestination(MAP_GROUP(INSIDE_OF_TRUCK), MAP_NUM(INSIDE_OF_TRUCK), WARP_ID_NONE, -1, -1);""",
        f"""#if STUDIO_MODE == TRUE // {MARKER}
    SetWarpDestination(MAP_GROUP({START_MAP}), MAP_NUM({START_MAP}), WARP_ID_NONE,
                       {START_X}, {START_Y});
#else
    SetWarpDestination(MAP_GROUP(INSIDE_OF_TRUCK), MAP_NUM(INSIDE_OF_TRUCK), WARP_ID_NONE, -1, -1);
#endif""",
    ),
    # 3. Apply the studio state LAST. Anything earlier gets wiped by the
    #    map-flag reset that runs partway through NewGameInitData.
    (
        "src/new_game.c",
        """    ResetContestLinkResults();
}""",
        f"""    ResetContestLinkResults();
#if STUDIO_MODE == TRUE // {MARKER}
    ApplyStudioState();
#endif
}}""".replace("}}", "}"),
    ),
    (
        "src/new_game.c",
        '#include "new_game.h"',
        f'#include "new_game.h"\n#include "config/studio.h" // {MARKER}\n#include "studio_state.h"  // {MARKER}',
    ),
    # 4. No truck cutscene.
    (
        "src/overworld.c",
        "    gFieldCallback = ExecuteTruckSequence;",
        f"""#if STUDIO_MODE == TRUE // {MARKER}
    gFieldCallback = NULL;
#else
    gFieldCallback = ExecuteTruckSequence;
#endif""",
    ),
    (
        "src/overworld.c",
        '#include "overworld.h"',
        f'#include "overworld.h"\n#include "config/studio.h" // {MARKER}',
    ),
]


def apply_patch(path, anchor, replacement, check_only):
    """Idempotent by construction: if the replacement is already present we do
    nothing, and if the anchor is missing we FAIL LOUDLY rather than silently
    producing a ROM that lacks the change. A patch tool that quietly no-ops is
    how you end up verifying a build that was never modified."""
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
    return "applied"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hack", default=str(HACK), help="fork to convert")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--check", action="store_true",
                    help="report what would change; write nothing")
    args = ap.parse_args()

    hack = pathlib.Path(args.hack)
    if not (hack / "src" / "new_game.c").exists():
        fail(f"{hack} is not a pokeemerald fork "
             f"(run: python3 tools/new_hack.py studio)")

    manifest_path = pathlib.Path(args.manifest)
    if not manifest_path.exists():
        fail(f"no manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text())

    print(f"==> studio manifest {manifest_path}")
    n_seen = sum(1 for s in manifest.get("species", []) if s.get("state") == "seen")
    n_caught = sum(1 for s in manifest.get("species", []) if s.get("state") == "caught")
    print(f"    {n_caught} caught, {n_seen} seen, "
          f"{len(manifest.get('items', []))} items, {manifest.get('badges', 0)} badges")

    files = {
        "include/config/studio.h": CONFIG_HEADER,
        "include/studio_state.h": STATE_HEADER,
        "include/studio_generated.h": render_generated_header(manifest),
        "src/studio_state.c": STATE_SOURCE,
    }

    print(f"==> {'checking' if args.check else 'writing'} studio files")
    for rel, content in files.items():
        target = hack / rel
        same = target.exists() and target.read_text() == content
        if args.check:
            print(f"    {rel}: {'unchanged' if same else 'WOULD WRITE'}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            print(f"    {rel}: {'unchanged' if same else 'written'}")

    print(f"==> {'checking' if args.check else 'applying'} engine patches")
    for rel, anchor, replacement in PATCHES:
        status = apply_patch(hack / rel, anchor, replacement, args.check)
        print(f"    {rel}: {status}")

    if not args.check:
        print(f"\nNext -- build it:\n"
              f"  docker run --rm -v \"{hack}:/hack\" -w /hack {hx.IMAGE} \\\n"
              f"    bash -c 'export PATH=/opt/devkitpro/devkitARM/bin:$PATH; \\\n"
              f"             make -j\"$(nproc)\" CPP=\"arm-none-eabi-cpp -std=gnu17\" && \\\n"
              f"             make syms CPP=\"arm-none-eabi-cpp -std=gnu17\"'")


if __name__ == "__main__":
    main()
