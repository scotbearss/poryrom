#!/usr/bin/env python3
"""Build the AUDIO CEILING FIXTURE: a ROM that runs the m4a mixer out of PCM
channels on purpose, so the failure can be HEARD.

Doc 67 slate item J; doc 76 is the record. The instrument half -- an mAVStream
tap in mgba-headless, so a spec can say `"audio": true` and get a .wav -- landed
2026-08-05. This is the experiment that tap was built for.

WHY THIS IS NOT A SCREENSHOT-CLASS FINDING AND NOT A PROBE-CLASS ONE EITHER
---------------------------------------------------------------------------
`src/m4a.c:82` configures the driver with `(5 << SOUND_MODE_MAXCHN_SHIFT)`:
FIVE simultaneous PCM voices, out of a `MAX_DIRECTSOUND_CHANNELS 12` array.
Past five the allocator in `src/m4a_1.s` (the loop at `_081DDBFA`, bounded by
`SoundInfo.maxChans`) does not error and does not fall back:

  * a channel that is not SOUND_CHANNEL_SF_ON is taken immediately;
  * otherwise it walks all five looking for a victim -- one already releasing
    (SF_STOP) first, else the LOWEST `priority`, tie-broken by the HIGHEST
    `track` pointer;
  * a victim is `ClearChain`d and STOLEN, cutting a sounding note mid-note;
  * with no victim it branches to `_081DDCEA` and the note is SILENTLY DROPPED.

A probe reading `gSoundInfo.chans[]` sees five busy channels, which is CORRECT.
The screen shows nothing at all. It is doc 62's class with the last instrument
removed -- which is why the deliverable here is a PAIR OF WAVS as much as it is
a set of assertions.

THE STEAL DETECTOR, AND WHY IT IS UNAMBIGUOUS
--------------------------------------------
`ClearChain` (`src/m4a.c:322`) is a C function, so it can be hooked without
touching a line of assembly. It has three call sites in `src/m4a_1.s`, and the
two that are NOT the steal both test SF_ON first and call ClearChain only when
it is CLEAR:

    m4a_1.s:1192  ldrb r1,[r4,statusFlags] / tst SF_ON / beq _081DD8AE -> bl ClearChain
    m4a_1.s:1379  ldrb r1,[r4,statusFlags] / tst SF_ON / bne _081DD9F6 ... bl ClearChain
    m4a_1.s:1721  <the steal>              -- reached only from the victim walk

So a ClearChain call that arrives with a PCM channel that IS SF_ON is the steal
at :1721 and cannot be anything else. The hook additionally range-checks the
pointer into `gSoundInfo.chans[]`, because CGB tracks put a `struct CgbChannel`
behind the same `track->chan` field.

THE CRY WALL IS A SECOND, INDEPENDENT ONE
-----------------------------------------
`SetPokemonCryTone` (`src/m4a.c`) walks `MAX_POKEMON_CRIES` (2) cry players for
a free one and, finding none, falls through to `maxClockIndex` -- the player
whose song is FURTHEST ALONG -- and restarts it there. A third overlapping cry
therefore CUTS OFF one of the first two. That is a C-level fallthrough, so it is
counted exactly rather than inferred.

WHAT IT MAKES -- three arms, one ROM, chosen by WHAT YOU HOLD AT BOOT
--------------------------------------------------------------------
The shape make_cliffs.py and make_palettes.py both use, for doc 68's reason:
every arm is a cold boot with one key held for the whole run, so there is no
walking, no frame counts and nothing to drift.

    (nothing) -> CONTROL   Littleroot's map music and nothing else.
    A         -> SATURATE  The same music, then one sound per two frames:
                           SE1, SE2, SE3 and both cry players, five claimants
                           arriving in a known order against five channels.
    B         -> CRYOVER   The same music, then FOUR cries six frames apart
                           against MAX_POKEMON_CRIES 2.
    R         -> QUIET     StopMapMusic(), then the SAME burst SATURATE fires.
                           Five claimants against five channels with nothing
                           else in the room.

CONTROL and QUIET are not decoration; they are why the numbers mean anything.
"Five channels were busy and a note was stolen" is equally consistent with
"ordinary map music already does that" -- and it turns out that IT DOES, about
eight times a second, because Littleroot's BGM has ten tracks and five voices.
CONTROL is what says so and QUIET is what attributes it: the same burst with the
music removed, so a steal count is a claim about the music rather than about the
fixture (doc 61 section 4's pair rule, twice).

The keys are picked against the ACTUAL mGBA keymap on the machine this gets
played on (`~/.config/mgba/config.ini`, section `gba.input.QT_K`): A=A, B=B,
L=L, R=R, Start=Return, Select=CAPS LOCK. Select is avoided entirely here --
Caps Lock is a toggle and does not reliably read as held.

STRUCT OFFSETS ARE PUBLISHED BY THE COMPILER, NEVER COMPUTED
------------------------------------------------------------
Doc 60 section 7's rule, earned again during doc 76: a regex over
`struct SoundChannel` derived 44 bytes by missing every pointer field (`wav`,
`currentPointer`, `track`, `prevChannelPointer`, `nextChannelPointer`); the real
size is 64. `gAudioProbeOffsets[]` is a const ROM array of `__builtin_offsetof`
and `sizeof` values, and the specs read it.

USAGE
    python3 tools/new_hack.py audio
    python3 tools/make_audio.py
    # build the fork, then:
    python3 tools/make_audio.py --specs
    python3 tools/verify_hack.py audio-saturate --rom <abs>/pokeemerald.gba

    python3 tools/make_audio.py --check     # report, write nothing

Exit 0 on success, 2 on any failed precondition or assertion.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import hx  # noqa: E402
REPO_ROOT = hx.HARNESS_ROOT
DEFAULT_HACK = hx.HACKS / "audio"
VERIFY_DIR = hx.SPEC_DIR

# Every generated file and every patch carries this, which is what makes
# re-running a no-op and the changes greppable in a 23,000-file fork.
MARKER = "AUDIO_PROBE_FIXTURE"

# Where the arms start. Littleroot Town because it has map music (MUS_LITTLEROOT)
# and because a fixture that needs no new map needs no map contract-check.
# (5,9) is the walkable tile one south of Brendan's door warp at (5,8) -- a warp
# tile would fire on the first frame and take the run somewhere else.
START_MAP, START_X, START_Y = "LITTLEROOT_TOWN", 5, 9

# Frames after the overworld callback is first seen before the burst begins.
# Long enough for MapMusicMain to have faded the map music all the way in, so
# the BGM is a full claimant rather than a quiet one.
BURST_AT = 240

# The five claimants of the SATURATE arm, in arrival order, two frames apart.
# One SE per music player, because MPlayStart on a player REPLACES that player's
# song -- two SE1 songs are a sequence, not a pile. Player indices read out of
# sound/song_table.inc: se_m_hydro_pump 1, se_m_solar_beam 2, se_low_health 3.
SATURATE_BURST = [
    ("PlaySE(SE_M_HYDRO_PUMP);", "SE1, 3 tracks"),
    ("PlaySE(SE_M_SOLAR_BEAM);", "SE2, 9 tracks"),
    ("PlaySE(SE_LOW_HEALTH);", "SE3, 1 track, and it loops"),
    ("PlayCry_NormalNoDucking(SPECIES_TORCHIC, 0, CRY_VOLUME, CRY_PRIORITY_NORMAL);",
     "cry player 0"),
    ("PlayCry_NormalNoDucking(SPECIES_WAILORD, 0, CRY_VOLUME, CRY_PRIORITY_NORMAL);",
     "cry player 1 -- both now busy"),
]

# NoDucking on purpose: PlayCry_Normal drops gMPlayInfo_BGM to volume 85 for the
# duration, which would make the BGM quieter in the saturated WAV for a reason
# that has nothing to do with the channel budget. It would not free a channel,
# so it changes only what the recording sounds like -- which is the deliverable.
CRYOVER_SPECIES = ["SPECIES_TORCHIC", "SPECIES_WAILORD", "SPECIES_ZIGZAGOON",
                   "SPECIES_MUDKIP"]
CRYOVER_GAP = 6      # frames between cries; a CRY_MODE_NORMAL cry runs far longer

ARM_CONTROL, ARM_SATURATE, ARM_CRYOVER, ARM_QUIET = 1, 2, 3, 4

# WHAT THE FIXTURE MEASURED, 2026-08-05, and the specs assert these exactly.
#
# They are written here rather than invented, and the order matters: the specs
# were first emitted in OBSERVATION form (`--observe`), run, and only then given
# expected values. Doc 74's palette-baseline discipline -- inventing an expected
# value for a wall nobody has hit is how you get a spec that can only agree with
# whoever wrote it.
#
# READ THE COLUMNS, NOT THE ROWS. `steals` is 249 / 251 / 256 / 0 and
# `steals_sounding` is 0 / 5 / 0 / 0: three arms that sound completely different
# have almost the same steal COUNT, and what separates them is the COMPOSITION.
# Doc 72's "diff the list, not the count" arriving in the measurement itself
# rather than in a counterfactual.
MEASURED = {
    # Littleroot's map music, alone. 249 steals in ~30 s -- about EIGHT PER
    # SECOND -- because the BGM has ten tracks and the mixer has five voices.
    # Doc 76 section 4 predicted "no stealing" here and was wrong: the ceiling
    # is not an edge case, it is the engine's normal operating condition.
    # Every one of the 249 took a channel already in SF_STOP, which is the
    # allocator's first preference and is why it is inaudible.
    "control": {"maxactive": 5, "slotmask": 0x001F, "steals": 249,
                "steals_sounding": 0, "stealmask": 0x001F, "crystarts": 0,
                "cryevict": 0, "cryplayers": 0, "fired": 0},
    # The same music plus five claimants. The count barely moves (+2) and
    # `steals_sounding` goes 0 -> 5: exactly the five burst items, each of which
    # had to cut a note that was still sounding. That is the audible half.
    "saturate": {"maxactive": 5, "slotmask": 0x001F, "steals": 251,
                 "steals_sounding": 5, "stealmask": 0x001F, "crystarts": 2,
                 "cryevict": 0, "cryplayers": 0x0004, "fired": 5},
    # cryplayers 0x44 = players 0,1,0,1 -- two bits per cry, oldest first. The
    # third and fourth cries REUSED the players the first two were still on,
    # and cryevict counts that at SetPokemonCryTone's own fallthrough.
    "cryover": {"maxactive": 5, "slotmask": 0x001F, "steals": 256,
                "steals_sounding": 0, "stealmask": 0x001F, "crystarts": 4,
                "cryevict": 2, "cryplayers": 0x0044, "fired": 4},
    # THE ATTRIBUTION. Same burst, music removed: ZERO steals, and the five
    # claimants reach FOUR simultaneous voices, not six. The saturation anyone
    # would design for never reaches the ceiling; the background music is
    # already sitting on it.
    "quiet": {"maxactive": 4, "slotmask": 0x000F, "steals": 0,
              "steals_sounding": 0, "stealmask": 0, "crystarts": 2,
              "cryevict": 0, "cryplayers": 0x0004, "fired": 5},
}


def fail(msg):
    print(f"make_audio.py: {msg}", file=sys.stderr)
    sys.exit(2)


def info(msg):
    print(f"    {msg}")


# --------------------------------------------------------------------------
# Re-derive every constant from the fork before building anything on it
# --------------------------------------------------------------------------

def read_engine_constants(hack: pathlib.Path) -> dict:
    """Doc 59's rule: a derived number rots, so read it rather than remember it.

    Everything this fixture is built around lives in the fork, and every one of
    them is asserted here rather than assumed. If the pin ever moves, this is
    where it stops instead of producing a fixture that measures the wrong wall.
    """
    m4a_h = (hack / "include/gba/m4a_internal.h").read_text()
    m4a_c = (hack / "src/m4a.c").read_text()
    ld = (hack / "ld_script.ld").read_text()

    def define(text, name, where):
        m = re.search(rf"^#define\s+{name}\s+(\d+)", text, re.M)
        if not m:
            fail(f"{name} not found in {where} -- the engine has moved")
        return int(m.group(1))

    out = {
        "max_directsound_channels": define(m4a_h, "MAX_DIRECTSOUND_CHANNELS",
                                           "m4a_internal.h"),
        "max_pokemon_cries": define(m4a_h, "MAX_POKEMON_CRIES",
                                    "m4a_internal.h"),
    }

    m = re.search(r"\((\d+)\s*<<\s*SOUND_MODE_MAXCHN_SHIFT\)", m4a_c)
    if not m:
        fail("the SOUND_MODE_MAXCHN_SHIFT term is not in m4aSoundInit -- "
             "the driver configuration has moved")
    out["max_chans"] = int(m.group(1))

    # THE 4-MUSIC-PLAYER LIMIT IS A LINKER-SCRIPT CONSTANT, and doc 76 section 5
    # left this open because it grepped src/ and sound/ only. NUM_MUSIC_PLAYERS
    # is ((u16)gNumMusicPlayers) and gNumMusicPlayers is not an object at all --
    # it is a linker ABSOLUTE whose ADDRESS is the number. That is why nothing in
    # C defines it and why `4` never appears next to it in any source file.
    m = re.search(r"^gNumMusicPlayers\s*=\s*(\d+)\s*;", ld, re.M)
    if not m:
        fail("gNumMusicPlayers is not assigned in ld_script.ld")
    out["num_music_players"] = int(m.group(1))

    # And the table it indexes, so the two cannot disagree silently.
    table = (hack / "sound/music_player_table.inc").read_text()
    out["music_player_rows"] = len(re.findall(r"^\s*music_player\s", table, re.M))

    if out["max_chans"] >= out["max_directsound_channels"]:
        fail(f"maxChans {out['max_chans']} is not below the array bound "
             f"{out['max_directsound_channels']} -- there is no wall to hit")
    if out["num_music_players"] != out["music_player_rows"]:
        fail(f"gNumMusicPlayers is {out['num_music_players']} but gMPlayTable "
             f"has {out['music_player_rows']} rows")
    if len(SATURATE_BURST) <= out["max_chans"] - 1:
        fail("the SATURATE burst has too few claimants to reach the ceiling")
    if len(CRYOVER_SPECIES) <= out["max_pokemon_cries"]:
        fail(f"{len(CRYOVER_SPECIES)} cries cannot overflow "
             f"{out['max_pokemon_cries']} cry players")
    return out


# --------------------------------------------------------------------------
# The generated fixture source
# --------------------------------------------------------------------------

CONFIG_HEADER = f"""// {MARKER}: written by tools/make_audio.py
#ifndef GUARD_CONFIG_AUDIO_PROBE_H
#define GUARD_CONFIG_AUDIO_PROBE_H

// One switch, so every fixture change in this fork is greppable.
#define AUDIO_PROBE_MODE TRUE

#endif // GUARD_CONFIG_AUDIO_PROBE_H
"""

PROBE_HEADER = f"""// {MARKER}: written by tools/make_audio.py
#ifndef GUARD_AUDIO_PROBE_H
#define GUARD_AUDIO_PROBE_H

#define AUDIO_ARM_CONTROL  {ARM_CONTROL}
#define AUDIO_ARM_SATURATE {ARM_SATURATE}
#define AUDIO_ARM_CRYOVER  {ARM_CRYOVER}
#define AUDIO_ARM_QUIET    {ARM_QUIET}

void AudioProbeSetStartWarp(void);
void AudioProbeSample(void);
void AudioProbeMainLoop(void);
void AudioProbeNoteClearChain(void *chan);
void AudioProbeNoteCryStart(s32 player);
void AudioProbeNoteCryEviction(void);

#endif // GUARD_AUDIO_PROBE_H
"""


def probe_source(k: dict) -> str:
    sat = "\n".join(
        f"        case BURST_AT + {i * 2}:   // {why}\n"
        f"            {call}\n"
        f"            gAudProbeFired++;\n"
        f"            break;"
        for i, (call, why) in enumerate(SATURATE_BURST))
    cry = "\n".join(
        f"        case BURST_AT + {i * CRYOVER_GAP}:\n"
        f"            PlayCry_NormalNoDucking({sp}, 0, CRY_VOLUME, "
        f"CRY_PRIORITY_NORMAL);\n"
        f"            gAudProbeFired++;\n"
        f"            break;"
        for i, sp in enumerate(CRYOVER_SPECIES))

    return f"""// {MARKER}: written by tools/make_audio.py -- do not hand-edit.
//
// Doc 67 slate item J. Everything here is a COUNTER or a LATCH: the events this
// fixture is about last a handful of frames each, and doc 66's storage rule
// applies with full force -- a value that is written and then overwritten by the
// next frame's correct behaviour is unobservable at any sampling rate, and every
// spec reading it would be forced down to a weak assertion.

#include "global.h"
#include "gba/m4a_internal.h"
#include "m4a.h"                 // gSoundInfo -- m4a_internal.h declares the
                                 // TYPE but not the object
#include "main.h"
#include "sound.h"
#include "overworld.h"
#include "main_menu.h"
#include "constants/maps.h"
#include "constants/songs.h"
#include "constants/species.h"
#include "constants/sound.h"
#include "config/audio_probe.h"
#include "audio_probe.h"

#define BURST_AT {BURST_AT}

EWRAM_DATA u8 gAudProbeArm = 0;
EWRAM_DATA u8 gAudProbeMaxActive = 0;      // most channels SF_ON at one time
EWRAM_DATA u8 gAudProbeMaxChans = 0;       // gSoundInfo.maxChans, read back
EWRAM_DATA u8 gAudProbeNumPlayers = 0;     // NUM_MUSIC_PLAYERS, read back
EWRAM_DATA u16 gAudProbeSlotMask = 0;      // every channel index ever SF_ON
EWRAM_DATA u16 gAudProbeSteals = 0;        // ClearChain on an SF_ON PCM channel
EWRAM_DATA u16 gAudProbeStealsSounding = 0;// ... that was NOT already releasing
EWRAM_DATA u16 gAudProbeStealMask = 0;     // which channel indices got stolen
EWRAM_DATA u16 gAudProbeCryStarts = 0;     // SetPokemonCryTone reached start_song
EWRAM_DATA u16 gAudProbeCryEvictions = 0;  // ... having found NO free player
EWRAM_DATA u16 gAudProbeCryPlayerLog = 0;  // 2 bits per cry, oldest in bits 0-1
EWRAM_DATA u16 gAudProbeFired = 0;         // burst items this arm actually fired
EWRAM_DATA u32 gAudProbeOwFrames = 0;      // main-loop frames with CB2_Overworld

// PUBLISHED BY THE COMPILER, NOT COMPUTED. Doc 60 section 7. A hand-derivation
// of struct SoundChannel during doc 76 came out at 44 bytes because a regex
// missed every pointer field; it is 64. A spec reads these and then reads
// gSoundInfo with them, so the harness can never be one field out of date.
const u32 gAudioProbeOffsets[] = {{
    sizeof(struct SoundChannel),                            // [0]
    __builtin_offsetof(struct SoundChannel, statusFlags),   // [1]
    __builtin_offsetof(struct SoundChannel, priority),      // [2]
    __builtin_offsetof(struct SoundChannel, track),         // [3]
    __builtin_offsetof(struct SoundInfo, maxChans),         // [4]
    __builtin_offsetof(struct SoundInfo, chans),            // [5]
    MAX_DIRECTSOUND_CHANNELS,                               // [6]
    MAX_POKEMON_CRIES,                                      // [7]
    sizeof(struct SoundInfo),                               // [8]
    SOUND_CHANNEL_SF_ON,                                    // [9]
}};

// Which arm, and where it starts. REG_KEYINPUT is read directly and is ACTIVE
// LOW -- a 0 bit means the key is down. gMain.heldKeys is deliberately not used:
// new-game init does not run at a fixed point in the input cycle, and a stale
// read selects the wrong arm silently, which looks like a broken fixture rather
// than a wrong button.
void AudioProbeSetStartWarp(void)
{{
    u16 keys = (u16)(~REG_KEYINPUT) & KEYS_MASK;

    // Doc 68 section 6.2: skipping the intro skips the naming screen, and
    // nothing else writes the player name -- eight zero bytes with no EOS,
    // which renders as a blank Start-menu row and clobbers gMain when selected.
    NewGameBirchSpeech_SetDefaultPlayerName(0);

    if (keys & A_BUTTON)
        gAudProbeArm = AUDIO_ARM_SATURATE;
    else if (keys & B_BUTTON)
        gAudProbeArm = AUDIO_ARM_CRYOVER;
    else if (keys & R_BUTTON)
        gAudProbeArm = AUDIO_ARM_QUIET;
    else
        gAudProbeArm = AUDIO_ARM_CONTROL;

    SetWarpDestination(MAP_GROUP({START_MAP}), MAP_NUM({START_MAP}),
                       WARP_ID_NONE, {START_X}, {START_Y});
}}

// Called from VBlankIntr immediately after m4aSoundMain(), so it observes the
// channel table the driver has just finished with. READ ONLY -- it never calls
// into m4a, because VBlank is where the driver itself lives.
void AudioProbeSample(void)
{{
    u32 i;
    u32 active = 0;

    gAudProbeMaxChans = gSoundInfo.maxChans;
    gAudProbeNumPlayers = (u8)NUM_MUSIC_PLAYERS;

    for (i = 0; i < MAX_DIRECTSOUND_CHANNELS; i++)
    {{
        if (gSoundInfo.chans[i].statusFlags & SOUND_CHANNEL_SF_ON)
        {{
            active++;
            gAudProbeSlotMask |= 1 << i;
        }}
    }}

    if (active > gAudProbeMaxActive)
        gAudProbeMaxActive = active;
}}

// Called from AgbMainLoop, NOT from VBlank. PlaySE and PlayCry both reach
// MPlayStart, which walks the player's track list and touches the same state
// m4aSoundMain is working on; firing them from inside the VBlank handler would
// be a race whose symptom is a corrupted mixer rather than an error.
void AudioProbeMainLoop(void)
{{
    if (gMain.callback2 != CB2_Overworld)
        return;

    gAudProbeOwFrames++;

    // QUIET takes the music away and then fires SATURATE's exact burst. It is
    // what turns CONTROL's steal count into an attribution: if the steals
    // survive the music being gone, they were never the music.
    // StopMapMusic (not m4aMPlayStop) because MapMusicMain owns the BGM and
    // would restart anything stopped behind its back.
    if (gAudProbeArm == AUDIO_ARM_QUIET && gAudProbeOwFrames == 1)
        StopMapMusic();

    switch (gAudProbeArm)
    {{
    case AUDIO_ARM_SATURATE:
    case AUDIO_ARM_QUIET:
        switch (gAudProbeOwFrames)
        {{
{sat}
        }}
        break;

    case AUDIO_ARM_CRYOVER:
        switch (gAudProbeOwFrames)
        {{
{cry}
        }}
        break;

    default:
        break;    // CONTROL: map music and nothing else. That is the point.
    }}
}}

// THE STEAL DETECTOR. ClearChain has three call sites in src/m4a_1.s and the
// two that are not the steal both test SOUND_CHANNEL_SF_ON and take the
// ClearChain branch only when it is CLEAR (:1192-1208 and :1379-1384). So a
// call arriving here with a PCM channel that IS SF_ON is the victim walk at
// :1721 and cannot be anything else.
//
// The range check is not belt-and-braces: a CGB track's `track->chan` points at
// a struct CgbChannel, so the argument is not always a SoundChannel at all.
void AudioProbeNoteClearChain(void *x)
{{
    struct SoundChannel *base = &gSoundInfo.chans[0];
    struct SoundChannel *chan = (struct SoundChannel *)x;
    u32 delta;
    u32 i;

    if (chan < base || chan >= base + MAX_DIRECTSOUND_CHANNELS)
        return;

    delta = (u32)((u8 *)chan - (u8 *)base);
    if (delta % sizeof(struct SoundChannel))
        return;
    i = delta / sizeof(struct SoundChannel);

    if (!(chan->statusFlags & SOUND_CHANNEL_SF_ON))
        return;

    gAudProbeSteals++;
    gAudProbeStealMask |= 1 << i;

    // The nastier half. A channel already in SF_STOP is releasing -- taking it
    // is the allocator's FIRST preference and costs a tail. A channel without
    // SF_STOP is still sounding, and that is the cut you can hear.
    if (!(chan->statusFlags & SOUND_CHANNEL_SF_STOP))
        gAudProbeStealsSounding++;
}}

// Which cry player each cry landed on, oldest first, two bits each. With
// MAX_POKEMON_CRIES 2 the third cry must reuse a player that is still running,
// so the log reads as a repeat rather than as a third index.
void AudioProbeNoteCryStart(s32 player)
{{
    if (gAudProbeCryStarts < 8)
        gAudProbeCryPlayerLog |= ((u16)(player & 3)) << (gAudProbeCryStarts * 2);
    gAudProbeCryStarts++;
}}

// SetPokemonCryTone found no free cry player and fell through to maxClockIndex
// -- the one whose song is furthest along. Whatever it was playing stops here.
void AudioProbeNoteCryEviction(void)
{{
    gAudProbeCryEvictions++;
}}
"""


# --------------------------------------------------------------------------
# The patches
# --------------------------------------------------------------------------

def patches() -> list[tuple[str, str, str]]:
    """(relative path, anchor, replacement).

    Same shape and the same idempotence argument as make_cliffs.py's: a patch
    tool that quietly no-ops is how you end up verifying a build that was never
    modified. apply_patch() asserts per replacement and reads the file back.
    """
    return [
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
            f"""#if AUDIO_PROBE_MODE == TRUE // {MARKER}
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
            f'#include "intro.h"\n#include "overworld.h"          // {MARKER}\n'
            f'#include "config/audio_probe.h" // {MARKER}',
        ),
        # 2. Start in Littleroot with an arm selected, not in the moving truck.
        (
            "src/new_game.c",
            "    SetWarpDestination(MAP_GROUP(INSIDE_OF_TRUCK), MAP_NUM(INSIDE_OF_TRUCK), WARP_ID_NONE, -1, -1);",
            f"""#if AUDIO_PROBE_MODE == TRUE // {MARKER}
    AudioProbeSetStartWarp();
#else
    SetWarpDestination(MAP_GROUP(INSIDE_OF_TRUCK), MAP_NUM(INSIDE_OF_TRUCK), WARP_ID_NONE, -1, -1);
#endif""",
        ),
        (
            "src/new_game.c",
            '#include "new_game.h"',
            f'#include "new_game.h"\n#include "config/audio_probe.h" // {MARKER}\n'
            f'#include "audio_probe.h"        // {MARKER}',
        ),
        # 3. No truck cutscene.
        (
            "src/overworld.c",
            "    gFieldCallback = ExecuteTruckSequence;",
            f"""#if AUDIO_PROBE_MODE == TRUE // {MARKER}
    gFieldCallback = NULL;
#else
    gFieldCallback = ExecuteTruckSequence;
#endif""",
        ),
        (
            "src/overworld.c",
            '#include "overworld.h"',
            f'#include "overworld.h"\n#include "config/audio_probe.h" // {MARKER}',
        ),
        # 4. Sample the channel table once per frame, right after the driver
        #    has finished with it.
        (
            "src/main.c",
            "    m4aSoundMain();\n    TryReceiveLinkBattleData();",
            f"""    m4aSoundMain();
#if AUDIO_PROBE_MODE == TRUE // {MARKER}
    AudioProbeSample();
#endif
    TryReceiveLinkBattleData();""",
        ),
        # 5. Fire the burst from the MAIN LOOP, where calling into m4a is safe.
        (
            "src/main.c",
            "        PlayTimeCounter_Update();\n        MapMusicMain();",
            f"""        PlayTimeCounter_Update();
        MapMusicMain();
#if AUDIO_PROBE_MODE == TRUE // {MARKER}
        AudioProbeMainLoop();
#endif""",
        ),
        (
            "src/main.c",
            '#include "main.h"',
            f'#include "main.h"\n#include "config/audio_probe.h" // {MARKER}\n'
            f'#include "audio_probe.h"        // {MARKER}',
        ),
        # 6. THE STEAL DETECTOR.
        (
            "src/m4a.c",
            """void ClearChain(void *x)
{
    void (*func)(void *) = *(&gMPlayJumpTable[34]);
    func(x);
}""",
            f"""void ClearChain(void *x)
{{
#if AUDIO_PROBE_MODE == TRUE // {MARKER}
    AudioProbeNoteClearChain(x);
#endif
    void (*func)(void *) = *(&gMPlayJumpTable[34]);
    func(x);
}}""",
        ),
        # 7. THE CRY WALL: which player a cry landed on, and whether the walk
        #    had to evict a running one to get there.
        (
            "src/m4a.c",
            """    i = maxClockIndex;

start_song:
    mplayInfo = &gPokemonCryMusicPlayers[i];""",
            f"""    i = maxClockIndex;
#if AUDIO_PROBE_MODE == TRUE // {MARKER}
    AudioProbeNoteCryEviction();
#endif

start_song:
    mplayInfo = &gPokemonCryMusicPlayers[i];
#if AUDIO_PROBE_MODE == TRUE // {MARKER}
    AudioProbeNoteCryStart(i);
#endif""",
        ),
        (
            "src/m4a.c",
            '#include "global.h"',
            f'#include "global.h"\n#include "config/audio_probe.h" // {MARKER}\n'
            f'#include "audio_probe.h"        // {MARKER}',
        ),
    ]


def apply_patch(path: pathlib.Path, anchor: str, replacement: str,
                check_only: bool) -> str:
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


def write_file(path: pathlib.Path, text: str, check_only: bool) -> str:
    """END-STATE assertion, never a change assertion (doc 73).

    "Did this file change" and "is this file now correct" are different claims,
    and only the second survives re-running the tool.
    """
    if path.exists() and path.read_text() == text:
        return "already correct"
    if check_only:
        return "WOULD WRITE"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if path.read_text() != text:
        fail(f"{path} did not read back")
    return "written"


# --------------------------------------------------------------------------
# The verification specs
# --------------------------------------------------------------------------
#
# Emitted AFTER the fork is built, from the constants read back out of the fork,
# so what a spec expects is derived from the tree the ROM was actually made from.
#
# EVERY ARM CAPTURES AUDIO. That is not decoration either: a steal is a cut note
# and no number in this file conveys it. The pair of WAVs is half the deliverable
# and the assertions are the other half.

# How long each arm runs. The burst starts BURST_AT frames after the overworld
# appears; boot to overworld is ~600 frames with the intro skipped. Sized in
# SECONDS of captured audio rather than in frames (doc 60 section 7), because the
# WAV is meant to be listened to: ~1500 frames is ~25 s of sound at 60 Hz.
BOOT_FRAMES = 900
RUN_FRAMES = 900


def build_specs(k: dict, measured: dict | None = None) -> list[dict]:
    """One spec per arm. `measured` supplies the exact expected values.

    Until a run has happened the specs are emitted in OBSERVATION form -- every
    assertion is always_valid and the run exists to print numbers. That is the
    same discipline palette-baseline.json used: measure first, then assert what
    was measured, and never invent an expected value for a wall nobody has hit.
    """
    specs = []
    for arm, key, desc in (
        ("control", None,
         "CONTROL. Littleroot's map music and nothing else. It exists so that "
         "'five channels were busy and a note was stolen' cannot be attributed "
         "to ordinary map music -- doc 61 section 4's pair rule."),
        ("saturate", "A",
         "SATURATE. The same music, then five claimants two frames apart: one "
         "SE on each of the three music players, then both cry players. Five "
         "PCM channels, more than five claimants."),
        ("cryover", "B",
         f"CRY OVERFLOW. Four cries {CRYOVER_GAP} frames apart against "
         f"MAX_POKEMON_CRIES {k['max_pokemon_cries']}. SetPokemonCryTone finds "
         f"no free player and restarts the one whose song is furthest along, "
         f"cutting it off."),
        ("quiet", "R",
         "QUIET. StopMapMusic() and then SATURATE's exact burst: five "
         "claimants against five channels with nothing else in the room. It is "
         "the attribution arm -- CONTROL measures a steal rate and this one "
         "says what was producing it. Also the clean half of the listening "
         "pair: the same five sounds, uncut."),
    ):
        keys = [key] if key else []
        spec = {
            "name": f"audio-{arm}",
            "description": desc + "  Generated by tools/make_audio.py "
                                  "--specs; do not hand-edit.",
            "symbols_from": "audio",
            "audio": True,
            "screenshot": True,
            "timeline": [
                {"name": "boot", "frames": BOOT_FRAMES, "keys": keys},
                {"name": "listen", "frames": RUN_FRAMES, "keys": []},
            ],
            "probes": arm_probes(arm),
            "assert": arm_assertions(arm, k, measured),
        }
        specs.append(spec)

    if measured is not None:
        specs.append(mirror_spec(k, measured))
    return specs


def mirror_spec(k: dict, measured: dict) -> dict:
    """THE MIRROR: QUIET's expectations, SATURATE's boot key. Must FAIL.

    Same ROM, same timeline, same probes, same expected values -- one key
    different. The wrong-values counterfactual class (docs 59, 63): what makes
    it a proof rather than a rebuild detector is WHICH assertions go red. Six of
    the seventeen describe the music's presence and must fail; the other eleven
    are shared between the two arms and must stay green, which is what aims the
    failure at the BGM rather than at "a different run".

    Run it with --expect-fail.
    """
    spec = {
        "name": "audio-quiet-counterfactual",
        "description": mirror_spec.__doc__.strip().splitlines()[0]
        + "  Generated by tools/make_audio.py --specs; do not "
          "hand-edit. Expected red: arm, maxactive, slotmask, steals, "
          "steals_sounding, stealmask. Expected green: the other eleven.",
        "symbols_from": "audio",
        "audio": False,
        "screenshot": False,
        "timeline": [
            {"name": "boot", "frames": BOOT_FRAMES, "keys": ["A"]},
            {"name": "listen", "frames": RUN_FRAMES, "keys": []},
        ],
        "probes": arm_probes("quiet"),
        "assert": arm_assertions("quiet", k, measured),
    }
    return spec


SAMPLE = {"every": 300, "at_step_end": ["boot", "listen"]}
END = {"at_step_end": ["listen"]}


def arm_probes(arm: str) -> list[dict]:
    p = [
        {"id": "arm",
         "why": "Which arm the boot key selected. A spec that asserts a steal "
                "count without asserting WHICH run produced it is a number "
                "about an unknown situation (doc 69).",
         "symbol": "gAudProbeArm", "type": "u8", "sample": dict(SAMPLE)},
        {"id": "maxchans",
         "why": "gSoundInfo.maxChans, read back out of the live driver. This is "
                "the wall itself: m4aSoundInit passes (5 << "
                "SOUND_MODE_MAXCHN_SHIFT) into an array of 12.",
         "symbol": "gAudProbeMaxChans", "type": "u8", "sample": dict(SAMPLE)},
        {"id": "players",
         "why": "NUM_MUSIC_PLAYERS. It is ((u16)gNumMusicPlayers), a LINKER "
                "ABSOLUTE whose address is the value -- which is why grepping "
                "src/ and sound/ for it finds nothing.",
         "symbol": "gAudProbeNumPlayers", "type": "u8", "sample": dict(SAMPLE)},
        {"id": "maxactive",
         "why": "The most channels ever SF_ON at one time, latched. The "
                "load-bearing observation: however many claimants arrive, this "
                "cannot exceed maxChans.",
         "symbol": "gAudProbeMaxActive", "type": "u8", "sample": dict(SAMPLE)},
        {"id": "slotmask",
         "why": "Every channel index ever seen SF_ON, one bit each. Channels 5 "
                "through 11 exist, are allocated, are 64 bytes each, and can "
                "never be reached -- the mask is what says so.",
         "symbol": "gAudProbeSlotMask", "type": "u16", "sample": dict(SAMPLE)},
        {"id": "steals",
         "why": "ClearChain calls arriving on a PCM channel that is SF_ON. The "
                "other two ClearChain sites in m4a_1.s both test SF_ON and call "
                "only when it is CLEAR, so this counts the victim walk at "
                ":1721 exactly.",
         "symbol": "gAudProbeSteals", "type": "u16", "sample": dict(SAMPLE)},
        {"id": "steals_sounding",
         "why": "The subset of steals that took a channel WITHOUT SF_STOP -- a "
                "note still sounding rather than one already releasing. This is "
                "the cut you can hear.",
         "symbol": "gAudProbeStealsSounding", "type": "u16",
         "sample": dict(SAMPLE)},
        {"id": "stealmask",
         "why": "Which channel indices were stolen from. A count says the "
                "budget ran out; the mask says where.",
         "symbol": "gAudProbeStealMask", "type": "u16", "sample": dict(SAMPLE)},
        {"id": "crystarts",
         "why": "SetPokemonCryTone calls that reached start_song.",
         "symbol": "gAudProbeCryStarts", "type": "u16", "sample": dict(SAMPLE)},
        {"id": "cryevict",
         "why": "SetPokemonCryTone calls that found NO free cry player and fell "
                "through to maxClockIndex, restarting a player that was still "
                "running. Counted at the fallthrough itself, not inferred.",
         "symbol": "gAudProbeCryEvictions", "type": "u16",
         "sample": dict(SAMPLE)},
        {"id": "cryplayers",
         "why": "Two bits per cry, oldest in bits 0-1: which player each cry "
                "landed on. With two players the third cry must repeat an "
                "index, and the log is what shows the repeat.",
         "symbol": "gAudProbeCryPlayerLog", "type": "u16",
         "sample": dict(SAMPLE)},
        {"id": "fired",
         "why": "How many burst items this arm actually fired. Doc 73's rule: "
                "when a feature reads as completely missing, suspect a consumed "
                "input or a path never reached before a dead code path.",
         "symbol": "gAudProbeFired", "type": "u16", "sample": dict(SAMPLE)},
        {"id": "chansize",
         "why": "gAudioProbeOffsets[0] = sizeof(struct SoundChannel), published "
                "by the compiler. A hand-derivation during doc 76 came out at "
                "44 by missing every pointer field.",
         "symbol": "gAudioProbeOffsets", "offset": 0, "type": "u32",
         "sample": dict(END)},
        {"id": "sf_on",
         "why": "gAudioProbeOffsets[9] = SOUND_CHANNEL_SF_ON, the mask the "
                "allocator itself tests.",
         "symbol": "gAudioProbeOffsets", "offset": 36, "type": "u32",
         "sample": dict(END)},
        {"id": "chan_count",
         "why": "gAudioProbeOffsets[6] = MAX_DIRECTSOUND_CHANNELS. The array "
                "bound, against maxchans which is the usable part of it.",
         "symbol": "gAudioProbeOffsets", "offset": 24, "type": "u32",
         "sample": dict(END)},
        {"id": "cry_count",
         "why": "gAudioProbeOffsets[7] = MAX_POKEMON_CRIES.",
         "symbol": "gAudioProbeOffsets", "offset": 28, "type": "u32",
         "sample": dict(END)},
        {"id": "cb2",
         "why": "Doc 66's rule -- assert that the thing under test actually "
                "happened. A channel table read outside the overworld is a "
                "measurement of a different screen.",
         "symbol": "gMain", "offset": 4, "type": "ptr", "sample": dict(SAMPLE)},
    ]
    return p


def arm_assertions(arm: str, k: dict, measured: dict | None) -> list[dict]:
    """Observation form until a run has produced numbers, then exact compares.

    The four constants below are asserted exactly from the start, because they
    are read out of the fork's own source by read_engine_constants() rather than
    predicted -- they are the fixture's preconditions, not its findings.
    """
    a = [
        {"probe": "cb2", "check": "symbol_at", "at": "last", "of": "value",
         "op": "==", "value": "CB2_Overworld",
         "why": "The run ended in the overworld, so every latch above was "
                "filled by the arm this spec names."},
        {"probe": "arm", "check": "compare", "at": "last", "op": "==",
         "value": {"control": ARM_CONTROL, "saturate": ARM_SATURATE,
                   "cryover": ARM_CRYOVER, "quiet": ARM_QUIET}[arm],
         "why": "The boot key selected this arm. Non-zero for every arm on "
                "purpose -- doc 58's rule that an exact compare against zero "
                "survives an address shift."},
        {"probe": "maxchans", "check": "compare", "at": "last", "op": "==",
         "value": k["max_chans"],
         "why": f"THE WALL. m4aSoundInit configures {k['max_chans']} "
                f"simultaneous PCM voices, read back out of the running driver "
                f"rather than out of the source."},
        {"probe": "chan_count", "check": "compare", "at": "last", "op": "==",
         "value": k["max_directsound_channels"],
         "why": f"MAX_DIRECTSOUND_CHANNELS is "
                f"{k['max_directsound_channels']}, so "
                f"{k['max_directsound_channels'] - k['max_chans']} channels are "
                f"allocated and unreachable."},
        {"probe": "cry_count", "check": "compare", "at": "last", "op": "==",
         "value": k["max_pokemon_cries"],
         "why": f"MAX_POKEMON_CRIES is {k['max_pokemon_cries']}."},
        {"probe": "players", "check": "compare", "at": "last", "op": "==",
         "value": k["num_music_players"],
         "why": f"NUM_MUSIC_PLAYERS is {k['num_music_players']}, and doc 76 "
                f"section 5 left this unestablished. It is a LINKER ABSOLUTE "
                f"(ld_script.ld: gNumMusicPlayers = {k['num_music_players']};) "
                f"whose address is the number, which is why no C file defines "
                f"it. Read here out of the running game."},
        {"probe": "chansize", "check": "compare", "at": "last", "op": "==",
         "value": 64,
         "why": "sizeof(struct SoundChannel), published by the compiler. Doc "
                "76's hand-derivation said 44."},
        {"probe": "sf_on", "check": "compare", "at": "last", "op": "==",
         "value": 0xC7,
         "why": "SOUND_CHANNEL_SF_ON = START|STOP|IEC|ENV. The mask the "
                "allocator's `tst` tests, so the detector tests the same one."},
    ]

    if measured is None:
        # OBSERVATION FORM. Doc 74's palette-baseline shape: the run exists to
        # print what the engine does, and inventing an expected value for a wall
        # nobody has hit yet is how you get a spec that can only agree with you.
        for pid in ("maxactive", "slotmask", "steals", "steals_sounding",
                    "stealmask", "crystarts", "cryevict", "cryplayers",
                    "fired"):
            a.append({"probe": pid, "check": "always_valid",
                      "why": "SUPPORTING -- OBSERVATION. Re-emit these specs "
                             "with --specs after a run to turn this into an "
                             "exact compare."})
        return a

    m = measured[arm]
    for pid, why in (
        ("fired", "Every burst item this arm declares actually fired. A zero "
                  "here would mean the arm never ran, which reads exactly like "
                  "a working ceiling."),
        ("maxactive", "THE LOAD-BEARING ONE. However many claimants arrive, "
                      "the mixer never has more than maxChans voices going."),
        ("slotmask", "Every channel index ever used, one bit each."),
        ("steals", "ClearChain on an SF_ON PCM channel: the victim walk."),
        ("steals_sounding", "Steals that cut a note that was still sounding."),
        ("stealmask", "Which channel indices got stolen from."),
        ("crystarts", "Cries started."),
        ("cryevict", "Cries that had to evict a running cry player."),
        ("cryplayers", "Two bits per cry: which player each landed on."),
    ):
        if pid not in m:
            continue
        a.append({"probe": pid, "check": "compare", "at": "last", "op": "==",
                  "value": m[pid],
                  "why": why + ("  SUPPORTING: an exact compare against zero "
                                "survives an address shift (doc 58)."
                                if m[pid] == 0 else "")})
    return a


# --------------------------------------------------------------------------

def emit_specs(k: dict, measured: dict | None, check_only: bool) -> None:
    for spec in build_specs(k, measured):
        path = VERIFY_DIR / f"{spec['name']}.json"
        status = write_file(path, json.dumps(spec, indent=2) + "\n", check_only)
        info(f"{path.name}: {status}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hack", type=pathlib.Path, default=DEFAULT_HACK)
    ap.add_argument("--check", action="store_true",
                    help="report what would change, write nothing")
    ap.add_argument("--specs", action="store_true",
                    help="emit verify/audio-*.json and stop")
    ap.add_argument("--observe", action="store_true",
                    help="emit the specs in OBSERVATION form (every finding "
                         "assertion becomes always_valid), which is how they "
                         "were authored before anything had been measured")
    args = ap.parse_args()

    hack = args.hack.resolve()
    if not (hack / "src/m4a.c").exists():
        fail(f"{hack} is not a pokeemerald fork -- run new_hack.py first")

    k = read_engine_constants(hack)
    print("==> constants re-read from the fork")
    info(f"maxChans            {k['max_chans']} "
         f"(of MAX_DIRECTSOUND_CHANNELS {k['max_directsound_channels']}; "
         f"{k['max_directsound_channels'] - k['max_chans']} unreachable)")
    info(f"MAX_POKEMON_CRIES   {k['max_pokemon_cries']}")
    info(f"music players       {k['num_music_players']} "
         f"(ld_script.ld absolute; gMPlayTable has "
         f"{k['music_player_rows']} rows)")
    info(f"SATURATE claimants  {len(SATURATE_BURST)} against "
         f"{k['max_chans']} channels")
    info(f"CRYOVER cries       {len(CRYOVER_SPECIES)} against "
         f"{k['max_pokemon_cries']} cry players")

    if args.specs:
        measured = None if args.observe else MEASURED
        print("==> specs" + ("" if measured else "  (OBSERVATION form)"))
        emit_specs(k, measured, args.check)
        return 0

    print("==> fixture source")
    for rel, text in (
        ("include/config/audio_probe.h", CONFIG_HEADER),
        ("include/audio_probe.h", PROBE_HEADER),
        ("src/audio_probe.c", probe_source(k)),
    ):
        info(f"{rel}: {write_file(hack / rel, text, args.check)}")

    print("==> patches")
    for rel, anchor, repl in patches():
        info(f"{rel}: {apply_patch(hack / rel, anchor, repl, args.check)}")

    print("==> next")
    info("build the fork, then:")
    info("python3 tools/make_audio.py --specs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
