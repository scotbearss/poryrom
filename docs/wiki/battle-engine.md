# battle-engine

**What this page is for.** The battle subsystem as it actually is at this pin: the script VM and its
eight-slot call stack (walked off on purpose and measured), how a move is defined and what it costs to
add one, the save-block pointer re-roll that fires at every battle start and what it does to a probe
that caches an address, and the trainer AI's flags, scoring model and exactly where it cheats. Read it
before adding a move, an ability, or anything that runs in battle. Nearly every wall in here is
**silent**, and one of them erases the evidence of its own overflow.

Naming, because three plausible symbol names are wrong at this pin: it is **`gMovesInfo`** (not
`gBattleMoves`), **`gBattleScriptingCommandsTable`** (plural), and there is **no
`gBattleScriptsForMoveEffects`** — that name appears nowhere (record 39).

---

## 1. Three layers, and only the middle one is scripted

| Layer | Lives in | Decides |
|---|---|---|
| Turn state machine | `src/battle_main.c`, the `gBattleMainFunc` chain | whose action runs, order, turn end |
| **Script VM** | `data/battle_scripts_1.s` + `asm/macros/battle_script.inc` + `src/battle_script_commands.c` | what sequence of events a move produces |
| Calculation core | `src/battle_util.c` | how much — damage, accuracy, speed, type, abilities |

The calculation core is **not** scripted; scripts reach it through single opcodes (`damagecalc`,
`critcalc`, `accuracycheck`).

## 2. Battle scripts

`data/battle_scripts_1.s` (**10,066 lines**) is **GNU `as` source**, not a bespoke format — it
`#include`s C headers, so `ABILITY_LIMBER` and `B_WEATHER_SUN` are assembler expressions. It is built
through a four-stage pipe (`preproc` → `cpp` → `preproc -ie` → `as`, `Makefile:443`), which has a
consequence worth writing down: **`include/config/battle.h` is visible inside battle scripts and they
branch at assemble time.** A config flip changes emitted byte-code, not just C behaviour. See
[[build-system]].

Everything lands in `.section script_data`. Scale: **509 macros**, 1,450 `BattleScript_*` labels
(1,026 exported), 838 `extern` declarations in `include/battle_scripts.h`.

### The opcode space is FULL

`void (* const gBattleScriptingCommandsTable[])(void)` (`src/battle_script_commands.c:600-858`) has
**exactly 256 entries, `0x00`–`0xFF`, no holes**. Ten are explicit `Cmd_unused*` placeholders, so
**246 opcodes are live**. Expansion's own tutorial says *"the battle engine upgrade has exhausted all
battle script command IDs"*. **A new engine primitive therefore has to be a `callnative`, not a new
opcode** (§5).

### One opcode per call, and the VM stalls itself

```c
EWRAM_DATA const u8 *gBattlescriptCurrInstr = NULL;          // src/battle_main.c:176
gBattleScriptingCommandsTable[gBattlescriptCurrInstr[0]]();  // five sites + battle_util.c:8298
```

There is **no loop and no `switch` on a program counter** — exactly one opcode executes per call,
driven per frame from `BattleMainCB1` and gated on `gBattleControllerExecFlags == 0`, so the VM stalls
automatically while a controller is mid-animation or mid-message.

Arguments are packed straight after the opcode byte with **no alignment padding** (`CMD_ARGS`,
`include/battle.h:22-40`); `nextInstr` is a zero-length array at the struct tail, so a command advances
with `cmd->nextInstr` and never hard-codes its own length.

Two escape hatches: **`various battler, id`** (`0x76`) — 143 ids declared, **140 implemented**, and
ids 43, 45 and 116 **fall through the switch silently** because their behaviour moved to `callnative`
helpers. And **`callnative func`** (`0xFF`) — 61 `BS_*` helpers, never written literally in scripts;
friendly macros wrap it.

## 3. THE CALL STACK — 8 deep, push unchecked — **SILENT AND SELF-ERASING**

```c
struct BattleScriptsStack        // include/battle.h:403-407
{
    const u8 *ptr[8];
    u8 size;
};
```

**There is no named constant.** The depth is the bare literal `8`. Accessors live at
`src/battle_util.c:1197-1211`, reached through `gBattleResources->battleScriptsStack`:

```c
void BattleScriptPush(const u8 *bsPtr)  { ...->ptr[...->size++] = bsPtr; }        // UNCHECKED
void BattleScriptPushCursor(void)       { ...->ptr[...->size++] = gBattlescriptCurrInstr; }
void BattleScriptPop(void)              { if (...->size != 0) ... }               // checked
```

`Cmd_call` pushes `cmd->nextInstr` (resume *after* the call); `BattleScriptPushCursor` pushes
`gBattlescriptCurrInstr` (resume *at the same command*, which is how an interrupting sub-script such
as an ability pop-up re-runs the command it interrupted). C code overwhelmingly uses the cursor form.
The stack is zeroed **once per turn** at `src/battle_main.c:5345`, which is what keeps normal play
inside the budget.

### The measured baseline: **peak depth 1 of 8**

Record 78 instrumented all three accessors with a **latched** peak, a sampled current size, and a
**total push count** — the last because without it `peak == 1` cannot be told apart from *the
instrument never ran*. Cost: 12 bytes of IWRAM.

| Three turns of a plain wild battle | |
|---|---:|
| Peak stack depth | **1** of 8 |
| Pushes during the run | 5 |
| Samples of current depth at 1 | 25 of 478 |
| Samples of current depth at 0 | 453 of 478 |

**The sampled depth was non-zero in only 25 of 478 samples** — the stack's occupancy is transient. A
sampling probe alone would have under-reported the peak or missed it; the latched high-water mark is
what makes the number trustworthy. See [[verification-discipline]].

**The multi-hit loop is a TRAMPOLINE, not a nest.** `MOVEEND_MULTIHIT_MOVE` really does
`BattleScriptPush(GET_MOVE_BATTLESCRIPT(gCurrentMove))` for every strike after the first — and then
jumps to `BattleScript_FlushMessageBox`, which is `flushtextbox` / `return`, two commands away, and
`Cmd_return` is a bare `BattleScriptPop()`. **Population Bomb at `strikeCount = 10` costs one slot of
eight, ten times over.** Confirmed empirically: a five-strike move leaves `depth_peak` at exactly 1,
the same as a one-hit move.

**The honest bound:** that baseline is one wild battle between two low-level Pokémon using plain
damaging moves. Ability pop-ups, held-item activations, status, mid-battle switch-ins, doubles and
trainer battles are **unmeasured**, and pop-ups are precisely what `BattleScriptPushCursor` is for. The
claim is *"a plain wild battle peaks at 1"*, not *"ordinary play peaks at 1"*.

### The ninth push, built on purpose and photographed

Record 39 recorded the overflow from a **negative grep** — *"I did not find a guard"* — which it
flagged as weaker than reading one. Record 78 converted it into an observation with a control arm
(7 pushes) and a fall arm (9), driven from C because `Cmd_call`'s entire body *is* `BattleScriptPush`.

| | control (7) | fall (9) |
|---|---:|---:|
| pointer pushed | `0825b771` | `0825b771` |
| `ptr[7]` — last legal slot | `00000000` | `0825b771` |
| **`ptr[8]` — which IS the `size` field** | `00000007` | **`0825b709`** |
| `size` as the engine reads it | 7 | **9** |

> **The prediction was wrong in the direction that matters.** Record 78 predicted `size` would come
> back as the pushed pointer's low byte + 1 — a number in the hundreds, conspicuous the first time
> anyone looked. It reasoned as if the increment happened after the pointer store. This toolchain
> emits the pointer store first and `size = 9` second, so **the counter wins the four bytes it shares
> and the POINTER is what gets mangled**: `0825b771` in, `0825b709` out — an address 104 bytes away,
> pointing into the middle of battle-script bytecode. **`size` reads a perfectly ordinary 9**, which
> looks like nothing at all.

**And the consequence is LATENT.** A screenshot arm that left the corruption in place showed the
battle carrying on completely normally, because the move's own `call … return` pushes and immediately
pops `ptr[9]` — a matched pair past the end of the array is self-consistent, so the VM never notices.
What actually happened is four bytes written **past a heap-allocated struct**, into whatever the
allocator put next. **A failure you cannot photograph is not a failure you do not have.** The
prediction is left standing uncorrected in record 78 on the principle that a prediction you edit after
the fact was never a prediction.

The cliff device was stripped from the fork once it had answered its question; only the measurements
survive. See [[engine-defects]] for the four confirmed defects, none of which is this — the overflow
is upstream behaviour, not a defect this project filed.

## 4. Script-visible RAM offsets — the highest-consequence hazard, now compiler-checked

Battle scripts touch engine RAM through **absolute addresses computed from hand-written struct
offsets** (`include/constants/battle_script_commands.h:4-42`):

```c
#define sMOVEEND_STATE   (gBattleScripting + 0x14) // moveendState
#define sMOVE_EFFECT     (gBattleScripting + 0x2E) // moveEffect
```

Insert one field into `struct BattleScripting` and every macro below it is wrong. **Nothing said so**
— record 39 grepped `src/` and `test/` and found no `STATIC_ASSERT` or `offsetof` binding the two.

Record 78 closed it. `check_battle_offsets.py` generates a header pairing **38 macros to 38 fields**
(read out of the trailing `// field` comments), and — the design point — **Python does the mechanical
transcription while the compiler computes the offsets**, because only the compiler knows this
toolchain's alignment rules. The tool also removes the second copy of the number:

```c
#define sB_ANIM_TURN_OFS   0x18 // animTurn
#define sB_ANIM_TURN       (gBattleScripting + sB_ANIM_TURN_OFS)
```

The constant the assertion tests **is** the constant the scripts assemble against, so they cannot
disagree. Cost **0 bytes** (`STATIC_ASSERT` is `typedef char id[1]`). Every field in the struct is
addressed by a macro; none is unreached.

**The counterfactual is the finding.** Inserting one `u8` after `battler` — the smallest possible
version of the hazard — fails **26 of 38 assertions, and exactly the right 26**: the first is the
first macro at or past the insertion point, running unbroken to the last, while **the twelve below the
insertion stay green**. Without the guard, `sSTATCHANGER` reads `statAnimPlayed` and `sMOVE_EFFECT`
straddles two fields while a third of the subsystem keeps working perfectly. **A fault that breaks two
thirds of a subsystem and leaves the rest correct is the hardest thing there is to diagnose from
behaviour** — which is why it belongs in the compiler and not in a checklist.

## 5. How a move is defined

Data lives in `src/data/moves_info.h` as `struct MoveInfo` rows (`include/pokemon.h`). Rows are
**config-conditional expressions, not constants** — Thunder Wave's `.accuracy` is
`B_UPDATED_MOVE_DATA >= GEN_7 ? 90 : 100`, and `GEN_LATEST` is `GEN_9` at this pin, so it is 90.

Bitfield widths, every one of them a silent truncation waiting to happen:

| Field | Declaration | Ceiling |
|---|---|---|
| `power` | `u16 power:9` | 511 |
| `priority` | `s32 priority:4` | 4-bit **signed** |
| `strikeCount` | `u32 strikeCount:4` | 15 |
| `numAdditionalEffects` | `u32 numAdditionalEffects:2` | **3** |

**`accuracy == 0` means "never miss", not "always miss".** And the expansion's own tutorial is wrong
about additional effects: it claims "up to 15", the field is 2 bits, and the source comment reads
`// limited to 3 - don't want to get too crazy`. Its own 6-effect example would truncate.

**`EFFECT_*` and `MOVE_EFFECT_*` are different namespaces.** `EFFECT_*` (352 values) is the **script
selector**, indexing `gBattleMoveEffects[]` → a `BattleScript_*` via `GET_MOVE_BATTLESCRIPT(move)`.
`MOVE_EFFECT_*` (79 values) is a status-or-stat **outcome** applied by `SetMoveEffect`. In
`ADDITIONAL_EFFECTS`, `chance == 0` means **primary** (unblockable by Shield Dust, undoubled by Serene
Grace); any non-zero chance, **including 100**, means secondary and is therefore nullified by Sheer
Force.

The 352 effects resolve to 281 distinct scripts; `BattleScript_EffectHit` alone serves **66** of them
— the plain damaging moves special-cased entirely in C.

### Adding a move: three tiers

- **Tier 0 — no new effect at all.** Damage plus an existing status/stat/flinch outcome is
  `.effect = EFFECT_HIT` and one `ADDITIONAL_EFFECTS({...})` row. Zero scripts, zero C.
- **Tier 1 — a new effect, no new primitive. Five files:** the enumerator (before
  `NUM_BATTLE_MOVE_EFFECTS`), the script, an `extern` in `include/battle_scripts.h`, the
  `gBattleMoveEffects` row, and the move's `.effect`. Optionally a string and an animation.
- **Tier 2 — a genuine engine primitive.** A `BS_*` function plus `NATIVE_ARGS` plus a friendly macro.
  **The macro's operand order must match the `NATIVE_ARGS` field order exactly and nothing checks
  this** — record 39 calls it the single unguarded contract in the VM.

**Two silent failures:** adding the enumerator without the `gBattleMoveEffects` row compiles to a
`NULL` `.battleScript` and **jumps to address 0 at runtime** — a crash, not a build error. And **find
the call sites, do not list them**: record 69 hand-enumerated the tables a new Poké Ball needed a row
in and got 6 of 9, two of the misses being arrays with an *implicit* size where a missing row makes
every read past that index out of bounds. Walk a peer's rows, then sweep peer-rows against new-rows
across the tree. See [[walls-and-budgets]].

**Adding a regular move renumbers every Z-move and Max move**, because the Z block is defined relative
to `MOVES_COUNT`. That is benign only because a mon stores `u16 move:11` and cannot hold one — unlike
[[save-system]]'s item-id case, where the bag stores a raw id and the same shape of renumber
invalidated every save. A move-count bump also silently grows `gBardSounds_Moves[MOVES_COUNT][…]` by a
zero row.

**Multi-hit: drive `gMultiHitCounter`, not `strikeCount`.** The data row's field is 4 bits and would
truncate a computed count at 16 with no error; `gMultiHitCounter` is a plain `EWRAM_DATA u8`
(`src/battle_main.c:175`). Record 78's LAST REP took that route, so the 4-bit field is never in the
path — **a question answered by avoidance rather than by test, which is the better outcome.**

**A worked example.** LAST REP (record 78) is a Fighting physical move, power 15, that strikes once
plus once more per half hour of banked training, capped at five — recomputed at use time, stored
nowhere, **0 save bytes**. Four arms: untrained → 1 hit, 90 min → 4, 150 min → **5 not 6** (the clamp
arm, because an unexercised clamp is where an off-by-one lives), and **`wrongcat`** — 90 minutes of the
*wrong* training category → 1 hit. `wrongcat` is the load-bearing arm: without it, *training makes it
hit more* is equally consistent with *any training makes it hit more*, and no amount of re-running the
other three would tell them apart.

## 6. The save-block pointer re-roll at battle start

```c
void SetSaveBlocksPointers(u16 offset)              // src/load_save.c:79-87
{
    offset = (offset + Random()) & (SAVEBLOCK_MOVE_RANGE - 4);   // 128 - 4 = 0x7C
    gSaveBlock2Ptr     = (void *)(&gSaveblock2)     + offset;
    gSaveBlock1Ptr     = (void *)(&gSaveblock1)     + offset;
    gPokemonStoragePtr = (void *)(&gPokemonStorage) + offset;
}
```

A 4-aligned offset in `[0, 124]` — **32 possible placements**, seeded by the sum of the trainer-ID
bytes plus `Random()`. `SaveBlock3` is **not** offset (`gSaveBlock3Ptr` is `IWRAM_INIT` to
`&gSaveblock3` and never reassigned), so it is the one block a harness may read single-indirect. There
is no `SaveBlock3ASLR`, and in the three wrappers that do exist the `aslr[]` array is the **trailing**
member — the block slides *forward* into slack reserved at the end.

**It fires at every battle start.** `CB2_InitBattle` (`src/battle_main.c:437-440`) calls
`MoveSaveBlocks_ResetHeap()` — guarded by `if (!gTestRunnerEnabled)`. Record 78 settled whether that
guard is live without running anything: the flag is `__attribute__((weak)) const bool8 = FALSE` in
`.rodata`, so its byte is a static file offset in the `.gba`, and it reads **0**. The re-roll runs in
the ROM we ship. (Map load hits the same function via `ResetMirageTowerAndSaveBlockPtrs`.)

`MoveSaveBlocks_ResetHeap` also **destroys and rebuilds the heap** and generates a brand-new
`encryptionKey` from `Random32()`. Nothing may hold an allocation across that boundary.

### The consequence for probes — **SILENT**

**Every read through SaveBlock1/2 requires double indirection**, re-done on the frame it is used.
Caching a save-block address or the encryption key across a battle transition or a map load yields
stale addresses and a stale key, and **the reads will not fault — they will silently return garbage**.
Entering a battle also consumes a `Random()` and a `Random32()`, so it **perturbs `gRngValue`**, which
matters to any seed-deterministic spec.

### Asserting that the re-roll fired: the key, not the pointer

> **"Assert the pointer moved" is a 31-in-32 coin flip dressed as a proof.** One of the 32 placements
> is where the pointer already was, so a correct run fails about once in thirty-two — and the
> counterfactual arm is a coin flip in the other direction.

The deterministic observable is four lines below in the same function: **`gSaveBlock2Ptr->encryptionKey`
changed**. Same event, same function, flake rate 1-in-2³² instead of 1-in-32. This is record 69's rule
— *a distribution you cannot bound is a threshold* — answered by **engineering the randomness out of
the claim** rather than widening a band around it. All four LAST REP arms assert it, which is how
record 67 §1.3's last harness gap closed; that list is now empty. See [[verification-discipline]].

The feature is the other half of the proof: LAST REP reads banked minutes **from inside a running
battle**, through the pointer the re-roll just moved, and the values came back exactly as seeded on
every arm — which is only possible if the code re-read the pointer.

## 7. Trainer AI

**At this pin the trainer AI is plain C, not a bytecode VM.** There is no `gBattleAICmdTable` and no
`battle_ai_scripts.s` in record 43's reading. It is `sBattleAiFuncTable`
(`src/battle_ai_main.c:62-96`), a 32-slot table of `s32 (*)(u32, u32, u32, s32)` with **only 14
non-NULL entries** — bits 0-9 and 28-31. **Bits 10-27 are NULL: those flags are pure conditional
gates read from inside other code, with no scoring function at all.** The in-repo tutorial
`docs/tutorials/ai_logic.md` is stale — its signature is wrong and its example flag collides with
`AI_FLAG_OMNISCIENT`.

### It cannot read your input

`HandleTurnActionSelectionState` computes the AI's move at `STATE_TURN_START_RECORD`, which *falls
through* to the state that first prompts the player (`src/battle_main.c:4200-4213`), caching the result
in `gBattleStruct->aiMoveOrAction[battler]` and replaying it later. **Input reading is not merely off
by default — there is no code path for it.** Move prediction is one unconditional, flag-free line:
`predictedMoves[battler] = gLastMoves[battler]` — the AI assumes you will repeat your last move, which
is public information.

### The scoring model

`AI_SCORE_DEFAULT` is **100**. Flags run **bit 0 → bit 31 in order**, each over all four move slots, so
scoring is sequential and order-dependent (`AI_CheckBadMove` always before `AI_CheckViability`,
`AI_DynamicFunc` always last). A move at zero PP or already at score ≤ 0 is **latched to 0 and skipped
by every remaining flag** — scores are absorbing at zero.

Selection is `return consideredMoveArray[Random() % numOfBestMoves];`. **That is the only randomness in
singles move selection — there is no "n% chance to blunder"; the AI always plays its argmax and breaks
ties uniformly.** The realistic band is roughly 80…115, and since the canonical penalty is `-10`
(261 occurrences of `ADJUST_SCORE(-10)` in one file), **a single +1 converts a coin flip into a
deterministic pick**.

The one place absolute values matter: if **all four** moves score ≤ 93 (or ≤ 95 with
`AI_FLAG_CHECK_VIABILITY`), the mon is flagged for a switch. One `-10` on every move trips it.

### The flags

24 are defined; `AI_FLAG_COUNT` is 20, so **bits 20-27 are free for new ones**.

| Class | Flags |
|---|---|
| **Scoring functions** (bits 0-9) | `CHECK_BAD_MOVE` (~1,900 lines, the largest), `TRY_TO_FAINT`, `CHECK_VIABILITY`, `SETUP_FIRST_TURN`, `RISKY`, `PREFER_STRONGEST_MOVE`, `PREFER_BATON_PASS`, `DOUBLE_BATTLE` (auto-set for any double), `HP_AWARE`, `POWERFUL_STATUS` (**+10, which outranks a KO at +6**) |
| **Gate-only** (bits 10-19) | `NEGATE_UNAWARE` (a *handicap*), `WILL_SUICIDE`, `PREFER_STATUS_MOVES`, `STALL` (**source-annotated `TODO not finished` — unsupported**), `SMART_SWITCHING`, `ACE_POKEMON`, **`OMNISCIENT`**, `SMART_MON_CHOICES`, `CONSERVATIVE` (another handicap — under-estimates its own damage), `SEQUENCE_SWITCHING` |
| **Hooks / scripted** (28-31) | `DYNAMIC_FUNC`, `ROAMING`, `SAFARI`, `FIRST_BATTLE` |

Flags reach a trainer through `src/data/trainers.party`'s `AI:` line (the `AI_FLAG_` prefix is added
for you) compiled by `trainerproc` into `src/data/trainers.h`. **Of 855 vanilla trainers, 640 carry
`Check Bad Move` and nothing else**, and nothing past bit 9 is used by any vanilla trainer — that
entire span is dead weight in the stock game and exactly the surface a difficulty hack lights up.

There is **no AI difficulty scalar**: nothing scales flags, scores, or trainer levels.

### Damage simulation, and where it cheats

`AI_CalcDamage` calls the same `CalculateMoveDamageVars` the engine uses, with the real defensive
stats, but with **believed** abilities and items and a **fixed 93 % roll** (the 9th of the 16 real
rolls 85…100) applied *after* the whole modifier chain where the engine applies its random factor
*inside* it — so it is **not bit-identical to any single real roll**; the ordering difference is
certain, the magnitude is not. `.minimum` is always the 85 % floor, so `TRY_TO_FAINT` only rewards a
**guaranteed** KO while `PREFER_STRONGEST_MOVE` acts on the expectation and will commit to a KO a low
roll misses.

**What it knows with no flags at all:** your exact current and max HP (you only see a bar), your exact
stats, your **true held item id**, and your trapping ability. Your moveset is filtered to moves you have
used; abilities and unseen party mons are not known. **`AI_FLAG_OMNISCIENT` is the cheat switch and it
is global rather than per-battler** — one omniscient opponent in a double makes both omniscient, with
the player's whole bench pre-loaded at battle start. `SMART_SWITCHING` and `SMART_MON_CHOICES` are
grey: their switch-in evaluation peeks at unrevealed moves. Accuracy and crits have **no
side-dependent branch anywhere** — record 43 found no forced-miss or guaranteed-crit mechanism
favouring the AI.

## 8. Still unverified

- **The stack overflow's downstream consequence.** The write past `ptr[7]` is measured; what it
  corrupts on the heap, and whether any unwind pattern surfaces it, is not.
- **Stack depth outside a plain wild battle** (§3).
- **What an over-wide `ADDITIONAL_EFFECTS` does** — hard error, warning, or silent truncation — is
  unknown; only the bitfield width is established.
- **Whether any save-visible structure holds a Z-move or Max-move id.** A mon's `move:11` cannot;
  recorded battles and Frontier data have not been read.
- Record 39 did not read `AbilityBattleEffects` (2,274 lines) in full — grep the phase you intend to
  extend rather than trusting its per-phase table as exhaustive.

---

**See also:** [[verification-discipline]] · [[save-system]] · [[walls-and-budgets]] ·
[[engine-defects]] · [[build-system]] · [[audio]] (cries and move SFX fire from battle scripts) ·
[[art-pipeline]] (back sprites and shared palettes — a battle is where they show) ·
[[maps-and-tilesets]] · [[dialogue-voice]]
