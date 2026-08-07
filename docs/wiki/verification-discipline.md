# Verification discipline

How this lab establishes that a change to a GBA ROM does what it claims: the harness's adversarial shape (inert JSON specs, a Lua driver that asserts nothing), the counterfactual requirement, the ranked table of weak assertion classes, the survivor-prediction protocol, and the traps this project has paid for. The numbered records are the evidence; this is the method. Siblings: [[engine-defects]], [[walls-and-budgets]], [[save-system]], [[build-system]], [[battle-engine]], [[maps-and-tilesets]], [[audio]], [[art-pipeline]], [[dialogue-voice]], [[working-lessons]].

## 1. Why the harness is adversarial by construction

The agent building the game would otherwise be the agent grading it, and that fails measurably: a Cursor audit of SWE-bench Pro found **63 % of "successful" agent resolutions had retrieved the fix rather than derived it**, and sealing git history and network dropped a score from **87.1 % to 73.0 %**. Documented hacks include `sys.exit(0)` before assertions run and monkey-patched runners fabricating a "100 % passed" report. Reward hacking is not a patchable bug but a consequence of optimising an imperfect objective, so **a harness must be adversarially designed, not merely present** (record 06).

Enforced by file layout, not intention (record 55):

- **`harness/read_symbols.lua` contains zero assertions.** It plays a mechanically-generated input schedule, samples memory, prints `SYMPROBE` lines, and never sees the spec's expectations. Re-verified independently: every comparison in it is a bounds/size/schedule test (record 55 §9.1).
- **Every judgement happens in Python, outside the emulator**, against values the Lua produced but did not interpret. **The spec is inert JSON — data, not code.** It cannot be made to pass itself.
- `validate_assertions()` rejects an **empty `assert` list, exit 2**, before a docker run is spent, in those words: *a spec that cannot fail is not a proof*.
- **Read RAM the game does not know is being read.** The engine is unmodified and cannot be made to narrate itself, so the harness resolves symbols out of the ROM's own `pokeemerald.sym`. State read behind the engine's back **cannot be faked by instrumenting the thing under test**. Where a spec *does* instrument the subject (the E1 probe spec), that is declared and the primary proof moves to a mechanism touching none of the instrumentation (record 58 §5; see [[engine-defects]]).

## 2. The spec format

`{name, symbols_from, description, timeline, probes, assert}` plus optional `savestate`, `screenshot`, `audio`.

- **Timeline**: ordered `{name, frames, keys}`; `frames` may be `{"random_range": [a, b]}` — randomised duration over exact scripted replay, per record 06.
- **Probes**: `{id, why, symbol, offset, type, length, deref, base_offset, sample}`. `type` ∈ `u8|u16|u32|s8|s16|s32|ptr|bytes`; `sample` combines `every`, `at`, `at_step_end`, `at_step_start`.
- **Checks**: `strictly_increases`, `non_decreasing`, `constant`, `changes_at_least`, `distinct_symbols_at_least`, `compare`, `in_range`, `resolves`, `symbol_at`, `symbol_sequence`, `symbol_never`, `always_valid`, `sample_count`. Ops `== != < <= > >= approx`. `at` ∈ `"first"|"last"|"all"|"any"|<frame>` (default `"last"`); `of` ∈ `"value"|"ptr"` on a deref probe.

**`deref` is mandatory for saveblock access.** `gSaveBlock1Ptr`/`gSaveBlock2Ptr` are re-rolled at **every battle start and every map load**, so the harness re-reads the pointer on every sample, never caches it, and prints it beside the value so the outside judge sees a re-roll (record 55). `SaveBlock3` is not ASLR'd. See [[save-system]].

**Never assert an exact saveblock pointer.** `gSaveBlock2Ptr` was observed at `0200b9d4`, `0200ba08` and `0200ba24` across runs of the *same* ROM — the offset differs **between** runs, not merely within one (record 55 §5). Assert the symbol it resolves into.

**Assert the number or the invariant, and say which.** `party-state.json` asserts `level == 5`, `hp == 20`, `personality == 0xf78da297`, `otId == 0x86df9fa6` — but gives `maxHP` a **range (15-25)**, because it is IV-derived and IVs re-roll on every cold boot (record 55 §2). The fields chosen sit outside the encrypted `secure` block: in the 100-byte `struct Pokemon`, `level` is at **0x54** and `hp` at **0x56**, re-derived from the pin rather than copied from the spec (record 55 §9.1). **Two structures agreeing on one number is far harder to produce by accident than either alone**: `*gSaveBlock2Ptr + 0x0A` is asserted equal to the starter's `otId` read out of EWRAM by a different route — read as `bytes`, not `u32`, since a 32-bit read at an odd offset is silently rotated by the hardware.

## 3. Counterfactuals: three mechanisms, not interchangeable

| Counterfactual | Mechanism | `party-state` |
|---|---|---|
| `--counterfactual` | every probe base shifted **+0x800** — addresses wrong, contents real | **20 FAIL / 3 PASS** |
| `--no-savestate` | **cold boot** — addresses correct, only *contents* differ | **16 FAIL / 7 PASS** |
| a wrong-value mirror spec | right addresses, right state, **wrong expected values** | **7/7 FAIL**; exit 0 under `--expect-fail` |

The shift lands in unrelated memory while staying inside the same RAM region, so the failure is *"you read the wrong thing"*, not *"the emulator refused to read"*. The wrong-value spec is **off by one where it can be** (`level == 6`, `hp == 19`) — an off-by-one is the error a level-cap or damage-formula hack actually produces (record 55 §3). `--expect-fail` on a *passing* spec exits 1: the inversion is not a rubber stamp (record 55 §9.1).

**A counterfactual that does not fail is a claim about the SAMPLE, not the mechanism.** Record 56 §10 patched `gTestRunnerEnabled` off, ran 5 `Sandstorm` tests, got 5 PASS, and reported it openly as unexplained. Settled later (record 56 §12.6): the mechanism was sound — *recompiling* the constant off rather than patching produced two ELFs differing in exactly one byte and **byte-identical 514-line emulator logs, same sha256**; the flag is enormously load-bearing (whole suite compiled-off: `PASS 1353 / FAIL 97 / TIMEOUT 20`, not surviving to the end); but **four of the five tests assert no positive `MESSAGE` at all**, and one uses `NOT MESSAGE`, which a disabled recorder satisfies *vacuously*. **Before believing the alarm is broken, check whether the sample can hear it** — and the cheap discriminator was recompiling rather than patching. One residue is still unexplained and stated as such.

## 4. WEAK CHECK CLASSES, RANKED

An assertion survives an address shift when garbage at the shifted address happens to satisfy it. The list grew across eleven-plus confirmations; the **ranking** is the newest and most useful part.

> **Do not predict what shifted memory will contain. Rank assertion forms by how much of the value space satisfies them.** A **threshold** (`>=`, `>`, `!=`) is satisfied by almost all garbage; a compare against a **common fill value** (0, or a bulk-init value) by a lot of it; an **exact non-zero compare** by almost none (record 80 §3.1).

| Class | Weak because | Record |
|---|---|---|
| `>` / `>=` / `!=` thresholds | a shifted base reads open bus (`0xfe3af34c` observed), trivially exceeding any small threshold | 55 §3, 61 §6 |
| `constant` | unrelated garbage is also unchanging; on cold boot the value is a steady zero | 55 §9.4 |
| `in_range`, `always_valid`, `sample_count` | bounded, or say nothing about the value | 55 §9.4, 58 §5 |
| **exact compare against `0`** | shifted RAM is full of zeros | 58 §5 |
| **exact compare against a bulk-init fill value** | a shifted address lands in more of the same fill; zero was only ever the commonest initialiser | 68 |
| **negative `symbol_at` (`!=` a name)** | under a shift the probe reads `<unresolved>`, and *unresolved ≠ any name* is true | 72 §7 |
| `symbol_at`, `symbol_sequence`, `resolves`, exact **non-zero** `compare` | **discriminating — prefer these** | 55 §9.4 |

Two refinements: **a deref-class zero DIES where a plain zero survives** — a shifted `gSaveBlock1Ptr` yields *unreadable* samples rather than more zeros (record 72 §7); and **a `constant` check is a SUPPORTING assertion** that must never be the only thing between a spec and a false PASS (record 55 §9.4). Specs label such assertions `SUPPORTING` in their own `why` field, and that labelling is load-bearing (§5).

**Zero-expectation counterfactual specs are supposed to have survivors**, and that is not a weakness: their job is discrimination against a positive twin, not standing alone (record 61 §6). The pleasing consequence: `reps_asked == 0` survives a shift while its mirror's `reps_asked == 1` does not — **the pair discriminates even though one half is individually weak** (record 62 §4).

## 5. Predict the survivors in writing, diff the LIST, and write a BOUND

**Why the count is worthless.** Record 72 §7 ran three written predictions: one predicted none and got **0 (clean sweep)**; one predicted 1 and got 2; one predicted 3 and got **3, with two of the three different**. That diff yielded two findings at once — the negative-`symbol_at` weak class (new), and independent re-confirmation that a dereferenced zero dies where a plain one survives. **A matching count would have been written up as a clean confirmation and hidden both.**

**Why the list should be a bound.** Two predictions failed in one day, in opposite directions: record 79 named small non-zero compares and the survivor was the compare against zero; record 80 named the compare against zero and the survivor was the **threshold** `refl_repairs >= 1`, because the shifted memory read `0x03ff03ff` rather than zeros. Both were guesses about **the contents of an address nobody chose**, which is unknowable. What is knowable is which assertions *could* survive — and the project already writes that down, **every time a spec labels an assertion weak in its own `why` field**. Both failed predictions named a different probe from the one whose `why` already said weak (record 80 §3.1, §5.3).

> **The predicted survivor set is every assertion the spec itself labels weak, and the score is whether every actual survivor fell INSIDE it — not whether the two sets were equal** (record 80 §5.3). Record 72's "diff the list, never the count" stands; this says which list to write.

Written as a bound, record 80's next prediction came back **8 FAIL / 0 PASS, a clean sweep**. Record 74 §4.1's three landed exactly — one arm's 3 survivors exactly as named, two arms clean sweeps, because those arms contain **no weak-class assertion at all**. **Corollary: if a spec's survivor bound is large, the spec is weak. Rewrite the assertions, not the prediction.**

## 6. When the PROOF is a PAIR OF RUNS, not an assertion

**The save-and-reload case** (record 61 §4). Every post-reset value in `reps-save-reload.json` is equally consistent with two stories: the save round-tripped through flash and was restored, **or** `SoftReset(RESET_ALL)` never cleared EWRAM and the old values were simply still there. Both predict identical output. A session shipping it alone would have shipped a proof of nothing while feeling thorough. `reps-save-reload-nosave.json` is the discriminator: identical reboot path, **second save omitted**, both tiers must read zero (measured `banked_legs 270 → 0`, `hist_count 240 → 0`). **Both halves are asserted deliberately** — without asserting the seed was alive at frame 1,440, a run where the debug hook silently did nothing would sail through the zero assertions and "prove" the discrimination while testing nothing.

> **When a proof's positive result and its most likely failure mode predict the same observation, the proof is not the spec that passes — it is the pair** (record 61 §4).

- **The hold/reps pair** (record 62 §2.2). `reps_asked == 0` for a wall sit is equally consistent with a build whose rep prompt is simply broken; the mirror drives a countable exercise on the same build and requires `reps_asked == 1`, `row_reps == 12`. The probe counts **entries into `STATE_REPORT_REPS`**, not answers — *"recorded zero reps"* and *"was never asked"* are different claims and only the second is the design.
- **The wrong-category evolution arm** (record 72 §7): without it, every assertion in the positive arm is equally consistent with *any training evolves anything*.
- **The three-arm palette fixture** (record 74 §3.1): one cliff arm alone cannot separate "the budget ran out" from "those two graphics are broken"; the reordered arm changes **only template order** and the victims move with it.
- **The E1 and E4 2×2 matrices** ([[engine-defects]]): diagonality is what makes a result a statement about the edited character rather than about "a different binary".
- **The persist pair** (record 82 §4.2): one spec needs a `.sav`, its twin requires its absence. On a machine with no history the pair flipped in **opposite directions** — the signature of leftover state rather than a regression.

## 7. LATCH a diagnostic, never sample it

**A one-frame value cannot be sampled.** `TrySpecialOverworldEvo` is installed as the main callback and calls `EvolutionScene` on its first frame, so `gMain.callback2` holds it for **one frame**; the fix was the instrument, not the sampling rate — the deliverable moved onto a function on screen for ~260,000 frames, and a **latched** flag proved the exit branch was taken (record 72 §4.3). Engine defect E4's wrong palette index likewise exists for one frame: a spec sampling `gSprites[n].oam.paletteNum` reads the *repaired* value on every sample and reports a clean run (record 80 §2).

The generalisation, from a diagnosis trail unobservable at its success value for three slices: **the fix is the storage rule — latch it, never clear it — not a faster sampling rate.** When a test settles for a weak assertion because the strong one will not go green, **suspect the INSTRUMENT before the assertion** (record 66, cited in 72 and 80).

**A one-frame fault cannot be photographed, so the latch IS the photograph** (record 80 §3). E4's screenshot shows an ordinary room with an ordinary player in it. This bounds the screenshot rule from the second side: a fault can render as **plausible content** (record 68), and a fault can **self-repair before any frame can be captured** (record 80).

## 8. Assert that the thing under test ACTUALLY RAN

Three times, clean zeros meant "nothing happened", not "nothing is wrong".

- **A debug hook that did not consume its input** (record 59 §9.1). `SELECT` reached the battle menu, where `DEBUG_BATTLE_MENU` is `TRUE` and `JOY_NEW(SELECT_BUTTON)` opens `CB2_BattleDebugMenu`. The arm silently left the battle into a debug menu and sat there. **Every number it reported was accurate; the experiment had not happened.** Caught by a `cb2` probe asserting `BattleMainCB2 → CB2_Overworld` by name; fixed by consuming the combo — zeroing `newKeys`/`newKeysRaw`/`newAndRepeatedKeys`/`heldKeys` in the same frame, leaving `heldKeysRaw` alone so the soft-reset check stays reachable.
- **A hook bound to a masked combination** (record 80 §4.1). `L+R+A` could never fire because `held` at the top of the debug tick **masks `A_BUTTON` out**. Nine probes read zero — indistinguishable from "the code is fine". **`refl_setups == 1` is the only reason it was caught.**
- **A swallowed confirmation press** (record 72 §7). 60 banked minutes is exactly cap 11's cumulative cost (`(L-5)(L-1)`, `6 × 10 = 60`), so the arm crossed a cap boundary and printed a line that **waits for A**. The single exit press was swallowed and every probe read zero — which looks exactly like a dead feature.

> **One counter asserting the hook fired exactly once is what separates "nothing is wrong" from "nothing ran".** Third time this control earned its place (record 80 §4.1).

## 9. What a harness structurally CANNOT see

**A harness proves the program does what you told it. It cannot tell you that you told it the wrong thing, and it cannot see the half of a UI that consists of matching what is already there** (record 62 §1). The canonical case: a screen copied the two lines that **load** the player's chosen window frame and not the call that **draws** them (`DrawBgWindowFrames()`). The tiles sat in VRAM, correctly styled, referenced by nothing. **There is no wrong number anywhere in it** — the `.sym` resolves, the palette is right, the text prints, callbacks fire in order, the save writes. A screenshot existed and was looked at: an unfamiliar screen with no border looks like a screen designed without one. Two more the same round, neither probe-reachable: a wall sit asked how many reps it was, and a diary that had been in the save file since slice 2 with no way to look at it. **Five minutes of play beat a round of proofs** (record 62). Same round: `LOG_ROWS_VISIBLE` is **5, not 6**, because `WIN_BODY` is 112 px, rows start at y=34 at a 14 px pitch, and six rows clip the last descenders at 118 — **no probe would ever have said so** (record 62 §3.1).

**The plausible-artifact class** — faults only a *static check before the build* or a *person looking* can catch:

| Fault | Renders as | Record |
|---|---|---|
| an oversize map | that map's own border block tiled edge to edge — a flawless meadow outdoors | 68 |
| an unterminated player name | blank menu rows, until something walks off the end | 68 |
| bad prose | perfectly | 71 |
| a save whose layout moved | a main menu identical to the correct one, minus one line | 73 |
| a sprite past the palette budget | in full, correctly animated, **in someone else's colours** | 74 |
| a missing window frame | a screen that looks designed without one | 62 |

> **If the failure produces a plausible artifact, the check has to be static.** That is the argument for the `check_*.py` family (`check_map`, `check_dialogue`, `check_tilesets`, `check_behaviors`, `check_battle_offsets`, `check_debug_keys`). See [[walls-and-budgets]], [[maps-and-tilesets]], [[dialogue-voice]].

**Therefore: send screenshots of every changed state, plus the states next to it, before anybody plays it — and save the PNG into the repo first.** A cosmetic edit reveals faults it has no business reaching.

## 10. Instrument limits — read the tool's own `main()` before blaming the subject

**A proof can be impossible rather than merely undone.** A spec proving a save survives a second launch was well-formed, correctly built, and its write half passed — and could never go green, because the headless emulator never attaches a save file to disk (record 61 §7). The flash round trip *is* proved (real soft reset, real reload, both tiers identical); **host-file persistence is a different claim, deliberately not made.** The follow-on: **ask who compiles the instrument.** "Structurally blocked by the emulator" was correct, and the emulator is built from our own Dockerfile — the fix was six lines and an env-var gate, and the specs it enabled now ship (record 73, referenced in record 82 §1.5, §4.2). See [[build-system]].

Four incidents where the tool's verdict was wrong while its subject was fine:

- **`--rom` emitted the basename only**, so a fork outside `engine/` could never be loaded. mGBA exits immediately, the log is **empty**, and the harness reports *"ROM did not complete 638 frames (docker exit 0)"* — naming frames and an exit code when the fault is a missing file (record 55 §9.2).
- **`No tests found.` is a lie about the cause** — hydra prints it whenever its results counter is 0, saying nothing about the ROM. The real cause was an `mgba-rom-test` built without `USE_ELF`, whose own CMake summary said `ELF loading support: OFF` and nobody read it (record 56 §5).
- **Never trust a frame number from a buffered log at a crash.** A crash "at frame 180 of 197" had happened well past 197; redirected stdout is block-buffered, so the last line is where the *buffer* ended. Two hours of bisecting were spent because frame 180 looked like data. **It is a lower bound** (record 55 §4).
- **`docker image inspect` answers "no such object"** for an image `docker image ls` lists and `docker run` starts, on Docker 29.6.1 — so the doctor reported a missing build image on a machine that had built two ROMs with it an hour earlier (record 82 §5.4).

**An empty result from a filtered command is not a result** — a drifted working directory produced a real error, eaten by a `grep`, presenting exactly as a clean run. Read a raw tail before believing a silence.

## 11. The second instrument: the engine's own `make check`

A genuinely independent grader — inert assertions matched by a fixed evaluator, touching none of our instrumentation (records 56, 58 §4). **Measured clean-tree baseline:** `2080 PASSED / 376 TO_DO / 26 KNOWN_FAILING / 2482 TOTAL`, **zero FAILED, zero ASSUMPTIONS_FAILED, zero KNOWN_FAILING_PASSING**, exit 0, 2m20s. Those three zero lines print only when > 0, so their absence is a positive statement; re-derived from the raw log by parsing every `[runner] name: RESULT` line rather than trusting the summary (record 56 §7). **It does not skip silently**: re-running with `TEST_SKIP_IS_FAIL` forced on gave **byte-identical** results (record 56 §8). "Green" means green over 2080 real tests — 15.15 % are `TO_DO` stubs.

**A real engine change turns it red, and only where predicted** (record 56 §12). One token, `[MOVE_ICE_FANG].power` 65 → 70, prediction written first: exit non-zero, `FAILED 2`, `PASSED 2078`, everything else unchanged — **every number matched and so did both names**. Name-diffed against the baseline: `PASS` in clean but not in the fork = **exactly the two predicted**; the reverse = **none**; same-file same-macro controls green. The other-direction control: a real content hack changing the starter table is **byte-for-byte the clean baseline** (record 56 §12.4), so the suite is not merely rebuild-sensitive.

Four rules for using it as a gate: **(1)** the failure message is a diff, not a flag — `EXPECT_EQ(196, 208)` names expected, actual, file, line and failing parameter, so baseline-diffing beats counting. **(2)** A parametrized test is **ONE result line**; 16 diverging blocks report a single `FAIL` naming only the first, so **`Tests FAILED` undercounts blast radius — read the names.** **(3)** An **`ASSUME`d constant degrades to a silent yellow SKIP, not a FAIL** at our config (`TEST_SKIP_IS_FAIL = \x00`, since we are not `GITHUB_REPOSITORY_OWNER=rh-hideout`): changing an `ASSUME`d value makes a test **stop running** rather than start failing, and **well-`ASSUME`d data is exactly the data a hack edits** — force the flag on for hack verification (record 56 §12.5). **(4)** The suite's size is a function of `include/config/*.h`, so a `TOTAL` diff is expected behaviour, not breakage: compare the three counts together and **diff the names** (record 56 §9). Verified arithmetically — 54,700 section bytes / 20-byte padded `struct Test` = 2735, minus 253 `ASSUMPTIONS` = **2482**, exactly the reported TOTAL.

**And a rule about the runner's own memory.** A single large file-scope static in ONE test file — a 1,444-byte fixture ring — corrupted **unrelated** tests: the failures named symbols from subsystems the slice never touched (`sDma3RequestCursor`, `gCgbChans`, `gIntroLightning_Gfx`, all "task not freed"), and the runner was eventually `Killed`. The named symbols are heap corruption surfacing at whoever allocated next; the test build sits tighter than the game build. **A `make check` failure naming symbols you did not touch is a memory story, not a logic story — and the first move is removing your own newest test file**, which is also the honest isolation (it returned the suite to a clean baseline and exonerated the accompanying SaveBlock3 growth). The fix pattern: point the tests at the real save-block buffer — `gSaveBlock3Ptr` is not ASLR'd (a static initializer, see [[save-system]]) and is valid from boot, including inside the runner — zero extra bytes, and it exercises the buffer the game really writes to (record 60 §6).

**Its boundary:** a headless black-box *battle* tester. Nothing drawn, no audio, no input, no overworld, no save. A hack that breaks a field script, the save layout, or `level_caps.c` sails through a green run (record 56 §11). See [[battle-engine]]. **And the paper arithmetic that made the proof work at all:** 65 → 66 would have been absorbed by the Gen5 formula's double truncation (base damage 33 either way), producing a "counterfactual that did not fail" for reasons having nothing to do with the harness. **A break the arithmetic swallows is not a break** — work it out on paper first (record 56 §12.1).

## 12. ROM and `.sym` are one pair

`--sym` defaults to the ROM's **own sibling** `.sym`, and the two are proved to be the same build by **content** before any symbol resolves (`tools/rom_pair.py`). It used to default to the engine's `.sym` regardless of `--rom`. **The near-miss, printed:** `gE1ProbeCap` lives at `0200b128` in the fork, and `0200b128` in the *engine's* table is **`sFavorLadyPtr`** — without the check the spec would have read the Lilycove Lady's pointer and reported it as a level cap (record 58 §6). A mismatched pair hard-fails **exit 2** before any docker run (`98022 of 98782 .sym entries are not in the ELF at that address/size`, coverage 0.77 %).

**The strongest proof that a check works is the wrong answer it prevents, printed** (record 72 §4.2). A code-moving edit moved **82,503 of 96,173 common symbols (85.79 %)**. Run against the stale `.sym` with the escape hatch, an *unchanged* spec produced:

```
[FAIL] cb2.symbol_sequence: observed CB2_Overworld -> CB2_InitTrainingMenu
                            vs wanted CB2_Overworld -> CB2_TrainingMenuMain
```

Runtime value `08203abc`. The correct table calls that `CB2_TrainingMenuMain` **exactly**; the stale one calls it `CB2_InitTrainingMenu`, **364 bytes into a different function** — a plausible, neighbouring, entirely wrong name. Nine data assertions failed with garbage; **ten still PASSED**. Cross-pairing two forks whose `.sym` files are genuinely byte-identical is **accepted, and correct** — it is a content check, not a filename check (record 58 §6).

## 13. Spec-authoring traps

- **A savestate spec structurally cannot cross builds.** The ROM-sha guard hard-fails exit 2 when the sidecar disagrees — right, since a state resumed against a different binary is nonsense. Consequence: **the spec asserting real gameplay state can never be run against a hack**, so the first two-build comparison must be a **cold-boot spec** against ROM-resident data addressed by symbol (record 55 §9.3).
- **A savestate PINS the ASLR the spec defends against.** Under a resumed state `gSaveBlock2Ptr` read `0200b9b4` identically on every run and seed, because a savestate restores RAM verbatim, pointer included. The deref probes are proven to *work*, not to *survive a re-roll* (record 55 §9.5).
- **`at: "all"` on a `deref` probe cannot be used across a reset.** `gSaveBlock1Ptr` is genuinely NULL until the engine reinstalls it, so the harness honestly reports "unreadable" and `all` fails on a good run. **Bracket the reboot rather than span it**: `at: "first"` and `at: "last"` (record 61 §5.2).
- **A coarse `every` chosen for a run's length steps over both ends of it.** On a 269,276-frame run, `"every": 2000` misses the leading `CB2_Overworld` and a `symbol_sequence` loses its first term. Pair `every` with explicit `"at": [20, 100, 170]` (record 61 §5.3).
- **There is no implicit end-of-run sample — a timeline can outrun its own sampling.** A refusal fired ~2,500 frames after the last every-4000 sample, and the assertion read a moment *before* the event it asserts: a FAIL with a correct game underneath. The evaluator samples only where told. **Stretch the tail so a sample lands after the final event, or sample denser** (record 63 §5).
- **Sample the transition, not just the endpoints.** `hist_count` at 4-frame resolution traced **0 → 240 → 0 → 240**: seeded, wiped by the reset, restored from flash. Weak class, labelled as such — but the only assertion that watches the value **die**, which is what makes its return mean anything (record 61 §5.4).
- **When a spec navigates a menu whose cursor persists, probe the cursor and assert it.** A screen exiting through `CB2_ReturnToFieldWithOpenMenu` leaves the start menu **already open** with the cursor remembered; the spec pressed `Start` anyway, closing it, then drove `Down, Down, A` at a menu that was gone. Eight assertions went red **pointing at the save system**; the one that said *why* was a probe on `sStartMenuCursorPos` reading `1 == 3` (record 61 §5.1). **The number of Downs to a menu entry is not a property of the menu.**
- **Probe the menu, do not guess it.** `sCurrentStartMenuActions` read `01 02 04 05 06 07 08` in the party state, because `BuildNormalStartMenu` gates rows on flags and an overworld-stage count is not transferable (record 72 §7). **And where a mash must cross a screen that becomes interactive, use the button that advances but cannot commit** — `B` advances text and cannot select.
- **Real wall-clock durations ARE verifiable headlessly, because mGBA's emulated RTC ADVANCES during a run, tracking the host clock.** That was settled by measurement, not assumption — the rival reading (host clock sampled once at boot, derived from emulated cycles thereafter) was equally consistent with everything known and would have made the claim unverifiable; idling 40,000 frames watched the seconds march (record 60 §1). Since headless runs at roughly 60–100× realtime, **a frame-driven fake timer is structurally distinguishable from an RTC-driven one in a single run**: a real 30-second set measured 175,265 frames against the ≤1,801 a frame-driven countdown could structurally reach — a 97× margin — and the 60-second version scales the same discrimination ×2 (records 60 §1.1, 63 §2). Read the time by **deltaing two raw `RtcGetInfo()` reads**: it bit-bangs the hardware independently of `gLocalTime` (whose ~2-second lumpy refresh is an overworld polling artifact, not the RTC's resolution) and of the overworld entirely — and **guard the backward jump**, which otherwise underflows into ~4 billion seconds and completes any timer instantly (record 60 §1.2). The design lesson: with real durations affordable, **keep no test-only time path** — honesty is then defended by the design rather than by a `#define` a future session could quietly widen (record 60 §1.1).
- **Emulator throughput tracks the emulated workload** (~4,250 frames/s in the overworld, ~6,150 in a menu). Size a wall-clock timeline by the **seconds** it needs, then over-provision frames: a real 30-second set measured **177,945 frames** against the **1,801** a frame-driven timer could structurally reach, a 98× margin (record 61 §3.2). **Every leg of a scripted walk should end against something** — a wall, furniture, a map edge; a move that stops in open space is a number that will drift. Dialogue counts must be exact.
- **Latch the harness's own finish block.** An unlatched `if (frame >= TOTAL_FRAMES)` ran on every frame after the finish line, calling `emu:screenshotToImage()` + `img:save()` hundreds of times and corrupting the heap; that call works for **one** invocation and not for a loop (record 55 §4). Log level: `-l 7` hides `console:log`; the harness defaults to **`-l 8`**; `-l 15` adds a DMA torrent.

## 14. Fixtures obey the same rule as the product

**A fixture must not produce a state the system cannot.** Four instances, in increasing order of how badly the wrong answer would have read:

1. A fixture repurposed an object without updating one field the real path writes; the result rendered as a plausible screen saying something false, with every assertion green (record 73).
2. A fixture skipped the naming half of catching a Pokémon, so a green 12-of-12 run produced *"Congratulations! Your **Torchic** evolved into Squataur!"* The species really had changed; the nickname had not, and the engine is correct to keep a chosen nickname. **Not a bug in the feature — a misleading picture in the build record, with no wrong number in it** (record 72 §5).
3. A boot shortcut skipped the naming screen, leaving `playerName` as `0000000000000000` — **eight space glyphs and no `EOS`** in this charmap — so the name renders as blanks and the string is unterminated. Selecting that menu row overwrote `gMain` and wedged the game (record 68 §6.2; see [[engine-defects]] E2).
4. **Worst: a fixture whose omission made a repair mechanism appear not to exist.** A hook called `SetUpReflection` without setting `objectEvent->hasReflection`, which the real path sets in the same breath, so the callback bailed on its first line and **the repair branch never ran**. Reported as measured, that is *"the engine does not repair it"* — a finding both false and **much more alarming than the truth** (record 80 §4.1).

> **A surprising result should prompt a check of the fixture before a headline.**

**A shortcut that skips a setup step inherits every default that step would have set**, and the ones that bite are *zero-valid*. **When you skip a screen, list what that screen writes and write it yourself.** And **a playtest of one artifact is a test of every artifact that shares its scaffolding** — the same boot shortcut was in `make_studio.py`, which had shipped a Start-menu row that crashes it because nobody had opened that row (record 68 §6.2).

## 15. Operator knowledge must be executable, not remembered

The migration audit (record 82) found three pieces of knowledge the harness required and did not hold:

- **F1.1 — `symbols_from` was documentary, not executable.** 77 specs declared it and `verify_hack.py` **ignored the key**; a spec run without `--rom` silently resolved the *engine* ROM, failing loudly only where a savestate's sha guard caught it. **Fixed: all 114 specs declare a fork or `"engine"`, enforced by a test, and `--rom` resolves from it** — one missing sentence in twelve files that closed three symptoms at once (wrong-ROM runs, two batch-runner artifacts, seven `SystemExit: 2` errors in a fresh clone) (record 82 §3.3, §2.4).
- **F1.2 — `--rom` resolved relative to the *engine*, not the cwd.** Absolute paths were mandatory and nothing said so. **F1.3 — a counterfactual's expected outcome is not in its spec**: `--expect-fail` is an operator flag and the convention lives in the filename, so **`expect_fail` belongs in the spec**, letting a batch run judge correctness rather than merely record outcomes (record 82 F1).
- **F2 — there was no batch runner.** Per-spec cost measured at **~2.2 s**, so a 114-spec slate is minutes — **cheap enough to be a routine gate rather than an occasion** (record 82 F2). **F3 — one fork was unbuilt and nothing noticed**, because the guard asserted the *directory* exists; `fixtures.json` now lists every fork, the wall it walks into, and its regenerate command, so a listed fork that is absent **skips with that command** while an unlisted name still fails. **A typo and an un-regenerated fixture are different things** (record 82 F3, §5.4).

**The baseline records the OBSERVED outcome of every spec rather than a judged pass/fail**, and later phases reproduce that list element-for-element — diff-the-list applied to a whole slate, robust to F1.3 precisely because it judges nothing. Phase 0: **114 specs, 1,472 s, 92 PASS / 18 FAIL / 4 ERROR**, of which 13 are counterfactuals failing by design, 4 stale savestates, 2 runner ignorance (both PASS when given the right ROM), 2 ordering, and **1 honestly recorded as UNDETERMINED** because no doc records its expected outcome (record 82 §1.5).

**The savestate gap.** **77 of 114 specs cannot run on a fresh clone**, because `.ss1` states are gitignored (verbatim RAM snapshots of a Nintendo-derived ROM, build-specific, regenerable) and only sidecars travel; 26 more need a fixture fork built; **11 run cold**. The hard half: **regenerating a state produces a different starter Pokémon**, since the boot RNG is RTC-seeded. Hence `doctor` must detect and offer to regenerate, and **pinning the boot RNG seed is the highest-value outstanding item** — it would turn savestates from irreproducible artifacts into derivable ones (record 82 §4.5).

**The backup is part of the verification chain.** The fork is gitignored, so the patch is the **only tracked copy of the game's code** (record 82 F4, F5, §3.4, §4.4). **D1** — build outputs entered the patch as content, fixed by asking the engine's own git what it considers a build product (`git check-ignore --stdin`); **deriving the list beats maintaining one**. **D2** — the patch was written **before** its assets were staged, so a crash left a backup that looks present and is not internally consistent; fixed by writing the patch last, because **a tool whose purpose is not losing data must not have a failure mode that writes a wrong one**. **F5** — the fork held a one-character edit the patch did not, made 8 minutes after export: **functionally harmless, and that is the point**, since regenerating the fork from the patch would have destroyed it silently. Therefore **export after every green build**, and **`--check` belongs in the session-start ritual** — it is the only thing that can see this class. **And `--check` itself compared CLOCKS**: 296 differing lines were all `diff` mtime headers, content byte-identical, so the guard whose job is detecting drift reported drift that did not exist, **in alarming words** — and the identical message had been *real* earlier the same day. **The same words, twice in one day, for opposite reasons**, which is why the fix was to diff the lines rather than trust either verdict. **F9 — a protection that lives in a file you are not moving is a protection you lose**: `git subtree split` carries the child's `.gitignore` and knows nothing about the parent's, so `*.sav`, `*.elf`, `build/`, `.DS_Store` and `.pipeline/` silently stopped existing as rules, and the first commit would have added **player save data out of a Nintendo-derived ROM, permanent once in history** — caught by a `git add -A --dry-run`, not by any rule (record 82 §4.5b).

**Determinism.** `make clean` + rebuild + `make syms` reproduced **both artifacts byte-identically** (ROM `42c8d33c…`, 33,554,432 B), proving the toolchain embeds no timestamp and no build-path bytes — so sha256 equality is a valid instrument, assumed for months and now evidenced (record 82 §1.4). The migration then rebuilt the game **in a different repository, from a fresh engine clone, with the patch as its only source of code, using rewritten tools**, and got the same bytes; the fresh engine clone built to the sha recorded months earlier; the patch replays at **122 files byte-identical** (record 82 §4.1). **A generator that replays byte-identically is what earns the word "disposable"** — until you have replayed it, "the tool can rebuild this" is a hope. See [[build-system]].

## 16. The checklist

1. Does the spec have **any** assertions? 2. Does it have a **counterfactual that actually fails**, pointed at something sensitive enough to hear the alarm? 3. Have you **written the survivor bound down** (every assertion the spec's own `why` labels weak) and diffed actual survivors against it as a **subset** test? 4. Is the positive result distinguishable from its **most likely failure mode**, or do you need the opposite **run**? 5. Is there a probe asserting **the thing under test ran**, exactly once? 6. Is any value you care about **one frame long**? Latch it. 7. Did you **look at a picture** of every changed state, and the states next to it? 8. Did you check the **instrument** — its `main()`, build flags, exit path — before concluding the subject is at fault? 9. Did the **fixture** produce a state the real game can produce? 10. Does `make check` diff clean **by name**, with `TEST_SKIP_IS_FAIL` on? 11. Did the **backup replay** byte-identically, and did anyone **play it**?
