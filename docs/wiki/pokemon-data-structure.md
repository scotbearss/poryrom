# The Pokémon data structure

**What this page is for.** The byte-exact layout of a Pokémon in RAM — the 100-byte party mon and the 80-byte box mon — and everything a harness needs to read one safely from outside the game: the XOR key, the checksum, the 24-way substructure permutation, and the expansion-era traps that make Gen 3 folk knowledge wrong at this pin. The headline trap is stated early because every external tool trips on it: **nature and shininess are no longer pure PID derivations** — each has a stored XOR modifier in the plaintext header, and a reader that recomputes them from the PID alone is wrong for any mon that has ever been modified (record 40 §5, §8.7).

Pin: `expansion/1.9.4`, `2e65627`. Related: [[save-system]], [[verification-discipline]], [[battle-engine]].

> **Evidence caveat, before any offset below is trusted for a write.** Every offset on this page is *(derived)* — computed from the field declarations under ARM EABI bitfield rules and cross-checked against the authors' own `unused_NN` field names, which independently encode the offsets they intended. **None has been read out of a compiled binary.** Record 40 §9.1 names compiled verification (`pahole`, `gdb ptype /o`, or an `offsetof` static assert in a scratch fork) as the single highest-value follow-up, and it is one build away. Where the record marks a claim *(unverified)*, this page carries the mark forward.

---

## 1. The two structs

| | Size | Contents |
|---|---|---|
| `Pokemon` (party) | **100 B (0x64)** | a `BoxPokemon` plus a plaintext tail of battle state |
| `BoxPokemon` | **80 B (0x50)** | plaintext header + 48-byte encrypted region |

Both sizes are unchanged from vanilla Gen 3 (record 40 §0). Expansion did not grow the byte budget; it **re-purposed vanilla padding and reserved bits**, which is exactly why the modifier fields of §3 exist and why "vanilla plus extended fields" is the wrong mental model (record 40 §0).

`gPlayerParty` and `gEnemyParty` are each 6 × 100 = 600 B (0x258), zero-init EWRAM symbols that survive the `.sym` filter with their sizes — which makes the size a free hard assertion: if `gPlayerParty` does not read 0x258, the stride changed and every offset here is suspect (record 40 §1.3, §7.2). *(The size field appearing non-zero in an actual built `.sym` is (unverified) at this pin — record 40 §9.2.)*

### 1.1 The `BoxPokemon` plaintext header

| Offset | Field | Notes |
|---|---|---|
| 0x00 | `personality` (PID), u32 | half of the key |
| 0x04 | `otId`, u32 | other half; TID = low half, SID = high |
| 0x08 | `nickname[10]` | **chars 11–12 live inside the encrypted Growth substruct** — reading +0x08 alone silently truncates (record 40 §8.10) |
| 0x12 | `language` bits 0–2, **`hiddenNatureModifier` bits 3–7** | see §3.1 |
| 0x13 | `isBadEgg` bit 0, `hasSpecies` bit 1, `isEgg` bit 2, … | `hasSpecies` is the empty-slot gate |
| 0x14 | `otName[7]` | |
| 0x1B | `markings` bits 0–3, `compressedStatus` bits 4–7 | the nibble is a lossy index, not a bitmask; party status lives at +0x50 (record 40 §1.4) |
| 0x1C | `checksum`, u16 | plaintext, over the *decrypted* payload |
| 0x1E | **`hpLost` bits 0–13, `shinyModifier` bit 14** | see §3.2 and §5 |
| 0x20–0x4F | `secure` — the encrypted region | 4 × 12-byte substructs, order permuted |

(All from record 40 §1.1–1.2.)

### 1.2 The party-mon fast path

Everything after the embedded `BoxPokemon` is plaintext — no key, no checksum, no permutation:

| Offset | Field |
|---|---|
| +0x50 | `status` (u32, full `STATUS1_*` mask) |
| +0x54 | `level` (u8) |
| +0x56 / +0x58 | `hp` / `maxHP` (u16) |
| +0x5A, 0x5C, 0x5E, 0x60, 0x62 | attack, defense, speed, spAttack, spDefense (u16) |

If an assertion only needs level, HP or stats, stop here (record 40 §1.3, §7.2 step 4).

---

## 2. Encryption, checksum, permutation

### 2.1 The key

Bytes 0x20–0x4F are XOR'd with `key = personality ^ otId`, applied **per 32-bit little-endian word** over the raw `u32[12]` view — not the permuted view. Encrypt and decrypt are the same involution. A harness decrypts the whole 48 bytes first and permutes afterwards; the two steps commute only because the permutation moves whole 3-word blocks (record 40 §2.1).

### 2.2 The checksum

A **16-bit truncating sum of the 24 decrypted little-endian `u16` halves**, stored plaintext at +0x1C. Accumulation is in a `u16`, wrapping mod 2¹⁶ — no fold, no complement, no seed. Because the four substructs are simply summed, **the checksum is order-independent**: a tool may sum the flat decrypted 48 bytes without applying the permutation at all; the engine's four `GetSubstruct` calls there are redundant work, not a semantic requirement (record 40 §2.2). It is verified on **every** encrypted read and write, and a mismatch has an irreversible consequence — §4.

### 2.3 The substructure permutation

The four 12-byte substructs — **G**rowth, **A**ttacks, **E**Vs/Condition, **M**isc — occupy slots in an order selected by `PID % 24`. There is **no permutation array symbol at this pin**; the table below is derived from a `switch` built by the `SUBSTRUCT_CASE` macro, and the guessed name `gSubstructPermutations` does not exist (record 40 §6.1, §8.2). The source args `(v1,v2,v3,v4)` mean "type *t* lives in slot *v[t]*"; the slot-order string is the *(derived)* inverse (record 40 §6.2). Byte address of type *t* at base *B*: `B + 0x20 + 12·v[t]`.

| `PID % 24` | `(v1,v2,v3,v4)` | Order | | `PID % 24` | `(v1,v2,v3,v4)` | Order |
|---|---|---|---|---|---|---|
| 0 | 0,1,2,3 | GAEM | | 12 | 1,2,0,3 | EGAM |
| 1 | 0,1,3,2 | GAME | | 13 | 1,3,0,2 | EGMA |
| 2 | 0,2,1,3 | GEAM | | 14 | 2,1,0,3 | EAGM |
| 3 | 0,3,1,2 | GEMA | | 15 | 3,1,0,2 | EAMG |
| 4 | 0,2,3,1 | GMAE | | 16 | 2,3,0,1 | EMGA |
| 5 | 0,3,2,1 | GMEA | | 17 | 3,2,0,1 | EMAG |
| 6 | 1,0,2,3 | AGEM | | 18 | 1,2,3,0 | MGAE |
| 7 | 1,0,3,2 | AGME | | 19 | 1,3,2,0 | MGEA |
| 8 | 2,0,1,3 | AEGM | | 20 | 2,1,3,0 | MAGE |
| 9 | 3,0,1,2 | AEMG | | 21 | 3,1,2,0 | MAEG |
| 10 | 2,0,3,1 | AMGE | | 22 | 2,3,1,0 | MEGA |
| 11 | 3,0,2,1 | AMEG | | 23 | 3,2,1,0 | MEAG |

Store it as a literal 24×4 array; do not try to compute it (record 40 §7.2 step 9). The permutation lookup uses only the plaintext PID, so lookup and decryption are independent and can be done in either order (record 40 §6.2).

---

## 3. The stored modifiers — where Gen 3 intuition breaks

Both live in the **plaintext** header, so a harness pays nothing to read them. The engine's own `UpdateMonPersonality` is the proof they are load-bearing: before rewriting a PID it captures shininess, hidden nature and tera type, and re-applies them after — a reader deriving them from the PID alone reproduces exactly the bug that function exists to prevent (record 40 §2.2).

### 3.1 Nature

`PID % 25` is still the *visible* nature, but the nature the game uses for stat calculation is that value **XOR the 5-bit `hiddenNatureModifier` at +0x12 bits 3–7** — written by the Mint item, decoupled from the PID by the expansion's own tests (record 40 §5.1, §8.7).

> effective nature = `(PID % 25) XOR ((byte@0x12 >> 3) & 0x1F)`

### 3.2 Shininess

The threshold is untouched: `(TIDhi ^ TIDlo ^ PIDhi ^ PIDlo) < 8`, `SHINY_ODDS` still 8/65536 — the suspicion that expansion changed it is corrected in the record (record 40 §5.2, §8.8). What changed is (a) a stored override, **bit 14 of the u16 at +0x1E**, XOR'd onto the PID-derived bit, and (b) the *probability*, raised by rerolling the PID at creation (Shiny Charm +2 rolls, lure +1, fishing chains) rather than by moving the threshold. Forced-shiny config flags land in the modifier bit, not the PID (record 40 §5.2).

> effective shiny = `((TIDhi^TIDlo^PIDhi^PIDlo) < 8) XOR ((u16@0x1E >> 14) & 1)`

---

## 4. The bad egg, and how to read without creating one

Exactly one trigger exists: on every encrypted read or write, the engine recomputes the checksum, and on mismatch it sets `isBadEgg` and `isEgg` — **without recomputing the checksum**, so every later access re-detects the mismatch. It also sets the *inner* egg flag inside the decrypted Misc payload, drifting the true checksum further from the stored one. Species reads become `SPECIES_EGG`; the write path refuses encrypted writes entirely. Irreversible in normal play — though not structurally sealed, since the stored checksum itself is a plaintext field and remains writable by a caller that knows the true value (record 40 §2.3). The displayed name comes from `gText_BadEgg`; the symbol `gBadEggNickname` that an earlier brief guessed does not exist (record 40 §8.3).

Two rules for an external reader follow directly:

- **A checksum mismatch is ambiguous on first sight.** The engine leaves a mon decrypted for the duration of one C call, so a mid-read snapshot can look corrupt. Retry with the XOR applied a second time — i.e. treat the 48 bytes as already plaintext — and if *that* passes, you caught a decrypted snapshot; re-read next frame instead of reporting corruption. Only a double failure, cross-checked against the `isBadEgg` bit at +0x13, is a genuine bad egg. *(That a frame-boundary Lua callback cannot land mid-call is (unverified) — the retry is the cheap mitigation regardless; record 40 §2.3, §7.2 step 8, §9.5.)*
- **Never write a decrypted word without recomputing the checksum.** The harness is read-only; a raw write converts the mon into a permanent bad egg (record 40 §7.2 step 12).

---

## 5. Reading a boxed mon

Three differences from the party path, each of which silently produces garbage if missed (record 40 §7.5):

1. **The base is a pointer, dereferenced on the frame of use.** `gPokemonStoragePtr` lives in IWRAM; the storage block behind it is ASLR'd over 32 placements exactly like the save blocks — see [[save-system]] §5 for the mechanism and when it re-rolls. Never use the backing array's symbol address, and never cache the dereferenced value across frames.
2. **The stride is 80, not 100.** Slot address: `M = P + 4 + 2400·box + 80·slot` (boxes 0–13, slots 0–29). The empty-slot gate, key, checksum, permutation and modifier XORs are all identical to the party path — everything lives in the first 0x50 bytes. Never index past `M + 0x4F`.
3. **There is no cheap path.** A box mon has no level, HP or stats. The only HP-ish plaintext is **`hpLost`, bits 0–13 of the u16 at +0x1E**, storing `maxHP − hp`. Converting it to absolute HP needs `maxHP`, which for a boxed mon exists only as a computation over ROM-side species tables — second-tier territory. **`hpLost == 0` ⇔ full health is exact and needs no ROM tables**, and is the one cheap full-health assertion a box mon offers (record 40 §1.2, §7.5).

---

## 6. What the PID still decides

The formulas that remain purely PID-derived, each with its exactness (all record 40 §5.3–5.8):

- **Gender** — female iff `genderRatio > (PID & 0xFF)`, **strictly greater**, after the sentinels `0x00`/`0xFE`/`0xFF` (all-male / all-female / genderless) short-circuit. The strict comparison makes a 0x1F ratio yield 31/256, not 32 — a real off-by-one against the naïve reading, inherited from vanilla. No stored gender modifier exists at this pin *(verified by absence in the declarations)* (record 40 §5.4). Needs ROM-side species data, so it is a second-tier assertion for a harness.
- **Ability slot** — `abilityNum` is a **2-bit stored field** (Misc word @0x08, bits 29–30), seeded from `PID & 1` at creation **only if the species has a second ability**, and fully independent of the PID thereafter (Ability Capsule/Patch, breeding). "Ability = PID bit 0" is wrong at read time (record 40 §5.3, §8.9). Resolving the slot to a concrete ability requires the engine's two fallback sweeps over sparse ability tables, or the harness will disagree with the game.
- **Wurmple branch** — Silcoon iff `((PID >> 16) % 10) ≤ 4`. The domain is a u16, and 65,536 does not divide by 10: Silcoon gets 32,770/65,536 (50.003%), Cascoon 32,766 *(derived)*. Not to be confused with the family-of-four rule in the same block, which uses the *full* PID mod 100 (record 40 §5.7).
- **IVs at creation** — one `Random32()`, three 5-bit IVs from each 16-bit half in HP/Atk/Def then Spe/SpA/SpD order, top bit of each half unused. Then two **mutually exclusive** overrides: `allPerfectIVs` forces all six and consumes nothing further; *else* the legendary path forces **3** randomly chosen perfect IVs and consumes **3 extra `Random()` calls** in doing so. Reading the overrides as sequential desynchronises any RNG replay (record 40 §5.8).
- Unown letter and default tera type are also PID-derived; the tera default applies only while the stored `teraType` is `TYPE_NONE` (record 40 §5.5–5.6).

Stored EVs and IVs use the Gen 3 stat order — HP, Attack, Defense, **Speed**, Sp.Atk, Sp.Def, with Speed third — the single most common off-by-one in third-party Gen 3 tooling (record 40 §3.3).

---

**Related:** [[save-system]] · [[verification-discipline]] · [[battle-engine]] · [[engine-defects]]

**Records distilled here:** 40 (the byte-exact brief, source-derived, offsets not yet compiled-and-dumped — its §9.1 follow-up is still open), 41 §5.4 via [[save-system]] (the ASLR mechanism the box path depends on).
