# build-system

**What this page is for.** How a ROM actually gets built here, end to end: the one non-obvious flag
without which nothing compiles, the targets that exist and the ones that are dead at this pin, why the
symbol table is a *separate* build step and what a stale one does to a verification run, what `gbafix`
writes into the cartridge header, how a hack fork is made, and what this project has patched into the
emulator it builds. Read it when the build behaves strangely, when you are changing how it runs, or
before you trust a green result that came out of a tree you did not build yourself. The recurring
theme: **the build system is part of the source** — constants live in the linker script, features live
in a Dockerfile `sed`, and a build can succeed while being wrong.

Pin throughout: `pokeemerald-expansion` at `expansion/1.9.4`, commit `2e65627`, built inside our own
Docker image (devkitARM 20260610 / **GCC 16.1.0**).

---

## 1. THE MANDATORY FLAG

```bash
make -j"$(nproc)" CPP="arm-none-eabi-cpp -std=gnu17"
```

**Without it a clean `make` fails on every C file that reaches `include/gba/gba.h`** (record 54):

```
.../16.1.0/include/stddef.h:465:22: error: 'nullptr' undeclared here (not in a function)
  465 |   typedef __typeof__(nullptr) nullptr_t;
```

This is not a code bug and not a devkitARM bug. It is a **language-standard disagreement inside one
compile rule**. `Makefile:397` pipes three tools together:

```make
$(CPP) $(CPPFLAGS) $< | $(PREPROC) -i $< charmap.txt | $(CC1) $(CFLAGS) -o - -
```

`CFLAGS` (`Makefile:153`) carries `-std=gnu17`, so `cc1` sees `__STDC_VERSION__ 201710L`. `CPPFLAGS`
(`Makefile:141`) carries **no `-std` at all**, so `cpp` uses the compiler default — and **GCC 15
changed that default to `gnu23`**. GCC 16 therefore preprocesses at `202311L`, satisfies `stddef.h`'s
`__STDC_VERSION__ > 201710L` guard, and emits the C23-only `nullptr_t` typedef into a token stream
that `cc1` then compiles under gnu17. Verified directly with `arm-none-eabi-cpp -dM -E -`, not
inferred.

**Two pins that were each individually reasonable are jointly broken.** `Makefile:75` defines
`CPP := $(PREFIX)cpp` with a plain `:=`, so a command-line assignment overrides it cleanly: zero
source edits, zero patches, survives re-cloning the engine. The alternative — pinning an older
devkitARM for this mode — was deliberately not taken; revisit if a *second* GCC-16 incompatibility
appears, because one is a workaround and three is a wrong pin.

**It must be on `make syms` too.** `new_hack.py` writes both build commands into every fork's
`HACK_MANIFEST.json` specifically because this flag is the single most forgettable thing in this mode
(record 57).

## 2. Targets — what exists, what is a no-op, what is dead

`MODERN ?= 1` is the **default** (`Makefile:13`), so plain `make` *is* the modern devkitARM build and
`make modern` is a bare alias that changes nothing. `make agbcc` prints a deprecation notice and
exits 1 (record 44).

| Target | Effect |
|---|---|
| *(default)* `all` → `rom` | builds `pokeemerald.gba` (+ `.elf`, + `pokeemerald.map`) |
| **`syms`** | **generates `pokeemerald.sym` from the ELF. NOT run by `make`. See §3** |
| `compare` | sets `COMPARE=1` and appends a sha1 check. **Structurally cannot pass — §2.1** |
| `check` | builds the test ELF and runs the hydra runner. Needs `mgba-rom-test`, a different binary |
| `generated` | only **four** files: `wild_encounters.h`, `region_map_entries.h`, `map_groups.h`, `layouts.h` |

Clean-build wall time: **56.4 s on 10 cores** for the engine tree; **75 s** from a cold `git archive`
fork, which includes ~19 s of host-tool rebuilding (records 54, 57). Output is `pokeemerald.gba` /
`.elf` / `.map` at the repo root — **there is no `pokeemerald_modern.gba`**; `_modern` is only an
object-directory suffix (record 44).

Three environment facts that bite: **bash is mandatory**, not `sh` (`SHELL := bash -o pipefail`, plus
process substitution in the compile rule); **GNU Make ≥ 4.2** is effectively required, because
`.SHELLSTATUS` never gets set on Make 3.81 and a **host-tool build failure is then silently ignored**;
and `SETUP_PREREQS=1` (the default) runs sub-makes at Makefile *parse* time, so almost any invocation
rebuilds host tools and regenerates map sources before a single rule runs.

### 2.1 `make compare` is dead at this pin — never put it in a build script

`rom.sha1` holds `f3ae0881…`, which is **vanilla Emerald's** agbcc byte-match hash. Three independent
facts make it unpassable: `COMPARE=1` only appends a sha1 check and does not change the compiler; the
non-modern path is hard-disabled; and expansion is not vanilla Emerald. `INSTALL.md` never mentions it
(record 44).

**The correct clean-tree proof at this pin** is `git status --porcelain` on the pinned engine clone
plus a successful `make` and a boot proof. `make check` is the real equivalent of a regression gate —
see [[verification-discipline]].

## 3. `make syms` is a SEPARATE target, and a stale `.sym` is the quiet killer

```make
Makefile:307   syms: $(SYM)
Makefile:493   $(SYM): $(ELF)
Makefile:494   	$(OBJDUMP) -t $< | sort -u | grep -E "^0[2389]" | $(PERL) -p -e 's/…/\1 \2 \3 \4/g' > $@
```

**A plain build produces no `.sym` at all** (record 54 corrected the Slice 0 plan on exactly this
point — the harness would have found nothing). It is cheap: `$(SYM)` depends only on `$(ELF)`. Always
run it in the same invocation:

```bash
make -j"$(nproc)" CPP="arm-none-eabi-cpp -std=gnu17" && \
make syms         CPP="arm-none-eabi-cpp -std=gnu17"
```

### What a stale symbol table does — **SILENT, and it reports PASS**

Because `.sym` is a separate target, **`make` alone rebuilds the ROM and leaves the previous `.sym`
sitting next to it.** That is a stale pair with perfect filenames. The harness originally defaulted
`--sym` to the *engine's* table regardless of which ROM was under test, and record 57 §5b built a fork
(`symshift`) to demonstrate the consequence rather than assert it:

> A spec asserting a starter table the ROM under test **does not contain** reported **exit 0, 10 PASS
> / 0 FAIL**. Symbols had moved by 8 bytes of `.rodata` — 17,085 of them — and every probe read a
> plausible neighbouring address.

Record 72 later printed the sharpest version of the same failure: the harness read address `08203abc`,
which the correct table calls `CB2_TrainingMenuMain` and the stale one calls `CB2_InitTrainingMenu` —
a real, neighbouring, plausible function 364 bytes away.

**The fix, in two halves, because the first alone was not enough:**

1. **Defaulting** — `--sym` defaults to the ROM's own **sibling** `.sym`, never to the engine's.
2. **Content proof** — `rom_pair.py` verifies the triple *before a symbol is resolved or a docker run
   is spent*, by chaining through the ELF in both directions: every `PT_LOAD` segment's bytes must
   appear verbatim in the ROM at `p_paddr - 0x08000000` (that is exactly what `objcopy -O binary`
   emits; `gbafix -p` only pads the tail), every `.sym` line must name a symbol the ELF has at that
   **exact address and size**, and the reverse direction must cover ≥99 % so a truncated `.sym` is
   caught too. ~0.5 s, no cache, because a cache is one more thing that can lie.

If there is no ELF the tool **refuses**; it does not fall back to filenames or mtimes and call that
proof. `--allow-unmatched-sym` reproduces the old bug but prints, in those words, that the run's
verdict — PASS *or* FAIL — means nothing.

Two ELF details confirmed against the pin, each of which would otherwise reject every legitimate pair:
**ARM Thumb function symbols carry the low bit SET in `st_value`** (`AgbMain` is `0x08000459` in the
ELF and `0x08000458` in the `.sym`), and **section symbols have `st_name == 0`** and are printed by
objdump under their section's name.

### Parsing the `.sym` safely

Accept a line **iff** `^([0-9a-f]{8}) ([a-z!]) ([0-9a-f]{8}) (\S+)$` — address, objdump binding flag,
size, name — and **reject anything else loudly** (record 44 §8.4). The pipeline's `grep -E "^0[2389]"`
keeps EWRAM/IWRAM/ROM and drops everything else; note it keys on the **address column, not the
section**, so a linker absolute holding a ROM address survives while `gNumMusicPlayers = 4` does not.

Three hazards the grammar must handle:

- **`perl -p` prints every line whether or not the substitution matched.** Lines whose first flag char
  is `!`, or where objdump inserts a `.hidden`/`.protected` marker, land in the `.sym` **in raw objdump
  form with 6 fields instead of 4** — 80 such lines exist in the engine's own table (record 57). The
  grammar was later widened to read **100.00 %** of it (record 69).
- **Names are not unique.** Every file-scope `static` is emitted with flag `l` under its source name;
  build the table as name → list and make a multi-hit lookup an error.
- **ARM mapping symbols (`$a`/`$t`/`$d`) match the contract regex perfectly** and arrive as mass
  duplicate names. Filter names that are not valid C identifiers first.

**Addresses are per-build.** Re-read the `.sym` produced by the same invocation that produced the ROM;
never cache across edits — and never cache a save-block address at all, because those move at runtime
(see [[save-system]] and [[battle-engine]]).

`pokeemerald.map` is produced by *every* build. Use it for linker-defined symbols, per-section size
accounting, and confirming an input section was placed rather than `/DISCARD/`ed — not as the harness's
symbol source. The **test** link has no map at all.

## 4. `gbafix` and the cartridge header

`tools/gbafix/gbafix.c` is devkitPro's gbafix v1.07. The header is `0xC0` = 192 bytes, `#pragma
pack(1)`, and `src/rom_header.s` and the tool agree field-for-field (record 44 §11):

| Offset | Size | Field | Default |
|---|---|---|---|
| `0x04` | 156 | `logo` | **injected by gbafix on every run** |
| `0xA0` | 12 | `title` | **`POKEMON EMER`** (`Makefile:2`) |
| `0xAC` | 4 | `game_code` | **`BPEE`** (`Makefile:3`) |
| `0xB0` | 2 | `maker_code` | **`01`** (`Makefile:4`) |
| `0xB2` | 1 | `fixed` | **`0x96`, forced** |
| `0xB4` | 1 | `device_type` | `0x00`, forced |
| `0xBC` | 1 | `game_version` | `0` (`REVISION`, `Makefile:5`) |
| `0xBD` | 1 | `complement` | computed |
| `0xBE` | 2 | `checksum` | **always `0x0000` — never computed** |

**The complement covers `0xA0..0xBC` — 29 bytes**, title through version:
`complement = (-(0x19 + Σ bytes)) & 0xFF`. Three consequences: the **logo field is not covered**, so a
post-build logo edit needs no fixup; `start_code` is not covered either; and the 16-bit body checksum
at `0xBE` is zeroed and the computing call is commented out, so **nothing in a built ROM validates its
own body**.

**gbafix runs twice** — once on the ELF with `-t -c -m -r --silent` (finding the header via the first
`SHT_PROGBITS` section whose `sh_addr == e_entry`), and once on the `.gba` with `-p --silent`. The
second call re-reads the on-disk header and only overwrites fields whose flags are present, so the
title/code/maker/version from the first call survive — but **the logo, `fixed` and `device_type` are
re-forced every single time**. Blanking the logo between the two calls would simply be undone. `-p`
pads with `0xFF` to the next power of two (which is why the ROM is 32 MB), and is refused on an ELF.

**`make check` ships a deliberately corrupted logo.** `-d0` on the test ELF writes `0xA5` over ROM
offset `0x9C`, inside the logo field. Keep that in mind when hashing headers.

Header title `POKEMON EMER` and game code `BPEE` were both read back off a real build (record 54).

## 5. The linker script is source

`ld_script_modern.ld` is where the ROM/RAM regions live (`ROM (rx) : ORIGIN = 0x8000000, LENGTH =
32M`) and where `src/rom_header.o(.text*)` is forced first at `ORIGIN(ROM)`. It is also where at least
one engine *constant* lives:

```
ld_script_modern.ld:3   gNumMusicPlayers = 4;
ld_script_modern.ld:4   gMaxLines = 0;
```

These are **linker absolutes whose ADDRESS is the value** — `NUM_MUSIC_PLAYERS` is
`((u16)gNumMusicPlayers)` over an `extern char[]`. There is no object, no initialiser, and no `4`
anywhere near the name in C. A prior session grepped `src/` and `sound/`, found nothing, and correctly
filed the claim unestablished; the fix was to widen the search (records 51, 76). **When a constant
cannot be found in the source, look in the build files.** See [[audio]].

Line 5 is `gInitialMainCB2 = CB2_InitCopyrightScreenAfterBootup;` — and `ld_script_test.ld:5` sets it
to `CB2_TestRunner` instead. **That is how the test build swaps the boot callback without touching a
line of C**, and because the value is a ROM address it survives the `.sym` filter: reading it back is a
cheap proof of which link script produced a given ROM.

### **The `/DISCARD/` trap** — **SILENT**

The script ends `/DISCARD/ { *(*) }`. **An input section whose name *or whose object path* is not
matched by one of the placement patterns vanishes with no link error.** Concretely: `EWRAM_DATA` in a
new file under `data/` rather than `src/` is discarded, because `.ewram.sbss` lists only
`src/*.o(.sbss)`. Record 44 calls this its clearest build-succeeds-while-wrong case.

Ignore `sym_bss.txt` / `sym_common.txt` / `sym_ewram.txt` and `ramscrgen`: `LD_SCRIPT_DEPS` is empty on
the modern path, so they never run. If a contract-check ever reports them touched, someone re-enabled
agbcc.

**Read the link report on every build.** A vanilla expansion build with zero hack content already
reports EWRAM 245,778 B (**93.76 %**), IWRAM 30,492 B (**93.05 %**), ROM 25,850,288 B (77.04 %) — about
16 KB of EWRAM and 2 KB of IWRAM of headroom before you add anything. It is printed for free on every
build and it is the cheapest early warning available (record 54). Full budget picture:
[[walls-and-budgets]].

**A build fact that will cost you an afternoon:** a fork global with a **non-zero initialiser** in an
IWRAM translation unit lands in a `.data` section this link **discards**, and the build dies with
`defined in discarded section`. Zero-initialised globals are fine — invert the flag's meaning rather
than fighting it (record 78).

## 5a. Codegen and dependency scanning — where wrongness hides

The build drives `cpp → preproc → cc1 → as` by hand rather than using the `gcc` driver, and runs
`preproc` **twice** around `cpp` for assembly under `src/` and `data/`. Twelve host tools do the
codegen: `preproc`, `scaninc`, `gbafix`, `gbagfx`, `mid2agb`, `aif2pcm`, `jsonproc` (the only C++17
one), `mapjson`, `ramscrgen` (dead), `trainerproc`, `rsfont`, `bin2c`.

Four quiet behaviours worth knowing (record 44):

- **`preproc` does not skip comments.** Its scanner is character-level, not a C parser. A `_("…")` or
  `INCBIN_U8("…")` inside a commented-out block is still expanded, and a *missing* file named in a
  commented-out `INCBIN` **still aborts the build**. `scaninc`'s near-identical scanner *does* strip
  comments — **the two tools genuinely disagree about commented-out code.**
- **`INCBIN_*` files are read at preproc time**, which is why every generated `.4bpp`/`.gbapal`/`.lz`
  must exist before `src/graphics.c` compiles — and why **a missing asset surfaces as a `preproc`
  error, not a linker error**.
- **`scaninc` silently skips an unresolvable include** and evaluates **no conditionals at all** — every
  textual `#include` becomes a dependency even inside `#if 0`. That direction over-approximates and is
  safe. **The unsafe direction is an include whose path comes from macro expansion**: scaninc cannot
  see it and the file will not trigger a rebuild. The Makefile contains an in-tree admission of
  exactly this, with the comment *"hacky, but we want to depend on everything event_scripts.s depends
  on without having to alter scaninc"*.
- **A stale host tool.** `tools/preproc` `#include`s the *game's* `include/constants/characters.h` for
  `CHAR_SPACE`, but its own Makefile lists only its own sources as prerequisites. **Editing that header
  does not rebuild `preproc`**, so a hack that renumbers a control character silently keeps using the
  old value until someone runs `make clean-tools`.

**Two ways a successful build dirties the tree**, both of which break a naive
`git status --porcelain` clean-tree gate: `KEEP_TEMPS=1` writes `.i`/`.s` temps to the **repo root**
(and there is no `*.s` gitignore rule), and **three build-generated headers are tracked in git anyway**
(`src/data/trainers.h`, `battle_partners.h`, `teachable_learnsets.h`), so editing a `.party` source
produces a git diff in the corresponding `.h`. `mid2agb` likewise writes generated `.s` back into
`sound/songs/midi/` — that one *is* ignored. See [[audio]].

## 6. Forking: `git archive`, not `cp -r`

`new_hack.py <name>` produces `hacks/<name>/` in **2.6 s / 23,145 files** by piping
`git archive HEAD | tar -x` (record 57).

**This is not a performance choice.** The archive contains exactly the tracked tree at the pinned
commit, which means `.git`, `build/`, `pokeemerald.gba`, `pokeemerald.sym`, `pokeemerald.map` and the
compiled host tools under `tools/*/` are **absent because they were never in it** — nothing has to be
excluded by name, so nothing can be forgotten. The cost is ~19 s of host-tool rebuilding on the first
build; the benefit is that **a fork can never inherit a stale artifact from a tree it is not a copy
of.**

Three further decisions inside the tool:

- **It refuses a dirty engine tree.** If the reference clone has uncommitted changes the manifest's
  `base_commit` would not describe the bytes copied, and *a provenance record that can lie is worse
  than no record*. `--allow-dirty` overrides and records `base_tree_dirty: true`. The refusal doubles
  as a tripwire — the reference clone is read-only by policy, so a dirty one is itself the bug.
- **It writes `HACK_MANIFEST.json`**: base commit, tree sha, `git describe`, upstream remote, the
  sha256 of the engine's own ROM and `.sym`, file count, and both build commands including §1's flag.
- **The fork has no `.git` and no remote**, on purpose. It cannot push anywhere.

**Same-commit reproducibility is measured, not assumed.** A stock ROM built in one session from the
engine tree with host tools already compiled, and a hack ROM built in a later session from a fresh
`git archive` extraction with host tools rebuilt from scratch, differed in **exactly the one byte that
was deliberately edited**, with byte-identical `.sym` files (record 57). Several later rounds replayed
a generated fork from a fresh extraction to a **byte-identical ROM sha256** — which is what earns a
generator the word *disposable* and lets a fork ship with no tracked patch at all (record 76).

One surprise worth knowing: `verify_hack.py` writes `build/_probe_data.lua`, `DONE` and the screenshot
into the **engine's** `build/` even when the ROM under test lives elsewhere, because the engine is
mounted for the Lua's `dofile`. That is scratch output inside an already-gitignored directory, not a
source edit.

### 6.1 Restoring a fork from its backup: `restore_hack.py`

`hacks/` is gitignored, so a fresh clone of a game repo has **no working copy at all** — the only
tracked form of the work is `patches/<name>.patch` plus `patches/assets/<name>/`.
`restore_hack.py <name>` rebuilds `hacks/<name>/` from exactly that: `git archive` of the pinned
engine, `patch -p1 --forward`, then the binary assets copied over the tree. It is `export_hack.py`'s
replay recipe running as a first-class tool — **literally the same function**
(`export_hack.materialize`), so the backup that export proved replayable is by construction the one
this restores. Record 85 §3 rehearsed the recipe by hand before the tool existed: 86 files,
**0 rejects**, and the rebuilt ROM came out **byte-identical** (`42c8d33c…`) to the canonical one.

Manners match `new_hack.py`: an existing `hacks/<name>/` is never touched without `--force`. And the
ordering is the same safety property export writes its patch last for: the tree materializes fully in
a scratch directory inside `hacks/` and only then replaces the old fork — a restore that rejects
leaves `hacks/` exactly as it was, old fork included. The restored tree gets a `HACK_MANIFEST.json`
recording `forked_by: tools/restore_hack.py`, `restored_from`, and the engine commit it was restored
against.

One trap on a fresh machine, which `doctor.py` now names up front (record 85 §4): a freshly cloned
engine is **unbuilt**, and the build writes generated files *into* the source tree. Build a fork
before building the engine and the first backup refresh stops on `export_hack.py`'s
build-state-mismatch guard (record 82 §4.3) — working as designed, but ~10 minutes after feeling
done. Doctor's soft **"engine clone built"** check says so before the bump, with the engine's Docker
build command as the remedy.

## 7. The Docker image, and the three patches to `mgba-headless`

The build and the emulator both run inside one image we build ourselves. That fact is load-bearing:
**when a limit is attributed to a tool, check whether the tool is one of ours** (record 73). Three
separate "structural" limits turned out to be six-line patches.

| # | Patch to `headless-main.c` | Why | Record |
|---|---|---|---|
| 1 | **video buffer** | `emu:screenshotToImage()` returns nothing otherwise | 54 |
| 2 | **`mCoreAutoloadSave` gate** | headless never attached a save file to disk, so cross-process `.sav` persistence was filed as structurally blocked. Gated on `MGBA_HEADLESS_AUTOLOAD_SAVE`; opens with `O_CREAT` beside the ROM, so the caller must put the ROM somewhere writable | 73 |
| 3 | **`mAVStream` audio tap** | headless has **no audio option whatsoever**; `mCore` exposes `setAVStream` and `mAVStream` carries `postAudioFrame`, so a stereo PCM tap is a callback, not a fork. Gated on `MGBA_HEADLESS_AUDIO_OUT` | 76 |

Every gate is an **environment variable**, so an unset run is byte-identical to every run recorded
before it — verified by re-running a prior baseline against the rebuilt image and getting identical
results.

### **A `sed` in a Dockerfile whose anchor stops matching exits 0 and silently does nothing**

> The image builds, the feature is silently absent, and everything downstream reads as a working build
> with a missing feature. **Every patch in a build file needs a `grep -q` after it, in the same `RUN`,
> so a non-match is a failed image build.** The `videoBuffer` patch had gone four months without one
> (record 73).

Same shape as the Python edit script that asserted only "the file changed" after several replacements
— assert **per replacement**, and assert the **end state** ("is this line now correct?") rather than a
change, because only the end-state form survives re-running the tool. All three seds are now asserted
(record 76).

Two more emulator-invocation traps, both of which look like a broken ROM:

- **`console:log` from a Lua script is invisible at `-l 7`.** It needs **`-l 15`** (adds INFO). Cost
  one failed run to find (record 54).
- **mgba-headless is muted by default** — with no config file on disk, `opts.volume` is zero, and an
  audio capture comes back as flawless silence that PASSES. Fixed with `-C volume=256 -C mute=0`. See
  [[audio]].

**Host requirements the engine's own `INSTALL.md` understates:** a C++17 host compiler (`jsonproc`
alone), libpng + zlib + **pkg-config** (without it `$(shell pkg-config …)` expands to empty and may
still succeed on Debian — a latent, silently platform-dependent failure), libm, coreutils `stdbuf`
(`make check` only), **perl** (used by exactly one rule: `$(SYM)`), and python3 (record 44 §4).

## 8. Ways a build succeeds while being wrong

The list, because every entry cost someone a session:

- **A stale `.sym`** — every probe reads a plausible neighbouring address and the run reports PASS
  (§3).
- **An unapplied Dockerfile `sed`** — the image builds and the feature is absent (§7).
- **A missing `make syms`** — no symbol table at all, which at least fails loudly; the dangerous case
  is the *old* one still sitting there.
- **`make check` unbuildable after a rename** — a suite that cannot build looks exactly like a suite
  nobody ran. It had been unbuildable for two slices while the notes recorded it green
  ([[verification-discipline]]).
- **A struct field inserted mid-struct** where assembly hardcodes offsets — nothing complains and the
  scripts read the wrong bytes. Now a compiler-checked claim; see [[battle-engine]].
- **A discarded section** — `EWRAM_DATA` under `data/` instead of `src/` links cleanly and is gone
  (§5).
- **A stale host tool** compiled against a game header you have since edited (§5a).
- **A dependency the scanner cannot see**, so the file never rebuilds (§5a).
- **A generated table missing a row** where the array size is implicit — every read past that index is
  out of bounds, with no blank slot to notice ([[walls-and-budgets]]).
- **Two copies of one constant in two bases** — a magic value written hex in source and decimal in an
  inert JSON spec; the hand conversion was wrong and a correct build failed its own test. Harmless in
  that direction, a **false PASS** in the other.

`make check` is the intended regression gate but has its own containerisation problem: the in-tree
`tools/mgba/mgba-rom-test` is a **prebuilt Linux x86-64 ELF** — no macOS and no arm64 binary — and our
image builds `mgba-headless`, a *different* binary that this target does not accept. The runner also
`execlp`s `patchelf` and `stdbuf` by relative path, so it only works with `cwd` = the repo root.

---

**See also:** [[verification-discipline]] · [[walls-and-budgets]] · [[save-system]] ·
[[battle-engine]] · [[audio]] · [[maps-and-tilesets]] · [[engine-defects]] · [[art-pipeline]] ·
[[dialogue-voice]]
