# poryrom — the harness

**This file is a MAP, not a manual.** Working rules live in skills, knowledge lives in
`docs/wiki/`. If something here needs more than a sentence or two, it belongs there and this
file gets a pointer.

## What this is

An expert Game Boy Advance ROM-hacking workbench, installed as a Claude Code plugin. It
scaffolds a game into its own repo, builds it in Docker, verifies it in a headless emulator by
reading the game's own memory, puts screenshots in front of the user, and deploys to a handheld.

**It is a tool, not a game.** Games live in their own repos beside it, each with a
`harness.json` that pins which version of this harness it was built against.

## Talk to the user in plain English

`skills/_shared/voice.md` is the rule and every skill loads it. Short version: no code in chat,
no symbol names, no file paths; lead with the answer; a few sentences by default; volunteer the
wall *before* their idea walks into it. **Precision belongs in the documents, never in the
reply** — this rule must never make a document vaguer.

## Where everything is

| | |
|---|---|
| `skills/` | the working rules. `_shared/voice.md` and `_shared/walls.md` are loaded by the others |
| `tools/` | the Python. `hx.py` answers "where is everything"; `doctor.py` answers "can this machine build" |
| `harness/` | the Lua the emulator runs. **It contains zero assertions, deliberately** |
| `docker/` | the build image, including the three patches this project added to mgba-headless |
| `verify/` | the harness's OWN checks — fixtures and stock-engine specs. A game's checks live in the game's repo |
| `fixtures.json` | every fixture fork, what wall it walks into, and the command that rebuilds it |
| `docs/wiki/` | maintained knowledge. **Read `docs/README.md` first** — it also explains the `(record NN)` citations |
| `templates/` | starter files a new game repo is scaffolded from |

## The three roots, which is the thing most likely to confuse you

- **The harness** — where the tools live. Correct even when running from a read-only plugin cache.
- **The workspace** — the game repo, found by walking up from the current directory for
  `harness.json`, the way git finds `.git`.
- **The engine cache** — `~/.poryrom/engines/<ref>`, a pinned clone shared by every game and
  living outside all repos.

`python3 tools/hx.py` prints all three. **Nothing that must not be redistributed may live inside
this repo**: installing a plugin copies its directory, so gitignoring is not protection.

## Rules that are not negotiable

- **Never commit a ROM, a savestate, a `.sav`, or captured audio.** The gitignore explains each.
  Nothing Nintendo-derived may ever enter this repository — it builds against a public engine
  cloned at setup time, and that engine and everything made from it stay outside.
- **The engine clone is read-only.** Edit a fork, never the reference.
- **`hacks/` is gitignored and disposable; the patch is precious.** A game's code exists in
  `patches/<game>.patch`, replay-checked. Refresh it after every green build — until then the
  work is on one disk.
- **Screenshots before playtests**, every changed state, saved into the game's design folder.
- **The Lua never asserts.** Every judgement happens outside the emulator, against values the
  Lua produced but did not interpret, and expectations it never saw.
- **Games built with this are for the builder.** The harness does not distribute games and must
  never help package one for distribution.

## Starting a session

Use the `session-start` skill: it runs `doctor.py`, checks the game's backup replays, and reads
where the game stands. Then say those three things in four sentences.

## Known and open

Savestate-based checks cannot run on a fresh machine: savestates are deliberately never
distributed, and regenerating a state re-rolls the boot RNG. Pinning the boot seed is the
highest-value open item. `docs/wiki/working-lessons.md` carries the rest of what this project
has learned about doing this work.
