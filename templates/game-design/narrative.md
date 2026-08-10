# Narrative

On-demand tier (spec: `design/living-design-doc.md`). Frameworks:
`docs/research/10-narrative-storytelling-frameworks.md`. For low-narrative archetypes
(puzzle, shmup) most sections stay thin — thin is a valid state, absence is not.

## Premise

TBD — a few sentences, player-facing fantasy first (MDA run backward).

## Act skeleton

Compressed ~17/66/17 act split for 2–10hr scope; Act 2 body carries the
town→dungeon→boss rhythm (see research doc 10 for why not film pacing).

- **Act 1 (~17%):** TBD
- **Act 2 (~66%):** TBD
- **Act 3 (~17%):** TBD

## Characters / creatures

One-line voice per speaking character — distinct voices are the craft consensus.

| Name | Role | Voice in one line |
|---|---|---|

## Dialogue budget

Butano text is sprite-based: dialogue competes with gameplay sprites for the same
128-OAM ceiling (research doc 10). Track it as a budget, not a vibe.

- **Max simultaneous text sprites in gameplay scenes:** TBD
- **Dialogue-heavy scenes (where gameplay sprites yield):** TBD

## Environmental storytelling

Techniques usable in 2D without voice acting (research doc 10's filtered list) —
what does the world say without a text box?

- TBD

## Route order

The critical path in play order, one entry per story beat, read by the companion site's
story-thread page (see the wiki's `companion-site` page). A beat's places are listed in the
order the player walks them; a place may appear in more than one beat, and a return visit is
labelled rather than deduplicated. This is the one place in this doc where a numbered list
carries `- **Key:** value` fields underneath, the same shape the index's Next actions and the
slice plan already use.

    1. **The parcel** — Oak's errand, and the first time the world asks for something back.
       - **Places:** Pallet Town, Route 1, Viridian City, Route 1, Pallet Town
       - **Gate:** none — this is the opening

    2. **Through the forest** — the first gym, and the first time a type matchup decides a fight.
       - **Places:** Route 2, Viridian Forest, Pewter City
       - **Gate:** the parcel delivered

Three fields, only the first required:

- **Places** — a comma-separated list of place names, matched against the map labels the
  companion site already derives from the tree. Order within the beat is play order.
- **Gate** — free prose, optional. What the game requires before this beat is reachable. This
  cannot be derived from scripts, so it's read back as authored, not verified against the tree.
- The beat's own sentence, after the em dash, is the beat's blurb, and doubles as the place-level
  note wherever those places are described elsewhere in the site.

## Open questions (overflow from index)

- none yet
