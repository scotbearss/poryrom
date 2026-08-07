# Art

On-demand tier (spec: `design/living-design-doc.md`). Pipeline is proven end-to-end:
PixelLab MCP → `tools/import_art.py` / `tools/import_animation.py` →
`graphics/` → build → `tools/verify_spec.py`. Frames auto-pad to legal OAM sizes;
verify the direction set after every PixelLab generation (directions can silently drop).

## Style direction

TBD — references, era anchors, readability notes at 240×160.

## Palette strategy

Proven approach: each animation sheet gets its own 16-color bank, with `set_palette`
on animation swap. Cross-sprite palette *sharing* and 8bpp are still build-untested
(`docs/research/05-open-gaps.md`) — don't design a dependency on them without proving
them first. Mirror the bank plan in mechanics.md's hardware budget.

| Bank | Assets sharing it | Notes |
|---|---|---|

## Asset ledger

One row per asset; every row starts `concept`. Status:
`concept | generated | imported | verified`. `verified` means it booted in the ROM
and passed the spec, not that it looks nice. PixelLab ids make regeneration and
new animations possible in a later session — always record them.

| Asset | Size | Frames × dirs | Bank | Status | PixelLab id | Notes |
|---|---|---|---|---|---|---|

## Open questions (overflow from index)

- none yet
