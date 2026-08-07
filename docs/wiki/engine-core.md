# Engine core

**What this page is for.** How the runtime of pokeemerald-expansion actually turns — screens,
frames, windows, sprites and field input — and specifically the conventions that are *conventions*,
not enforcement. Nearly everything here comes from record 42, the engine-architecture study, which
read the source at the pin rather than running it; where a claim was inferred rather than read, the
record flags it and so does this page. The organising fact is a cousin of the one that organises
[[walls-and-budgets]]: **the engine's core idioms are unenforced, and omitting a required call does
not error — it silently freezes exactly one subsystem** while everything else keeps running. The
counts and ceilings (sprites, palettes, tasks, VRAM) live in [[walls-and-budgets]] and are not
repeated here; this page is about the *machinery* those budgets sit inside.

---

## 1. The screen idiom: CB2 owns everything, and calls everything

A "screen" is a function installed as `gMain.callback2`. The engine's main loop calls `callback1`
(the persistent controller — overworld field input, or battle) and then `callback2` (the current
screen), and that is all it does. `RunTasks()`, `AnimateSprites()` and `BuildOamBuffer()` are
**not called by the engine anywhere** — every single CB2 in the tree calls them itself, dozens of
copies of the same triple across the source (record 42 §2.7).

The failure mode this buys is the silent kind: omit `RunTasks()` and your tasks never tick; omit
`BuildOamBuffer()` and every sprite freezes at its last built position — **and queued sprite pixel
copies stop flushing too**, because `BuildOamBuffer` is what arms the vblank drain of the sprite
copy queue (record 42 §3.6). No assert, no blank screen, no error. A screen that "mostly works but
sprites are stuck" is a screen missing one line of boilerplate.

**Two rules of the idiom:**

- **`SetMainCallback2` zeroes `gMain.state`** as its second and only other line (record 42 §1.4).
  `gMain.state` belongs to the incoming screen, and every init CB2 is a `switch (gMain.state)`
  state machine that increments it once per main-loop iteration — one chunk of loading per state,
  which is how a screen avoids a multi-frame stall behind its fade.
- **The final state ends in `return`, not `break`** — by then `SetMainCallback2` has already zeroed
  `gMain.state`, and a `break` would fall out of a switch on a now-reset variable (record 42 §1.7).

The recipe for any new screen is the option menu, the cleanest full example at the pin
(record 42 §1.7): state 0 uninstalls the vblank callback before touching VRAM; state 1 clears
VRAM/OAM/palettes and initialises BGs and windows; state 2 runs the four global teardowns
(`ResetPaletteFade` / `ScanlineEffect_Stop` / `ResetTasks` / `ResetSpriteData`); middle states load
one thing each; the final state creates the screen's task, begins the fade, installs the real
vblank CB and CB2, and returns. Note that `ResetTasks` and `ResetSpriteData` are *global* resets —
there is no per-scene sandbox, and switching screens destroys every task and sprite in the machine
(record 42 §1.7).

**The triple's ordering is not canonical and it matters.** The option menu runs `RunTasks` before
`AnimateSprites`/`BuildOamBuffer`; battle runs the sprite pair *first* and `RunTasks` last. The
consequence is a one-frame latency difference between a task moving a sprite and that move reaching
OAM. Copy the ordering from a screen that behaves the way you want — the source has no single
answer (record 42 §2.7). The overworld's own CB2 threads `CameraUpdate` between `AnimateSprites`
and `BuildOamBuffer` for exactly this reason: sprite callbacks move objects, then the camera moves,
then OAM is built, so the offset applied is always this frame's (record 42 §4.4).

---

## 2. The frame contract

The frame, in order: read keys → soft-reset check → link service → `callback1` → `callback2` →
play-time and map music → `WaitForVBlank` → **the vblank interrupt**, which runs the game's
`vblankCallback`, then the engine's GPU-register flush and DMA3 queue drain, then the sound engine,
then `AdvanceRandom()` (record 42 §1.8).

Three load-bearing consequences:

- **The game's `vblankCallback` runs *before* `CopyBufferedValuesToGpuRegs()` and
  `ProcessDma3Requests()`** — so a `SetGpuReg(...)` made inside a vblank callback still lands this
  frame (record 42 §1.5).
- **Compute in the CB2, transfer in the VBlankCB.** The CB2 half builds buffers in RAM
  (`BuildOamBuffer` fills `gMain.oamBuffer`; text and palette work fills shadow buffers); the
  vblank half commits them (`LoadOam`, `ProcessSpriteCopyRequests`, `TransferPlttBuffer`). This is
  why forgetting the vblank callback renders nothing with no error (record 42 §1.7, §1.9), and why
  palette writes are always one frame late and always whole-palette — they only reach hardware when
  `TransferPlttBuffer()` DMAs the entire faded buffer (record 42 §3.5).
- **`AdvanceRandom()` fires every vblank** unless `gTestRunnerEnabled` is set or the battle is
  link/frontier/recorded (record 42 §1.5). The RNG is wall-clock-coupled: it advances whether or
  not anything asked for a number, so two runs that differ by one frame anywhere differ in every
  roll after it. This is the root fact under the harness's determinism rules — see
  [[verification-discipline]] — and under the open boot-seed item in record 82 §4.5.

---

## 3. Windows: `baseBlock` is yours to get wrong

A window is a software rectangle of BG tiles with its own off-screen pixel buffer — every text box,
menu frame and HUD panel. Two facts govern all window work:

**The auto-allocator is dead code.** `BgTileAllocOp` is a stub that returns 0, and the flag that
would enable it is never set by any caller in the tree — so **`baseBlock` is entirely
hand-assigned**, and if the stub were ever enabled every window would allocate at block 0 and
overlap. Record 42 flags this as a version-drift landmine to re-check on any engine upgrade
(record 42 §5.2).

**A window costs `32 × width × height` bytes of EWRAM heap and `width × height` VRAM tiles**
starting at `baseBlock` (record 42 §5.2). The standard 27×4 field text box is 108 tiles and 3,456
heap bytes.

The hand arithmetic has two worked budgets:

- **Field:** the text box is parked at `baseBlock` 404, and 404 + 108 = 512 — exactly the top of
  BG0's char block. **A field HUD window gets tiles 0–403; 404–511 are the text box**
  (record 42 §5.3).
- **Battle:** unioning every window in the standard battle set, BG0's claimed ranges leave gaps at
  248–255, 268–399, 504–655 and 720–767 — and **268–399 (132 tiles) is the only comfortable one**
  (record 42 §5.4). Beware the top of that space generally: battle BG0's own windows run past tile
  511 into the char block BG1/BG2 share, so a high `baseBlock` aliases terrain tiles. That the
  engine's own overlaps are safe is inferred from the windows being mutually exclusive on screen,
  not verified (record 42 §5.4). Battle's `baseBlock` ranges also deliberately overlap *each other*
  between UI states that are never up together — do not read an existing overlap as free space.

**Drawing is two independent steps, and each half-done state looks like a different bug.**
`PutWindowTilemap` points screen cells at the window's tiles and moves no pixels;
`CopyWindowToVram` moves the pixels. Skip the first and you get a correctly rendered but
**invisible** window; skip the second and you get the **previous frame's pixels** in a visible one
(record 42 §5.2). The full sequence for text is fill → print → `PutWindowTilemap` (once) →
`CopyWindowToVram(id, COPYWIN_FULL)`.

---

## 4. Sprites: two modes, silent sentinels, and a free depth sort

**The `tileTag == TAG_NONE` fork governs the whole graphics-insertion story** (record 42 §3.4).
With a real tag, the sprite is in **sheet mode**: all frames already resident in VRAM, changing
frame just moves `oam.tileNum` — VRAM cost, no bandwidth. With `TAG_NONE`, it is in
**frame-image mode**: the sprite owns a small tile allocation and each frame change DMAs new pixels
into the *same* tiles — bandwidth cost, no VRAM. Overworld object events use frame-image mode,
which is why an NPC's whole walk sheet does not sit in OBJ VRAM.

`CreateSprite` **loads nothing**. The sheet and palette must have been loaded by tag beforehand, or
the tile lookup returns `0xFFFF` and the palette lookup `0xFF` — silently, with no diagnostic
(record 42 §3.4). The `0xFF` palette case is the mis-colouring wall documented in
[[walls-and-budgets]] §2. Palette dedup is **by tag, not by content**: two differently-coloured
sheets given the same tag means the second silently renders in the first's colours
(record 42 §3.5).

The allocator's failure channels are all ambiguous or silent:

- **`LoadSpriteSheet` returns 0 on failure — indistinguishable from "loaded at tile 0"**, and there
  is no other error channel (record 42 §3.5).
- The tile allocator is **first-fit, contiguous, no compaction, one forward pass**: it never
  reconsiders a gap it has passed, so long sessions with mixed allocation sizes fragment OBJ VRAM
  until sheet loads start failing. Its two `-1` exits — no free tile at all, versus a gap that
  exists but is too short — are indistinguishable to the caller (record 42 §3.5).
- **`CreateSprite`'s failure sentinel is `spriteId == MAX_SPRITES`** — a valid-looking index one
  past the array (record 42 §3.4). Check it; the counts are in [[walls-and-budgets]] §2.

**Draw order is `priority` → `subpriority` → descending screen Y → array index**, packed into one
sort key per sprite by `BuildOamBuffer` (record 42 §3.6). The Y term means lower-on-screen sprites
draw in front at equal priority — **that is the overworld's depth sort, and it is free**.
`subpriority` is the author-facing knob. The sort is an insertion sort over the previous frame's
order, deliberately, because order is stable between frames.

---

## 5. Field input: a strict priority ladder

The whole field control loop is seven lines: read input; if `ProcessPlayerFieldInput` consumed the
frame, lock controls; otherwise move the player one step (record 42 §4.4). Two properties of it do
the work of an entire design document:

**Buttons are only accepted at tile centers.** Input gathering is gated on the avatar's
tile-transition state — the grid-lock that makes Pokémon movement feel the way it does is eight
lines of C, and it means no script, menu or interaction can trigger mid-step (record 42 §4.5).

**`ProcessPlayerFieldInput` is a first-match-wins ladder, and the ladder order *is* the game
design** (record 42 §4.5):

1. trainer sight-lines — beat everything
2. on-frame map scripts
3. step-based scripts (poison, Safari counter, repel) — fire *before* the encounter roll
4. the standard wild-encounter roll
5. arrow warps (held direction matching facing)
6. A-button interaction — **the position is deliberately re-targeted to the tile in front**
   mid-function before this check
7. door warps
8. start menu, then Select's registered item

Each rung returns TRUE to mean "I consumed the frame, lock controls". A difficulty hack that wants
"encounters cannot be walked out of" or a changed escape/encounter relationship **edits this
ladder, not a data table** — the ordering is code, and there is no table behind it. What each rung
resolves against (metatile behaviors, map events) is [[maps-and-tilesets]] territory.

---

## 6. Reading this page

The through-line, one more time: **the core idioms are load-bearing boilerplate.** The engine will
not call the triple for you, will not assign your window tiles, will not tell you a sheet load
failed, and will not stop you breaking the ladder's order. Every one of those is a silent wall in
the sense [[walls-and-budgets]] uses the word — and the reason screenshots and memory probes (see
[[verification-discipline]]) carry the verification weight that they do here.

---

**Related:** [[walls-and-budgets]] · [[verification-discipline]] · [[maps-and-tilesets]] ·
[[battle-engine]] · [[build-system]] · [[engine-defects]]

**Records distilled here:** 42 (the engine-architecture study — read at the pin, not run; its own
corrections to earlier docs are §C1–C6), with 82 §4.5 for the open RNG-determinism item the frame
contract explains.
