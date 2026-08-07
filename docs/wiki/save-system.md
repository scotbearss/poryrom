# The save system

**What this page is for.** How pokeemerald-expansion's save file is physically laid out, validated, loaded and moved in RAM — and, more importantly, **every known way it can be silently corrupted**. The save is the one surface in this engine where the door is genuinely one-way for the *player*: there is no save-version field, no migration framework, and nothing in the file records which binary wrote it. A save is only interpretable by the exact binary that wrote it (record 41 §12.0). Two of the four corruption classes are loud and two are silent, and the silent ones produce a save file that **loads, validates, and lies** (record 73 §4). Anything marked 🔇 below produces no error, no crash, and no wrong number on any screen.

Pin: `expansion/1.9.4`, `2e65627`. Related: [[walls-and-budgets]], [[verification-discipline]], [[build-system]].

---

## 1. The physical layer

**Flash 1M, not SRAM.** 131,072 B = 32 sectors × 4096 B (record 41 §1.1). The ROM header save-type string is `"FLASH1M_V103"` (`src/agb_flash_1m.c:4`).

> The toolkit's "save data capped at 32 KB SRAM" is a **Butano** fact and must never cross into this mode.

- All three flash setups (`MX29L010`, `LE26FV10N1TS`, `DefaultFlash`) are **geometrically identical** — 131072 / 4096 / 32 — and `DefaultFlash` is the guaranteed fallback, so mGBA always lands on the same geometry (record 41 §1.2).
- `gFlashMemoryPresent` is the single boolean deciding whether saving is attempted at all. `IdentifyFlash` returns 0 on match, 1 on fallback; only a match sets the flag. If clear, every save entry point bails and the loader reports `SAVE_STATUS_NO_FLASH`. **Assert it early in any save spec.**
- The flash window is 64 KiB, so 128 KiB is two **banks of 16 sectors**. Slot B (sectors 14-27) straddles the bank boundary. Byte-wise reads only; the driver runs its inner loops from a stack buffer.
- **Erase-before-write, footer last.** `ProgramFlashSector_MX` erases the whole sector, then programs 4096 bytes ascending — so the 12-byte footer at `0xFF4`-`0xFFF` is written last. A power loss mid-write leaves the signature unwritten, the sector is rejected, and **the previous save survives because the write went to the other slot.** The A/B alternation is the recovery mechanism, not belt-and-braces (record 41 §1.4).

---

## 2. Sector and slot layout

```c
struct SaveSector {
    u8  data[3968];              // 0x0000  this sector's chunk of SaveBlock2/1/PokemonStorage
    u8  saveBlock3Chunk[116];    // 0x0F80  this sector's stripe of SaveBlock3
    u16 id;                      // 0x0FF4  LOGICAL chunk id 0-13
    u16 checksum;                // 0x0FF6  folded word sum over data[0..size) ONLY
    u32 signature;               // 0x0FF8  SECTOR_SIGNATURE = 0x08012025
    u32 counter;                 // 0x0FFC  gSaveCounter at write time
};                               // = 4096 B
```

| Sectors | Contents |
|---|---|
| 0-13 | Save slot A |
| 14-27 | Save slot B |
| 28-29 | Hall of Fame |
| 30 | Trainer Hill |
| 31 | Recorded Battle |

The whole chip is allocated; **there is no spare sector** (record 41 §1.1).

**Two other footer conventions exist and are easy to get wrong** (record 41 §2.3.1):

| Sectors | `id` | `checksum` | `signature` | `counter` | Payload |
|---|---|---|---|---|---|
| 0-27 | logical chunk id | folded word sum | `0x08012025` | `gSaveCounter` | `data[0..3968)` + 116 B SB3 stripe |
| 28-29 (HOF) | **the checksum** | **always 0** | `0x08012025` | **never written** | `data[0..3968)` |
| 30-31 | *payload* | *payload* | *payload* | *payload* | sentinel `0xB39D` at `0x000`, then **4092 B** running straight through the footer region |

A spec asserting `checksum != 0` after a Hall-of-Fame save will fail correctly-but-confusingly; one reading `signature` on sector 30/31 is reading Trainer Hill payload.

### 2.1 Chunking — the root cause of everything in §6

```c
#define SAVEBLOCK_CHUNK(structure, chunkNum) {                                  \
    chunkNum * SECTOR_DATA_SIZE,                                                \
    sizeof(structure) >= chunkNum * SECTOR_DATA_SIZE ?                          \
    min(sizeof(structure) - chunkNum * SECTOR_DATA_SIZE, SECTOR_DATA_SIZE) : 0 }
```

The **offset** is fixed at `chunkNum * 3968`. The **size** is derived from `sizeof()`. So a shrink never moves a boundary — it shortens the *last* chunk of that block and nothing else. **Changing any struct's size changes at least one sector's `size`, which changes that sector's checksum domain, which invalidates it against every previously written save** (record 41 §2.4; measured in record 73 §3).

| Block | Sectors | Ceiling | Arithmetic |
|---|---|---|---|
| `SaveBlock2` | 0 | **3,968 B** | 3968 × 1 |
| `SaveBlock1` | 1-4 | **15,872 B** | 3968 × 4 |
| `PokemonStorage` | 5-13 | **35,712 B** | 3968 × 9 |
| `SaveBlock3` | striped ×14 | **1,624 B** | 116 × 14 |
| **Slot payload** | 14 | **57,176 B** | 55,552 + 1,624 |

Exceeding a ceiling is a **compile** error (`STATIC_ASSERT`, `src/save.c:80-83`) — you cannot ship an over-size saveblock. Everything *under* the ceiling silently changes the on-flash format.

**And the arithmetic that fills a ceiling can be right on the host and wrong about the machine.** This toolchain builds with `-mabi=apcs-gnu`, whose default `-mstructure-size-boundary=32` rounds every struct's **size** — not merely its alignment — up to a multiple of 4. A 6-byte save row with every field naturally aligned (`u16 u16 u8 u8`) silently becomes an **8-byte array stride**, and 240 rows budgeted at 1,444 B by host-side `sizeof` arithmetic link at 1,924 — over the ceiling (record 60 §2). The fix is `__attribute__((packed))` (already idiomatic in this codebase) **plus your own `STATIC_ASSERT(sizeof(struct X) == N)`** on both the row and the container, so the stride can never drift silently again. When an assert fires and you need the number, make the compiler print it: `char (*probe)[sizeof(struct X)] = 1;` fails with `initialization of 'char (*)[1924]'` — faster than bisecting asserts, and worth keeping (record 60 §2). More toolchain surprises of this shape in [[build-system]].

### 2.2 `SaveBlock3` — 1,624 B with no integrity check

Vanilla's sector was `data[3968]` + **116 unused bytes** + footer. Expansion repurposed exactly those bytes, which is why `SaveBlock3` is save-compatible with vanilla. It is striped: logical sector *i* carries bytes `[i*116, (i+1)*116)`.

🔇 **`SaveBlock3` is outside every checksum, in both directions.** `CalculateChecksum` is computed over the *source RAM buffer* (`locations[sectorId].data`), not the assembled sector, so the 116-byte stripe, the zero-padding between `size` and 3968, and the footer are all excluded (record 41 §3). Bit-rot confined to those bytes of an otherwise-valid sector is **silently accepted**. A `SaveBlock3` growth is one of the few changes that will *not* trip the corrupt detector — it will silently misread instead.

> **Consequence, and the reason record 79 exists:** never put anything a hack depends on for correctness into `SaveBlock3` without your own checksum. `reps` kept its 1,444-byte training diary there for five slices and moved it out to nine fully-checksummed sectors as a **correctness upgrade before a capacity one**.

**Trap:** the community "extra save space with two lines of code" tutorial and expansion's `SaveBlock3` make **mutually exclusive claims on the same 116 bytes/sector**. Applying both silently overlaps `SaveBlock1`'s tail with `SaveBlock3` (record 41 §2.2).

---

## 3. The checksum

```c
static u16 CalculateChecksum(void *data, u16 size) {
    u32 checksum = 0;
    for (u16 i = 0; i < (size / 4); i++) { checksum += *((u32 *)data); data += 4; }
    return ((checksum >> 16) + checksum);
}
```

- Reads `size / 4` little-endian words, **truncating** — a `size` not a multiple of 4 leaves 1-3 trailing bytes unchecked.
- Accumulates in `u32` with wraparound; folds **once**, then truncates to `u16`. A carry out of bit 15 of the fold is discarded, so it is *not* a true one's-complement checksum.
- 🔇 **It is order-sensitive only at word granularity.** Swapping two whole `u32` fields does not change it. This is exactly the class of change that slips through (§6.2).

---

## 4. Write and read paths

### 4.1 Writing

`TrySavingData(saveType)` → `HandleSavingData` → `WriteSaveSectorOrSlot(FULL_SAVE_SLOT, …)`. Every path first calls `UpdateSaveAddresses()`, which rebuilds the location table from the **current** pointers — necessary because they move (§5).

| `saveType` | Behaviour |
|---|---|
| `SAVE_NORMAL` | all 14 sectors |
| `SAVE_LINK` / `SAVE_EREADER` | sectors 0-4 only — **skips the PC** |
| `SAVE_HALL_OF_FAME` | full slot, then two raw sectors into 28/29 |
| `SAVE_OVERWRITE_DIFFERENT_FILE` | erases 28-31, then full slot |

Two counters, two jobs (record 41 §4.2):

- **`gSaveCounter`** — increments once per full save; `% 2` selects the slot; written into every footer; the loader picks the newer slot by it.
- **`gLastWrittenSector`** — increments once per full save, mod 14. It is a **rotation offset**, not a sector index despite the name.

Physical target: `((S + rot) mod 14) + 14 * (counter mod 2)`. The footer's `id` records *S*, which is what makes the rotation decodable on load. Upstream is honest that the rotation does not reduce wear (all 14 sectors are rewritten anyway); the real wear-levelling is the A/B alternation.

On any sector failure the counters roll back to `gLastKnownGoodSector` / `gLastSaveCounter`, so a failed save does not consume a slot flip. `DoSaveFailedScreen` then attempts to wipe every sector in `gDamagedSaveSectors`, 3 outer tries × up to 130 zero-fills each.

**The link path** (`Task_LinkFullSave`, 12 states, one sector per pass) uses `HandleReplaceSector`, which writes `[0, 0xFF8)` then `[0xFF9, 0x1000)`, **deliberately skipping byte `0xFF8`** — the low byte of the signature. Erased flash reads `0xFF`, so the sector reads `0x080120FF` and fails validation until a separate `ProgramFlashByte(sector, 0xFF8, 0x25)` commits it. A genuine one-byte commit barrier. `SAVE_NORMAL` does not use it; it relies on the footer being physically last instead.

### 4.2 Reading, and the fact that matters most

```c
status = GetSaveValidStatus(locations);
CopySaveSlotData(FULL_SAVE_SLOT, locations);   // runs UNCONDITIONALLY
```

**A partially-invalid save is still partially loaded.** Sectors that validate are copied; sectors that don't are left as whatever EWRAM already held (record 41 §5.1).

`GetSaveValidStatus`, per slot: a slot is `OK` iff `validSectorFlags == (1 << 14) - 1` — **all 14 logical ids present and valid**; else `ERROR` if any signature was valid; else `EMPTY`. Then:

| slot A | slot B | Result |
|---|---|---|
| OK | OK | `OK`, larger counter wins (with a `0xFFFFFFFF`/`0` wraparound case) |
| OK | ERROR | `ERROR` |
| OK / EMPTY | EMPTY / OK | `OK` |
| EMPTY | EMPTY | `EMPTY` |
| **ERROR** | **ERROR** | **`CORRUPT`** |

| Status | Message | CONTINUE? |
|---|---|---|
| `OK` (1) | none | yes |
| `ERROR` (0xFF) | "save file is corrupted" | **yes** — the partially-loaded state is playable |
| `CORRUPT` (2) | **"the save file has been erased"** | **no** |
| `EMPTY` (0) | none | no |
| `NO_FLASH` (4) | JP "no 1M sub-circuit" | no |

🔇 **Latent out-of-bounds read, inherited from vanilla and still present:** `id` is taken from the sector footer and used as `locations[id].size` *before* the signature is validated. `gRamSaveSectorLocations` has 14 entries; a garbage `id ≥ 14` reads past it, and `CalculateChecksum(data, locations[id].size)` can then walk an arbitrary length. Relevant before trusting a fuzzed or hand-edited `.sav` (record 41 §5.1).

**And `CORRUPT` is handled identically to `EMPTY`.** `CB2_InitCopyrightScreenAfterBootup` runs `LoadGameSave(SAVE_NORMAL)` and then, five lines later, `if (status == EMPTY || status == CORRUPT) Sav2_ClearSetDefault();`. The partial copy really happens and is really thrown away — measured: every probe reads 0 while `gSaveFileStatus` reads 2 (record 73 §3.1). The reading that predicted otherwise stopped at `TryLoadSaveSlot` and never asked who called it.

---

## 5. ASLR — the save blocks move, and so does the key

`gSaveBlock1Ptr`, `gSaveBlock2Ptr` and `gPokemonStoragePtr` are **not** the addresses of the EWRAM arrays. Each array is over-allocated by 128 bytes (`struct SaveBlock1ASLR { struct SaveBlock1 block; u8 aslr[128]; }`) and the live pointer slides forward into the slack:

```c
offset = (offset + Random()) & (SAVEBLOCK_MOVE_RANGE - 4);   // 124 = 0b1111100
```

- **32 possible placements**, always 4-aligned, **identical for all three blocks** (record 41 §5.4).
- **`SaveBlock3` is NOT ASLR'd.** There is no `SaveBlock3ASLR`; `gSaveBlock3Ptr` is `IWRAM_INIT` to `&gSaveblock3` and never reassigned. Its `.sym` address *is* where the block lives — the one save block a harness may read directly (records 41 §8, 44 §6.3).
- **`MoveSaveBlocks_ResetHeap`** copies all three blocks to `gHeap`, re-rolls the pointers, copies back, re-inits the heap, and then **generates a brand-new encryption key** with `Random32()`, re-encrypting everything. **The heap is destroyed and rebuilt** — nothing may be held allocated across that boundary (record 78 §6.2e).

**When it fires:** every **battle start** (`CB2_InitBattle`, guarded by `if (!gTestRunnerEnabled)` — which reads **0** in the shipped ROM, so the guard is off and the re-roll runs) and every **map load** (`ResetMirageTowerAndSaveBlockPtrs`), plus boot and `ReloadSave`.

**Asserting that the re-roll fired: use the key, not the pointer.** "The pointer moved" is a **31/32 coin flip dressed as a proof** — one of the 32 placements is where it already was. `MoveSaveBlocks_ResetHeap` ends by regenerating `gSaveBlock2Ptr->encryptionKey` from `Random32()` in exactly one place, so **the key changing is the same event observed through a variable with 2³² outcomes instead of 32** (record 78 §6.2c-d, §7a.1). Engineer the randomness out of the claim rather than widening a band around it.

### 5.1 The encryption key

Money, coins, game stats, bag quantities and berry powder are **XOR-obfuscated** with `gSaveBlock2Ptr->encryptionKey`. Party level/HP/stats are **not**. It is obfuscation, not integrity: the key is stored in the clear two structs away, and exists only to defeat naive Action-Replay searches (record 41 §5.5).

🔇 **An encrypted field cannot be asserted by its stored bytes.** The same file's money read `0x9bb48c81` on the writing run and `0x5ec66288` on the very next read, because a new key is generated on every load. **Call the accessor** (`GetMoney()`, `GetGameStat()`), or do not assert it (records 73 §7, 69 §8.3).

---

## 6. The four ways a save silently dies

Record 41 §12 names four classes; records 73, 69 and 79 have since **built and photographed** three of them.

### 6.1 Class A — size change that moves a chunk boundary → **loud, save unusable**

`sizeof` changes → `SAVEBLOCK_CHUNK` recomputes that chunk's `size` → `GetSaveValidStatus` recomputes the checksum with the **new** size over the **old** bytes → mismatch → that slot is `ERROR`. Both slots were written by the old build, so both fail → **`CORRUPT`** → "the save file has been erased", **no CONTINUE**.

**Measured** (record 73 §3): turning on all twelve `FREE_*` switches shrinks `SaveBlock1` 15,568 → 13,152 and `SaveBlock2` 3,884 → 2,544, changing **exactly 2 of 14 sectors' sizes** (sector 0: 3884→2544; sector 4: 3664→1248). The picture is `assets/73-freesave/menu-on-2026-08-04.png`. **This is good behaviour, and it is not the dangerous case.**

The reclaimable total is **3,756 B**, not the header's advertised 3,790 — the header's SaveBlock1 total is 100 B high and its SaveBlock2 total 66 B low.

### 6.2 Class B — size-preserving layout change → 🔇 **silent, and worse**

Reorder fields, change a `u8` to an `s8`, swap two `u16`s, repurpose a `filler`. The checksum is a word sum and is blind to all of it.

**Built deliberately** (record 73 §4), because **no combination of `FREE_*` switches can produce it** — every one of the twelve changes a size and the engine catches every size change. The third build removed 4 bytes from `filler1` and appended 4 bytes after `waldaPhrase`: `sizeof(struct SaveBlock1)` is **15,568 in both builds**, every checksum recomputes over the length it was written with, and the save is **accepted** — while `flags[]`, `vars[]`, `dexSeen` and `dexCaught` have all slid 4 bytes down.

| probe | control | size-changed | **size-preserved** |
|---|---|---|---|
| `gSaveFileStatus` | 1 OK | 2 CORRUPT | **1 OK** |
| party count / level | 1 / 17 | 0 / 0 | 1 / 17 |
| `FLAG_SYS_POKEDEX_GET` at **this** build's offset | 2 | 0 | **0** |
| the same byte at its **old** offset | — | 0 | **2** |
| `dexCaught[0]` old / new | — | 0 | **255 / 0** |

**And the picture is the finding.** The main menu is identical to the correct one — CONTINUE offered, right name, right play time, right badge count — **except that there is no POKéDEX row**, because the menu prints that row only when `FLAG_SYS_POKEDEX_GET` is set and that byte is now read four bytes off. **There is no wrong number anywhere on that screen.** The probes saw it only because they had been pointed at that exact byte by the struct definition; a probe suite written without that knowledge would have found nothing wrong.

> **A size-preserving save-layout change produces a save file that loads, validates, and lies.**

### 6.3 Class C — changed enum ordinals → 🔇 **silent, semantic**

The byte layout does not change; the *meaning* of stored numbers does. The save stores raw ordinals:

| Stored ordinal | Where | Width | Headroom | Breaks on |
|---|---|---|---|---|
| species | `BoxPokemon` substruct0 | 11 bits | 1,524 of 2,047 → **523 left** | inserting a species anywhere but the end |
| held item | substruct0 | 10 bits | 828 of 1,023 → **195 left** | inserting into `items.h` |
| moves ×4 | substruct1 | 11 bits each | — | inserting into `moves.h` |
| **ball** | substruct0 | **6 bits** → 63 | 28 used | **reordering balls — see below** |
| flag ids | `SaveBlock1.flags` bit index | — | — | inserting a flag before `DAILY_FLAGS_START`; **raising `MAX_TRAINERS_COUNT`, which shifts `SYSTEM_FLAGS` and moves every badge the player earned to a different bit** |
| var ids | `SaveBlock1.vars` index | — | — | changing `VARS_START`/`VARS_END` |
| map/warp ids | `WarpData` | — | — | reordering map groups |

**The measured instance: the Rep Ball** (record 69 §1). A new ball's item id is forced to `LAST_BALL + 1 = 28`, and item 28 was `ITEM_POTION` — so taking that slot shifts **800 item defines** by one. `SaveBlock1`'s bag pockets are arrays of `struct ItemSlot { u16 itemId; u16 quantity; }` storing the **raw id**, so 🔇 a pre-shift save reads every item one slot off, **silently, with a valid checksum**. A Potion becomes a Rep Ball.

> **A content change can cost ZERO save bytes and still invalidate a save.** Every other budget this project tracks is a *size*; this one is a *semantics*. When you renumber anything, ask what **stores** it, not what references it. The engine's own comment describes the insert perfectly and never mentions that item ids live in the save file — **read what a comment does not say.**

**Contrast, for calibration:** appending a new *move* shifts ~100 Z-move and Max-move ids and is benign, because that block is defined *relative* to `MOVES_COUNT` and a mon's `move:11` cannot hold one (record 78, finding 2).

### 6.4 Class D — config toggles → all three at once

`include/config/save.h`'s twelve `FREE_*` (Class A). `P_GEN_x_POKEMON` — Class A via `NUM_DEX_FLAG_BYTES` (currently 129 B each for `dexSeen`/`dexCaught`; disabling generations shrinks it and **moves every field after it**). `ROAMER_COUNT` (Class A). `TOTAL_BOXES_COUNT` / `IN_BOX_*` (Class A on `PokemonStorage`). `OW_USE_FAKE_RTC` changes `sizeof(SaveBlock3)`, which **no checksum covers**, so it is **pure Class B**.

### 6.5 The fifth class, found in 2026 — a legal range that shrank underneath a stored byte

Not in record 41. **The bytes stayed still and the valid range moved out from under one of them** (record 79 §3.5).

`struct PokemonStorage`'s first field is `u8 currentBox` — save-resident, the player's own last-viewed box. **Writes are bounded** (`SetCurrentBox`: `if (boxId < TOTAL_BOXES_COUNT)`). **Reads are not** (`StorageGetCurrentBox()` returns the stored byte verbatim). Shrink the visible box count from 14 to 10 and a `.sav` written by a player who last had box 12 open hands the new build a `currentBox` of **12** — a value the new bounds can never produce and never correct.

- `GetCurrentBoxMonData` / `SetCurrentBoxMonData` pass it into bounded helpers, so they fail **silently and harmlessly**.
- 🔇 **`IsDestinationBoxFull` does not.** It seeds `box = StorageGetCurrentBox()` and walks `if (++box == TOTAL_BOXES_COUNT) box = 0;` — a wrap that **only closes if the seed was in range**. Seeded at 12 against a count of 10 it goes 13, 14, 15 … and never equals 10. `box` is an `int` and `GetBoxedMonPtr(u8, …)` truncates, so it eventually re-enters the legal range rather than hanging — but every iteration in between calls `GetBoxMonData(NULL, …)`, because **`GetBoxedMonPtr` returns NULL out of bounds and the caller does not check.** The observable failure is a caught Pokémon filed into a box that does not exist. **No wrong number appears until a Pokémon is caught with a full party.**

**The migration must clamp it**, and 🔇 **the measurement that confirms the fix is a zero.** On the real `.sav` the clamp never fired, because that player had never opened the PC that far. The hazard is invisible on every input that does not happen to trip it — it cannot be found by using the thing, only by reasoning about who reads what.

> **Ask not only whether anything MOVED, but whether anything's legal RANGE shrank — and then who reads that field WITHOUT the bound its writer applies.**

---

## 7. The box arena — 9,600 usable bytes, at zero layout cost

Emerald Rogue's trick, built into `reps` (record 79). `struct PokemonStorage` is 34,144 B and lives in **nine ordinary, fully-checksummed sectors** (5-13). A hack nobody boxes in barely uses it.

```
offset      0  u8 currentBox                            1 B  (+3 pad)
offset      4  struct BoxPokemon boxes[14][30]     33,600 B
offset 33,604  u8 boxNames[14][9]                     126 B
offset 33,730  u8 boxWallpapers[14]                    14 B
offset 33,744  struct Pokemon fusions[4]              400 B
                                                   ─────────
                                                    34,144 B   ✓ matches nm -S
```

- **The arena is `boxes[10..13]` = 4 × 30 × 80 = 9,600 B at offset 24,004.**
- **The size must not change.** `ACTUAL_TOTAL_BOXES_COUNT 14` / `TOTAL_BOXES_COUNT 10`, with **all three** array dimensions on `ACTUAL`. Repointing only `boxes` (as the teardown's quote implies) shrinks `boxNames` by 36 B and `boxWallpapers` by 4 B — **a 40-byte `sizeof` change, i.e. Class A, i.e. the save is erased.** Guarded by `STATIC_ASSERT(sizeof(struct PokemonStorage) == 34144)`, and proved twice: `pre 02010d08 g 000085e0` / `post 02010d08 g 000085e0`.
- **The 1,568-byte tail of the storage sectors is NOT usable.** Reaching it means growing the struct. The whole point of the box trick is that it is *not* a size change.
- 🔇 **`TOTAL_BOXES_COUNT` is used in two incompatible senses** across 85 references: **42 bound uses** (`boxId < TOTAL_BOXES_COUNT`) which *should* shrink, and **31 equality uses** (`boxId == TOTAL_BOXES_COUNT`) meaning *"this mon is in the party"*. After the change that sentinel is 10, and box 10 is the first arena box. A `boxId` of 10 reaching a pokenav ribbon list would read as "party mon" and show a real Pokémon — no wrong number, no crash. It stays unambiguous only because nothing can produce a real `boxId` of 10 once every bound is `< 10`.
- 🔇 **A new game will NOT zero the arena.** `ResetPokemonStorageSystem`'s three loops all run `boxId < TOTAL_BOXES_COUNT`, so boxes 10-13 keep whatever was in EWRAM — a previous save's boxes on a warm boot, and **zeros on a cold one, which is zero-valid**: version 0, count 0, "a fresh empty arena". Hence the three required properties, from the teardown: **a magic value** written first and checked on read, **a version gate**, and **length-prefixed arrays**. One serializer with an `isWriteMode` flag, so read and write cannot diverge.
- **The arena survives the battle-start re-roll for free** — `MoveSaveBlocks_ResetHeap` backs the block up with a whole-struct assignment, so the array dimension never having changed is enough. **A cached pointer does not survive.** Recompute at every access; never cache and refresh.
- **The price is visible and permanent:** four PC boxes are gone. Proved rather than shown — ten Rights from box 0 walk 0→9 and **wrap to 0**.

Cost of the whole round: EWRAM +20 B, IWRAM 0, ROM +704 B, **save 0 B**, 9,600 B gained. The real `.sav` off the RG34XX loads on the new build with its diary carried across.

---

## 8. Migration — there isn't any

There is **no `SAVE_VERSION`, no save-version field, no `MigrateSave*` function** anywhere in the pin. The only acknowledgment is a comment: `// TODO: Turn this into a save migration once those are available.` The sector footer has no version field; `signature` is a constant (record 41 §12.5).

**`migration_scripts/` migrate SOURCE CODE, not saves.** Seven Python scripts that rewrite the developer's C/data (item-ball refactor, battle-anim table removal, trainer parties → `.party`, egg-move refactor …). **Zero of them touch a `.sav`, a SaveBlock, or flash.** Any claim that expansion "shipped save-migration scripts" is a misreading of that directory (record 41 §12.6).

What upstream *does* ship is conservative defaults and one hand-written shim, which is the shape every hack-side migration has to take — `SaveObjectEvents` byte-swaps `graphicsId` on the save boundary so vanilla-range ids stay in the vanilla byte.

**Options, in increasing cost** (record 41 §12.7): (1) **don't break it** — append-only discipline, new state in `SaveBlock3` or the box arena; (2) repurpose existing padding (size-preserving, therefore Class B against any other reader); (3) a hand-written boundary shim at the `CopySaveSlotData` seam, which requires having kept the old struct definition; (4) a real versioned migration you build yourself; (5) an out-of-game `.sav` converter in Python — §2 and §3 give you everything needed, and it is the only approach that can migrate a save a player already has.

---

## 9. Reading the save from a harness

**Direct reads** (no indirection): `gSaveblock3` (not ASLR'd), `gSaveDataBuffer` (the last staged sector image — assert `id`/`checksum`/`signature`/`counter` directly), `gFlashMemoryPresent`, `gSaveFileStatus`, `gSaveAttemptStatus`, `gSaveCounter`, `gLastWrittenSector`, `gDamagedSaveSectors`, `gPlayerParty` / `gPlayerPartyCount`.

**Indirect reads — every time, on the frame you sample:**

```
sb1 = read32(sym["gSaveBlock1Ptr"]);  sb2 = read32(sym["gSaveBlock2Ptr"])
key = read32(sb2 + OFF_SB2_ENCRYPTION_KEY)
flag(id) = bit (id & 7) of read8(sb1 + 0x1270 + (id >> 3))    # LSB-first
var(id)  = read16(sb1 + 0x139C + (id - 0x4000) * 2)
money    = read32(sb1 + 0x490) ^ key
```

Chain-verified offsets: party count `0x234`, party `0x238`, money `0x490`, coins `0x494`, flags `0x1270` (300 B), vars `0x139C` (512 B), game stats `0x159C` (256 B), SB2 name `0x00`, trainer id `0x0A`, play-time hours `0x0E`. **Not safe to hardcode:** anything at or after `SaveBlock2 + 0x98`, *including `encryptionKey`* — the source annotation says `0xAC` and hand layout says `0xA8`, and the discrepancy is unresolved. Publish the offsets from the compiler instead (`__builtin_offsetof` into a `const` ROM array), which `reps` now does for both the battle-script offsets and the arena.

**Three determinism hazards** (record 41 §13.4): pointer re-randomisation, key regeneration, and `SetSaveBlocksPointers` consuming a `Random()` (plus `MoveSaveBlocks_ResetHeap` a `Random32()`) — so a spec that pins RNG must account for map loads and battle entries.

**Harness traps that cost real time:**

- 🔇 **The `.sav` is keyed to the ROM's filename.** Presenting the same build under a different basename makes mGBA create a fresh empty save next to it, and the run reads zeros and stays on the main menu — which is *exactly* what a rejected save looks like. **The size is the tell: a real save is 131,088 B (mGBA appends a 16-byte flash footer); a freshly-created one is exactly 131,072.** Every build in a cross-build save test must be presented under the same basename (record 73 §7).
- **`mgba-headless` never called `mCoreAutoloadSave`**, so its emulated flash had never touched a file — filed for months as "structurally blocked". The emulator is one **we build ourselves**; the fix was six lines and an env-var gate in the Dockerfile. **When a limit is attributed to a tool, check whether the tool is one of ours** (record 73 §1).
- **The save is loaded during the copyright screen**, long before a menu exists — so a save-load observation needs **no input at all**, and any input is a risk. A mash walked past the corrupt-save message and committed to NEW GAME, zeroing every block; all ten probes read 0 and it looked like a clean dramatic finding (record 73 §6.1).
- **Moving data between save blocks moves which CLAIMS the harness can make about it.** A DEREF probe cannot span a soft reset (the pointer is genuinely NULL until the engine reinstalls it), which never applied to `SaveBlock3` because it is not ASLR'd. Moving the diary into `gPokemonStoragePtr`'s block **inherited that limitation**, and a correct spec started failing (record 79 §6.9).

More on all of this in [[verification-discipline]].

---

**Related:** [[walls-and-budgets]] · [[verification-discipline]] · [[engine-defects]] · [[battle-engine]] · [[build-system]] · [[maps-and-tilesets]]

**Records distilled here:** 41 (the save system, source-verified), 73 (the layout change, built in three arms), 79 (the box arena and the `currentBox` range hazard), 69 (item-id renumbering), 78 (the battle-start re-roll, asserted on the key), 44 §6.3 (the ASLR wrapper set), 54 and 67 (the free-space figures), 60 §2 (the struct-size rounding trap).
