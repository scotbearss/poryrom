---
name: build-and-verify
description: Build a GBA ROM hack and prove the change actually works — run the static checks first, build in Docker, verify in a headless emulator, put screenshots in front of the user, and refresh the backup. Use after editing anything in a game's source, when the user says "build it", "does it work", "test this", "make the ROM", or before any playtest or deploy.
---

# Build and verify

Load `../_shared/voice.md` first. Consult `../_shared/walls.md` whenever the change touches maps,
sprites, NPCs, sound, items, saves or battles — and say the relevant wall **before** building,
not after.

## The order is the point

**1 — Static checks BEFORE the build.** Whichever apply to what changed:

- `check_map.py` — map contracts, baseline-diffed against the original
- `check_dialogue.py` — does the writing sound like the game, measured against its own corpus
- `check_tilesets.py`, `check_behaviors.py` — tileset and behaviour budgets

These run before compiling for a reason: **a fault that renders as plausible content cannot be
caught by looking at the result.** An oversize map draws as a perfect empty field. Bad dialogue
renders beautifully. There is no wrong *number* in either — only a check that runs first can see
them.

**2 — Build.** In the container, from the game's fork:

```
make -j"$(nproc)" CPP="arm-none-eabi-cpp -std=gnu17"   # then: make syms CPP=...
```

The `CPP=` is required, and `make syms` is a **separate target** — the symbol table is what every
later check reads addresses from, and a build without it leaves a stale one behind that will
resolve probes against the wrong build.

**3 — Verify.** `python3 "$PORYROM/tools/verify_hack.py" <spec>`. Each spec names the ROM it
needs, so you do not pass one. Specs that resume from a saved state need that state to exist —
if it does not, say so rather than reporting a pass.

**4 — Screenshots, before they play it.** Required, not a courtesy. Save the PNG into the game's
design folder under `reports/assets/`, then put it in chat and say what changed and what you want
them to look at. Every state you touched, plus the ones beside it.

**5 — Refresh the backup.** `export_hack.py <game>` after a green build. The working copy is not
in version control; until this runs, the change exists on exactly one disk.

**6 — Regenerate the dex site.** `python3 "$PORYROM/tools/make_dex.py"` after a green build.
The site at `<game>/dex/` is the user's progress tracker — every new and changed species, derived
from the same source the build compiled, so it can never disagree with the ROM. It is gitignored
(it contains sprites); it regenerates in seconds, so never skip it to save time.

**7 — Put the ROM where they can reach it.** Copy the built ROM to the game repo root as
`<game>.gba`, replacing what is there. That is the file they pick up to test — it must be at the
top of their project, named after their game, and never stale.

## Rules that have been paid for

- **Never report a check as passing when it did not run.** Skipped and passed look identical in a
  summary and only one is true.
- **A verification harness proves the program does what you told it.** It cannot tell you that you
  told it the wrong thing, and it cannot see a screen that is merely wrong-looking. That is why
  step 4 exists and why it is not optional.
- **If a result surprises you, check the fixture before writing the headline.** A test that
  produces a state the real game cannot reach yields a dramatic, false finding.
- **Two runs must not share the scratch directory.** Concurrent verification produces a confident
  wrong answer rather than an error.
- **When a build changes anything's size or numbering, ask what STORES that value** — not what
  references it. That is where saves get quietly invalidated.
