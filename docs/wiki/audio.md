# audio

**What this page is for.** Everything sound on this engine: the M4A driver's mixer and its five PCM
voices, the four music players (which are defined in the linker script, not in any C file), how a cry
travels from an `.aif` to a speaker, how the harness got ears, and where an instrument may safely run
inside the sound subsystem. Read it before adding music, a cry, or a sound effect — and especially
before designing an experiment that expects the audio ceiling to be an edge case, because **it is the
engine's normal operating condition**. The walls here are almost all silent; the loud ones are in
[[walls-and-budgets]].

---

## 1. The configuration, as actually set at this pin

`m4aSoundInit` (`src/m4a.c:71-101`, called once from `src/main.c:99`) configures the driver with a
single `m4aSoundMode` word (record 51):

| Setting | Value | Constant |
|---|---|---|
| Mixing rate | **13,379 Hz** | `SOUND_MODE_FREQ_13379` |
| DAC resolution | 8-bit | `SOUND_MODE_DA_BIT_8` |
| Master volume | 12 of 0-15 | `SOUND_MODE_MASVOL_SHIFT` |
| **Simultaneous PCM (DirectSound) voices** | **5** | `(5 << SOUND_MODE_MAXCHN_SHIFT)` |

`MAX_DIRECTSOUND_CHANNELS` is **12** — the array is twelve `SoundChannel`s long and `maxChans` is
five. The five software voices are *in addition to* the four hardware PSG channels, wired in by
`MPlayExtender(gCgbChans)` (`src/m4a.c:78`). The mixer runs out of IWRAM: `SoundMainRAM` is
`CpuCopy32`'d into `SoundMainRAM_Buffer` at init, for the cycle budget. `PCM_DMA_BUF_SIZE` is 1584,
double-buffered — **3,168 bytes** of PCM buffer inside `struct SoundInfo`.

**`sizeof(struct SoundChannel)` is 64** — published by the compiler through `gAudioProbeOffsets[]`
rather than derived by hand, after a hand-derivation in the same session said 44 by missing every
pointer field (record 76). **Seven of the twelve channels are unreachable**: `slotmask` never widens
past `0x001F`, so channels 5-11 are **448 bytes of EWRAM nothing can ever reach**. Not reclaimable
without editing the driver's own struct, which the BIOS sound syscalls also see — recorded as a
measurement, not a proposal.

## 2. THE CEILING — five voices, and the game is already over it — **SILENT**

The single most important audio fact in this corpus (record 76):

> **Ordinary map music steals a PCM voice about ten times a second, forever.** Littleroot's BGM has
> ten tracks and the mixer has five voices. Measured: **249 steals in 30 seconds** with nothing
> playing but the map music, climbing `3 → 52 → 104 → 153 → 198 → 249` at 300-frame samples — a flat
> rate, not a transient.

### What passing five looks like

Reading the allocator (`src/m4a_1.s`, the loop at `_081DDBFA`, bounded by `SoundInfo.maxChans`):

1. If a channel is not `SOUND_CHANNEL_SF_ON`, take it immediately.
2. Otherwise walk all five tracking a victim: prefer one already in `SF_STOP` (releasing), else the
   **lowest `priority`**, tie-broken by the **highest `track` pointer**.
3. If a victim was found — `ClearChain` it and **steal it**. The sixth sound cuts a sounding note
   mid-note.
4. If no victim was found — branch to `_081DDCEA` and **the note is silently dropped**.

**There is no error, nothing on screen, and a probe reading `gSoundInfo.chans[]` sees five channels
busy, which is correct.** This is the class in [[verification-discipline]] with the last instrument
removed: no RAM probe and no screenshot can see it. Hence §5.

**The drop branch has never been observed.** The music's notes always leave something in `SF_STOP`,
which is the allocator's first preference, so the fixture never reached `_081DDCEA`. Reaching it
needs a same-priority pile-up engineered against the priority table, or an assembly instrument
(record 76 §8).

### Why the count does not tell you anything

Three arms that sound completely different came back at **249 / 251 / 256** steals. What discriminated
was `steals_sounding` — the subset that cut a note *still sounding* rather than one already releasing
— which went **0 / 5 / 0**. An aggregate that moves by 1 % between two conditions you can hear apart is
the wrong aggregate. See [[verification-discipline]] for the general rule (diff the composition, not
the count).

### The arm that attributed it

`QUIET` — the same five-sound burst with `StopMapMusic()` first — produced **zero steals**, and the
five deliberate claimants reached **four** simultaneous voices (`slotmask 0x000F`, channel 4 never
touched). **The saturation anyone would design for does not reach the ceiling on its own.** The
background music is already sitting on it. When you go to construct a failure, measure the baseline
first — it may already be failing.

## 3. Music players — four, and the number is in the linker script

**`gNumMusicPlayers = 4;` is defined at `ld_script.ld:3` / `ld_script_modern.ld:3`.**
`NUM_MUSIC_PLAYERS` is `((u16)gNumMusicPlayers)` over an `extern char gNumMusicPlayers[]` — a **linker
absolute whose ADDRESS is the value**. There is no object, no initialiser, and no `4` anywhere near
the name in C, which is why grepping `src/` and `sound/` finds nothing (records 51, 76). Changing the
player count is a **linker-script edit**. See [[build-system]] — the build files are part of the
source.

`gMaxLines = 0` on the next line disables M4A's max-lines CPU-load governor.

The four players and their track budgets are declared in assembly
(`sound/music_player_table.inc`):

| Index | Player | Tracks |
|---|---|---|
| 0 | `gMPlayInfo_BGM` | **10** |
| 1 | `gMPlayInfo_SE1` | 3 |
| 2 | `gMPlayInfo_SE2` | 9 |
| 3 | `gMPlayInfo_SE3` | 1 |

`TRACK_SIZE` is `0x50` (80 B) = `sizeof(struct MusicPlayerTrack)`; the four track arrays total
**1,840 bytes of BSS**. `MAX_MUSICPLAYER_TRACKS` is 16 — that is the engine ceiling, not this ROM's
allocation. **A song with more than 10 tracks has tracks silently dropped or misbehaves.**

**Which mixer a sound plays on is a property of the song-table row, not of the call site.**
`sound/song_table.inc`'s second column is an index into `gMPlayTable`, read by `m4aSongNumStart`
(`src/m4a.c:108-116`). A new SFX that must not cut off an existing one is assigned by choosing its
player column. And note the corollary used to build the audio fixture: **`MPlayStart` on a player
*replaces* that player's song** — two SE1 sounds are a sequence, not a pile, so saturating the mixer
means firing one sound per player, not three on one.

**Cries use two further players that are NOT in `gMPlayTable`.** `MAX_POKEMON_CRIES` is **2**, each
opened with 2 tracks, so a cry never steals a BGM or SFX *track* — but it competes for the same five
PCM voices. A third overlapping cry restarts the player whose song is furthest along, cutting it off.
Observed: four cries six frames apart read `cryplayers 0x44` = players 0, 1, 0, 1 with an eviction
count of **2**, counted at `SetPokemonCryTone`'s own fallthrough (records 51, 76).

### Adding a song or SFX

Two source classes built by different rules in `audio_rules.mk`: checked-in M4A assembly
(`sound/songs/*.s`, 110 files) and raw MIDI (`sound/songs/midi/*.mid`, 420 songs, compiled by
`mid2agb`). **A song binds to a voicegroup by a single 4-byte pointer in its header**, emitted from a
`.equ` mid2agb writes from its `-G` option — changing a song's instrument bank is one number in
`midi.cfg` and a rebuild. Per-song master volume (`-V`) is folded into every volume byte **at assembly
time**. Editing `midi.cfg` rebuilds every song, and mid2agb writes its generated `.s` back into the
*source* directory (see [[build-system]]).

Two failure modes: **a `.mid` with no `midi.cfg` line fails at LINK time** with an undefined symbol
rather than at the audio step (the rule only `$(warning)`s) — unusually, a loud one, and a one-line
contract check catches it. And **mid2agb never clamps the track count**, so a 14-track MIDI compiles
fine against a 10-track player.

## 4. Cries — the whole path

A cry is **not a song in ROM**. `SetPokemonCryTone` (`src/m4a.c:1641-1680`) picks a cry slot (a free
one, else the one that has been playing longest), **builds a `PokemonCrySong` in RAM around the
`gCryTable` row**, and `MPlayStart`s it. `struct PokemonCrySong` is a `SongHeader` with the track
byte-code embedded field by field (record 51).

### Authoring and import: five edits plus one asset

Cross-checked against the in-pin tutorial (`docs/tutorials/how_to_new_pokemon_1_9_0.md:255-324`):

1. **The asset** — `sound/direct_sound_samples/cries/<name>.aif`: 8-bit signed mono PCM at
   **13,379 Hz** (the engine's own mixing rate).
   `ffmpeg -i <in> -c:a pcm_s8 -ac 1 -ar 13379 …`. No Makefile edit: `audio_rules.mk:20-21`'s pattern
   rule picks it up and produces `<name>.bin` **with `--compress` automatically**.
2. **`sound/direct_sound_data.inc`** — `.align 2` + `Cry_<Name>::` + `.incbin` the `.bin`.
3. **`include/constants/cries.h`** — add `CRY_<NAME>,` **before `CRY_COUNT`**.
4. **`sound/cry_tables.inc`** — add `cry Cry_<Name>` to `gCryTable` **and** `cry_reverse Cry_<Name>`
   to `gCryTable_Reverse`, **at the same ordinal position in both**.
5. **The species entry** in `src/data/pokemon/species_info/*.h` — `.cryId = CRY_<NAME>,`.

No voicegroup edit, no song, no C code, no build-system registration. Every edit is a mechanical
text insertion — **squarely automatable**, in the same class as the species and map codegen described
in [[maps-and-tilesets]].

### The tables and the codec

- Both tables are **1,113 rows** (1,111 `cry` + 2 `cry_uncomp`), 12 bytes per row, **26,712 bytes for
  the pair**.
- The `cry` macro writes a full 12-byte `ToneData` with envelope `0xff, 0, 0xff, 0` — **every cry uses
  the same envelope**. Cry character has to be in the `.aif`; there is no per-species envelope to
  tune.
- `gCryTable_Reverse` plays the *same* sample pointer backwards in the mixer. No reversed audio is
  stored.
- Cries are **compressed by default** (a 4-bit block-delta codec, ~51.7 % of raw); every other
  DirectSound sample is not. The opt-out is the `uncomp_` **filename prefix**, which is what selects
  the make rule — and the table macro (`cry_uncomp`) is a *separate* declaration of the same fact.
- The codec is lossy enough to destroy some material outright: two cries ship uncompressed with the
  in-source comment *"Cannot be heard unless we use cry_uncomp here."* **Nothing detects the need for
  it except listening.**

### Failure modes, all silent

| Mistake | What happens |
|---|---|
| The two cry tables desynchronised | every later species gets someone else's reversed cry — **silent** |
| `cryId` missing on a species | a silent species, no error |
| Off-by-one | the table index is `cryId - 1` (`src/sound.c:465`) |
| Family toggles set `1`/`0` instead of `TRUE`/`FALSE` | every cry id shifts |
| `cry` vs `cry_uncomp` out of step with how the `.bin` was built | the mixer decodes raw PCM as deltas or vice versa |
| Sample rate ≠ 13,379 | wrong pitch/speed — the mixer resamples from the header's `freq`, so a wrong `freq` is the fatal half |

Statically checkable, and worth a `check_*.py` in the same family as the map and dialogue checkers:
`rows(gCryTable) == rows(gCryTable_Reverse) == CRY_COUNT - 1`; the `Cry_*` label sets in
`cry_tables.inc` and `direct_sound_data.inc` must be equal; every `cry_uncomp` row must `.incbin` an
`uncomp_*.bin`. **A fault here produces a plausible artifact — a sound, just the wrong one — so the
check has to be static.**

### Two exactness notes for any reimplementation

The 16-byte header aif2pcm emits **is** `struct WaveData`. `freq` is `sample_rate * 1024` — a 22.10
fixed-point Hz value, not raw Hz. `size` is `num_samples - 1`, and `num_samples` may come from an AIFF
*marker* rather than the frame count. An off-by-one here is silent and produces a click.

### Playback parameters

`PlayCryInternal(u16 species, s8 pan, s8 volume, u8 priority, u8 mode)` (`src/sound.c:368-451`)
selects among **thirteen `CRY_MODE_*` presets**, each a fixed tuple of length / reverse / release /
pitch / chorus (defaults `210 / – / 0 / 15360 / 0`). Only `CRY_MODE_ECHO_START` and `CRY_MODE_GROWL_1`
set `reverse` — **those two effects are the entire reason `gCryTable_Reverse` exists**, at 13,356 bytes
of ROM. Pitch is 16-bit with the key at `((pitch + 0x80) >> 8) & 0x7F` — the low byte is **rounded**
into the key, not truncated (15360 → 60, middle C). Chorus is `SetPokemonCryChorus`, which raises
`trackCount` to 2; **record 51's original headline claimed the cry is always two detuned tracks and its
own audit corrected that in place** — the template ships `trackCount = 1` and the second part is inert.
BGM ducks to 85/127 while a cry plays.

### ADSR is TWO systems with opposite senses — the most error-prone fact in M4A authoring

| | DirectSound (PCM) | CGB (PSG) |
|---|---|---|
| Volume space | 0-255 | **0-15** (the APU's 4-bit field) |
| Attack | linear per-tick **increment** — **larger = FASTER** (255 = instant) | a **step counter** — larger = slower |
| Decay | multiplicative `v ← (v·decay)/256` — **larger = SLOWER** (255 ≈ ×0.996/tick, 0 = instant) | step counter — larger = slower |
| Sustain | an absolute level 0-255 | a 0-15 fraction |
| Release | multiplicative, decaying **toward the pseudo-echo volume, not toward zero** | step counter |

The macros mask PSG A/D/R to **3 bits** and sustain to **4** precisely because values above 7 are
meaningless there. Attack runs in opposite directions between the two systems. Record 51 notes most
tutorials get the decay/release sense backwards.

Two related traps for anything that parses voicegroups: **`REV` (0x10) and `CMP` (0x20) exist only on
the assembler side** — the C header defines just `CGB`/`FIX`/`SPL`/`RHY`, so a tool reading
`m4a_internal.h` alone will misinterpret every `gCryTable` row. And **there is no single
field-offset mapping correct for all voice kinds** (square-1 puts pan at +2 where the struct says
`length`). Trust the macro in `asm/macros/music_voice.inc`, not the struct comment.

### The ROM cost

Cries are **8,398,141 B ≈ 8.01 MiB, 25.03 % of the 32 MiB cart** (1,111 compressed + 2 raw, plus
headers), against 15.48 MiB raw. Plus 26,712 B of tone tables. `P_CRIES_ENABLED FALSE` reclaims all of
it and kills every cry; the per-family `P_FAMILY_*` toggles in `include/config/species_enabled.h` are
the surgical lever. See [[walls-and-budgets]] for the ROM/EWRAM/IWRAM picture this sits inside.

Non-cry DirectSound samples: 105 `.aif`, ~636 KiB, stored **uncompressed**. 420 `.mid` songs and 110
checked-in `.s` SFX compile to byte-code at build time (`mid2agb`).

## 5. The harness's ears — the `mAVStream` tap

`mgba-headless` has **no audio option whatsoever** (`-b -c -C -g -l -t -p -s -S -R --script` and
nothing more), so audio was unverifiable in the strongest sense. **The emulator is one we build
ourselves** — `mCore` exposes `setAVStream` and `struct mAVStream` carries
`postAudioFrame(stream, int16_t left, int16_t right)`, so a stereo PCM tap is a callback, not a fork
(record 76). This is the **third** patch this project has added to `headless-main.c`; see
[[build-system]] for all three and for the rule that a `sed` in a Dockerfile whose anchor stops
matching exits 0 and silently does nothing.

- Gated on `MGBA_HEADLESS_AUDIO_OUT`, so an unset run is byte-identical to every run recorded before
  it — confirmed by re-running a prior baseline against the rebuilt image.
- `verify_hack.py` grew an `"audio": true` spec key and writes a `.wav` beside the screenshot.
- **The sample rate is READ, never assumed** — the emulator writes `core->audioSampleRate()` to a
  `.rate` sidecar. A WAV built on a guessed rate plays at the wrong speed and still plays. (It is
  32768 Hz.)

### **mgba-headless is muted by default, and nothing says so** — **SILENT**

`src/gba/core.c:358-361` sets `masterVolume = core->opts.volume` when not muted, and **with no config
file on disk — which is every run inside a container — `opts.volume` is zero.** The first two capture
runs produced **25.21 s and 61.36 s of flawless silence, and both PASSED**: the APU mixed correctly,
the tap fired on schedule, the sample count was right, the rate was right, the duration matched, and
every sample was `0`. **There is no wrong number anywhere in a silent WAV** — the purest member of the
plausible-artifact class (see [[verification-discipline]]).

Fixed with `-C volume=256 -C mute=0` (256 is `GBA_AUDIO_VOLUME_MAX`); after, 62.08 s at 76.8 %
non-zero samples, peak 13056. **The check is now executable**: `verify_hack.py` measures peak
amplitude on every capture and refuses a run that asked for sound and got silence, with
`"audio_expect_silence"` as the opt-out.

**Captures are gitignored** (`docs/wiki/assets/*-audio/*.wav`, `*.pcm`, `*.pcm.rate`). A `.wav` off a
vanilla-music run is Game Freak's composition verbatim — a boundary rule, not a size one.

## 6. Instrumenting the sound subsystem

### Hook the function, not the symptom — and check whether it is already C

The steal detector was planned as "watch `chans[i].track` change while `statusFlags` stays `SF_ON`",
which is a sampling-rate problem with a race in it. **`ClearChain` is a plain C function**
(`src/m4a.c:322`), and reading its three call sites in `src/m4a_1.s` showed the two innocent ones both
test `SF_ON` and call `ClearChain` **only when it is CLEAR**. So a `ClearChain` call arriving with a
PCM channel that **is** `SF_ON` is the victim walk at `:1721` and cannot be anything else — the
inference collapsed into one exact counter (record 76). Read the call sites before designing an
inference.

The hook additionally **range-checks the pointer** into `gSoundInfo.chans[]`, because a CGB track's
`track->chan` points at a `struct CgbChannel` and the argument is not always a `SoundChannel`.

The cry wall is hooked the same way and more directly: `SetPokemonCryTone` falls through to
`i = maxClockIndex` when no cry player is free, and the eviction counter is called **at that
fallthrough**, not inferred from a symptom.

### Where an instrument may run — this is part of its design

> **A read-only probe can go anywhere. Code that FIRES sounds must not run inside the sound driver's
> interrupt.**

- **The channel sampler runs in `VBlankIntr`, immediately after `m4aSoundMain()`.** It observes the
  table the driver has just finished with, and it is read-only.
- **The burst driver runs in `AgbMainLoop`, after `MapMusicMain()`.** `PlaySE` and `PlayCry` both
  reach `MPlayStart`, which walks the player's track list and touches the same state `m4aSoundMain` is
  working on. Firing them from inside the VBlank handler is a race whose symptom is **a corrupted
  mixer rather than an error**.

### Cost of the whole instrument

EWRAM **+24 B** (thirteen latches; the offset table is `const` ROM), IWRAM **0**, ROM **+608 B**, save
**0**. See [[walls-and-budgets]] — IWRAM is the scarcest pool and a probe should not spend it.

## 7. What is still not known

- **The drop branch is inferred, not observed** (§2).
- **The steal counts are a property of `MUS_LITTLEROOT` played for 30 seconds**, not of the engine.
  They are asserted exactly because they reproduce across four seeds and rebuilds. A different map
  changes all three numbers.
- **Nothing has been listened to on hardware.** The WAVs are mGBA's mix, and mGBA's APU is not the
  GBA's. The difference between "a note was stolen" and "a note was stolen *audibly*" is a speaker.
- Raising `maxChans` is one argument to `m4aSoundMode` and would cost CPU in the mixer's per-sample
  loop. **Nobody has measured what.**

---

**See also:** [[walls-and-budgets]] · [[verification-discipline]] · [[build-system]] ·
[[battle-engine]] (cries and move SFX fire from battle scripts) · [[art-pipeline]] (the sibling
question of generating an asset versus deriving it) · [[engine-defects]] · [[maps-and-tilesets]] ·
[[save-system]] · [[dialogue-voice]]
