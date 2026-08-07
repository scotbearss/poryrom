# Audio

On-demand tier (spec: `design/living-design-doc.md`). The toolkit audio pipeline is
built and proven (`docs/research/22-audio-pipeline.md`) — this file tracks *this game's*
tracks and SFX against it. Non-negotiable workflow facts:

- Music: `tools/make_song.py` compiles an inert JSON song spec → GBT-subset `.s3m`
  → `dmg_audio/` (no tracker GUI). GBT constraints: tempo exactly 150, all four DMG
  channels (2 pulse + wave + noise) enabled. There is **no** Furnace/`.vgm`/advgm path —
  Butano ships GBT Player, not a VGM player (`docs/research/22`, correcting `02`).
- SFX: `tools/make_sfx.py` renders seeded sfxr-style params/presets → 22050Hz 8-bit
  mono WAV → `audio/` (Maxmod). MilkyTracker stays the optional manual tracker path
  (OpenMPT has no Mac build).

## Direction

TBD — mood references, DMG-channel character (2 pulse + wave + noise), where music
must yield to SFX.

## Tracks

Status: `concept | composed | imported | verified`.

| Track | Where it plays | Status | File | Notes |
|---|---|---|---|---|

## SFX

Every core verb should have one (feedback chain: anticipation → action → impact →
resolution). Same status column.

| SFX | Trigger | Status | File | Notes |
|---|---|---|---|---|

## Open questions (overflow from index)

- none yet
