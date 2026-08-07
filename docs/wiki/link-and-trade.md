# Link and trade

What the link cable actually carries at this pin, why a hack's link compatibility dies at the first data edit and cannot be saved, and how trade evolution is already solved without a second console. Also the patch-format taxonomy (IPS/UPS/BPS), kept because understanding the ecosystem's distribution conventions requires it — **this project distributes nothing**; the knowledge here is for reading the ecosystem, not for shipping into it. Siblings: [[battle-engine]], [[save-system]], [[build-system]].

## 1. Trade evolutions are already solved at this pin

The expected work — "convert 30 trade-evolution rows across 4 files" — **does not exist; upstream already did it** (record 49 §5.4). Verified row by row:

| Method | Rows | Substitute shipped |
|---|---|---|
| `EVO_TRADE` | 12 | an `{EVO_ITEM, ITEM_LINKING_CORD}` sibling row on every one, **unconditional, always on** |
| `EVO_TRADE_ITEM` | 16 | an `EVO_ITEM` sibling with the same held item on every one, gated by `I_USE_EVO_HELD_ITEMS_FROM_BAG` (**FALSE** at this pin — one `#define` flip turns all 16 on) |
| `EVO_TRADE_SPECIFIC_MON` | 2 | **none** — Karrablast→Escavalier and Shelmet→Accelgor are the only genuinely trade-locked evolutions |

The Linking Cord (item id 796) is fully implemented — party-menu use, evolution-stone field function, working at default config with no edits — **but is placed nowhere**: no map, no mart, no script, no Pickup table. Making it obtainable is the one real piece of work, and it is ordinary content authoring, not engine work (record 49 §5.4).

The two hard-locked species have a natural fix: two added `EVO_SPECIFIC_MON_IN_PARTY` rows, which route through the ordinary evolution handler. Two data rows and nothing else (record 49 §5.4).

One more offline trigger already exists: the **in-game (NPC) trades** run the same trade-evolution path as a link trade, so a hack that wants to hand out a trade-evolved mon without touching evolution data at all can do it through an in-game trade — a working, offline trade-evolution mechanism shipped in the base game (record 49 §8.4).

Three bounding negatives survive the audit: there is no trade-equivalent evolution *mode* (the substitute routes through the ordinary item-use handler), no script/debug hook for trade evolution, and no trade-related config key at all — the toggle that matters is filed under *items*. That last fact is also the search trap: **grepping this tree for "link cable" finds only UI text**, because the item carries its Gen 8/9 name, Linking Cord. The original finding here was wrong for exactly that reason and was corrected in the record (record 49 §5.3–5.4).

## 2. Why hack link compatibility is unfixable

The rule first: **assume link is broken from the first data edit, and design as if link does not exist** (record 49 §8.4). This is not caution — it follows from three structural facts, in tiers.

**Tier 1 — the payload is raw structs, and the sizes are literals.** A trade transmits `struct Pokemon` verbatim, two at a time, in **hard-coded 200-byte block requests** — a constant in the link code, not a `sizeof`. Two 100-byte Pokémon fit exactly; **a fork that grows the struct silently truncates the transfer rather than erroring** (record 49 §4.2). Around that central fact:

- The full exchange is five blocks — three of party mons, one of mail, one of gift ribbons — and every block size is a literal from the same hard-coded table (record 49 §4.2).
- The mail block already *over-reads* at this pin: a 220-byte request for 208 bytes of mail, leaking 12 bytes of adjacent EWRAM onto the wire harmlessly — and a hack that widens the mail struct pushes past 220 and quietly truncates the other way (record 49 §4.2).
- The tree's one defence against the class is deliberate: the stored nickname field is clamped to 10 bytes even though the display name length is 12, precisely so that raising the display length does not change the struct that crosses the wire (record 49 §4.2).
- The species, move, item and ability ids inside those bytes are indices into the *receiver's own* tables, not names; the only integrity check on a received mon is its own checksum — computed by the sender, so it validates transport, not provenance (record 49 §8.1).

**Tier 2 — nothing can detect divergence.** The only identity a peer asserts is the ASCII magic `"GameFreak inc."` plus a compile-time version byte; the battle version signature is a hard-coded constant identical for every Emerald-lineage build. The expansion *does* compile a self-describing ROM header carrying species/move/ability/item counts — **and no link code reads it**; it occurs in exactly one file, its own (record 49 §8.1). So the failure modes stratify (record 49 §8.2):

- **Stat retunes trade "fine" — and that is the dangerous case.** Ids still resolve on both sides, so a Blaziken traded out of a retuned fork is a *vanilla* Blaziken on the other cartridge; the receiver applies its own tables. EVs, IVs, moves and level cross verbatim; the redesign does not.
- **Id-space divergence trades garbage, not refusal.** An id valid on one side names something else, or nothing, on the other — and the magic matches, the version byte matches, the checksum matches. At least one receive path indexes the species table with a wire-supplied id and no range guard (record 49 §8.1).
- **Behavioral divergence desyncs link battles.** A GBA link battle is not a thin client sending "I chose move 2": **both consoles run the entire battle engine from a shared seed** and exchange battle-controller commands and their results, with the master's attacker/target globals authoritative for the slave. Any change to damage calc, ability hooks, turn order, or RNG consumption breaks the shared-computation assumption and produces disagreement-while-continuing, not an error (record 49 §6.3).

No mechanism exists at this pin to negotiate any of this — no capability exchange, no table hashing, no feature bits, and the self-describing header goes unread; the search covered the link headers and sources in full, the link-type set, and every config header, and the only "LINK" hits in config are a save-space toggle and two species-family switches (record 49 §8.3). The one single-player casualty of abandoning link is trade evolution, which §1 shows is already solved. Two residual cautions from the same analysis: if a fork ever grows `struct Pokemon`, the hard-coded 200 must move with it or the party exchange truncates — the kind of thing that bites years after a "harmless" struct change — and the in-game trade NPCs are *not* unaffected by evolution-data edits, because they run the same trade-evolution path (record 49 §8.4).

## 3. Patch formats: IPS, UPS, BPS, and why BPS won

The ecosystem distributes hacks as patches against a clean ROM. The formats differ structurally, not incidentally (record 49 §11.1–11.5):

| | IPS | UPS | BPS |
|---|---|---|---|
| Max addressable | **16 MiB** (24-bit offsets) | unbounded (VLV) | unbounded (VLV) |
| Verification | **none** | CRC32 × 3 (source/target/patch) | CRC32 × 3 |
| Expresses relocation | no | no (positional XOR) | **yes** (`SourceCopy`) |
| Reversible by re-application | no | **yes** (XOR is self-reversing) | no |

- **IPS** writes literal hunks at 24-bit big-endian offsets: a 16 MiB ceiling on a platform whose ROMs reach 32 MiB — a maximum-size GBA ROM is *twice* the addressable range — plus a 64 KiB per-record cap, an unrepresentable offset where a record start collides with the `EOF` footer, no source check, no target check — a patch applied to the wrong base ROM corrupts **silently** — and no way to express "this block moved" except rewriting it (record 49 §11.1).
- **UPS** fixes verification with three CRC32s — source, target, and the patch itself — and stores hunks as `source XOR target`, which makes the patch **self-reversing**: applying it to the patched file recovers the original. Variable-length integers remove the size ceiling. It is still positional — a block move is a full rewrite of both the vacated and occupied regions (record 49 §11.2).
- **BPS** encodes the steps to *build the target from scratch*, and its `SourceCopy` opcode expresses **relocation**: moving a block costs one action, not its length in literals. **Every recompile of a decomp fork relocates code and data — this is exactly the case IPS handles worst, and it is why BPS displaced IPS as the GBA default**, not fashion (record 49 §11.3, §11.5). xdelta/VCDIFF has the same expressive power with windowing for disc-sized inputs; at 16–32 MiB that consideration never arises, which is why it stayed a DS/ISO convention (record 49 §11.4).

**mGBA soft-patches automatically**: at load it looks for a sibling file with the ROM's basename and the suffixes **`.bps`, then `.ups`, then `.ips`** — first hit wins. And despite the file naming, **BPS is handled inside the UPS loader**: `patch-ups.c` checks both magics in the same function and dispatches to separate appliers, so all three formats work through two loader entry points, and anyone reading the loader file names alone would wrongly conclude BPS is unsupported (record 49 §12). The reference creator/applier for both IPS and BPS is Flips, which is in maintenance mode by its own README; RetroArch soft-patches all three formats plus XDelta1 (record 49 §12).

None of this is operational here. The project produces no patch for distribution at any point; a game's own `patches/<game>.patch` is a *source* patch inside the replay chain ([[build-system]]), not a ROM patch, and nothing Nintendo-derived leaves the machine.
