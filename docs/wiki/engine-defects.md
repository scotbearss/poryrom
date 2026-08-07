# Engine defects in the pinned engine

The four defects this lab has found in its own pinned engine — `rh-hideout/pokeemerald-expansion` at `expansion/1.9.4`, commit `2e6562740674f29be8c756fe6a6a91f8d5322d46`. These are defects in the **upstream tree we forked**, not errors in our documentation: anyone building on this pin inherits them. Each entry gives what is wrong, how it was established (and whether by reading or by execution), the fix, and whether it is applied. Two have been measured in a running ROM and fixed; two remain static readings with no fixture. Siblings: [[verification-discipline]], [[walls-and-budgets]], [[save-system]], [[battle-engine]], [[maps-and-tilesets]], [[build-system]], [[dialogue-voice]], [[art-pipeline]], [[working-lessons]].

| ID | Location | What is wrong | Evidence class | Fixed? |
|---|---|---|---|---|
| **E1** | `src/level_caps.c:57`, `:74` | `>` where `>=` is needed; indexes one past the end of a `[5]` array | **Executed, twice, by two independent mechanisms** | **YES** — two characters |
| **E2** | `src/string_util.c:351-372` | `StringExpandPlaceholders` mis-lengths control codes; can read past end-of-string | Static read; the **surface** was reached in a running ROM by another route | **NO** — one caller-side hole closed |
| **E3** | `src/field_camera.c:401`, `:403` | `CameraUpdate` tests Y and assigns `deltaX` (copy-paste, unguarded) | Static read, independently confirmed | **NO** — latent, no known trigger |
| **E4** | `src/field_effect_helpers.c:164` | `LoadObjectRegularReflectionPalette` tests its condition backwards | **Static contradiction + measured + 2×2 fix proof** | **YES** — one character |

**A mode-level fact governing all of them: every fork starts at the pin, so every fix must be re-applied per fork. There is no patch queue.** E1 was fixed in a fixture fork, and a later fresh fork inherited the defect again and had to re-fix it (record 59 §3.3). Fine at four forks, not at forty. See [[build-system]].

**Numbering caution.** Record 52 §1 assigned E1–E3 and later inserted the reflection defect as **E4**, while a pre-existing heading in the same section — *"E4 (candidate, not a defect claim)"* — covers three defects found in **other people's hacks** during a teardown (Emerald Rogue's `AnyCursesActive()` copy-paste inversion, its dead `AUTO_FLAG_TRAINER_LVL_5`, and Inclement's `LEVEL_CAPS_OFF` falling through its switch). **None of those is in our tree**; the ID collision is bookkeeping, not a fifth defect. Where this page says E4, it means the reflection defect.

## E1 — `src/level_caps.c` indexes one past the end of a `[5]` array

**Severity: HIGH.** Latent at stock defaults, **live the moment soft EXP capping is turned on** — the most likely first difficulty knob in this mode. Established by reading (record 52 §1), **confirmed by execution twice** (record 58).

```c
static const u32 sExpScalingDown[5] = { 4, 8, 16, 32, 64 };
static const u32 sExpScalingUp[5]   = { 16, 8, 4, 2, 1 };
...
:57      if (levelDifference > ARRAY_COUNT(sExpScalingUp))          // 5 > 5 is FALSE
             return expValue + (expValue / sExpScalingUp[ARRAY_COUNT(sExpScalingUp) - 1]);
         else
             return expValue + (expValue / sExpScalingUp[levelDifference]);   // [5] on a [5]
...
:74      if (levelDifference > ARRAY_COUNT(sExpScalingDown))        // 5 > 5 is FALSE
             return expValue / sExpScalingDown[ARRAY_COUNT(sExpScalingDown) - 1];
         else
             return expValue / sExpScalingDown[levelDifference];             // [5] on a [5]
```

`ARRAY_COUNT` is `(size_t)(sizeof(a)/sizeof(a[0]))` (`include/global.h:45`) = **5**; the arrays are indexed `[0..4]`. At `levelDifference == 5` — **and only there** — the guard is false, the `else` branch runs, and the index is one past the end. Both comparisons need `>=`. Containing function: `GetSoftLevelCapExpValue` (`src/level_caps.c:39-83`).

**Why "latent at defaults" is literal.** The pin ships `B_EXP_CAP_TYPE = EXP_CAP_NONE` and `B_LEVEL_CAP_TYPE = LEVEL_CAP_NONE`, and GCC folds both functions away. Disassembled from the stock `pokeemerald.elf` (record 58 §1):

```
0814de50 <GetCurrentLevelCap>:        2064  movs r0, #100     4770  bx lr
0814de54 <GetSoftLevelCapExpValue>:   0008  movs r0, r1       4770  bx lr
```

**Four bytes each**, `.sym` sizes `00000004`. **The defective comparison does not exist in the shipped default binary** — stronger than "the branch is never taken", and why no amount of testing the default build could have found E1. Nor is there a configuration that dodges it: `include/level_caps.h` `#error`s if `B_EXP_CAP_TYPE` is `HARD`/`SOFT` while `B_LEVEL_CAP_TYPE` is `NONE`, so turning capping on **forces** a real cap source.

### What the out-of-bounds read lands on — measured from the ROM, before running anything

From the `.sym`, both forks (record 58 §3): `0865e2b8 l 00000014 sExpScalingUp.1`, `0865e2cc l 00000014 sExpScalingDown.0`, `0865e2e0 l 00000009 __compound_literal.0`. The tables are **adjacent**, `Up` immediately followed by `Down`. Therefore:

- **`sExpScalingUp[5]` IS `sExpScalingDown[0]` = 4.** Line 57 unfixed returns `6400 + 6400/4 = 8000` where it should return `6400 + 6400/1 = 12800`.
- **`sExpScalingDown[5]` is the first word of `__compound_literal.0`** — bytes `c2 bb c8 be`, decoding through `charmap.txt` as **`HAND`**, the front of the in-ROM string `"HANDSOME"`. As a little-endian `u32`, **3,200,826,306** — so line 74 unfixed returns `6400 / 3200826306 = 0` instead of `6400/64 = 100`.

**Gameplay consequence unfixed:** a mon exactly 5 levels **over** the cap gains **0** EXP instead of `exp/64`; a mon exactly 5 levels **under** gets **+25 %** instead of **+100 %**. Two things worth banking (record 58 §3): **the divisor is a text string** — arbitrary, build-layout-dependent, and could as easily have been `0`, which on the GBA (no hardware divide; `__aeabi_uidiv`) is a division by zero rather than a wrong number; and **the up-path bug is the more dangerous**, because `sExpScalingUp`'s overflow reads its own sibling table and **silently produces a plausible answer** — 8000 is a perfectly sensible EXP number, so its garbage is not obviously garbage (the plausible-artifact class, [[verification-discipline]] §9).

### How it was proven

Two forks differing in exactly two files (`HACK_MANIFEST.json`'s timestamp and `src/level_caps.c`'s two characters), verified by `diff -rq`: `e1bug` (capping ON, probe, two new tests, **defect present**, ROM `af530dbff1171e0b…`) and `e1fix` (the same tree **plus the fix**, `eb01c4a81811e361…`).

**Proof one — the engine's own `make check`, which touches none of our instrumentation.** A new `test/level_caps.c` calls `GetSoftLevelCapExpValue` directly and asserts what the *correct* clamp gives, so it fails whatever the garbage is. **The boundary's two neighbours are asserted before the boundary itself**, and the framework stops a test at its first failure — so a report naming the third line is itself evidence the failure is at `levelDifference == 5` alone (record 58 §4):

```
[1] E1: level-cap EXP boost does not index past sExpScalingUp[4]: FAIL
[0] E1: soft EXP cap does not index past sExpScalingDown[4]:      FAIL
  - test/level_caps.c:27: EXPECT_EQ(0, 100) failed
  - test/level_caps.c:39: EXPECT_EQ(8000, 12800) failed
```

**`0` and `8000` are exactly the two numbers predicted from the ROM bytes**, reached by a completely different route. On `e1fix`: both PASS, exit 0.

**Proof two — the `.sym` harness, a 2×2 mirror-image matrix.** Same probes, same controls, same liveness assertions; only the discriminating expected values differ. 15 assertions each, cold boot, 600 + `random_range(30, 90)` frames. Diagonal on seeds 1 / 2 / 42 / 99991, all sixteen runs (record 58 §5):

| | ×`e1fix` | ×`e1bug` |
|---|---|---|
| `e1-fixed` | **15 PASS / 0 FAIL** | 11 PASS / **4 FAIL** |
| `e1-buggy` | 11 PASS / **4 FAIL** | **15 PASS / 0 FAIL** |

The 4 FAILs are **exactly** the 4 discriminators. Everything else passes on **both** builds — including the four boundary controls (indices 4 and 6, last in-bounds and clamped path), `gE1ProbeValid == 1`, and the boot `symbol_sequence`. **That combination is what makes the failure a statement about the one out-of-bounds index rather than about "this is a different binary"**, and it rules out "the unfixed build simply does not boot."

```
gE1ProbeDown[0..6]   1600 800 400 200 100 [   0] 100        <- unfixed
                     1600 800 400 200 100 [ 100] 100        <- fixed
gE1ProbeUp[0..6]     1600 7200 8000 9600 12800 [ 8000] 12800   <- unfixed
                     1600 7200 8000 9600 12800 [12800] 12800   <- fixed
```

The probe is deliberately **cap-relative** (`GetSoftLevelCapExpValue(cap ± i, 6400)` for `i` in `0..6`), so every number is independent of what the cap happens to be — it runs at the end of `AgbMain`, before the saveblock pointers are installed. `gE1ProbeValid` exists so a nonsense cap makes the spec FAIL rather than quietly report nonsense (record 58 §2). Probe cost: EWRAM **+72 B exactly**, IWRAM unchanged, ROM +512.

### The fix, its status, and two findings that outlive it

**Two characters: `>` → `>=` at `:57` and `:74`.** Applied and proven in `e1fix` (record 58), and **re-applied in the shipped game**, where it is **live rather than latent** because `B_EXP_CAP_TYPE` is `EXP_CAP_SOFT`; the game carries 10 of its own tests calling the shipping functions directly (record 59 §3.3).

- **The fix moved NOTHING.** The two forks' `.sym` files are **byte-identical** (`cmp` exit 0) — `>` and `>=` are the same-size THUMB comparison, and 0 of 95,851 unique symbols changed address or size. **The fork as a whole moved 99.21 %** (95,092 of 95,846), driven by the config change and the probe, not by the fix (record 58 §6). See [[verification-discipline]] §12.
- **`make check` on the fixed fork is NOT green, and that is reported rather than smoothed over** (record 58 §7). The residual is `test/battle/exp.c:46: EXPECT_GT(1, 1) failed — "Higher leveled Pokemon give more exp 2/2"`, **identical on both forks**, so it cannot be caused by E1 or its fix. Cause: the *config* change — that test is a real emulated wild battle with a level-20 player, and with soft capping on, both parametrizations' gained EXP collapse to the same floor of 1.

  **A sharp coincidence inside it, measured rather than assumed:** the level cap inside the test ROM is **15** and `exp.c`'s player is level **20** — *exactly* 5 levels over, precisely E1's out-of-bounds index. **The pin's own test suite stands on the defect's boundary the moment soft capping is switched on**, and still cannot detect it, because the buggy divisor (3,200,826,306 → 0) and the correct one (64 → 0 at Caterpie magnitudes) floor to the same reported 1. **A test that executes the defective line is not a test that detects the defect.** Operational consequence: **the green baseline for any fork with soft capping enabled is `FAILED == 1`, not `0`** — record it alongside the clean-tree `0/2080/376/26/2482`. See [[verification-discipline]] §11 and [[battle-engine]].

**What the proof did NOT establish**, stated openly (record 58 §8): **nobody has watched the gameplay consequence.** `exp.c` is a real emulated battle and the defective line *does* execute in it, but the observable difference there is nil — what is proven is a **return value**, not a player-visible outcome. Also untouched: `B_LEVEL_CAP_VARIABLE`, `B_RARE_CANDY_CAP`, `EXP_CAP_HARD`; the flag-list cap path with badges actually set; and the `#define` change's own side effects beyond `make check`.

## E2 — `StringExpandPlaceholders` mis-lengths control codes and can read past end-of-string

**Severity: MEDIUM-HIGH — every field-dialogue string goes through this path.** Established by reading (record 52 §1, spot-checked at the pin; the mismatch reproduces exactly). **Never fixed in the engine.**

`GetExtCtrlCodeLength`'s `lengths[]` table (`src/string_util.c:660-686`) is the engine's own statement of how many bytes each `EXT_CTRL_CODE_*` occupies, **including the code byte** — proved by `SkipExtCtrlCode` (`:694-700`), which does `s++` past `EXT_CTRL_CODE_BEGIN` then `s += GetExtCtrlCodeLength(*s)`. `StringExpandPlaceholders` (`:351-372`) re-implements the same knowledge as a `switch`, and **the two disagree**:

| Code | `lengths[]` says | The expander's `switch` does | Net |
|---|---|---|---|
| `[0]` (the unnamed `0x00` slot) | 1 → **0 arg bytes** | not in the 0-arg list → `default:` → consumes **1** | **over-reads 1 byte** |
| `EXT_CTRL_CODE_WAIT_SE` (`0x0A`) | 1 → **0 arg bytes** | not in the 0-arg list → `default:` → consumes **1** | **over-reads 1 byte** |
| `EXT_CTRL_CODE_PLAY_SE` (`0x10`) | 3 → **2 arg bytes** | no case → `default:` → consumes **1** | **under-reads 1 byte** |

The expander's 0-arg list is exactly `RESET_FONT, PAUSE_UNTIL_PRESS, FILL_WINDOW, JPN, ENG, PAUSE_MUSIC, RESUME_MUSIC` (`:358-364`) — **seven codes**. The `lengths[]` table has **nine** entries of length 1; the two missing ones are the over-read cases. **The dangerous half:** if the byte the expander wrongly consumes is `EOS`, it writes the terminator and then **keeps reading past the end of the source string**. **The `PLAY_SE` row is the same family running the other way** — the second argument byte escapes the inner switch and is copied into the destination as an ordinary character, **corrupting the rendered string** rather than over-reading. It is explicitly labelled **`[derived]`**: arithmetic over the cited table and switch, **no shipped string traced to prove one exercises it, and no ROM run for it.** Treat it as a candidate, not a confirmed defect (record 52 §1).

**The surface was reached in a running ROM — by a different route.** Record 68 §6.2 hit the read-past-end-of-string surface **without a bad string constant**. A boot shortcut jumping straight to `CB2_NewGame` skips the naming screen, and nothing else writes the player name. Measured: `gSaveBlock2Ptr->playerName` reads `0000000000000000` — and in this charmap `0x00` is the **space glyph** while `0xFF` is the terminator, **so the name renders as blanks and the string has no EOS**. Selecting the resulting blank Start-menu row (`MENU_ACTION_PLAYER`) takes an unterminated string into the trainer card and **overwrites `gMain` itself**:

```
frame 1085  gMain.callback2 = 08172d75 CB2_Overworld     vblankCounter1 rising
frame 1140  gMain.callback2 = 0fbe8b00 <unresolved>      vblankCounter1 frozen at garbage
```

**The fix taken was caller-side, not engine-side:** `NewGameBirchSpeech_SetDefaultPlayerName(0)` — what the naming screen itself calls, copying a preset and writing `EOS` at `PLAYER_NAME_LENGTH` — called at the tail of `NewGameInitData` where nothing upstream can undo it. After, `playerName` reads `cdcecfff…` and the row opens `CB2_TrainerCard` and stays there. ROM +16 B, RAM unchanged. **The same shortcut and the same hole were in `make_studio.py`**, fixed the same day.

**Fix status: not fixed.** The three-row mismatch is untouched at the pin. What exists is one closed caller-side hole and a standing rule: **any dialogue tooling generates strings that go through this function**, so a generator emitting `{WAIT_SE}` or `{PLAY_SE}` is emitting into a known-broken path (record 52 §1). See [[dialogue-voice]]. The obvious untaken fix is to make the expander's 0-arg case list agree with `lengths[]` — better, to delete the duplicate knowledge and have the expander call `GetExtCtrlCodeLength`. **Two copies of one decision that disagree** is E4's shape; here the disagreement is between a table and a switch rather than between two functions.

## E3 — `CameraUpdate` tests Y and assigns X

**Severity: LOW at this pin — no known reachable trigger — but unguarded and unfixed.** Established by reading (record 47), confirmed verbatim by that document's independent auditor, registered in record 52 §1.

In `src/field_camera.c`, the **fourth delta block** of `CameraUpdate` tests `curMovementOffsetY` / `movementSpeedY` but assigns **`deltaX`** at `:401` and `:403` — unlike its three siblings, which each test and assign the same axis. A plain copy-paste. **There is no `BUGFIX` / `UBFIX` guard on it.** pokeemerald marks known vanilla bugs that way, so the absence of a marker means **this one is not known upstream** (record 52 §1).

**Reachability**, narrowed by the audit: it requires a **mid-tile sign reversal**, which tile-locked player movement cannot produce, so it is latent under normal play. **Why it is recorded anyway:** any hack adding a **non-tile-locked camera mode** — a cutscene pan, a free camera, a mount or vehicle — leaves the regime in which it is unreachable. See [[maps-and-tilesets]].

**Fix status: not fixed, no fixture, never executed.** The correct change is to assign `deltaY` in that block, in line with its siblings. A defect with no reachable trigger is a poor use of a build cycle **until a camera mode exists** — at which point it becomes a required pre-check.

## E4 — `LoadObjectRegularReflectionPalette` tests its condition BACKWARDS

**Severity: LOW in effect, HIGH in clarity — bounded to one frame, but unambiguous, and it fired on every reflection the game ever drew.** Read as a candidate by record 74, **settled and measured** by record 80, **fixed and proved** by a diagonal 2×2 the same day. **The governing rule it was filed under: a fourth engine defect must not be filed on a reading** (record 74 §6). Record 80 discharged that.

### The static case, which needs no fixture

`src/field_effect_helpers.c` contains **two functions that do the same job on the same value**, and the source says so — `:204` reads *"This is basically a copy of LoadObjectRegularReflectionPalette"*. Their conditions are **exact opposites** (record 80 §1):

```c
// :158  LoadObjectRegularReflectionPalette  -- runs ONCE, at SetUpReflection
u8 paletteNum = IndexOfSpritePaletteTag(paletteTag);
if (paletteNum <= 16)          // <-- true for 0..15, i.e. ALREADY LOADED
{ ...build filtered palette...; paletteNum = LoadSpritePalette(&filteredPal); ... }
sprite->oam.paletteNum = paletteNum;

// :210  UpdateObjectReflectionSprite     -- runs EVERY FRAME, the sprite's callback
u8 paletteNum = IndexOfSpritePaletteTag(paletteTag);
if (paletteNum >= 16)          // <-- true for 0xFF, i.e. NOT LOADED
{ ...build filtered palette...; paletteNum = LoadSpritePalette(&filteredPal); ... }
reflectionSprite->oam.paletteNum = paletteNum;
```

`IndexOfSpritePaletteTag` returns **`0xFF` when the tag is absent** (`src/sprite.c:1618-1626`, a loop from `gReservedSpritePaletteCount` to 16 with `return 0xFF` as the fallthrough), so its reachable range is `{0..15} ∪ {0xFF}` — over which **`<= 16` and `>= 16` are exact complements.** One of the two is inverted, and it is the first: **the version that builds a palette only when that palette already exists.** The second — the one that runs every frame — is right.

> **When a codebase contains two copies of one decision and they differ, you do not need to know which is right to know that one is wrong** (record 80 §1). A strictly stronger class of evidence than record 74 could get, which was a reading of one function against a general fact about a helper; here the fallthrough value of `IndexOfSpritePaletteTag` says *which*.

**Traced.** `SetUpReflection` (`:65-86`) creates the reflection sprite, **sets its callback to `UpdateObjectReflectionSprite` first**, then calls `LoadObjectReflectionPalette` → `LoadObjectRegularReflectionPalette`. At that moment the filtered tag has never been loaded — nothing else in the tree references `REFLECTION_PAL_TAG` (three grep hits: its own `#define` and the two functions). So (record 80 §1.1): `IndexOfSpritePaletteTag` → **`0xFF`**; `0xFF <= 16` is **false**, so the branch is skipped and no palette is built or loaded; `sprite->oam.paletteNum = 0xFF` goes into a **4-bit bitfield** (`include/gba/types.h:71`), truncating to **15**.

**This is the OBJ-palette wall arrived at from the opposite direction.** In record 74 sixteen dynamic slots ran out and `LoadSpritePalette` returned `0xFF` into the same 4-bit field; here nothing ran out and the `0xFF` is *manufactured* by a backwards comparison. Same truncation, same consequence: the sprite renders **in full, in the right place, correctly animated, wearing whatever palette 15 holds** (records 74 §2, 80 §1.1). See [[walls-and-budgets]].

### The measurement

`verify/reflection-inverted.json`, **9 assertions, all PASS**, driven by a throwaway latching device. Every number `[measured]` (record 80 §3):

| Probe | Value | What it says |
|---|---|---|
| `refl_setups` | **1** | the hook fired exactly once — the control that makes the rest mean anything |
| `refl_index_first` | **255** | `IndexOfSpritePaletteTag` → `0xFF`; the filtered tag is **not loaded** |
| `refl_took_first` | **0** | **the `<= 16` branch was SKIPPED.** The defect, as a number |
| `refl_wrote_first` | **255** | `0xFF` assigned into `oam.paletteNum` |
| `refl_oam_first` | **15** | and the **4-bit field** reads it back as 15 — somebody else's palette |
| `refl_repairs` | **1** | the correct `>= 16` branch fixed it on the next frame |
| `refl_freed_first` | **15** | **and the repair freed slot 15**, which this sprite never owned |

**Why a probe could not see this and a latch could.** The wrong value lives for **one frame**, so no sampling rate lands on it: a spec sampling `gSprites[n].oam.paletteNum` reads the *repaired* value on every sample and reports a clean run (record 80 §2). The measurement needed latching probes inside the load and inside the repair branch. **And there is no picture of this fall** — the screenshot shows an ordinary room with an ordinary player in it, because by the time any screenshot can be taken the engine has already repaired itself. **A one-frame fault cannot be photographed, so the latch IS the photograph** (record 80 §3): the opposite boundary of the screenshot rule from record 68's, where the fault rendered as plausible content. See [[verification-discipline]] §7.

**The part that is not self-limiting.** The repair path frees the old palette before loading the new one (`:214-217`): `reflectionSprite->inUse = FALSE;` / `FieldEffectFreePaletteIfUnused(reflectionSprite->oam.paletteNum);` / `reflectionSprite->inUse = TRUE;`. On the repair frame that argument is **15** — a slot the reflection never owned, **measured**. The `IfUnused` guard is the only thing standing between a backwards comparison and another sprite's palette being freed underneath it. **What the guard does with that argument is still unmeasured**, and the case that would break it — an owner the guard does not count — **has not been constructed** (record 80 §1.3, §6). Record 74's three-arm palette fixture is the obvious place to build it.

### The fix, and the 2×2 that aims it at one character

**One character at `src/field_effect_helpers.c:164`: `if (paletteNum <= 16)` → `>= 16`**, making the load agree with the copy 46 lines below that was always right. The diff against the pin is **the fix and its comment and nothing else**, verified after the diagnostic device was stripped (record 80 §5).

| | `reflection-inverted` (broken spec) | `reflection-fixed` (mirror) |
|---|---|---|
| **unfixed build** | **9 PASS** | **4 FAIL / 5 PASS** |
| **fixed build** | **5 FAIL / 4 PASS** | **8 PASS** |

**Diagonal**, which makes it a proof about the edited character rather than about "a different build". **The three shared controls — `refl_setups`, `refl_first_seen`, `refl_index_first` — are green in all four cells.** The third is load-bearing: `refl_index_first == 255` on **both** arms, so the fix demonstrably did not preload anything or change what the code *sees*; it changed only what the code *does* when it finds nothing (record 80 §5.1).

| Probe | unfixed | fixed |
|---|---|---|
| `refl_index_first` | 255 | **255** *(shared control — must not move)* |
| `refl_took_first` | 0 | **1** — the branch that builds the palette now runs |
| `refl_wrote_first` | 255 | **5** — a real slot |
| `refl_oam_first` | **15** | **5** — no longer another sprite's palette |
| `refl_repairs` | 1 | **0** — nothing left to repair |
| `refl_freed_first` | 15 | **0** — nothing freed |

> **`refl_repairs == 0` is the quiet one.** On the shipped code the correct copy had to rebuild the palette **every single time a reflection appeared**. The defect was not rare; it was **universal and invisible** (record 80 §5.2).

Address-shift counterfactual on the fixed arm: **8 FAIL / 0 PASS, a clean sweep**, against a prediction written as a *bound* rather than a list (record 80 §5.3; see [[verification-discipline]] §5).

**Fix status: APPLIED, 2026-08-06, in the shipped game fork** (record 80 §5). Measured before it was touched, per the order E1 established — which is what lets the fix's own source comment state the numbers it corrects (*"tag 255, branch skipped, 255 written, field reads 15"*) rather than *"this looked wrong"*. The throwaway diagnostic device was **stripped, and the removal asserts its END STATE** rather than trusting the edits (record 80 §4, §5.4): zero grep matches for the probe symbols under `src/` or `include/`; `src/field_effect_helpers.c` and `include/field_effect_helpers.h` **byte-identical to the pin** by `diff -q` (which caught three stray blank lines a grep would not have); **EWRAM back to 247,850 B and IWRAM to 30,516 B**, the exact pre-device figures — the link report as a third independent check; and the patch replayed **121/121 byte-identical**.

### Still open on E4

- **Whether the wrong palette is ever DISPLAYED.** Bounded to **at most one frame**. Whether that frame reaches the screen depends on whether `BuildOamBuffer` runs between the load and the repair, which needs a frame-exact OAM read rather than a latch. The practical answer is "no player will see it"; **the practical answer is not the same as the measured one, and record 80 does not claim it.**
- **What `FieldEffectFreePaletteIfUnused(15)` actually does** on the repair frame (above).
- **Whether this is an expansion regression or Game Freak's.** **`[inference, not measured]`** it is the expansion's: record 74 established that vanilla's reflection scheme — `sObjectPaletteTagSets`, `gReflectionEffectPaletteMap`, `InitObjectEventPalettes` — is **dead code with no callers** at this pin, and the live dynamic-tag system (`REFLECTION_PAL_TAG`, `GetSpritePaletteTagByPaletteNum`) is what replaced it. The inverted line is in the replacement. **That is an inference from our own prior work, not an upstream diff**, and the diff is what would settle it — *"the expansion broke this"* and *"Game Freak shipped this in 2004"* are different findings resting on the same three lines (record 80 §6).

## What the defect count means

**Four defects — one ours-to-hit, one live in the dialogue path, one dormant, one universal and invisible — surfaced from a static read of a mature, CI-tested engine carrying 2,124 automated tests** (record 52 §1.1, which still says "three" and predates E4's insertion). That is the strongest available argument for pulling a clean-tree `make check` baseline before any hack work: **the baseline is the only thing that tells you whether a later failure is yours or was already there** (records 52 §1.1, 56 §7).

Three method rules earned across this register, in the order learned:

1. **MEASURE BEFORE YOU FIX.** A one-character change is exactly the size that tempts you to just make it. Measuring first cost one extra build and bought a source comment stating the numbers it corrects (record 80 §5, following record 58's order).
2. **A defect must not be filed on a reading.** Record 74 wrote the rule and deliberately did not file E4; record 80 measured it and then filed it. The gap between reading and measuring produced two facts no reading had — the `FieldEffectFreePaletteIfUnused(15)` call, and that the repair fires on **every** reflection.
3. **The strongest evidence a codebase can give you is two copies of one decision that disagree.** E4's static case needed no fixture at all; E2's is the same shape between a table and a switch.
