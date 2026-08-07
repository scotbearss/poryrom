---
name: session-start
description: Orient at the start of a session working on a GBA ROM hack — check the machine can build, confirm the game's backup is current, and report where things stand in plain English. Use when opening a game repo, when the user says "where were we", "what's the state", "let's get going", or before starting any build work in a poryrom game repo.
---

# Session start

Load `../_shared/voice.md` first and follow it for every reply in this session.

## What to do

Run these, in order, from the game repo (the directory holding `harness.json`):

1. **`python3 "$PORYROM/tools/doctor.py"`** — can this machine build right now? It checks
   Docker, the build image, the engine clone and its pin, savestates, and whether the installed
   harness matches the version this game expects. Exit 0 means every blocking check passed.

2. **`python3 "$PORYROM/tools/export_hack.py" <game> --check`** — is the game's backup
   current? The working copy of the game is deliberately not in version control, so this patch is
   **the only tracked copy of their code**. It replays the backup onto a clean engine and
   byte-compares every file.

3. **Read the game's design doc index** and the most recent entry in its log, so you know what
   was last being worked on.

`$PORYROM` is this plugin's directory. If the variable is not set, find it — the tools live
beside this skill, one level up (`../tools/`). Resolve it once and reuse it.

## What to say

Three or four sentences, no headers:

- whether the machine is ready to build (and if not, the one thing to fix)
- whether their game's backup is current — and if it is **not**, say so plainly and offer to
  refresh it, because that means work exists in only one place
- where the game stands and what was last in flight
- the one thing you need from them, if anything

## Two things that are easy to get wrong

**A skipped check is not a passing check.** If the doctor reports missing savestates, most of the
game's automated checks cannot run at all. Say that. Silence there reads as "everything passed",
which is the one impression you must never leave.

**"The backup has drifted" has two very different causes**, and only one is bad. Content drift
means real work exists nowhere else — act on it. If the tool reports drift, trust it: it compares
content and ignores timestamps.
