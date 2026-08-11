# hack-conventions

**What this page is for.** [[design-craft]] is *why* — difficulty, progression, fairness, what
gets a hack remembered. This page is *what, concretely* — a practical rundown of what a good Gen 3
hack is actually built out of, phase by phase: the title screen, the opening tour, the emote
bubble, the post-gym reward bundle. Load this one when you're about to build a specific feature and
want to know what players already expect it to do, before inventing it from scratch.

**Each entry ends with a tag showing how solid the ground under it is.** Read them once here, then
trust the entries:

- **`ENGINE`** — already built into the pinned engine. A config flag or a call away, not a project.
- **`HACK-TEXT n/3`** — read directly out of shipped hacks' own ROM text (record 87). `n/3` is how
  many of three independent hack lineages agree — Sors and Saiph share a common base, so they count
  as one lineage together, not two (record 90). No fraction shown = seen once, not yet cross-checked.
- **`HACK-SEQUENCE`** — sequencing (not just text) reconstructed from a hack's own script bytecode
  (record 88), validated exactly against Emerald's own source. A long reconstructed chain is a lead,
  not a citation.
- **`RESEARCH`** — from the craft/teardown research behind [[design-craft]] (records 35, 36, 50).
- **`COMMUNITY`** — web and video research (record 91): ROM-hacking forums/wikis plus five
  transcribed YouTube reviews. Secondhand opinion rather than a ROM's own bytes, but the only tier
  that captures what players actually like or don't.
- **`USER-IDEA`** — this project's own invention. Worth prototyping, not worth citing as convention.

Full sourcing for anything here: `docs/records/87` through `91`.

---

## Title & boot

- **Give the title screen its own art and music.** The three-phase state machine underneath it
  (logo → idle "press start" → advance) is already built — reuse it. `ENGINE`
- **Don't put a player-facing feature on `A+B+START+SELECT`.** That combo is the engine's standing
  debug/reset gate. `ENGINE`

## The opening sequence

- **Build the opening as a small state table, not one long script.** Littleroot's own intro is
  exactly this: two tracked variables stepping through truck → house → clock set → meet rival, and
  met rival → saved the professor → got the dex → got running shoes, each step an ordinary
  movement-plus-dialogue call on a named NPC. `ENGINE`
- **Give the starter pick real stakes — a rescue, a crisis — instead of handing it over at a
  menu.** The engine already treats the pick and the crisis as separate calls, so this costs
  nothing extra to do right. `ENGINE`
- **Hand off the Pokédex right after the crisis resolves, in the same beat as the nudge toward the
  rival.** Not two beats. `ENGINE`
- **Give the hack its own named professor, distinct from the base game's.** The cheapest identity
  beat there is, and nobody skips it — confirmed in every hack lineage checked, including a pair
  that shares nearly all its other text and still each picked a different name. `HACK-TEXT 3/3`

## Signaling what an NPC is thinking

- **Use the three built-in emotes (`!`, `?`, heart) instead of new sprite work.** One call, no art
  budget — `MOVEMENT_ACTION_EMOTE_*` in `event_object_movement.h`. `ENGINE`

## Systems that run the whole game

- **Ship a named, tracked quest/mission layer, separate from the main story.** Every hack lineage
  checked has one, each at a different scope — pick the scope that fits the pitch rather than
  cloning one. `RESEARCH + HACK-TEXT 3/3`
- **Use the built-in DexNav-style species lookup instead of building one.** Config flag
  (`dexnav.h`). `ENGINE`
- **Turn on EXP Share.** Table stakes, not a nice-to-have, and free to enable. Consider capping it
  against the difficulty system rather than leaving it unconditional. `ENGINE + HACK-TEXT 2/3`
- **Give the player some cosmetic customization.** Scope is flexible — a milestone unlock and a
  menu choice both work. `HACK-TEXT 2/3`
- **Use the stock Itemfinder for hidden items.** No custom system needed. `ENGINE`
- **Gate every HM-blocked path with something diegetic** — an NPC, a tree, a ledge — never an
  invisible wall. `RESEARCH`
- **Pick one HM-softening approach, deliberately — this is the single most convention-heavy QoL
  pattern the community has.** Swap HM moves for TMs/level-up moves; replace them with key items;
  allow bag-use with no teaching; or drop the gating requirement with open-world layout. `COMMUNITY`
- **Turn on Critical Capture before building a custom catch mechanic.** Already a config flag.
  `ENGINE`
- **Turn on following Pokémon if the budget allows it at all.** Config flag, and the single most
  spontaneously praised feature found anywhere in this research. `ENGINE + COMMUNITY`
- **State the difficulty choice explicitly, once, at new game — one-way relaxation at most.**
  Consider a separate, named harder mode on top for the players who want it. `HACK-TEXT 2/3 + RESEARCH`
- **Bundle the QoL cluster players actually name together**: an always-available heal, free move
  relearners, a reduced EV grind, in-game nature/ability editors, a quest tracker. `COMMUNITY`
- **Give evolution a no-trade-needed stand-in item** for single-player play. A common community
  ask, not yet directly evidenced in this project's own hack corpus. `RESEARCH`
- **A rising reputation/bounty system for morally-loaded choices is real, shipped territory**, if
  the pitch wants one. `COMMUNITY`
- **Small side-content beyond quests has real precedent**: minigames (scuba diving, pinball), a
  gacha-style "wishing well" trading currency for a random Pokémon. `COMMUNITY`
- **Watch for exploitable AI move-pattern repetition** — attentive players notice, at any
  difficulty tier. `COMMUNITY, single anecdote`

## Alternative architectures

- **Region structure has two real options**: linear gym-by-gym (the default, needs no
  justification), or open-world — start anywhere, any order, encounters scaled to the player. Both
  are shipped and celebrated. `COMMUNITY`
- **Starter selection has a real spread**: the classic three-ball pick; a personality quiz that
  assigns one; more than three choices; or letting the player eventually obtain every option
  regardless of pick. `COMMUNITY`
- **The antagonist team has no single right answer.** Keep it stock; keep it stock but give it its
  own arc; or replace it outright with a hack-original identity, optionally with a visible logo
  beat at their base. All three are shipped, deliberate choices across independent hacks.
  `HACK-TEXT 3/3, three different answers`

## Day and night

- **Not native to this pin, but a real, buildable pattern if it's in scope**: RTC-driven,
  time-of-day-keyed encounter tables, with a default-period fallback. Scope it as its own slice,
  not a config flag. `COMMUNITY`
- **Per-town unique music needs no extra work** — it's already stock. `ENGINE`
- A dedicated skip-to-time-of-day menu option hasn't turned up anywhere in this research yet.
  `UNVERIFIED`

## The post-gym beat

- **Bundle the reward**: badge + a specialty TM + money + a traversal unlock + a story beat, all in
  one scene. It's the pacing anchor for the segment before it, not decoration after. `RESEARCH`

## The post-game

- **Don't skimp on the post-game.** Even players enjoying a hack notice and are let down by a thin
  one — a real, in-the-moment reaction from a fan, not a critic. `COMMUNITY`

## Untested ideas from this project

- **Button-mash/combo input affecting catch difficulty.** Not observed anywhere in this project's
  research, including a dedicated web sweep — genuinely open ground, not a borrowed convention.
  Worth prototyping on its own merits. `USER-IDEA`
