# Walls and budgets

**What this page is for.** Every measured hard limit of pokeemerald-expansion (`expansion/1.9.4`, `2e65627`) on GBA hardware, in one place, with the observable symptom of hitting each one. The organising fact is that **most of these walls are silent**: the engine does not assert, log, or crash — it produces a plausible artifact (a flawless meadow you cannot walk in, an NPC in someone else's colours, a counter reading a perfectly ordinary 9). Anything marked 🔇 fails without any wrong number appearing anywhere, and can only be caught by a static check that runs *before* the build, or by a person looking at a picture. See [[verification-discipline]] for why a probe suite cannot see this class, and [[engine-defects]] for the walls that turned out to be upstream bugs.

Every fact is cited to the record that established it. Records are immutable; where a later record corrected an earlier one, this page carries the corrected value and names both.

---

## 1. Field and map walls

### 1.1 Map size — `(w+15) × (h+14) ≤ 10240` words 🔇

`InitMapLayoutData` fills `sBackupMapData` with `MAPGRID_UNDEFINED` **unconditionally**, sets `gBackupMapLayout.map`, `.width` and `.height` **unconditionally**, and only *then* tests the ceiling. That ordering is the entire reason the failure is invisible: everything a debugger looks at first is correct on a broken map.

Measured, same run, same probes (record 68 §3):

| | `CliffLegal` (10,205) | `CliffVoid` (10,270) |
|---|---|---|
| `gBackupMapLayout.width` / `.height` | 65 / 157 | 65 / **158** — both *correct* |
| `sBackupMapData[w*7+7]` | `0x3601` | `0x03FF` |
| player y after 420 frames of Down held | 12 → **39** | 12 → **12** |

- **It is a WALL, not an empty room.** `MapGridGetCollisionAt` returns `TRUE` for `MAPGRID_UNDEFINED`, so every tile is impassable and the player cannot take a single step in any direction.
- **And the player still TURNS.** Turning writes `facingDirection`, not `currentCoords` — so input is accepted, the sprite responds, the menu opens, and only *translation* is refused. **A player reads that as a wall, not as a broken game.** No coordinate probe could have found this; it took someone playing it.
- **It renders as the map's OWN BORDER BLOCK.** `MapGridGetMetatileIdAt` substitutes `GetBorderBlockAt(x, y)` for the undefined value, and `DrawMetatileAt` goes through that same accessor. Ours read as solid black only because an indoor border is black. **Give a map an outdoor grass border and blow the ceiling, and it boots into a flawless, uniform, entirely walkable-looking meadow you cannot walk in.** Nothing about the picture says "error" — which is why the screenshot rule is not sufficient here and a static check before the build is.
- 🔇 **Second consequence, not on the original slate:** `AreCoordsWithinMapGridBounds` tests against `.width/.height`, which are set *before* the ceiling test. On a 65×158 void map that is 10,270 words over a 10,240-word buffer, so the last **30 words / 60 bytes** of the coordinate space the engine certifies as in-bounds lie past the end of the array — and what sits immediately after `sBackupMapData` (`0x02005650`) is `gMapHeader` (`0x0200a650`) and `gCamera`. `MapGridGetBlockAt` would **read** them; `MapGridSetMetatileIdAt` would **write** them, starting with a pointer. A write-out-of-bounds surface opened by a **pure data edit**, no C required. **Status: static, not observed** — the player cannot walk to the far corner of a map he cannot walk in (record 68 §3.4).

`check_map.py` catches it statically and has been judged against real data: **3 FAIL over 522 maps, all three ours, `CliffLegal` at 10,205 clean** — a checker that fires on the boundary is a checker you learn to ignore. `new_map.py` refuses to write an oversize map at all, behind an `--allow-oversize` gate that says out loud what you are giving up.

### 1.2 Object events — 16 slots, **15 NPCs** 🔇

`OBJECT_EVENTS_COUNT` is 16, and `InitObjectEventsLocal` runs `ResetObjectEvents()` → `InitPlayerAvatar()` → `TrySpawnObjectEvents()`, so **the player takes slot 0 before a single template is considered**. The budget for map objects is therefore **15**, counted in a 20×17 **spawn window**, not per map.

> **The 16th NPC you place is the first one that does not appear.** Record 67's table said "16 slots, the 17th is silently ignored" — right about object events, misleading about NPCs, which is how a map author counts.

**The victim is decided purely by position in the template list**, and that is what makes it a budget rather than two broken templates: the same 17 templates at the same coordinates, with the two scientists moved from the back of the list to the front, lose **two kids instead** (record 68 §4.2).

`events` per map are capped at 255 each (all four counts are `u8`) — far above the spawn limit, so never the binding constraint.

### 1.3 Tilesets and metatile behaviors

| Wall | Value | What hitting it looks like | Record |
|---|---|---|---|
| **Metatiles per tileset pair** | 512 + 512 | `MB_INVALID` past 1024. | 67 (cites 47) |
| **`gTileset_General` occupancy** | **512 / 512 — already full** | Any genuinely new general-purpose metatile needs a **secondary tileset**. There is no codegen path for a new tileset — `new_map.py --dump-layout` derives from existing layouts and cannot help. This is the binding constraint on outdoor map authoring. | 67 (cites 51) |
| **Triple-layer metatiles** | not supported at any setting | `NUM_TILES_PER_METATILE` is 8. `METATILE_LAYER_TYPE_*` is a different feature and is the thing usually mistaken for it. | 67 §3.D |

**Metatile behavior ids: 240 of 240 defined, zero free** 🔇 (record 77 §2.1, §7.1a). `NUM_METATILE_BEHAVIORS` is `0xF0` and the highest defined id is `0xEF`. A new behavior is a **reclaim, not an append** — and a reclaimed slot carries luggage in two different ways:

- **`sTileBitAttributes` is sparse and some "unused" slots carry live flags.** `[MB_UNUSED_05] = TILE_FLAG_HAS_ENCOUNTERS`, `[MB_UNUSED_6F] = TILE_FLAG_UNUSED | TILE_FLAG_SURFABLE`, verbatim. Reclaim the wrong slot and your climbing wall **spawns wild Pokémon**, or the player **Surfs up it**. Nothing errors and there is no wrong number on any screen.
- 🔇 **"Unreferenced in C" is not "unused in data."** A behavior id lives as the low byte of a `u16` in every tileset's `metatile_attributes.bin` — **binary files no grep will ever hit**. `MB_SECRET_BASE_WALL` (`0x01`) has *zero C references* and is painted in **52 layouts**. `MB_CAVE` (`0x08`) — zero references, **88 layouts**, and it carries `HAS_ENCOUNTERS`. `MB_SLOT_MACHINE` (`0x89`) — zero references, 1 layout. Reclaiming one changes what an existing tile *means* on shipped maps, and the first sign would be a player walking through a wall in a secret base nobody tests.

The census (`check_behaviors.py`, which decodes the binaries and resolves every layout **and border** through its own tileset pair) reads: 240 defined · 77 named `MB_UNUSED_*` · 160 referenced in C · 117 carry a tile-flag row · 158 declared in a tileset · 120 actually painted → **68 reclaimable, and 12 that a grep would have handed you.** The tool also expands the ten **two-sided range tests** in `metatile_behavior.c`, which name only their endpoints — `MB_BRIDGE_OVER_POND_LOW` is written nowhere and is accepted by two predicates because it falls inside a range — and **refuses to run at all** if it meets a comparison it cannot pair. *A census that can only over-report is safe; one that can under-report is worse than none.*

**Tilesets reference tiles they do not ship** 🔇 (record 77 §7.1b, §12.4). `gTileset_PokemonSchool`'s build rule emits **278** tiles; its window metatiles (529, 530, 537, 538 — used along the annex's whole back wall) reference secondary tiles **279-281**, whose cells are blank and truncated away by `-num_tiles 278`. In the shipped game those VRAM slots hold whatever the previously-loaded tileset left there. Appending new art at the *declared* count landed straight into the gap and rebuilt the annex with **its windows drawn as climbing wall** — right place, right tiling, correct palette, entirely deliberate-looking, `check_map.py` clean.

> **A declared count is a claim about what a thing SHIPS; the question you need answered is what it REFERENCES.** Derive the first free tile from the highest tile any existing metatile *references*.

`check_tilesets.py` pins the set — it is **four tilesets in the pin, not one**: `PokemonSchool` 278/281, **`Petalburg` 159 shipped / 307 referenced (a 148-tile gap)**, `Lavaridge` 450/456, `BattleFrontierOutsideEast` 508/511. These are **WARN with the pin named**, not suppressed like `check_map.py`'s vanilla quirks: a script-only warp is intentional and this is upstream's latent defect.

### 1.4 Field moves, movement and field effects

- **Field-move → badge-flag positional weld** 🔇 (record 77 §2.2, §12.5). `party_menu.c:3922`: `if (fieldMove <= FIELD_MOVE_WATERFALL && FlagGet(FLAG_BADGE01_GET + fieldMove) != TRUE)`. **Insert** a field move anywhere in the first eight and every later HM demands the next gym's badge — Cut starts asking for the Knuckle Badge and the screen says `CAN'T USE UNTIL NEW BADGE`, **a correct-looking, well-typeset refusal for a completely wrong reason**. Three further tables are index-parallel to the same enum (`sFieldMoves`, `sFieldMoveCursorCallbacks`, and the menu-action ids via `j + MENU_FIELD_MOVES`). **Appending is safe, and badge-free by construction** — which is why CLIMB needs no badge check at all. Demonstrated as a 2×2 of one tree differing in one `#define`: control `cut_index` 0 / tested flag **2151** (the Stone Badge the fixture held), cliff `cut_index` 1 / tested flag **2152**. Eight `STATIC_ASSERT`s now make it a compile error, verified in **both** directions.
- **`movementActionId` has no bounds check at either call site** 🔇 (record 77 §12.5). `gMovementActionFuncs[objectEvent->movementActionId][...]` is dereferenced with no range test (`event_object_movement.c:6330`, `:6336`) — the field VM does not fail safe the way the script VM does. Walked off on purpose with one id past the last real entry: it **commits, and it does not crash.** The two arms differ in **16,885 of 38,400 pixels** — the camera ends up somewhere else entirely — while the tick counter reaches the same 1,584 in both, so the engine is alive at the end of the fall. **What the garbage actually executes is not established.** *(The fixture's first version never fired at all: `ObjectEventSetHeldMovement` returns early when movement is overridden, so the bad id was never stored, while the probe at the top of that function counted the attempt and read 1. `ObjectEventForceSetHeldMovement` was the fix — a probe on a call site is not a probe on the effect.)*
- **`gFieldEffectScriptPointers` is not in constant order** 🔇 (record 77 §12.1). The table is indexed by `FLDEFF_*`, but at this pin it is transposed: `FLDEFF_TRACKS_SPOT` is 71 and `FLDEFF_TRACKS_BUG` is 72, while the table holds TracksBug at index 71 and TracksSpot at 72 — **and each row carries a comment naming the other one.** Upstream's, not ours, and the engine's own bug- and spot-type footprints have been swapped since this pin was cut. An append anchored on the *comment* lands one slot early and silently displaces its neighbour. **Assert `table index == <your constant>` after writing.**

More on tileset/behavior authoring in [[maps-and-tilesets]].

---

## 2. Sprite, palette and task walls

| Wall | Value | What hitting it looks like | Record |
|---|---|---|---|
| **OBJ palette slots** | **16, dynamic, first-fit** | 🔇 **The refused sprite is not dropped.** `LoadSpritePalette` returns `0xFF` when all sixteen tags are taken; `CreateSprite` assigns it to `oam.paletteNum`, a **4-bit bitfield**, so `0xFF` truncates to **15**. The NPC is drawn in full, in the right place, correctly animated, at the right priority — **wearing whatever palette 15 holds**. There is no wrong *number* anywhere in it. Victim chosen by **template list order**: reorder the list and the mis-coloured pair swaps. | 74 |
| ↳ measured baseline | **5 of 16**, not 12 | Stock outdoor overworld: weather ×2, player, `NPC_1`, `NPC_2`. **Record 67's "12 of 16 pre-committed; 4 NPC + 1 special" is wrong**, and so is its claim that every NPC palette costs a second bank for its reflection — `SetUpReflection` allocates **on demand** through the same allocator. | 74 §1.1 |
| ↳ the documented wall is **dead code** | — | The engine's own comment (*"two 'special' NPCs with competing palettes cannot be properly loaded at the same time"*) describes a system with **no callers**: `InitObjectEventPalettes` is uncalled, `sObjectPaletteTagSets` and `gReflectionEffectPaletteMap` are read only from inside uncalled functions, and `ObjectEventGraphicsInfo.paletteSlot` is **written in 36 data rows and read nowhere**. `PALSLOT_PLAYER` / `PALSLOT_PLAYER_REFLECTION` are dead for the same reason. Two "special" NPCs coexist fine. | 74 §1, 75 |
| ↳ why the wall is hard to reach | 15 + 1 = 16 exactly | Fifteen NPCs (the object-event budget) plus the player is *exactly* the palette table. **Indoors, nothing ever overflows.** The fixture had to be built **outdoors** so that weather — a claimant that is not an object event — would be in the room. Two budgets that nearly protect each other are still two budgets. | 74 §5 |
| **Sprites** | `MAX_SPRITES 64`; field worst case ~35 | `CreateSprite` returns the guard slot 64. | 67 (cites 42, 47) |
| **Tasks** | **16 slots, no error sentinel** | 🔇 Past 16 you silently get a handle to **task 0**. | 67 (cites 42) |

Sprite authoring, palette editing and the scale rules are in [[art-pipeline]].

---

## 3. Battle-engine walls

| Wall | Value | What hitting it looks like | Record |
|---|---|---|---|
| **Battle-script call stack** | **8 deep, push unchecked** | 🔇 The struct is `const u8 *ptr[8]; u8 size;` — **`ptr[8]` *is* `size`**. The ninth push runs `ptr[size++] = bsPtr` with `size == 8`; two stores race for the same four bytes and this toolchain emits **the pointer first, `size = 9` second**. So the **counter wins and the pointer is mangled**: `0825b771` in, `0825b709` out — an address 104 bytes off, pointing into the middle of battle-script bytecode. `size` reads a perfectly ordinary **9**. Nothing visible happens: the following `call`/`return` pair pushes and pops `ptr[9]`, which is self-consistent, so the VM never notices. It writes 4 bytes past `gBattleResources->battleScriptsStack` on the heap. **The consequence is latent.** | 78 §7b |
| ↳ record 78's own prediction | wrong | It predicted `size` would read *(low byte of the pushed pointer) + 1* — a number in the hundreds. Left standing rather than corrected, per this project's rule. A counter holding 347 announces itself; a counter holding 9 on an eight-slot array looks completely reasonable. | 78 §7b.2 |
| ↳ measured baseline depth | **1 of 8** | A plain wild battle peaks at **one slot**, over three full turns. The multi-hit path is a **trampoline, not a nest** — `MOVEEND_MULTIHIT_MOVE` pushes, jumps to `flushtextbox`/`return` two commands later, and `Cmd_return` is a bare `BattleScriptPop()`. Population Bomb (`strikeCount = 10`, the deepest shipped) costs **one slot, ten times over**. **Bound honestly:** this is one plain wild battle — ability pop-ups, held items, status, switch-ins, doubles and trainer battles are unmeasured, and `BattleScriptPushCursor` exists precisely for those. | 78 §4.1, §7a.2 |
| **`struct BattleScripting` field insertion** | shifts every hardcoded script offset | 🔇 The `s*` macros (`sMOVEEND_STATE`, `sSTATCHANGER`, `sMOVE_EFFECT` …) are hardcoded byte offsets. One `u8` inserted after `battler` (offset `0x17`) breaks **26 of 38** macros and leaves the twelve below it **green** — a fault that breaks two thirds of a subsystem and leaves the other third correct is the hardest possible thing to diagnose from behaviour. `check_battle_offsets.py` now generates `STATIC_ASSERT`s pairing all 38 macros to all 38 fields; cost **0 bytes**. | 78 §5.1 |
| **`strikeCount:4`** | 15 hits max | 🔇 A 4-bit bitfield in `gMovesInfo`; a training-derived strike count would truncate silently. Routed around by driving `gMultiHitCounter` (a plain `EWRAM_DATA u8`) instead — **answered by avoidance rather than by test**. | 78 §4 |
| **Move ids** | `MOVES_COUNT 848` | Soft. The Z-move and Max-move blocks are defined **relative** to `MOVES_COUNT` (`MOVE_CATASTROPIKA (MOVES_COUNT + 18)`, `FIRST_MAX_MOVE MOVES_COUNT_Z`), so appending shifts ~100 later ids and they stay self-consistent — **nothing hardcodes them**, and a mon's `move:11` cannot hold one. Contrast the Poké Ball, §5. Side effect: `gBardSounds_Moves[MOVES_COUNT][…]` and `sValidApprenticeMoves[MOVES_COUNT]` grow a zero row. | 78 §finding 2, §7c |
| **Battle move effects** | ~352 of a `u16` field | Genuine headroom, unlike the behavior table. | 78 §7 (cites 39) |
| **Battle-start ASLR re-roll** | fires every battle | See [[save-system]] §ASLR. `CB2_InitBattle` runs `if (!gTestRunnerEnabled) MoveSaveBlocks_ResetHeap();` and `gTestRunnerEnabled` reads **0** in the shipped ROM (read straight out of `.rodata` at file offset `0xd3a6b5` — no emulator needed). The heap is destroyed and rebuilt at every battle start. | 78 §6.2 |

Damage maths, the catch formula and the AI live in [[battle-engine]].

---

## 4. Audio walls

**The headline: the engine is permanently over its own ceiling, in normal play.** This is the only item on the stress-test slate that is a floor you are standing on rather than a cliff you walk off (record 76).

| Wall | Value | What hitting it looks like | Record |
|---|---|---|---|
| **Simultaneous PCM voices** | **5** of a compile-time 12 | 🔇 `m4a.c:82` sets `(5 << SOUND_MODE_MAXCHN_SHIFT)`. Past five the allocator walks all five tracking a victim: prefer one already in `SF_STOP` (releasing), else the **lowest `priority`**, tie-broken by the **highest `track` pointer** — then `ClearChain`s it and **steals it**. With no victim at all it branches away and the note is **silently dropped**. A probe reading `gSoundInfo.chans[]` sees five busy channels, which is *correct*. The screen shows nothing. **Record 67 filed this as a LOUD wall; record 76 moved it to the silent column.** | 76 §1 |
| ↳ measured, control arm | **249 steals in 30 s** | Littleroot's ordinary map music has ten tracks and the mixer has five voices, so it steals a voice at a flat **~10 per second, forever**, with nothing else playing. Every one of the 249 took a channel already in `SF_STOP`, which is the allocator's first preference and is exactly why nobody has ever noticed. | 76 §5 |
| ↳ **the count does not discriminate** | 249 / 251 / 256 / 0 | Music only / music + a five-sound burst / music + four cries / burst with music stopped. Three of those sound completely different. What separates them is `steals_sounding` — the subset that cut a note still **sounding** rather than one already releasing: **0 / 5 / 0 / 0**. An aggregate that moves by 1 % between two conditions you can hear apart is the wrong aggregate. | 76 §5 |
| ↳ the burst alone never reaches it | 4 voices | With `StopMapMusic()`, the same five deliberate claimants reach `slotmask 0x000F` — channel 4 is never touched, and steals are **zero**. The saturation anyone would design for does not reach the ceiling on its own. | 76 §5 |
| **Overlapping cries** | `MAX_POKEMON_CRIES 2` | 🔇 `SetPokemonCryTone` falls through to `i = maxClockIndex` when no cry player is free, **restarting the player whose song is furthest along** and cutting it off. Four cries → players 0, 1, 0, 1 and two evictions. | 76 §5 |
| **Music players** | **4** | A **linker absolute**: `ld_script.ld:3`, `gNumMusicPlayers = 4;`, where the symbol's *address* is the value. There is no object, no initialiser and no `4` anywhere near the name in C, which is why grepping `src/` and `sound/` finds nothing. Changing it is a linker edit. **The build files are part of the source.** | 76 §5.1 |
| **Unreachable channels 5-11** | **448 B of EWRAM** | `MAX_DIRECTSOUND_CHANNELS` is 12 and `maxChans` is 5, so seven `SoundChannel`s (64 B each) are allocated and can never be used. Not reclaimable without editing the driver struct the BIOS sound syscalls also see. Recorded as a measurement, **not a proposal**. | 76 §5 |

Instrumentation (the `mAVStream` tap, and the fact that `mgba-headless` mixes at **volume zero** by default) is in [[audio]] and [[verification-discipline]].

---

## 5. Content-addition walls that cost zero bytes

These are the ones that break nothing you can measure with a size.

- **A new Poké Ball's item id is FORCED.** Three sites require ball ids to be contiguous and first: `u16 pokeball:6` in `struct BoxPokemon`, `gBattleResults.catchAttempts[gLastUsedItem - FIRST_BALL]` into a `u8[POKEBALL_COUNT]` (an out-of-bounds **write** during a catch), and `.secondaryId = ITEM_<X>_BALL - FIRST_BALL`. `ITEM_CHERISH_BALL` is 27 and **item 28 is `ITEM_POTION`**, so a new ball must take slot 28 and shift **every later item id by one** — 800 defines, `ITEMS_COUNT` 828 → 829. 🔇 **The bag stores the raw id**, so a save written before the shift reads every item one slot off, silently, with a valid checksum. **Zero save bytes, and the existing save is invalidated anyway.** The engine's own comment describes the insert perfectly and never mentions that item ids are in the save file (record 69 §1).
- **Ball art has no `gPokeballGraphics` row** for the stock Poké Ball either, so a new ball is exactly as covered as the vanilla one; latent while `OW_FOLLOWERS_ENABLED` is `FALSE` (record 69 §3.2).
- **Implicit-size arrays are the trap when adding a table row.** Hand-enumerating the tables a new ball needs got **6 of 9**. Two of the misses — `sBallParticleSpriteSheets[]`, `sBallParticlePalettes[]` — are declared with an *implicit* size, so a missing row does not leave a blank slot, it makes the array one element **shorter** and every read at the new index out of bounds. Walk a donor peer's rows and sweep peer-rows against new-rows tree-wide (record 69 §3.2).
- **Field-move enum position** — §1, record 77.
- **`currentBox` legal-range shrink** — see [[save-system]], record 79 §3.5.

---

## 6. Hard budgets — loud, and mostly generous

| Resource | Ceiling | Free (in `reps`, as measured) | Notes |
|---|---|---|---|
| ROM | 32 MiB | **~7.4 MiB** (77.2 % used) | **Cries alone are 25.03 % of the cart** (record 67, cites 51). |
| EWRAM | — | ~14 KB (94.5 % used); **247,850 B used** after record 79 | Prefer `const`/ROM always. |
| **IWRAM** | — | **~2.3 KB** (93.1 % used); **30,516 B used** after records 78/79 | **The scarcest pool by a wide margin.** A plain global declaration lands here; use `EWRAM_DATA` deliberately. Nothing about a successful link tells you which pool you spent (record 79 §6.2). |
| `SaveBlock1` | 15,872 B | **236 B** | Over-size is a **compile** error (`STATIC_ASSERT`). |
| `SaveBlock2` | 3,968 B | **84 B** | The tight block. *(Record 41's hand layout computes 120 B free against the header's annotated 84; the discrepancy is two identified causes in `struct Time` and is not resolved.)* |
| `SaveBlock3` | 1,624 B | **180 B** | Striped 116 B/sector across 14 sectors, and **outside every checksum**. |
| `PokemonStorage` | 35,712 B | 1,568 B tail — **NOT usable** | Reaching the tail means growing `sizeof`, which erases the save. The **9,600-byte box arena** is usable precisely because it is *not* a size change. See [[save-system]]. |
| `FREE_*` switches | 12 toggles | **3,756 B**, not the header's 3,790 | Measured through the compiler; the header's SaveBlock1 total is 100 B high and its SaveBlock2 total 66 B low. **Every one erases every existing save** (record 73 §2). |
| Field effect ids | — | `FLDEFF_USE_CLIMB = 73` was the first free | `FLDEFF_TRACKS_BUG` is 72 (record 77 §3.5). |
| Sound channels | 12 allocated | 5 usable | §4. |

**A generated fixture that only reads costs nothing.** A four-map cliff fixture with 88 assertions came in at **+0 bytes** of EWRAM and IWRAM, because every probe named a global the engine already had (record 68 §1). Reach for that first.

---

## 7. Reading this page

Three rules the corpus keeps re-deriving, which are why the table above is shaped as it is:

1. **What a thing DECLARES is not what it HAS.** 240 behavior ids "defined" → 68 free and 12 that a grep calls free and the binary data does not. A tileset "ships 278 tiles" → four live metatiles reference 279-281. A table row "is `FLDEFF_TRACKS_BUG`" → it is index 71 and the constant is 72. **Count the slot** (record 77 §12.1).
2. **Ask who READS a field, not who writes it.** `paletteSlot` is written in 36 data rows and read in none — reading the setters said the system was alive, and only asking for the readers said it was dead. One grep turned an unbuildable round into a real one before a line was compiled (record 74 §5). The polarity reverses too: `currentBox` is bounded on **write** and raw on **read** (record 79 §3.5).
3. **A comment is evidence about the pin it was written for.** The OBJ-palette comment is real, correctly quoted, and describes code with no callers. The `fusions` offset annotation is 98 bytes stale. The `gFieldEffectScriptPointers` comments name the wrong effects (records 74, 79, 77).

**Where a wall has never been walked off, it says so.** Still secondhand at time of writing: the `>64 templates` and dangling `dest_warp_id` map contracts (record 68 §8), the `pokeball:6` ceiling (record 69 §7), the *drop* branch of the audio allocator — the fixture only ever reached the *steal* branch (record 76 §8), and the out-of-bounds **write** past `sBackupMapData` (record 68 §3.4).

---

**Related:** [[save-system]] · [[verification-discipline]] · [[engine-defects]] · [[maps-and-tilesets]] · [[battle-engine]] · [[audio]] · [[art-pipeline]] · [[build-system]] · [[dialogue-voice]]

**Records distilled here:** 67 (the slate, which tabulates them), 68 (map size, spawn window), 69 (Poké Ball item ids), 74 (OBJ palette), 76 (audio ceiling), 77 (metatile behaviors, tilesets, field moves), 78 (battle-script stack, `BattleScripting`), 79 (box arena, budgets), plus 41/42/47/51 for the read-not-run figures they carry.
