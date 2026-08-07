# Architecture — how poryrom actually works

This is the technical companion to the [README](../README.md). If you just want to make a game,
you never need this page.

## The three separations

```mermaid
flowchart TB
    subgraph harness["poryrom — this repo, the harness (MIT)"]
        direction LR
        skills["skills/<br/>session rituals,<br/>working rules"]
        tools["tools/<br/>doctor, scaffolder,<br/>checks, verifier"]
        dock["docker/<br/>devkitARM +<br/>headless mGBA"]
        wiki["docs/wiki/<br/>measured limits,<br/>engine defects, lessons"]
    end

    subgraph machine["your machine"]
        direction LR
        plugin["installed plugin<br/>(Claude Code)"]
        cache["engine cache<br/>~/.poryrom/engines/&lt;ref&gt;<br/>pinned pokeemerald-expansion<br/>read-only, outside every repo"]
        img["poryrom-build:1<br/>Docker build image"]
    end

    subgraph game["your game — one repo per hack"]
        direction LR
        pin["harness.json<br/>pins harness version"]
        specs["design/ + verify/<br/>your docs and checks"]
        patch["patches/&lt;game&gt;.patch<br/>the ONLY tracked copy<br/>of your code"]
        fork["hacks/&lt;game&gt;/<br/>working copy<br/>gitignored, disposable"]
    end

    rom["&lt;game&gt;.gba — yours, played in mGBA<br/>or deployed to a handheld over Wi-Fi"]

    harness -->|"install once"| plugin
    plugin -->|"scaffolds & drives"| game
    cache -->|"forked, never edited"| fork
    patch <-->|"replay ⇄ refresh<br/>byte-checked"| fork
    fork -->|"Docker build"| rom
```

Three separations carry the whole design. The **engine cache** is a pinned clone of the public
decompilation, shared by every game, never edited, and never inside any repo. Your **game repo**
tracks only what is yours — design, checks, and a patch that replays byte-for-byte onto the
pinned engine. The **working copy** where edits actually happen is disposable and gitignored,
rebuilt from the patch on any machine with one command.

## The verification loop

```mermaid
flowchart TB
    A["you describe the next thing<br/><i>'the gym leader should heal you first'</i>"]
    B["Claude edits the fork<br/>the engine clone stays pristine"]
    C["static checks — BEFORE the build<br/>maps, dialogue, tilesets, behaviours<br/><i>faults that render as plausible content<br/>are only catchable here</i>"]
    D["Docker build<br/>devkitARM → .gba + symbol table"]
    E["headless verify<br/>mGBA runs Lua probes that read RAM at chosen frames —<br/>the Lua contains zero assertions; judgement happens outside,<br/>and counterfactual specs keep the checks honest"]
    F["screenshots in chat, backup refreshed,<br/>then you playtest / deploy"]

    A --> B --> C --> D --> E --> F
    F -.->|"findings become the next change"| A
```

Most ROM-hacking setups can build. This one can **prove**. Every claim of "it works" is a spec
file replayed in a headless emulator against named symbols in the game's own memory — and each
spec has a counterfactual twin pointed at an unpatched ROM, expected to fail, so a check that
passes for the wrong reason gets caught.

## What's where

| | |
|---|---|
| `skills/` | the working rules Claude loads — voice, measured walls, session ritual, build ritual |
| `tools/` | the Python: `doctor.py` (can this machine build?), `new_game.py` (scaffold a hack), `restore_hack.py` (rebuild the working copy from a patch), `verify_hack.py` (prove a change), map/dialogue/tileset checkers, sprite and audio pipelines, handheld deploy |
| `harness/` | the Lua the emulator runs — zero assertions, by design |
| `docker/` | the build image recipe, including three patches to headless mGBA |
| `verify/` | the harness's own checks; your game's checks live in your game's repo |
| `docs/wiki/` | 17 pages of distilled knowledge — see [docs/README.md](README.md) for the map |
| `templates/` | starter files a new game repo is scaffolded from |

## Standards

Beyond being a Claude Code plugin, the repo carries a root `plugin.json` conforming to the
[Agent Plugins](https://agent-plugins.org) 1.0.0 open standard, so other compliant clients can
discover the plugin and its skills.
