# Maps and tilesets

**What this page is for.** How the field engine actually works — maps, the map buffer, tilesets,
metatile behaviors, object events, field effects — and how to author each of them without walking into
something. [[walls-and-budgets]] is the *catalogue* of the limits; this page is the *mechanism*, the
authoring surface, and the tools. The organising fact is that the field engine's error behaviour is
**"look wrong", never "crash"** (record 47): out-of-bounds reads fall through to a border pattern, an
oversize map draws its own border edge to edge, a refused NPC renders in someone else's colours, and a
warp on the wrong tile simply does nothing. Every limit below therefore says what hitting it looks
like, and silent ones are marked 🔇. The three static checkers exist because a plausible artifact can
only be caught **before** the build — see [[verification-discipline]].

---

## 1. The model

A map is **static ROM data** (`struct MapHeader` → `struct MapLayout` → two `struct Tileset`s + a
`u16[]` grid) plus **four event lists** (objects / warps / coord triggers / bg signs). At load the grid
is *copied* into one 10,240-entry EWRAM scratch buffer `sBackupMapData`, offset by **7 tiles on every
side**, and the margins are filled from connected maps' real data or from a 2×2 repeating **border**
pattern. Every tile is one `u16`. The *meaning* of a tile — grass, ledge, water, door, warp — is **not
in the grid at all**; it is a **behavior byte** looked up from the tileset's `metatileAttributes` by
metatile id. Object events are 16 fixed RAM slots driven by a two-tier VM (movement **type** = the AI,
movement **action** = one animation primitive). The camera is not a transform: it is an invisible
sprite whose per-frame pixel delta scrolls three BG layers by hardware register (record 47).

Three consequences that bite immediately:

- **`gMapHeader` is a whole-struct copy into EWRAM** (28 bytes), writable at runtime. Scripts that
  change weather or map music for the session are editing that copy, not the ROM.
- **`mapLayout` is re-resolved through `mapLayoutId`** — `gMapLayouts[mapLayoutId - 1]`, **1-based** —
  not taken from the ROM header's own pointer. That indirection is how the Battle Pyramid substitutes
  a generated layout.
- **`gMapGroups[mapGroup][mapNum]` has no bounds check anywhere on that path.**

---

## 2. The grid, and where behavior lives

| Field | Mask | Notes |
|---|---|---|
| metatile id | `0x03FF` | 10 bits |
| collision | `0x0C00` | 2 bits, but **only ever tested `!= 0`**; the setter writes both at once |
| elevation | `0xF000` | 4 bits; **elevation 0 is a wildcard**, not "ground level" |
| `MAPGRID_UNDEFINED` | `0x03FF` | id all-ones, collision 0, elevation 0 — the buffer's bulk fill |

`MapGridGetCollisionAt` returns **`TRUE`** for `MAPGRID_UNDEFINED`, so "no data here" is a *value*, not
a bounds condition, and every accessor special-cases it (record 47).

**Behavior is a property of the *metatile* — of the tileset, not of the map.** Painting the same grass
metatile anywhere in any map using that tileset gives encounter-triggering grass; there is **no
per-tile override in the grid**. "This one grass tile doesn't spawn encounters" means a new metatile,
or patching the runtime grid. `MapGridSetMetatileIdAt` (the `setmetatile` primitive) rewrites the id
while preserving the elevation nibble — and therefore changes behavior too, because behavior follows
the id.

**Layer type** decides which BG layers a metatile's two halves land on: `NORMAL` = middle + top,
`COVERED` = bottom + middle, `SPLIT` = bottom + top. **BG1 is the layer that draws over NPCs** — tree
canopies, roof overhangs, doorway tops — and `COVERED` exists precisely so a metatile can *not* have
one while still occupying the bottom. Combined with elevation-derived subpriority, that is the whole
depth model.

---

## 3. The map buffer

`MAP_OFFSET` = 7, `MAP_OFFSET_W` = 15, `MAP_OFFSET_H` = 14. **Buffer coordinate = map coordinate + 7 on
both axes**, and everything downstream carries that +7: `SetCameraFocusCoords` subtracts it,
`InitObjectEventStateFromTemplate` adds it to template x/y, `GetWarpEventAtMapPosition` subtracts it
before comparing against warp coords (record 47).

> **The ceiling: `(width + 15) × (height + 14) ≤ 10240`.** Worked: width 30 → max height 213 · 50 → 143
> · 100 → 75 · 200 → 33.

🔇 **Hitting it is silent and plausible.** `InitMapLayoutData` sets `gBackupMapLayout.map`, `.width` and
`.height` **unconditionally** and only *then* tests the ceiling, so everything a debugger looks at first
is correct on a void map. It is a **wall, not an empty room** (every tile impassable), **the player
still turns** (turning writes `facingDirection`, not `currentCoords`, so no coordinate probe sees it),
and **it renders as the map's own border block tiled edge to edge**. The `reps` fixture read as solid
black only because an indoor border is black — give a map an outdoor grass border and blow the ceiling
and it boots into a flawless uniform meadow you cannot walk in. Full measurements and the
out-of-bounds-write consequence: [[walls-and-budgets]] §1.1, record 68.

**Border facts** (record 47): a **2×2 tile pattern** indexed `((y+1)&1)*2 + ((x+1)&1)`, phased by the
`+1` so it aligns with even map coordinates — Porymap's border editor is exactly these four entries. It
is **always impassable** (`| MAPGRID_COLLISION_MASK` is forced), so you cannot make a walkable border.
And **out-of-bounds reads never fault**; they fall through to it.

**The saved map view** is `u16 mapView[0x100]` in SaveBlock1 — 256 entries, of which the engine writes
**14 × 15 = 210**. That is why a returned-to map remembers its cut trees. See [[save-system]].

---

## 4. Tilesets

| Resource | Primary | Secondary | Total |
|---|---|---|---|
| 8×8 tiles in VRAM | 512 (`0x000`–`0x1FF`) | 512 (`0x200`–`0x3FF`) | 1024 |
| Metatile definitions | 512 | 512 | 1024 |
| BG palettes | 6 (slots 0–5) | 7 (slots 6–12) | 13 of 16 |

The split is enforced by **index arithmetic in two places that must agree** —
`GetMetatileAttributesById` and `DrawMetatileAt` both test `< NUM_METATILES_IN_PRIMARY`, on
`metatileAttributes` and `metatiles` respectively. A metatile is 8 `u16`s: 4 bottom-layer tiles + 4
top-layer. A metatile id past 1024 returns `MB_INVALID` (record 47).

**A primary tileset's palette colour 0 is ignored** — `LoadTilesetPalette` force-writes `RGB_BLACK`
there, so the field backdrop is always black.

**Connected maps share the primary tileset**, because the camera-transition load path reloads only the
*secondary*. This is the engine-level reason for a rule usually stated as folklore (record 47).

`gTileset_General` is already **512/512** and is the binding constraint on new outdoor art. Indoor
tilesets have room — `gTileset_PokemonSchool` was 58/512 metatiles used when the climb wall landed
(record 77).

🔇 **A tileset can reference tiles it does not ship.** `gTileset_PokemonSchool`'s build rule emits **278
tiles**; its window metatiles (529, 530, 537, 538) reference secondary tiles **279–281**, which
`-num_tiles 278` truncates away, so those VRAM slots hold whatever the previously-loaded tileset left
there. Appending art at the *declared* count landed in the gap and rebuilt the map with **its windows
drawn as climbing wall** — right place, right tiling, correct palette, entirely deliberate-looking, and
`check_map.py` clean (record 77).

> **A declared count is a claim about what a thing SHIPS; the question you need answered is what it
> REFERENCES.** Derive the first free tile from the highest tile any existing metatile references, then
> assert nothing pre-existing draws from the range you claimed.

`tools/check_tilesets.py` answers this without building, resolving primary references through the
pairings in `layouts.json` (the same secondary can sit on two primaries, and only a pairing that exists
can be judged). **It is four tilesets in the pin, not one** — `PokemonSchool` 278/281, **`Petalburg`
159/307**, `Lavaridge` 450/456, `BattleFrontierOutsideEast` 508/511 — reported as **WARN with the pin
named**, not suppressed as a vanilla quirk. Tileset art itself is [[art-pipeline]]'s problem.

---

## 5. Metatile behaviors — the id space is FULL

**241 `MB_*` constants over 240 distinct ids**, highest `0xEF`, the last slot below
`NUM_METATILE_BEHAVIORS 0xF0`. `MB_INVALID` is `0xFF` and survives the behavior mask intact. **Zero free
ids.** A new behavior is a **reclaim, not an append** (records 47, 77).

The only behavior-indexed table in the codebase is `sTileBitAttributes[NUM_METATILE_BEHAVIORS]`, with
two live bits — `TILE_FLAG_HAS_ENCOUNTERS`, `TILE_FLAG_SURFABLE` — and a third, `TILE_FLAG_UNUSED`,
carrying the source's own admission that it is *"set but never read"*. **Exactly two properties of a
behavior are table-driven; everything else is a function** in the 1,402-line predicate wall of
`src/metatile_behavior.c`. There is no behavior → handler dispatch table; the five places a behavior
*is* dispatched through a table are keyed by **direction** or are linear-scanned predicate/action
pairs, never by behavior id (record 47).

### 5.1 The census — `tools/check_behaviors.py`

Byte-identical between the pin and a fork that has not touched behavior data, so the baseline diff is
clean (record 77):

```
  free slots (never defined)      : 0
  named MB_UNUSED_*               : 77
  referenced in C                 : 160
  carry an sTileBitAttributes row : 117
  declared in a tileset           : 158
  painted in a layout or border   : 120

RECLAIMABLE -- dead in code, dead in data, no inherited tile flags: 68
LOOKS FREE, IS NOT -- no C reference, but luggage or live data:    12
```

**The twelve are the finding, not the 68** — ids a `grep` hands you as free: `MB_SECRET_BASE_WALL`
(`0x01`, zero C references, **52 layouts**), `MB_CAVE` (`0x08`, zero references, **88 layouts**, carries
`HAS_ENCOUNTERS`), `MB_SLOT_MACHINE` (`0x89`, zero references, 1 layout), `MB_SECRET_BASE_DECORATION`
(`0xB4`, 6 tilesets), the four diagonal `MB_JUMP_*` (`0x3C`–`0x3F`, two of them painted in 11 and 16
layouts), and `MB_UNUSED_23 / _49 / _4A / _6F` (tile-flag rows only; `0x6F` is `SURFABLE`).

🔇 Two traps, both the inherited-default shape:

- **`sTileBitAttributes` is sparse.** An id with no designator reads `0`; an id with one reads whatever
  the original author left. **Reclaim the wrong slot and your new wall spawns wild Pokémon, or the
  player Surfs up it** — nothing errors and there is no wrong number on any screen.
- **"Unreferenced in C" is not "unused in data."** A behavior id is the low byte of a `u16` in every
  tileset's `metatile_attributes.bin` — binary files no grep will ever hit. The census decodes all 70
  and resolves every layout's blockdata **and border** through its own tileset pair.

Two riders (record 77). **The diagonal ledge behaviors are painted and unread** — `MB_JUMP_NORTHEAST` …
`MB_JUMP_SOUTHWEST` have tile-flag rows and appear in shipped layouts, but `GetLedgeJumpDirection`'s
table holds only the four cardinal predicates, so a tile painted `MB_JUMP_SOUTHEAST` does nothing at
all. And **the census nearly committed the error it exists to prevent**: its first version classified by
whether a *name* appeared in the tree, and `metatile_behavior.c` contains **ten two-sided range tests**
which name only their endpoints — `MB_BRIDGE_OVER_POND_LOW` (`0x71`) is written nowhere and is accepted
by two predicates. It now expands ranges and **refuses to run** if it meets a comparison it cannot pair.
*A census that can only over-report is safe; one that can under-report is worse than none.*

### 5.2 Adding one

An `MB_*` constant (a **rename** of a reclaimed id keeping the numeric value — nothing shifts, no save
is touched) + a predicate + an **explicit `0`** `sTileBitAttributes` row, written out rather than left
to the sparse default + at least one call site. Ten to thirty lines of mechanical C (records 47, 64,
77). `MB_CLIMBABLE_WALL` = `0xD7`, reclaimed from `MB_UNUSED_D7`, is the worked example.

---

## 6. Object events — 16 slots, 64 templates, 15 NPCs

Two ceilings, and conflating them is a common error (record 47):

- **`OBJECT_EVENTS_COUNT` = 16** — live RAM slots in `gObjectEvents`, **including the player** and, in
  expansion, the follower.
- **`OBJECT_EVENT_TEMPLATES_COUNT` = 64** — the SaveBlock1 working copy of the map's template list, the
  number a *map* can define. Scripts mutate that copy, which is why a `setobjectxy` persists across a
  re-spawn within a map visit but not across a map load.

**The player takes slot 0 before a single template is considered**, so the map-object budget is **15**:
🔇 **the 16th NPC you place is the first one that does not appear**, and which one is lost is decided
purely by **position in the template list** (record 68).

**The spawn window, exactly** (buffer coords relative to `pos`): x ∈ `[pos.x−2, pos.x+17]`,
y ∈ `[pos.y, pos.y+16]` — a **20 × 17** window, asymmetric: 2 tiles of slack left and right, **0 above
and 2 below**. Despawn uses the same numbers as hardcoded literals, and an object survives if **either**
its current **or** its initial position is inside — which is what stops a wandering NPC from despawning
the instant it steps off-screen. Both run from `CameraUpdate` **only on a tile-boundary crossing**, so
spawn/despawn happens at most once per 16 pixels of camera travel (record 47).

*Record 47 §14.4 recommends checking a 20×18 window; the derived bounds and `check_map.py` both use
20×17. Prefer 20×17.*

🔇 `GetAvailableObjectEventId` is a two-pass first-fit scan in which **"no slot available" and "already
loaded" return the same `TRUE`** — callers cannot tell them apart and `TrySpawnObjectEvents` does not
try. *(Sprite exhaustion, by contrast, does roll back: `CreateSprite` returning `MAX_SPRITES` sets
`active = FALSE`.)*

🔇 **Over 64 templates is save corruption, not a cosmetic loss.** `LoadObjEventTemplatesFromHeader` does
a `CpuCopy32` of `objectEventCount` templates with **no `min()` against 64**, overrunning
`objectEventTemplates` into SaveBlock1's following `flags[]` array. This is `check_map.py`'s check 4 and
it is **still secondhand — nobody has built it** (records 47, 68). See [[save-system]].

**To assert an object is absent, account for every slot.** The first attempt — "no slot holds the
missing object's x" — **failed on a correct run**, because a coordinate is not an identifier
(record 68). See [[verification-discipline]].

### 6.1 NPC palettes

The fixed-slot scheme the engine documents in its own comment (`PALSLOT_PLAYER`, `PALSLOT_NPC_1..4`,
their reflections, `PALSLOT_NPC_SPECIAL`) **has no callers at this pin** — `InitObjectEventPalettes` is
uncalled and `ObjectEventGraphicsInfo.paletteSlot` is **written in 36 data rows and read nowhere**. What
runs is dynamic, tag-keyed, first-fit allocation over slots `gReservedSpritePaletteCount .. 15`, and
the measured stock baseline is **5 of 16 used** with `gReservedSpritePaletteCount = 0` (record 74).

🔇 The real wall is 16 slots whose exhaustion returns `0xFF` into a **4-bit** `oam.paletteNum`, so it
truncates to 15 and **the refused NPC renders in full, in the right place, correctly animated, wearing
someone else's colours.** Numbers, the reordering control, and why the wall is only reachable outdoors:
[[walls-and-budgets]] §2.

*Sprite budget context: `MAX_SPRITES` is 64; the field's worst realistic case is 16 object events + 16
attached effects + 1 camera object + 2 reflection distortion sprites = 35. **16 object events is roughly
half the OAM budget**, which is why it is the ceiling it is (record 47).*

---

## 7. Field effects, movement, collision, warps

- **The active list is 32 entries.** `FieldEffectActiveListAdd` is first-fit and **silently drops the
  effect from the list if all 32 are taken** — the sprite is still created, but
  `FieldEffectActiveListContains` will not see it, so a `waitfieldeffect` on it would **hang**
  (record 47). Graphics are loaded lazily and shared by tag, so a second grass rustle costs no VRAM.
- 🔇 **`gFieldEffectScriptPointers` is not in constant order at this pin, and its comments name the
  wrong effects** — `FLDEFF_TRACKS_SPOT` is 71 and `FLDEFF_TRACKS_BUG` is 72, while the table holds
  TracksBug at 71 and TracksSpot at 72. It is upstream's. An append anchored on the *comment* lands one
  slot early and displaces a real effect (record 77). **A name written beside a slot is documentation,
  not data. Count the slot** — and assert `table index == FLDEFF_*` after writing.
- A new field effect is an id + a `gFieldEffectScriptPointers` entry + a two-line script + a `FldEff_*`
  spawner + a self-terminating sprite callback. Medium risk: **the `gFieldEffectArguments` ABI is
  unchecked** (records 47, 64).
- 🔇 **`movementActionId` has no bounds check** at either dereference of `gMovementActionFuncs` — the
  field VM does not fail safe the way the script VM does. Walked off on purpose it **commits and does
  not crash**; see [[walls-and-budgets]] §1.4 and [[engine-defects]].
- **Collision codes 0–4** come from the shared `GetCollisionAtCoords` (`NONE`, `OUTSIDE_RANGE`,
  `IMPASSABLE`, `ELEVATION_MISMATCH`, `OBJECT_EVENT`); **5–13 are player-only**. The function is a
  **priority ladder whose order is the design** — reordering changes behaviour globally.
- **A held movement bypasses collision.** Confirmed by observation, not reading: a held `WALK_SLOW`
  crosses a tile whose collision bit is set, so one impassable metatile **bumps a walker and carries a
  climber** with no forced-movement row (record 77).
- 🔇 **`elevation: 0` is a wildcard, not "ground level."** It makes an object collide with everything
  and a warp fire at any elevation (record 47).
- 🔇 **A warp on the wrong metatile behavior**: the warp event exists, the tile looks right, nothing
  happens. `check_map.py` cross-checks every warp event's tile behavior against the engine's own
  warp-behavior list (records 47, 65).
- *A coord event's `var` field may name a **flag*** — `ShouldTriggerScriptRun` falls back to `FlagGet`
  when `GetVarPointer` returns NULL. A free authoring affordance (record 47).

---

## 8. Authoring — `tools/new_map.py`

**A map is six edits across five files plus two binaries, and five of the six fail silently when
skipped** (record 65):

| # | Artifact | What its absence looks like |
|---|---|---|
| 1 | `data/layouts/<Name>/{map.bin,border.bin}` | — (the layout itself) |
| 2 | `data/layouts/layouts.json` row | the layout is simply not built |
| 3 | `data/maps/<Name>/map.json` | — |
| 4 | `data/maps/<Name>/scripts.inc` | — |
| 5 | `data/maps/map_groups.json` entry | no `MAP_*` constant exists |
| 6 | `data/event_scripts.s` `.include` | the scripts link against nothing, taking the map's script pointers with them |

Everything `mapjson` generates — `header.inc`, `events.inc`, `connections.inc`, the `map_groups.h` /
`layouts.h` constants — is left to the build.

🔇 **APPEND-ONLY, and not as a style preference.** A map's identity is `(group, num)` and `num` is its
**index inside its group**; `SaveBlock1.location` stores that pair, so **inserting a map mid-group
teleports every existing save**. The tool refuses any placement but the end of a group. See
[[save-system]].

- **`--dump-layout` — authoring starts with a dump.** A metatile id is meaningless outside its tileset
  pair, and a wrong one is not an error, it is a wall where you wanted a floor. The tool prints an
  existing layout as an editable ASCII plan plus a palette, so **every block in the result is one the
  engine itself ships with that exact tileset pair**. The round trip (dump → `pack_block` →
  byte-identical `map.bin`) is the load-bearing property and has its own test. Same rule as
  [[dialogue-voice]]'s corpus scoring and [[art-pipeline]]'s kitbash: **derive from the original**.
- **Buildings are stamped, not drawn.** `host_door` copies a rectangle of an existing building block
  for block and appends the warp on the door tile, asserting **both** that the stamped rectangle matches
  the source block for block **and that every block outside it is unchanged** — a paste with a wrong
  width corrupts one row at a time and looks entirely plausible in a diffstat.
- **Placement by search, not by eye.** The `reps` annex site was the **only** 5×5 rectangle of plain
  ground in the whole 40×60 city with a walkable tile below its door. A playtest later found a building
  stamped **on top of an NPC**, which is why `check_map.py` gained a contract for it (records 65, 70).
- **`--allow-oversize`** gates the size ceiling for fixtures, printing what you give up, and is inert on
  a legal map. Coverage: 27 tests, both directions for every guard; three sabotages fail 10 of the 27.

**An append-only tool's refusal is not its caller's failure.** `new_map.py` exits 1 on "this map already
exists", which is right for it and wrong to propagate — a wrapper that treated the exit code as the
answer aborted its loop and **silently produced a fixture with one of three arms missing**. Assert the
**end state** (is the layout in `layouts.json`?), never the tool's opinion of whether it changed
anything (record 74).

---

## 9. The static checks, and their baseline

`check_map.py` judges map data, `new_map.py` writes it: **author, then check.** Over the whole fork it
reports **522 maps, and vanilla itself trips 131 FAIL + 7 WARN = 138 quirks suppressed by the baseline**
(records 65, 68).

**That baseline is what lets the rules stay absolute.** "No NPC may stand on an impassable tile" sounds
absolute, and vanilla Emerald breaks it **378 times on purpose** — clerks behind counters, a legendary
on its rock, a ship on water. Without a measured baseline the rule would have to be softened into
uselessness; with one, the rule stays absolute and the exceptions become *data* (record 70).

Judged against real fixture data for the first time it got all four maps right — FAILing the oversize
map and both crowded ones with the exact numbers, and producing **nothing** on the map at 10,205, which
is the half that matters: *a checker that fires on the boundary is a checker you learn to ignore*
(record 68).

| Checker | Answers |
|---|---|
| `check_map.py` | size ceiling · spawn-window budget · warp metatile behavior · >64 templates · dangling `dest_warp_id` · NPCs on impassable tiles |
| `check_behaviors.py` | which behavior ids are reclaimable in **code, data and tile flags** |
| `check_tilesets.py` | does any metatile draw from a tile its tileset does not ship |

---

## 10. The silent-failure index

| Fault | What you see | 🔇 |
|---|---|---|
| Map over `(w+15)(h+14) = 10240` | the map's own border block tiled edge to edge; the player turns but cannot step | 🔇 |
| …with an outdoor border | a flawless uniform meadow you cannot walk in | 🔇 |
| 16th+ NPC in the spawn window | that NPC is simply not there; which one depends on template order | 🔇 |
| >64 object-event templates | SaveBlock1 `flags[]` overrun — save corruption | 🔇 **unbuilt** |
| 17th distinct OBJ palette | renders perfectly, in someone else's colours | 🔇 |
| Reclaimed behavior id carrying tile flags | the new tile spawns encounters, or is surfable | 🔇 |
| Reclaimed id that was painted in data | a wall you can walk through, in 52 maps nobody tests | 🔇 |
| Art appended past a tileset's referenced range | existing metatiles redraw as your new art, correctly tiled | 🔇 |
| Field-effect append anchored on a comment | the effect never dispatches; every probe reads zero | 🔇 |
| >32 simultaneous field effects | the effect plays but `waitfieldeffect` hangs | no — it hangs |
| Warp on the wrong metatile behavior | you stand on the door and nothing happens | 🔇 |
| `elevation: 0` on an object | it collides with everything; warps fire at any elevation | 🔇 |
| Map inserted mid-group | every existing save is somewhere else | 🔇 |

---

## 11. Still open

- The **out-of-bounds write** past `sBackupMapData` is static, never observed — reaching it needs a
  script, since you cannot walk to the far corner of a map you cannot walk in (record 68).
- **`check_map.py` checks 4 and 5** — >64 templates and dangling `dest_warp_id` — are still secondhand.
  Check 4 is the interesting one: it is save corruption, not a cosmetic loss (record 68).
- Whether **`mapjson` / Porymap enforce the 64-template and 10,240-cell limits upstream** was never
  established; the *engine* enforces neither (record 47).
- **`field_player_avatar.c` is only partially read.** The player-only collision codes 5–13 are named but
  not traced, and the ledge-jump, surf/dive and acro-bike paths are unread — record 47's own largest
  admitted hole.
- **Nothing measured what happens when the *player's own* palette is the one refused** (record 74).

---

**Related:** [[walls-and-budgets]] · [[verification-discipline]] · [[engine-defects]] · [[save-system]]
· [[art-pipeline]] · [[dialogue-voice]] · [[build-system]] · [[battle-engine]] · [[audio]]

**Records distilled here:** 47 (the field engine, read-not-run), 65 (the first map and `new_map.py`),
68 (map size and spawn window, walked off), 70 (the baseline-diff rule), 74 (OBJ palettes, the
append-only refusal), 77 (behaviors, tilesets, field effects, held movement).
