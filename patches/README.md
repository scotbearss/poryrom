# `patches/` — the hack sources, as diffs against the pin

**Why this exists.** `hacks/` is gitignored wholesale, because a fork of
`pokeemerald-expansion` is Nintendo-derived and cannot go into this repo. That rule is right, but it
had a side effect nobody had accounted for: **the hack's own code — ours, entirely — existed in exactly
one place on one disk, tracked by nothing.** Slice 2 of `reps` was ~700 lines in that state.

A patch fixes it without breaking the rule. The diff carries **our lines**, plus the few lines of
context a patch needs to apply. The pin's source stays out of git; the fork stays disposable; the work
becomes recoverable.

**It also closes a gap the corpus already knew about.** `docs/58` recorded that a fresh fork
re-inherits engine defect E1 because *there is no patch queue across forks* — the fix had to be redone
by hand. These files are that queue.

## Recreating a hack from scratch

```bash
python3 tools/new_hack.py reps          # fresh fork of the pin at expansion/1.9.4
cd hacks/reps
patch -p1 < ../../patches/reps.patch
(cd ../../patches/assets/reps && tar cf - .) | tar xf -   # the binary sources; see below
docker run --rm -v "$PWD:/hack" -w /hack rombench-build:1 bash -c \
  'export PATH=/opt/devkitpro/devkitARM/bin:$PATH; make -j"$(nproc)" CPP="arm-none-eabi-cpp -std=gnu17" && make syms CPP="arm-none-eabi-cpp -std=gnu17"'
```

## Regenerating a patch — USE THE TOOL

```bash
python3 tools/export_hack.py reps
```

It diffs, classifies every binary as generated-or-source, copies the sources into
`patches/assets/reps/`, then **replays onto a clean extraction of the pin and byte-compares every
file**, refusing to leave a patch behind that does not come back identical. `--check` verifies the
existing patch and writes nothing.

**The hand recipe below is kept only as the record of what the tool automates. Do not run it.**
On 2026-08-03 it would have produced a patch that applied cleanly, with zero rejects, and rebuilt a
ROM with no building in Rustboro and no room behind the door — see `docs/65` §7. Three
specific traps, each of which the hand recipe walks straight into:

- **`diff -ruN` cannot carry a binary.** It prints `Binary files ... differ` and `patch` skips it.
  The first map added `data/layouts/<Map>/map.bin` and changed the host city's; neither would have
  travelled. Same shape as the moocalf sprite-PNG lesson, one class later.
- **`.pal` is CRLF and `patch` rewrites it LF-only** — moocalf's palette replayed at 190 bytes
  against the fork's 209, and had done since the day it landed. It was invisible because the asset
  copy ran afterwards and put the CRLF version back: the redundancy was the repair. `.pal`,
  `map.bin` and `border.bin` are now carried as assets only, so there is one mechanism instead of
  two that happen to cancel.
- **Path depth is load-bearing.** `diff` must run from `` with RELATIVE paths, or `patch -p1`
  lands on `engine/test/level_caps.c`, cannot find it, prompts `File to patch:` and
  non-interactively drops the hunks into `Oops.rej`.

<details><summary>the superseded hand recipe</summary>

```bash
cd pokemon && diff -ruN \
  -x build -x '.git' -x 'HACK_MANIFEST.json' \
  -x '*.a' -x '*.elf' -x '*.gba' -x '*.map' -x '*.sym' -x '*.sav' \
  -x 'events.inc' \
  engine/ hacks/reps/ > patches/reps.patch
```

`diff` exits **1** when it finds differences; that is success here, not failure. The exclusion list
grew twice by hand (`events.inc` at slice 3, the generated art at moocalf) and was one class short
both times — which is the argument for the tool, not against the list.

</details>

## Contents

| Patch | Covers | Files |
|---|---|---|
| `reps.patch` | `reps` slices 1-4 and the content phase: the level cap bound to banked minutes (`docs 59`), the real-RTC timed set that earns them (`docs 60`), the playtest fixes (`docs 62`), the EXP bar and the training card (`design/reps/reports/2026-07-30-pentagon-fidelity.md` §3b), the gym door's two locks (`docs 63`), slice 4's countdown audio and title, the Legs species line, and the RUSTBORO TRAINING ANNEX (`docs 65`) | **41 text + 24 assets** |

**One file in `reps.patch` is GENERATED, not written:** `include/training_card_panel.h`, the training
card's background panel art, comes from `tools/make_card_panel.py`. It is carried in the patch
because the patch is the only tracked copy of the fork and a build must not depend on remembering to
run a script — but **do not hand-edit it.** Change the generator and re-run:

```bash
python3 tools/make_card_panel.py --engine engine \
  --out hacks/reps/include/training_card_panel.h --preview /tmp/panel.png
```

The `--preview` PNG is worth taking every time: it is the cheapest look at the art there is, and on
2026-07-31 diffing it against an emulator screenshot is what located a scroll-register bug in one
command (`design/reps/reports/2026-07-30-pentagon-fidelity.md` §3b).

**Not covered:** the harness-fixture forks (`proofhack`, `symshift`, `e1bug`, `e1fix`, `redproof`,
`studio`). Those are disposable by design and their recipes are written up in docs `57`, `58` and `56`.
`reps` is the only fork that is a *game*.

## No longer by hand

`tools/export_hack.py` (2026-08-03) does the diff, the asset classification and the replay,
and **exits 2 rather than leave behind a patch that does not come back byte-identical**. It was
written the moment the hand recipe was about to lose a map (`docs/65` §7) — the
nothing-by-hand principle applied to the one artifact that is otherwise a single point of failure.

Verified beyond what the tool itself checks: a clean extraction of the pin + `reps.patch` + the
assets **builds to the same ROM**, sha `3b39e9bf55a0c068…`, with an identical link report.

**One trap from the old hand-verification loop, kept because it produced a false green.** The obvious

```bash
for f in $(grep '^diff ' patches/reps.patch | awk '{print $NF}'); do cmp ...; done
```

**does not work in zsh**, this project's shell: zsh does not word-split an unquoted parameter, so the
whole list arrives as ONE word and `cmp` compares one nonsense path. A verification step that
silently checks zero items is worse than none, because it prints what success prints.

## Binary sources: `patches/assets/<hack>/`

Moocalf (2026-08-02) was the first content to add BINARY sources to a fork — sprite PNGs, JASC
palettes, a cry sample — and `diff -ruN` cannot carry those (the patch says "Binary files differ"
and `patch` skips them). The fix: binary sources live under `patches/assets/<hack>/` mirroring the
fork's tree, and recreating a fork is now THREE steps — apply the patch, copy the assets over,
build:

```bash
patch -p1 < ../../patches/reps.patch
(cd ../../patches/assets/reps && tar cf - .) | tar xf -   # ALL of them, never a named subset
```

**Copy the whole tree, never a named subset.** The old recipe named `moocalf` explicitly and was
already two species out of date; by 2026-08-03 the asset set had also grown a class nobody had
anticipated — layout `map.bin`/`border.bin` and the JASC `.pal` files, which `patch` corrupts from
CRLF to LF. `export_hack.py` maintains this directory; a hand-named copy list is how content goes
missing.

The regeneration diff also excludes generated art (`*.4bpp`, `*.lz`, `*.gbapal`, `*.1bpp`,
`*.latfont`, `*.hwjpnfont`, `*.fwjpnfont`) — build outputs that sit in the source tree, same class
as `events.inc`. Verified 2026-08-02: fresh fork + patch (36 files) + assets → byte-identical
`pokeemerald.gba`.
