#!/usr/bin/env python3
"""Drive the built pokeemerald-expansion ROM from cold boot into real gameplay
with scripted input, then write a COMMITTED save state that later verification
runs boot from directly.

Why this exists (doc 34's Slice 1 plan): Slice 1 has to assert real gameplay
values -- party level/HP, battle outcome -- and replaying the whole Emerald
opening on every verification run would be slow and fragile. So the opening is
paid for ONCE, here, and its result is committed as an artifact.

Design discipline (docs/research/06-ai-harness-lessons.md), identical to
boot_proof.py:

  * harness/drive_input.lua contains ZERO assertions. It drives the
    keypad, samples state, and prints. Nothing inside the emulator decides
    whether the run succeeded.
  * Every judgement happens here, outside, against values the Lua did not
    produce. In particular the party slot crosses the boundary as a RAW hex
    dump; the Gen-3 substructure decryption (personality-ordered, XOR-keyed,
    checksummed) is done in Python. The emulator never gets to declare a mon
    valid -- it only hands over bytes, and the checksum has to come out right.
  * --counterfactual runs the SAME timeline but stops before the point where
    the party exists, so it must FAIL the party assertions. A proof that cannot
    fail is not a proof.

Nothing is written into the party by this script. If the assertions below pass,
the Pokemon was obtained by the ROM's own code in response to button presses.

Two stages are produced, both committed to saves/ with a .json sidecar
recording exactly what they should resume to:

    emerald_overworld.ss1  intro fully done, player free in Littleroot Town.
    emerald_party.ss1      + starter obtained (Torchic, L5) and the scripted
                           first battle won; parked in Birch's lab.

Usage:
    python3 tools/make_savestate.py --stage party        # build it
    python3 tools/make_savestate.py --stage overworld
    python3 tools/make_savestate.py --verify emerald_party.ss1
    python3 tools/make_savestate.py --counterfactual     # must FAIL
    python3 tools/make_savestate.py --determinism        # twice, compare
    python3 tools/make_savestate.py --upto <phase> --no-savestate \\
        --shot-every 100      # the iteration loop: stop early, screenshot, look

DETERMINISM, measured (--determinism): the NAVIGATION PATH is bit-for-bit
identical across cold boots -- same callback2, map, tile and script-lock state
at every sample -- but the full state is NOT. gSaveBlock1Ptr lands at a
different address each boot (doc 44's ASLR, observed directly), and every
RNG-derived value differs: the starter's personality, its IVs, and therefore
its maxHP (20 on one run, 19 on the next). That is the empirical case for doc
34's "boot from a COMMITTED save state": regenerating it does not reproduce
the same Pokemon, so Slice 1 must assert against the committed file, not
against a re-run of this script.
"""

import argparse
import bisect
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

import hx  # noqa: E402
REPO_ROOT = hx.HARNESS_ROOT
ENGINE = hx.ENGINE
HARNESS = hx.HARNESS
SAVES = hx.SAVES
IMAGE = hx.IMAGE

# --rom / --sym resolution and the rom/sym pairing proof are verify_hack.py's
# and rom_pair.py's job, and they are IMPORTED rather than re-implemented. Two
# copies of "which .sym goes with this ROM" is exactly how doc 57 §5's quiet
# false PASS happened in the first place.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rom_pair                                  # noqa: E402
from verify_hack import resolve_artifacts        # noqa: E402

# ---------------------------------------------------------------------------
# Offsets. All named, all sourced -- a version bump that reorders a struct is a
# one-line edit here rather than a hunt through magic numbers.
# ---------------------------------------------------------------------------

MAIN_CALLBACK2 = 0x004          # struct Main, include/main.h

# struct Pokemon / struct BoxPokemon, include/pokemon.h.
# BoxPokemon is 80 B (personality 0, otId 4, ... secure block at 0x20, 48 B),
# then struct Pokemon appends status/level/mail/hp/maxHP/stats -> 100 B stride,
# which agrees with the .sym: gPlayerParty SIZE 0x258 = 600 = 6 * 100.
MON_STRIDE = 100
MON_PERSONALITY = 0x00
MON_OTID = 0x04
MON_SECURE = 0x20
MON_SECURE_LEN = 48
MON_CHECKSUM = 0x1C
MON_STATUS = 0x50
MON_LEVEL = 0x54
MON_HP = 0x56
MON_MAXHP = 0x58

# mGBA C.GBA_KEY, confirmed by introspection inside the emulator (not guessed).
KEY_BITS = {"A": 0, "B": 1, "SELECT": 2, "START": 3,
            "RIGHT": 4, "LEFT": 5, "UP": 6, "DOWN": 7, "R": 8, "L": 9}
SAVESTATE_ALL = 31              # C.SAVESTATE.ALL, likewise confirmed


def keymask(keys):
    m = 0
    for k in keys:
        m |= 1 << KEY_BITS[k]
    return m


# ---------------------------------------------------------------------------
# Timeline DSL. Ops compile to (mask, frames) runs the Lua walks.
#
# `mash` matters: Emerald's field/text code reads JOY_NEW, so a held button
# registers exactly once. Every "advance the text" beat has to be an actual
# press/release cycle, which is why nothing here is a long hold of A.
# ---------------------------------------------------------------------------

def op_wait(frames):
    return [(0, frames)]


def op_hold(keys, frames):
    return [(keymask(keys), frames)]


def op_mash(key, frames, on=6, off=10):
    runs, spent, mask = [], 0, keymask([key])
    while spent < frames:
        a = min(on, frames - spent)
        runs.append((mask, a)); spent += a
        if spent >= frames:
            break
        b = min(off, frames - spent)
        runs.append((0, b)); spent += b
    return runs


def op_tap(key, on=6, off=10):
    return [(keymask([key]), on), (0, off)]


def compile_ops(ops):
    runs = []
    for op in ops:
        runs.extend(op)
    return runs


def total_frames(runs):
    return sum(f for _, f in runs)


# ---------------------------------------------------------------------------
# Symbol table. The line grammar is rom_pair.parse_sym_line() -- shared, not
# copied. This file used to carry its own copy of the regex and it rotted.
# ---------------------------------------------------------------------------

def load_symbols(sym_path):
    syms, by_name = [], {}
    for line in sym_path.read_text(errors="replace").splitlines():
        parsed = rom_pair.parse_sym_line(line)
        if parsed is None:
            continue
        addr, _flag, size, name = parsed
        syms.append((addr, size, name))
        by_name.setdefault(name, (addr, size))
    syms.sort(key=lambda t: t[0])
    return syms, by_name


def resolve(syms, addr):
    addr &= ~1
    starts = [s[0] for s in syms]
    i = bisect.bisect_right(starts, addr) - 1
    while i >= 0:
        start, size, name = syms[i]
        if size and start <= addr < start + size:
            return name
        if start == addr:
            return name
        if start + max(size, 1) <= addr - 0x2000:
            break
        i -= 1
    return None


# ---------------------------------------------------------------------------
# Gen-3 Pokemon decryption -- done HERE, outside the emulator, on purpose.
# ---------------------------------------------------------------------------

# Substructure order is a permutation of GAEM selected by personality % 24.
# Table order matches include/pokemon.h's union PokemonSubstruct ordering:
# 0=Growth, 1=Attacks, 2=EVs, 3=Misc.
SUBSTRUCT_ORDER = [
    [0, 1, 2, 3], [0, 1, 3, 2], [0, 2, 1, 3], [0, 3, 1, 2],
    [0, 2, 3, 1], [0, 3, 2, 1], [1, 0, 2, 3], [1, 0, 3, 2],
    [2, 0, 1, 3], [3, 0, 1, 2], [2, 0, 3, 1], [3, 0, 2, 1],
    [1, 2, 0, 3], [1, 3, 0, 2], [2, 1, 0, 3], [3, 1, 0, 2],
    [2, 3, 0, 1], [3, 2, 0, 1], [1, 2, 3, 0], [1, 3, 2, 0],
    [2, 1, 3, 0], [3, 1, 2, 0], [2, 3, 1, 0], [3, 2, 1, 0],
]


def decrypt_mon(raw):
    """raw = 100 bytes of struct Pokemon. Returns a dict, or None if empty.

    Decrypts the secure block the way the engine does (XOR by otId^personality
    in 32-bit words) and RE-DERIVES the stored checksum from the plaintext. If
    the checksum does not match, the bytes are not a real Pokemon -- which is
    what makes this a genuine check rather than a hopeful cast.
    """
    if len(raw) < MON_STRIDE:
        return None
    personality = int.from_bytes(raw[MON_PERSONALITY:MON_PERSONALITY + 4], "little")
    ot_id = int.from_bytes(raw[MON_OTID:MON_OTID + 4], "little")
    stored_checksum = int.from_bytes(raw[MON_CHECKSUM:MON_CHECKSUM + 2], "little")
    if personality == 0 and ot_id == 0:
        return None

    key = (ot_id ^ personality) & 0xFFFFFFFF
    secure = raw[MON_SECURE:MON_SECURE + MON_SECURE_LEN]
    plain = bytearray()
    checksum = 0
    for i in range(0, MON_SECURE_LEN, 4):
        word = int.from_bytes(secure[i:i + 4], "little") ^ key
        b = word.to_bytes(4, "little")
        plain += b
        checksum = (checksum + int.from_bytes(b[0:2], "little")
                    + int.from_bytes(b[2:4], "little")) & 0xFFFF

    order = SUBSTRUCT_ORDER[personality % 24]
    # DIRECTION MATTERS AND IS EASY TO GET BACKWARDS: in the engine's own
    # GetSubstruct (src/pokemon.c:2268 SUBSTRUCT_CASE, :2295 the switch), the
    # row is indexed BY SUBSTRUCT TYPE and yields the physical SLOT --
    # order[type] = slot, not order[slot] = type. The two readings agree for
    # some personalities and disagree for others, so the wrong one produces
    # plausible-looking values most of the time and nonsense occasionally
    # (species 4096, exp 490114211) -- while the checksum still passes, because
    # the checksum covers the whole block and says nothing about field layout.
    growth_slot = order[0]          # substruct type 0 = Growth
    growth = plain[growth_slot * 12:growth_slot * 12 + 12]
    species = int.from_bytes(growth[0:2], "little")
    held_item = int.from_bytes(growth[2:4], "little")
    experience = int.from_bytes(growth[4:8], "little")

    return {
        "personality": personality,
        "otId": ot_id,
        "species": species,
        "heldItem": held_item,
        "experience": experience,
        "checksum_stored": stored_checksum,
        "checksum_computed": checksum,
        "checksum_ok": stored_checksum == checksum,
        "level": raw[MON_LEVEL],
        "hp": int.from_bytes(raw[MON_HP:MON_HP + 2], "little"),
        "maxHP": int.from_bytes(raw[MON_MAXHP:MON_MAXHP + 2], "little"),
        "status": int.from_bytes(raw[MON_STATUS:MON_STATUS + 4], "little"),
    }


# ---------------------------------------------------------------------------
# The timeline itself. Built in named phases so a stall is localisable to one
# phase rather than to "somewhere in 20000 frames".
# ---------------------------------------------------------------------------

def build_timeline():
    """The full opening, as named phases.

    Named phases are not cosmetic: a stall is then localisable to one phase
    instead of to "somewhere in 30000 frames", which is the only way a blind
    scripted sequence through a 20-minute cutscene chain is debuggable at all.

    Every coordinate and trigger below was read out of the engine's own map
    data (`data/maps/<Map>/map.json`, `scripts.inc`) rather than guessed from
    memory of the retail game.
    """
    phases = []

    def phase(name, *ops):
        phases.append((name, [r for o in ops for r in o]))

    # ---------------- title / new game / character creation ----------------

    # Boot: expansion splash + the intro movie. A skips through both.
    phase("intro", op_wait(240), op_mash("A", 900, on=4, off=12))
    # Title screen -> main menu.
    phase("title", op_mash("START", 240, on=6, off=18), op_wait(60))
    # Main menu: with no save file the cursor sits on NEW GAME.
    phase("newgame", op_tap("A", 8, 60), op_wait(180))
    # Birch's speech. NOTE: all of this runs UNDER CB2_MainMenu -- main_menu.c
    # owns the whole new-game flow -- so the callback2 trace stays on
    # CB2_MainMenu here and that is not a stall.
    phase("birch", op_mash("A", 1500, on=6, off=14))
    # "Are you a boy or a girl?" -- cursor starts on BOY.
    phase("gender", op_tap("A", 8, 60), op_mash("A", 300, on=6, off=14))
    # Naming screen: one letter, then START = OK.
    phase("name", op_tap("A", 8, 40), op_wait(30),
                  op_tap("START", 8, 60), op_mash("A", 400, on=6, off=14))
    # Confirm the name, finish Birch's speech, fade into the moving truck.
    # LENGTH MATTERS: CB2_Overworld appears around frame 4990, and every A
    # pressed after that lands on the truck's moving-box SIGNS (bg_events at
    # (2,3),(0,1),(0,2),(1,0),(3,4)). Mashing past the transition leaves a
    # message box open, and a message box eats the D-pad -- which is exactly
    # how the first attempt at this got permanently stuck in the truck.
    phase("intro_end", op_mash("A", 860, on=6, off=14), op_wait(150))

    # ---------------- the Littleroot opening ----------------
    # InsideOfTruck (map 25.40): player spawns at (2,2). map.json puts the
    # intro-flag coord trigger at x=3 and the exit warp at x=4, so two steps
    # right is the whole map.
    # The truck fades in SLOWLY: CB2_Overworld appears ~frame 4990 but the
    # screen is still fully black at 5200 and only readable by ~5300 (verified
    # by screenshot). Field input is ignored while gPaletteFade is active, so
    # the walk has to start well after the callback changes -- the callback is
    # not the "you may now move" signal.
    phase("exit_truck", op_wait(900),
                        op_hold(["RIGHT"], 300), op_wait(150))
    # Littleroot Town: LittlerootTown_EventScript_GoInsideWithMom is fully
    # automatic apart from one msgbox, and ends with a warpsilent into
    # BrendansHouse_1F (8,8).
    phase("mom_outside", op_mash("A", 900, on=6, off=14))
    # PlayersHouse_1F_EventScript_EnterHouseMovingIn: two msgboxes, then the
    # script walks the player in and sets VAR_LITTLEROOT_INTRO_STATE = 4.
    phase("enter_house", op_mash("A", 1600, on=6, off=14), op_wait(120))
    # Stairs warp is at (8,2); the player ends up around (8,7) facing up.
    # STOP holding UP once 2F is reached: the 2F stairs tile is at (7,1) and
    # the player lands one tile below it, so another UP walks straight back
    # downstairs. Verified -- the first attempt did exactly that.
    phase("go_upstairs", op_hold(["UP"], 120), op_wait(90))

    # ---------------- 2F: the wall clock ----------------
    # map.json: the clock is a bg_event sign at (5,1), player lands at (7,2).
    # Two steps left, face north, A.
    # 45 frames of LEFT overshot to (4,2) -- steps here cost ~10 frames each
    # after the initial turn. 34 lands exactly on (5,2), below the clock.
    phase("to_clock", op_hold(["LEFT"], 34), op_wait(30),
                      op_tap("UP", 4, 30), op_wait(30))
    # PlayersHouse_2F_EventScript_WallClock -> StartWallClock, a whole separate
    # callback (CB2_WallClock).
    #
    # THE TRAP: src/wallclock.c:838 calls CreateYesNoMenu(..., 1) -- the confirm
    # menu opens with the cursor on **NO**, not YES. Mashing A therefore loops
    # forever: A opens the confirm, A picks NO, back to the clock. Verified --
    # 1500 frames of A-mashing never left CB2_WallClock. So the mash has to stop
    # before the clock UI appears, and the confirm is driven deliberately:
    # A (ask) -> UP (cursor to YES) -> A (confirm).
    # The leading B makes the sequence robust to whether a stray A from the
    # msgbox mash already opened the confirm: B in Task_SetClock_HandleInput
    # does nothing, and B in Task_SetClock_HandleConfirmInput is MENU_B_PRESSED,
    # which returns to the clock. Either way the next three taps start clean.
    phase("set_clock", op_mash("A", 400, on=6, off=14), op_wait(420),
                       op_tap("B", 6, 60),
                       op_tap("A", 6, 70), op_tap("UP", 6, 50),
                       op_tap("A", 6, 260))
    # Mom comes upstairs, one msgbox, then leaves. Sets INTRO_STATE 6.
    phase("mom_upstairs", op_mash("A", 900, on=6, off=14), op_wait(90))

    # ---------------- back down for the TV scene ----------------
    # 2F stairs are at (7,1); the player is standing at (5,2).
    # 22 not 34: the player is ALREADY facing east here, so no frame is spent
    # turning and each step costs ~11 frames -- 34 walked three tiles, one too
    # many. Step cost differs depending on whether a turn is needed first.
    phase("go_downstairs", op_hold(["RIGHT"], 22), op_wait(30),
                           op_hold(["UP"], 40), op_wait(180))
    # INTRO_STATE 6 fires LittlerootTown_BrendansHouse_1F_EventScript_
    # PetalburgGymReport on frame: the Dad-on-TV scene. Long, all msgboxes.
    phase("tv_scene", op_mash("A", 2600, on=6, off=14), op_wait(150))

    # ---------------- out of the house, into Littleroot Town ----------------
    # 1F exit warps are (8,8)/(9,8); the TV scene leaves the player at (4,5).
    phase("exit_house", op_hold(["RIGHT"], 60), op_wait(30),
                        op_hold(["DOWN"], 60), op_wait(180))

    # ---------------- meeting the rival (gates the route north) ----------------
    # LittlerootTown_EventScript_NeedPokemonTrigger blocks the Route 101 exit
    # while VAR_LITTLEROOT_TOWN_STATE == 0. Only MeetMay (May's house 2F, via
    # her Poke Ball) sets it to 1, so the rival visit is not optional flavour --
    # it is the gate. Player exits its own house at (5,9); May's door is (14,8).
    phase("to_rival_house", op_hold(["RIGHT"], 150), op_wait(40),
                            op_hold(["UP"], 30), op_wait(200))
    # RivalsHouse_1F "oh, you're the new neighbour" auto-scene, then upstairs:
    # 1F stairs warp is at (2,2), player lands at (2,8).
    # Mash only as long as the scene actually needs (~650 frames): past that,
    # every extra A re-triggers a nearby msgbox and re-locks the field.
    # Mash only as long as the scene actually needs, then MASH B to close
    # whatever the last stray A opened: an A landing on a nearby sign leaves a
    # message box up, the box holds sLockFieldControls, and every subsequent
    # D-pad frame is silently discarded. B closes it and does nothing otherwise
    # (running shoes are not owned yet, so B is not "run" here).
    # The rival's mother walks up and stands ADJACENT to the player, so a stray
    # A after the scripted scene ends starts her (long, multi-page) idle
    # dialogue and re-locks the field. The trick: advance the tail of the scene
    # with **B** instead of A. B advances an open message box exactly like A but
    # never STARTS a conversation, so it can be over-applied safely -- A cannot.
    phase("rival_mom", op_mash("A", 620, on=6, off=14), op_wait(60),
                       op_mash("B", 400, on=6, off=14), op_wait(150))
    # 1F stairs warp is at (2,2); the player is standing on the door at (2,8).
    phase("rival_upstairs", op_hold(["UP"], 115), op_wait(200))
    # 2F: the rival's Poke Ball is an object event at (5,4); the player lands at
    # (1,2). Go to (4,4) -- (3,4) holds the Pichu doll and (5,4) the ball, so
    # (4,4) is the one adjacent tile that is both reachable and free -- face
    # east, and interact. That fires MeetMay, which sets
    # VAR_LITTLEROOT_TOWN_STATE = 1 and unblocks Route 101.
    phase("to_pokeball", op_hold(["RIGHT"], 48), op_wait(40),
                         op_hold(["DOWN"], 38), op_wait(40),
                         op_tap("RIGHT", 4, 40))
    phase("meet_rival", op_tap("A", 6, 60), op_mash("A", 900, on=6, off=14),
                        op_wait(60), op_mash("B", 500, on=6, off=14),
                        op_wait(150))

    # ---------------- north to Route 101 ----------------
    # 2F (4,4) -> stairs (1,1). Overshooting UP into the wall is harmless.
    phase("leave_rival_2f", op_hold(["UP"], 45), op_wait(30),
                            op_hold(["LEFT"], 55), op_wait(30),
                            op_hold(["UP"], 40), op_wait(180))
    # 1F: land at (2,2), door warps at (1,8)/(2,8).
    phase("leave_rival_1f", op_hold(["DOWN"], 120), op_wait(200))
    # Littleroot: land at (14,9). Go up column x=11, NOT x=10: once
    # VAR_LITTLEROOT_TOWN_STATE becomes 1, LittlerootTown_EventScript_SetTwinPos
    # parks the twin NPC ON (10,1), so x=10 is a dead end. (10,1)/(11,1) both
    # carry the exit trigger; only (11,1) is reachable. Screenshot confirmed the
    # NPC standing in the gap.
    phase("to_route101", op_hold(["LEFT"], 45), op_wait(40),
                         op_hold(["UP"], 240), op_wait(300))
    # The twin's "can you go see what's happening?" box, then north across the
    # map CONNECTION into Route 101 (a connection, not a warp), which fires
    # Route101_EventScript_StartBirchRescue at (10,19)/(11,19).
    phase("twin_msgbox", op_mash("A", 300, on=6, off=14), op_wait(60),
                         op_mash("B", 300, on=6, off=14), op_wait(120))
    phase("enter_route101", op_hold(["UP"], 120), op_wait(200))
    # The rescue cutscene: Birch and the Zigzagoon run in circles, two msgboxes.
    phase("birch_rescue", op_mash("A", 1400, on=6, off=14), op_wait(60),
                          op_mash("B", 600, on=6, off=14), op_wait(150))

    # ---------------- the starter ----------------
    # Birch's bag is an object event at (7,14); the scene leaves the player at
    # (11,15). Stop at x=7 -- x=6 carries Route101_EventScript_PreventExitWest.
    phase("to_bag", op_hold(["LEFT"], 58), op_wait(40),
                    op_tap("UP", 4, 40))
    # Route101_EventScript_BirchsBag: three Poke Balls, cursor starts on the
    # first (Treecko). A picks, then a "do you choose this?" yes/no.
    phase("choose_starter", op_tap("A", 6, 90), op_mash("A", 500, on=6, off=14),
                            op_wait(200))
    # The scripted first battle (wild Zigzagoon). A picks FIGHT and then the
    # first move; the same mash carries every message box in between.
    phase("battle", op_mash("A", 2600, on=6, off=14), op_wait(200))
    # Winning warps straight into Birch's lab, whose auto-scene asks TWO yes/no
    # questions ("give it a nickname?", "go see your rival?"), both defaulting
    # to YES. Mashing A therefore walks into the nickname keyboard and stalls
    # there -- observed. Mashing B advances every message box AND answers NO to
    # both, which is exactly the state we want to park in.
    phase("lab", op_mash("B", 3500, on=6, off=14), op_wait(300))

    return phases


# Where each committed stage stops. "overworld" is the degrade-gracefully
# target: player free, standing outside in Littleroot Town, intro fully done.
STAGE_END = {"overworld": "exit_house"}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TRACE_RE = re.compile(
    r"TRACE frame=(\d+) cb2=([0-9a-f]{8}) sb1=([0-9a-f]{8}) "
    r"x=(-?\d+) y=(-?\d+) mg=(-?\d+) mn=(-?\d+) pc=(\d+) "
    r"px=(-?\d+) py=(-?\d+) f=(\d+) hk=([0-9a-f]{4}) pa=([0-9a-f]{2}) ps=(\d+) "
    r"lk=(\d+) st=(\d+) sp=([0-9a-f]{8})")
PARTY_RE = re.compile(r"PARTY frame=(\d+) slot=(\d+) raw=([0-9a-f]+)")
SAVESTATE_RE = re.compile(r"SAVESTATE path=(\S+) returned=(\S+)")


def run(runs, by_name, *, rom, savestate_path, shot_dir, trace_every, shot_every,
        timeout, load_state=None):
    build = ENGINE / "build"
    build.mkdir(exist_ok=True)
    shots = ENGINE / "build" / shot_dir
    if shots.exists():
        shutil.rmtree(shots)
    shots.mkdir(parents=True)

    gmain = by_name["gMain"][0]
    plan = {
        "gmain": gmain,
        "off_callback2": MAIN_CALLBACK2,
        "gsaveblock1ptr": by_name["gSaveBlock1Ptr"][0],
        "gplayerpartycount": by_name["gPlayerPartyCount"][0],
        "gplayerparty": by_name["gPlayerParty"][0],
        "gobjectevents": by_name["gObjectEvents"][0],
        "gplayeravatar": by_name["gPlayerAvatar"][0],
        "slockfieldcontrols": by_name["sLockFieldControls"][0],
        "sglobalscriptcontextstatus": by_name["sGlobalScriptContextStatus"][0],
        "sglobalscriptcontext": by_name["sGlobalScriptContext"][0],
        "mon_stride": MON_STRIDE,
        "trace_every": trace_every,
        "shot_every": shot_every,
        "shot_dir": f"/engine/build/{shot_dir}",
        "final_shot": f"/engine/build/{shot_dir}/final.png",
        "total_frames": total_frames(runs),
        "savestate_path": savestate_path or "",
        "savestate_flags": SAVESTATE_ALL,
    }
    lua = ["-- generated by tools/make_savestate.py; do not hand-edit",
           "return {"]
    for k, v in plan.items():
        lua.append(f"  {k} = " + (f'"{v}"' if isinstance(v, str) else str(v)) + ",")
    lua.append("  runs = {")
    for mask, frames in runs:
        lua.append(f"    {{{mask},{frames}}},")
    lua.append("  },")
    lua.append("}")
    (build / "_drive_plan.lua").write_text("\n".join(lua) + "\n")
    (build / "DONE").unlink(missing_ok=True)

    load_flag = f"-t {load_state} " if load_state else ""
    # -l 8 = INFO alone. Doc 54 found console:log is invisible at -l 7 and used
    # -l 15; INFO is the only bit that matters, and dropping WARN/ERROR here
    # matters a lot at this length -- the GBA DMA chatter at -l 15 is several
    # lines per frame, i.e. hundreds of MB across a 20k-frame run.
    script = f"""
set -e
mgba-headless /rom/{rom.name} {load_flag}-l 8 --script /harness/drive_input.lua \
    > /engine/build/mgba_drive.log 2>&1 &
PID=$!
START=$SECONDS
while [ ! -f /engine/build/DONE ] && kill -0 $PID 2>/dev/null; do
    if [ $((SECONDS - START)) -ge {timeout} ]; then
        echo 'TIMEOUT' >&2; kill -9 $PID 2>/dev/null || true; exit 1
    fi
    sleep 0.1
done
kill -SIGINT $PID 2>/dev/null || true
wait $PID 2>/dev/null || true
"""
    t0 = time.time()
    proc = subprocess.run(
        ["docker", "run", "--rm",
         "-v", f"{ENGINE}:/engine", "-v", f"{HARNESS}:/harness",
         "-v", f"{SAVES}:/saves",
         # The ROM's OWN directory, so a fork outside engine/ is
         # loadable at all. This is the identical bug doc 55 §9.2 found in
         # verify_hack.py: passing the basename works for the default ROM at the
         # engine root and silently fails for anything else, with the useless
         # symptom "did not complete N frames" and an empty log.
         "-v", f"{rom.parent}:/rom:ro",
         "-w", "/engine", IMAGE, "bash", "-c", script],
        capture_output=True, text=True)
    wall = time.time() - t0
    log_path = build / "mgba_drive.log"
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    done = (build / "DONE").exists()
    return {
        "done": done, "log": log, "wall": wall, "rc": proc.returncode,
        "stderr": proc.stderr,
        # groups 1,2 (cb2, sb1) and 11,12,16 (heldKeys, avatar flags, scriptPtr)
        # are hex. Samples past total_frames are dropped: the Lua keeps running
        # (and tracing) between writing DONE and being SIGINTed, and how many
        # extra frames that is depends on host scheduling -- including them
        # would make every run look non-deterministic for no reason.
        "traces": [t for t in
                   (tuple(int(g, 16 if i in (1, 2, 11, 12, 16) else 10)
                          for i, g in enumerate(m))
                    for m in TRACE_RE.findall(log))
                   if t[0] <= total_frames(runs)],
        "party": [(int(f), int(s), bytes.fromhex(r))
                  for f, s, r in PARTY_RE.findall(log)],
        "savestate": SAVESTATE_RE.findall(log),
        "shots": shots,
    }


def print_trace(res, syms, phase_marks, limit=None):
    print(f"    {'frame':>7} {'px':>4} {'py':>4} {'f':>2} {'map':>7} {'pc':>3}  callback2")
    last = None
    rows = res["traces"]
    for (frame, cb2, sb1, x, y, mg, mn, pc, px, py, face, hk, pa, ps,
         lk, st, sp) in rows:
        name = resolve(syms, cb2) or "<unresolved>"
        sig = (name, mg, mn, pc, px, py, face, ps, lk, st, sp)
        if sig == last and limit != "all":
            continue
        last = sig
        ph = ""
        for f, n in phase_marks:
            if f <= frame:
                ph = n
        script = resolve(syms, sp) if sp else None
        print(f"    {frame:>7} {px:>4} {py:>4} {face:>2} {mg:>3}.{mn:<3} {pc:>3} "
              f"hk={hk:04x} lk={lk} st={st}  {name}"
              + (f" <- {script}" if script else "") + f"  [{ph}]")


def verify_state(args, syms, by_name, rom):
    """Boot the ROM from a committed state and check it resumes where claimed.

    This is what turns the file into an artifact Slice 1 can rely on: the
    expected values come from the state's OWN .json sidecar, written by the
    generating run, and are compared against a fresh emulator that only got the
    binary state -- no timeline, no scripted input, 120 idle frames.
    """
    name = args.verify
    ss = SAVES / name
    meta_path = SAVES / (name + ".json")
    if not ss.exists():
        sys.exit(f"FAIL: {ss} not found")
    if not meta_path.exists():
        sys.exit(f"FAIL: {meta_path} not found -- cannot verify without the "
                 f"sidecar that records what the state should resume to")
    meta = json.loads(meta_path.read_text())

    rom_sha = hashlib.sha256(rom.read_bytes()).hexdigest()
    if meta.get("rom_sha256") != rom_sha:
        print(f"WARNING: state was made against ROM {meta.get('rom_sha256')[:16]}"
              f"... but the ROM on disk is {rom_sha[:16]}...", file=sys.stderr)

    runs = op_wait(120)
    res = run(runs, by_name, rom=rom, savestate_path="", shot_dir="verify_shots",
              trace_every=30, shot_every=0, timeout=args.timeout,
              load_state=f"/saves/{name}")
    if not res["done"]:
        print(res["log"][-2000:], file=sys.stderr)
        sys.exit("FAIL: emulator did not complete the verify run")

    print_trace(res, syms, [(1, "resume")], "all")
    (_, cb2, _, x, y, mg, mn, pc, px, py, face,
     _hk, _pa, _ps, _lk, _st, _sp) = res["traces"][-1]
    cb2_name = resolve(syms, cb2) or "<unresolved>"

    failures = []
    if cb2_name != meta["final_callback2"]:
        failures.append(f"callback2 {cb2_name} != recorded {meta['final_callback2']}")
    if f"{mg}.{mn}" != meta["map"]:
        failures.append(f"map {mg}.{mn} != recorded {meta['map']}")
    if [px, py] != meta["player"]:
        failures.append(f"player ({px},{py}) != recorded {meta['player']}")
    if pc != meta["partyCount"]:
        failures.append(f"partyCount {pc} != recorded {meta['partyCount']}")

    mons = [decrypt_mon(raw) for _, slot, raw in res["party"] if slot == 0]
    slot0 = mons[0] if mons else None
    recorded0 = next((m for m in meta.get("party", []) if m["slot"] == 0), None)
    if recorded0:
        if slot0 is None:
            failures.append("recorded a slot-0 Pokemon, resumed state has none")
        else:
            for k in ("species", "level", "maxHP", "personality"):
                if slot0[k] != recorded0[k]:
                    failures.append(f"slot0.{k} {slot0[k]} != recorded {recorded0[k]}")
            if not slot0["checksum_ok"]:
                failures.append("slot0 checksum mismatch after resume")
            print(f"    resumed slot 0: species={slot0['species']} "
                  f"level={slot0['level']} hp={slot0['hp']}/{slot0['maxHP']}")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        sys.exit(1)
    print(f"PASS: {ss.name} reloads into {cb2_name} at map {mg}.{mn} "
          f"({px},{py}) with partyCount={pc}.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="party",
                    choices=["overworld", "party"])
    ap.add_argument("--upto", default=None,
                    help="truncate the timeline after this phase (iteration aid)")
    ap.add_argument("--trace-every", type=int, default=30)
    ap.add_argument("--shot-every", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-savestate", action="store_true")
    ap.add_argument("--shot-dir", default="shots")
    ap.add_argument("--full-trace", action="store_true")
    ap.add_argument("--counterfactual", action="store_true",
                    help="truncate the timeline before the party is obtained; "
                         "the party assertions must then FAIL. Proves the PASS "
                         "is not vacuous.")
    ap.add_argument("--determinism", action="store_true",
                    help="run the timeline twice and compare traces + state hash")
    ap.add_argument("--rom", default=None,
                    help="ROM to drive. Relative paths resolve under "
                         "engine/; absolute paths are used as given. "
                         "Defaults to the engine's own build.")
    ap.add_argument("--sym", default=None,
                    help="symbol table. Defaults to the ROM'S OWN SIBLING "
                         "pokeemerald.sym, never the engine's (doc 57 §5b) -- "
                         "and the pair is then proved by CONTENT via "
                         "rom_pair.py before a docker run is spent.")
    ap.add_argument("--allow-unmatched-sym", action="store_true",
                    help="skip rom_pair.py's proof. It prints, in those words, "
                         "that the verdict then means nothing.")
    ap.add_argument("--verify", metavar="NAME", default=None,
                    help="boot the ROM FROM a committed save state in "
                         "saves/ and check it lands where its .json "
                         "says. A state that cannot be reloaded is worthless, "
                         "so this is the check that makes it an artifact.")
    args = ap.parse_args()

    rom, sym, sym_source = resolve_artifacts(args.rom, args.sym)
    if not rom.exists():
        sys.exit(f"FAIL: {rom} not found -- build it first")
    if not sym.exists():
        sys.exit(f"FAIL: {sym} not found -- run `make syms`")
    print(f"==> rom {rom}")
    print(f"==> sym {sym}  ({sym_source})")
    # Prove the two are ONE build before spending a long drive on them. A state
    # captured against a mismatched pair would be silently worthless, and this
    # script's whole output is a state.
    if args.allow_unmatched_sym:
        print("!!! --allow-unmatched-sym: the rom/sym pair is NOT proved. "
              "Whatever this run produces, its provenance means nothing.")
    else:
        rom_pair.verify_pair(rom, sym)
    SAVES.mkdir(exist_ok=True)

    syms, by_name = load_symbols(sym)

    if args.verify:
        return verify_state(args, syms, by_name, rom)

    phases = build_timeline()
    if args.stage in STAGE_END and not args.upto:
        args.upto = STAGE_END[args.stage]
    if args.upto:
        names = [n for n, _ in phases]
        if args.upto not in names:
            sys.exit(f"FAIL: no phase named {args.upto!r}; have {names}")
        phases = phases[:names.index(args.upto) + 1]
    if args.counterfactual:
        # Stop before the starter is obtained. Everything else is identical,
        # so the party assertions must FAIL -- the PASS is therefore load-bearing.
        names = [n for n, _ in phases]
        # Cut before choose_starter, NOT before battle: ChooseStarter already
        # puts the mon in gPlayerParty on Route 101 (the lab scene only makes
        # it official), so cutting at the battle would still find a party and
        # the counterfactual would silently pass.
        cut = names.index("choose_starter")
        phases = phases[:cut]
    ops, phase_marks, acc = [], [], 0
    for name, o in phases:
        phase_marks.append((acc + 1, name))
        acc += total_frames(o)
        ops.append(o)
    runs = compile_ops(ops)

    out_name = args.out or f"emerald_{args.stage}.ss1"
    savestate_path = "" if args.no_savestate else f"/saves/{out_name}"

    print(f"==> timeline: {len(phases)} phases, {total_frames(runs)} frames, "
          f"{len(runs)} input runs")
    for f, n in phase_marks:
        print(f"      frame {f:>7}  {n}")

    if args.determinism:
        # Two identical cold-boot runs of the SAME timeline. Compared: the whole
        # trace sequence (map/position/lock state at every sample) and the raw
        # party bytes. Emerald seeds its RNG at boot, so anything RNG-derived
        # (personality, IVs, therefore maxHP) is where a difference will show.
        a = run(runs, by_name, rom=rom, savestate_path="", shot_dir="det_a",
                trace_every=args.trace_every, shot_every=0, timeout=args.timeout)
        b = run(runs, by_name, rom=rom, savestate_path="", shot_dir="det_b",
                trace_every=args.trace_every, shot_every=0, timeout=args.timeout)
        if not (a["done"] and b["done"]):
            sys.exit("FAIL: a determinism run did not complete")
        # Two projections, because they answer different questions.
        # NAV = frame, callback2, map, player x/y, facing, script lock: does the
        #       scripted input drive the game along the same PATH every time?
        # FULL = NAV + the SaveBlock1 pointer: is the whole observable state
        #       identical? It is not, and doc 44's ASLR is exactly why.
        def nav(t):
            f, cb2, _sb1, x, y, mg, mn, pc, px, py, face, hk, pa, ps, lk, st, sp = t
            return (f, cb2, mg, mn, pc, px, py, face, lk)
        ta, tb = [nav(t) for t in a["traces"]], [nav(t) for t in b["traces"]]
        fa, fb = [t[1:] for t in a["traces"]], [t[1:] for t in b["traces"]]
        same_nav = ta == tb
        same_trace = fa == fb
        print(f"    navigation path identical: {same_nav}")
        pa = {s: r for _, s, r in a["party"]}
        pb = {s: r for _, s, r in b["party"]}
        same_party = pa == pb
        print(f"==> determinism: {len(ta)} vs {len(tb)} samples")
        print(f"    full trace identical: {same_trace}")
        print(f"    party bytes identical: {same_party}")
        if not same_trace:
            for i, (x_, y_) in enumerate(zip(fa, fb)):
                if x_ != y_:
                    print(f"    first divergence at sample {i}:\n"
                          f"      A {x_}\n      B {y_}")
                    break
        for label, res_ in (("A", a), ("B", b)):
            m = decrypt_mon(pa[0] if label == "A" else pb[0]) if 0 in pa else None
            if m:
                print(f"    run {label} slot0: species={m['species']} "
                      f"level={m['level']} hp={m['hp']}/{m['maxHP']} "
                      f"personality={m['personality']:#010x}")
        return 0 if (same_trace and same_party) else 1

    res = run(runs, by_name, rom=rom, savestate_path=savestate_path,
              shot_dir=args.shot_dir, trace_every=args.trace_every,
              shot_every=args.shot_every, timeout=args.timeout)
    print(f"==> ran in {res['wall']:.1f}s wall, done={res['done']}, "
          f"{len(res['traces'])} traces")
    if not res["done"]:
        print(res["log"][-3000:], file=sys.stderr)
        sys.exit("FAIL: run did not complete")

    print_trace(res, syms, phase_marks, "all" if args.full_trace else None)
    print(f"    shots: {res['shots']}")

    # ---- assertions, all evaluated here, outside the emulator ----
    failures = []
    final = res["traces"][-1]
    (_, cb2, _, x, y, mg, mn, pc, px, py, face,
     _hk, _pa, _ps, _lk, _st, _sp) = final
    cb2_name = resolve(syms, cb2) or "<unresolved>"
    print(f"\n    final: callback2={cb2_name} map={mg}.{mn} camera=({x},{y}) "
          f"player=({px},{py}) facing={face} partyCount={pc}")

    mons = []
    for frame, slot, raw in res["party"]:
        d = decrypt_mon(raw)
        if d:
            mons.append((slot, d))
            print(f"    slot {slot}: species={d['species']} level={d['level']} "
                  f"hp={d['hp']}/{d['maxHP']} exp={d['experience']} "
                  f"checksum={'OK' if d['checksum_ok'] else 'BAD'}")

    if args.stage in ("overworld", "party"):
        if cb2_name != "CB2_Overworld":
            failures.append(f"not in the overworld: callback2={cb2_name}")
    if args.stage == "party":
        if pc < 1:
            failures.append(f"gPlayerPartyCount == {pc}, expected >= 1")
        if not mons:
            failures.append("no decryptable Pokemon in gPlayerParty")
        else:
            slot0 = dict(mons).get(0)
            if slot0 is None:
                failures.append("party slot 0 is empty")
            else:
                if not slot0["checksum_ok"]:
                    failures.append("slot 0 substructure checksum mismatch -- "
                                    "the bytes are not a real Pokemon")
                if slot0["species"] == 0:
                    failures.append("slot 0 species == 0")
                if slot0["level"] < 1:
                    failures.append("slot 0 level < 1")
                if slot0["maxHP"] < 1:
                    failures.append("slot 0 maxHP < 1")

    if not args.no_savestate:
        ss = SAVES / out_name
        if not res["savestate"] or res["savestate"][0][1] not in ("true", "1"):
            failures.append(f"emu:saveStateFile did not report success: "
                            f"{res['savestate']}")
        if not ss.exists():
            failures.append(f"{ss} was not written")
        else:
            h = hashlib.sha256(ss.read_bytes()).hexdigest()
            print(f"    savestate: {ss} ({ss.stat().st_size} B) sha256={h[:16]}...")
            meta = {
                "rom_sha256": hashlib.sha256(rom.read_bytes()).hexdigest(),
                "savestate_sha256": h,
                "frames": total_frames(runs),
                "stage": args.stage,
                "final_callback2": cb2_name,
                "map": f"{mg}.{mn}", "camera": [x, y],
                "player": [px, py], "facing": face, "partyCount": pc,
                "party": [{"slot": s, **d} for s, d in mons],
                "wall_seconds": round(res["wall"], 1),
            }
            (SAVES / (out_name + ".json")).write_text(
                json.dumps(meta, indent=2) + "\n")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        sys.exit(1)
    print(f"PASS: reached stage '{args.stage}'.")


if __name__ == "__main__":
    main()
