# Mechanics

On-demand tier (spec: `design/living-design-doc.md`). Keep the heading skeleton —
skills navigate by section name. Score everything here against `design/frameworks.md`;
check the archetype's pitfalls doc (`docs/research/11`–`15`) before locking anything.

## Core loop — nested

The one-sentence loop lives in the index. Interrogate each timescale separately
(`design/frameworks.md` §3):

- **Micro (seconds):** TBD — is the verb satisfying with zero reward attached?
- **Meso (minutes):** TBD — what structures repeats into a short-term goal?
- **Macro (session):** TBD — natural stopping point; why turn it back on tomorrow?

## Verb set vs. input surface

D-pad + A/B + L/R + Start/Select — no analog, ~8 useful signals (`frameworks.md` §5).

| Verb | Input | Notes (buffering, timing windows) |
|---|---|---|

## Systems

Status: `designed | building | verified | cut`. Every system starts `designed` —
nothing is `verified` until `verify/spec.json` asserts it (see
`docs/research/16-verification-test-spec-format.md`).

| System | Status | One-line description | Spec keypoint(s) |
|---|---|---|---|

## Hardware budget

Budgeted at design time, not as a polish pass (`frameworks.md` §2 GBA note; the
frame-budget-first mandate from `docs/research/01`). Numbers, not adjectives.

- **Sprites/OAM (128 ceiling):** TBD — worst-case simultaneous count, incl. sprite-based text
- **Palette banks (16 × 16-color):** TBD — which assets share which banks (mirror art.md)
- **VRAM / tiles:** TBD
- **Per-frame CPU concerns:** TBD — collision broad-phase, entity counts

## Feel targets

Swink's six components (`frameworks.md` §2) — what should each core verb feel like?
Filled in loosely at design, scored for real during the feel phase.

- TBD

## Open questions (overflow from index)

- none yet
