---
name: new-game
description: Start a brand-new GBA ROM hack — create its own repo beside the harness, fork the pinned engine, wire up the pin file and design doc, and build a first playable ROM. Use when the user says "start a new game", "new hack", "I want to make a game about...", or asks to set up a new project with rombench.
---

# New game

Load `../_shared/voice.md` first. This is often the user's first contact with the harness — the
whole session should read as an expert setting things up, not as a build log.

## Before anything

Run `python3 "$ROMBENCH/tools/doctor.py"`. If a blocking check fails, fix that first and say
so in one sentence. Do not start a game on a machine that cannot build one.

Ask them two things, in plain language, and nothing else:

- **What is the game called?** (a short name; it becomes the folder and the cartridge title)
- **What is it about?** (one or two sentences — enough to seed the design doc)

Do not ask about engines, versions, image tags or paths. You know those.

## What to create

A new repo **beside** the harness, at `~/Documents/GitHub/<game>/`:

```
<game>/
  harness.json          the pin file: game name, harness version, engine ref + cache, image
  CLAUDE.md             short: what this game is, where things are, current status
  .claude/settings.json declares this marketplace + enables the plugin
  design/               from the harness's templates/game-design/
  verify/               this game's checks
  patches/              the only tracked copy of the game's code
  saves/                savestate sidecars (the states themselves stay out of git)
  hacks/                the working copy — deliberately NOT in version control
  .gitignore            copy the harness's, which carries the reasoning in comments
```

`harness.json` is what makes every tool work from anywhere inside the repo — it is found by
walking up from the current directory, the way git finds its own folder. Record the harness
version so a future session is warned if the plugin has moved on.

Then: fork the pinned engine with `new_hack.py <game>`, set the cartridge title in the fork's
Makefile from the game's name, build it, and copy the ROM to the repo root as `<game>.gba`.

## What to tell them at the end

Four sentences at most: that the game exists and builds, where the file they play is (top of
their project folder, named after the game), what the first thing to decide is, and what you need
from them.

Then show them a screenshot of it booting.

## Worth knowing while you do this

- **The engine clone is shared between games** and lives outside any game repo. Cloning it takes a
  while the first time and no time afterwards.
- **The cartridge title is 12 characters** and is not the same thing as the file name. Set both.
- **Their game's code lives in `hacks/` which is not in version control** — that is deliberate,
  and it is why the backup patch is refreshed after every good build. Say this once, plainly, so
  they understand why that step keeps happening.
