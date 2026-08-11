# Conventions Checklist

On-demand tier (spec: `design/living-design-doc.md`). A menu drawn from
`docs/wiki/hack-conventions.md`, not a mandate — read that page for the evidence behind every line
here before citing one as "what hacks do." This file exists to be *walked once*, during scoping,
and then left alone.

## How to use this, once

1. **Write the one-sentence pitch first** (index.md's Identity block). Everything below is judged
   against that sentence, not the other way around.
2. **Walk every item and mark it** `KEEP` / `CUT` / `ADAPT` in the Decisions table, with the
   one-line why. A marked `CUT` is a *finished* decision, not a gap.
3. **Cut hard, and say so in scope.md's cut list.** Design-craft's own named killer of solo
   projects is scope creep. A single-mechanic hack that cuts 80% of this page on purpose isn't
   behind — it read the menu and ordered one thing.
4. Each item ends with a tag — `ENGINE` (already built), `HACK-TEXT n/3` (how many independent
   hack lineages ship it), `RESEARCH`, `COMMUNITY` (what players actually say they like or don't),
   `USER-IDEA`, or `UNVERIFIED`. A high `n` means players will expect it, not that it's required.

## Decisions

| Item | Keep / Cut / Adapt | Why (one line) |
|---|---|---|
| | | |

---

## Title & boot

- [ ] Own title-screen art/music over the stock three-phase state machine (logo → idle →
      press-start) — the state machine itself is free. `ENGINE`
- [ ] Keep the `A+B+START+SELECT` debug/reset combo clear of anything player-facing. `ENGINE`

## The opening sequence

- [ ] Build the opening as a small state table, not one giant script. `ENGINE`
- [ ] Give the hack its own named professor. The cheapest, most-confirmed identity beat there is.
      `HACK-TEXT 3/3`
- [ ] Give the starter pick narrative stakes (a rescue, a crisis) instead of handing it over at a
      menu on day one. `ENGINE`
- [ ] Land the Pokédex hand-off and the "go meet your rival" nudge in the same beat. `ENGINE`

## Signaling what an NPC is thinking

- [ ] Use the three built-in emotes (`!`, `?`, heart) instead of new sprite work — one
      `applymovement` call, no art budget. `ENGINE`

## Systems that run the whole game — pick what the pitch needs, not all of them

- [ ] A named, tracked mission/quest layer, distinct from the main story. `RESEARCH + HACK-TEXT 3/3`
- [ ] DexNav-style in-game "where is this species" lookup — already built, a config flag away.
      `ENGINE`
- [ ] EXP Share, on by default or as an early give. Consider capping it against the difficulty
      system instead of leaving it unconditional. `ENGINE + HACK-TEXT 2/3`
- [ ] Player-character cosmetic customization — a menu choice or a milestone unlock both work.
      `HACK-TEXT 2/3`
- [ ] Hidden overworld items via the stock Itemfinder — no custom system needed. `ENGINE`
- [ ] Every HM-gated critical-path block is diegetic (an NPC, a tree, a ledge) — never an
      invisible wall. `RESEARCH`
- [ ] **Pick one HM-softening approach, deliberately** — the community's single most
      convention-heavy QoL pattern: swap for TMs/level-up moves; replace with key items; allow
      bag-use with no teaching; or drop the gating requirement via open-world design. `COMMUNITY`
- [ ] Critical Capture (one-shake catch check) — already a config flag; reach for it before
      building anything custom in the catch-feel space. `ENGINE`
- [ ] Following Pokémon (`follower_npc.h`) — a config flag, and the single most spontaneously
      praised feature found anywhere in this research. `ENGINE + COMMUNITY`
- [ ] An explicit, player-facing difficulty choice, stated once at new-game, one-way-relaxable at
      most. Consider a separate named harder mode on top. `HACK-TEXT 2/3 + RESEARCH`
- [ ] The QoL cluster players actually name together: an always-available heal, free move
      relearners, a reduced EV grind, in-game nature/ability editors, a quest tracker. `COMMUNITY`
- [ ] A no-trade-needed evolution item/stand-in, for single-player play. `RESEARCH`
- [ ] A rising reputation/bounty system for morally-loaded choices, if the pitch wants one.
      `COMMUNITY`
- [ ] Small side-content beyond quests: minigames (scuba diving, pinball), a gacha-style "wishing
      well" trading currency for a random Pokémon. `COMMUNITY`

## Alternative architectures — real menus, pick deliberately

- [ ] **Region structure:** linear gym-by-gym (the default) vs. open-world (start anywhere, any
      order, encounters scaled to the player) — both shipped, both celebrated. `COMMUNITY`
- [ ] **Starter selection:** the classic three-ball pick vs. a personality quiz that assigns one
      vs. more than three choices vs. letting the player eventually obtain every option regardless
      of pick. `COMMUNITY`
- [ ] **Antagonist team, if the pitch wants one:** keep it stock; keep it stock with its own arc;
      or replace it with a hack-original identity, optionally with a visible logo beat at their
      base. All three are shipped, deliberate choices — no default here. `HACK-TEXT 3/3, three
      different answers`

## Day and night

- [ ] Not native to this pin, but a real, buildable pattern if it's in scope: RTC-driven,
      time-of-day-keyed encounter tables with a default-period fallback. Scope it as its own
      slice, not a config flag. `COMMUNITY`
- [ ] Per-town unique music needs no extra work — already stock. `ENGINE`
- [ ] A dedicated skip-to-time-of-day menu option hasn't turned up anywhere in this research yet.
      `UNVERIFIED`

## The post-gym beat

- [ ] Bundle the reward: badge + a specialty TM + money + a traversal unlock + a story beat, all
      in one scene — the pacing anchor for the segment before it, not decoration after. `RESEARCH`

## The post-game

- [ ] Don't skimp on it. Even players enjoying a hack notice and are let down by a thin one.
      `COMMUNITY`

## Untested ideas from this project

- [ ] Button-mash/input-combo affecting catch difficulty. Genuinely open ground, not a borrowed
      convention — worth prototyping on its own merits. `USER-IDEA`

---

Sourcing, caveats, and the full evidence trail for every tag above: `docs/wiki/hack-conventions.md`
and `docs/records/87`–`91`.
