# rombench

An expert Game Boy Advance ROM-hacking workbench, installed as a Claude Code plugin.

It scaffolds a game into its own repo, builds it in Docker, **verifies changes in a headless
emulator by reading the game's own memory**, puts screenshots in front of you before you
playtest, and deploys to a handheld. It is a tool, not a game: games live in their own repos
beside it, each pinned to the harness version it was built against.

## What makes it different

Most ROM-hacking setups can build. This one can **prove**. Every change is checked by a spec
file that boots the ROM in a headless [mGBA](https://mgba.io), reads named symbols out of RAM
at chosen frames, and judges the values *outside* the emulator — the Lua that runs inside
contains zero assertions, deliberately, so the instrument can never decide its own verdict.
Counterfactual specs (the same check pointed at an unpatched ROM, expected to fail) keep the
checks themselves honest.

Around that core:

- **The patch is precious, the working copy is disposable.** A game's code exists as a replayable
  patch against a pinned public engine; the backup tool refuses to write a backup that would not
  replay byte-for-byte.
- **The walls are written down.** Years of measured engine limits — sprite palettes, map sizes,
  audio voices, save sectors — live in `docs/wiki/`, each with *what hitting it looks like*,
  because thirteen of them fail silently.
- **Nothing proprietary ships.** No ROMs, no savestates, no extracted assets — the engine is
  [pokeemerald-expansion](https://github.com/rh-hideout/pokeemerald-expansion), cloned from
  public GitHub at setup time into a cache outside every repo.

## Setup on a machine that has nothing

1. **Install Docker Desktop** and start it — everything compiles inside a container.
2. **Install this plugin** in Claude Code, then open any folder and ask it to
   *"check the setup"*. The doctor reports exactly what is missing and the one command that
   fixes each thing, including cloning the engine (~1 GB, one command).
3. **Ask to start a new game.** The scaffolder creates the game's own repo with its design doc,
   verification folder, and pin file, and builds a first playable ROM.

You do not need to read any code to do any of this. Ask in plain English.

## Where everything is

| | |
|---|---|
| `skills/` | the working rules the assistant loads — voice, walls, session ritual, build ritual |
| `tools/` | the Python. `hx.py` answers "where is everything"; `doctor.py` answers "can this machine build" |
| `harness/` | the Lua the emulator runs — zero assertions, by design |
| `docker/` | the build image, including three patches to headless mGBA |
| `verify/` | the harness's own checks; a game's checks live in the game's repo |
| `docs/wiki/` | the knowledge: measured limits, engine defects, working lessons |
| `templates/` | starter files a new game repo is scaffolded from |

## Honest limits

- Specs that resume from a savestate cannot run on a fresh machine yet — savestates are
  deliberately never distributed, and regenerating one re-rolls the RNG. Pinning the boot seed
  is the top of the roadmap.
- The harness targets pokeemerald-expansion; other engines would need their own symbol maps and
  walls.

## Legal posture

This repository contains **only original tooling and documentation**, MIT-licensed. It contains
no Nintendo code or assets and no ROMs, and it never downloads any: the engine it builds against
is the community's public decompilation project, fetched from its own repository. Anything you
build with it is yours to keep to yourself — this project does not distribute games and does not
help you distribute anyone else's work.

## License

MIT — see [LICENSE](LICENSE). The mGBA patches under `docker/` modify MPL-2.0 code and carry
that license.
