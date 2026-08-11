# design-craft

**What this page is for.** The game-design layer: what makes a hack *good*, as distinct from what
makes it build. It distils the craft research (records 35, 36), the teardown of four acclaimed hacks
(record 50), and — critically — the corrections register (record 52), because records 35 and 36 carry
known errata and every claim here is stated post-correction. Engine facts live in [[battle-engine]],
[[maps-and-tilesets]] and their siblings; this page is about choices. For the granular,
moment-to-moment version of this — what the opening tour is built from, what an emote bubble
actually is, what a hack's own shipped text confirms — see [[hack-conventions]].

**Two standing hedges.** First: community-reception claims in records 35 and 36 arrived largely via
search-snippet extraction because the primary forums block automated fetch — the *patterns* are
corroborated across independent sources, but specific community-reported numbers were never
independently verified (record 35 §9, 36 §9). That hedge is inherited here wherever those records
carry it. Second: design lessons from the two closed-source exemplar hacks are exactly that —
design lessons. No implementation claim about them is possible, and none appears here (record 50 §2).

---

## 1. The difficulty design space

Read across four acclaimed hacks, "difficulty" decomposes into **six independent axes**
(record 50 §7):

| Axis | What it means |
|---|---|
| **A. Team quality** | IVs, EVs, natures, movesets, held items |
| **B. Team size** | how many mons the opponent fields |
| **C. AI competence** | which behaviours, on which trainers |
| **D. Level relationship** | caps, scaling, EXP flow |
| **E. Player-side clauses** | bag access, battle style, party rules |
| **F. Environment** | weather, terrain, boss gimmicks |

Every exemplar picks a subset; none uses all six; and **not one of the four implements difficulty as
parallel authored parties** — the architecture an earlier plan assumed (record 50 §0, §10; record 52
§6.2). Every one of them got its leverage from a knob plus authored detail, never from a second set
of teams. The cheap replacement is one party table plus a difficulty-gated quality layer.

**Axis A is the cheapest and it is where everyone starts** — one well-regarded hack's entire
difficulty system is a single quality bit plus two clauses on axis E (record 50 §7). **Axis D is the
one that makes the others matter**, and it fails in a mirrored pair:

- A **cap without relative levels** punishes exploration — the player walks out of a gym and the
  next optional route is a tax (record 35 §4, record 50 §7).
- **Relative levels without a cap** make the player's own grinding the difficulty setting.

The two open exemplars solve the pair in opposite directions — one moves the *player's* ceiling
toward the boss, the other moves the *boss* toward the player — and both work. Doing neither is the
failure mode (record 50 §7).

**The architecture two of the four converged on independently: difficulty is a preset over an
orthogonal settings space.** A difficulty label is a *recommended point* in a vector of
independently-settable knobs, never a mode that owns them — and the moment the player touches a
classified knob, the label **auto-demotes to CUSTOM**, so "the game says Hard" can never desync from
"the knobs say Hard" (record 50 §3.3, §6.1). Two caveats travel with the pattern: the demotion
guarantee is only as good as its knob classifier, which must be *derived from the knob table* rather
than hand-maintained beside it (a forgotten entry silently breaks the invariant); and the preset does
not eliminate mode branching — it seeds the value the branches read. Promise the label is never the
authority; do not promise "no second code path" (record 50 §3.3, §8).

## 2. Hard versus unfair — the contract

**Players never complain a hack is "too hard." They complain it cheated** (record 35 §4). The line
they police:

*Fair, and respected:* AI that reacts to what you telegraph; bosses with full teams whose movesets
cover their own weaknesses, so the difficulty lives in preparation; level caps; item-spam limits;
opponent teams that are *knowable in advance*, turning each boss into a solvable puzzle.

*Unfair, and sentiment-killing:* enemy-only mechanics before the player can access them; perfect
competitive sets the player cannot yet build; unlimited enemy healing; removing good options from
the player while trainers keep using them; and every difficulty jump that was not foreshadowed and
beatable with resources already held. Pure stat inflation is corroborated from the implementation
side too — none of the four exemplars inflates stats (record 50 §7).

Two folklore items in the fair/unfair lists needed correction. "AI that reads inputs" is not a thing
the engine this harness builds on can even do: the AI commits its move before the player is prompted,
and the flag folklore blames for input-reading actually disables the knowledge filter — still worth
withholding, for a different reason (record 52 §5.2). And the *baseline* AI is not perfectly fair
either: it reads the player's true held item at several scoring sites, unflagged, on every trainer —
so "withhold the omniscience flag and the AI is fair" is false at this pin (record 52 §7.1). See
[[battle-engine]] for the full fairness table.

**A difficulty tier is a written contract.** Every tier states what it assumes of the player —
nothing, strategy, a fully EV-trained team — and the strongest form of the norm is that **a tier may
even be unfair, provided it says so**: one exemplar's top tier warns in its own intro text that it
was designed to feel unfair, and another's setting-selection text names which of its own knobs is
unbalanced and why (record 50 §4.4, §6.1). A tier without a stated assumption is an unlabelled trap.
The genre is allowed to cheat *provided it discloses* — which is exactly what makes an undisclosed
engine-level knowledge leak a defect rather than a difficulty feature.

**The choice is made up front.** Record 35's "mid-save-changeable difficulty" recommendation is
reversed: none of the exemplars it cited supports it. One forbids config edits during a run; one
allows only lowering, with a no-re-raise ratchet until the Champion; one has no mid-save change at
all. The corrected norm: **explicit, player-facing, chosen at new game, with at most a one-way
relaxation** (record 52 §4 item 35-5; record 50 §10.1). A first-run quiz that *recommends* a tier —
and locks the cruellest tier away from declared first-timers — is the best-evidenced onboarding
pattern (record 50 §6.1).

## 3. Progression numbers

These are heuristics from the craft research, not constants — tune, don't transcribe (record 36 §9).

- **Level curve:** Gym 1 ≈ Lv 10–11 → Gym 8 ≈ Lv 44–46 → League 54–60; roughly **4–6 levels per
  badge**; roughly **5–8 trainer battles per badge segment**, so the player arrives on-level
  *without grinding* (record 36 §3).
- **Wild tables:** 6–10 land species per route (fewer early), in a rarity shape of one common
  anchor, two or three mid-tier, one or two rare reward pulls. A species is only as good as its
  availability — the common slots of an early route are a bigger balance decision than any 1% slot
  (record 36 §3).
- **Availability curve:** front-load breadth, gate power. Most first-stage species catchable early;
  evolutions and high-BST lines behind progress. First evolutions land by Gym 2–3; teams finish
  forming through the mid-gyms (record 36 §3).
- **The hard rule:** for every gym and boss, at least one **super-effective-and-resists answer must
  be catchable, in its usable form, on the routes before it** — and the boss carries one coverage
  move that punishes bringing *only* the obvious counter. An answer exists; a free win does not
  (record 36 §3).
- **Fix a broken curve by adding trainers, never by rescaling wild levels.** The broken level curve
  is the community's #1 named hack-killer, and the diagnostic fix is more battles per segment, not
  hotter grass (record 35 §2).
- **A route teaches; the gym tests.** Introduce each type, mechanic and species before the fight
  that demands it; a gym demanding a strategy the player had no room to learn is a difficulty spike
  in disguise (record 35 §6).

## 4. The QoL floor, and QoL as the difficulty budget

The clearest reception finding in the corpus: the physical/special split plus modern mechanics is
the line between "aged well" and "unplayable" (record 35 §3). The floor whose absence reads as
*old*: the split, running everywhere from the start, reusable TMs, painless HMs, fast low-grind EXP,
fast text. On the engine this harness pins, most of the floor is configuration, not code.

The deeper finding reframes the whole category. One difficulty hack's developer states the causal
order plainly: the game is hard, *therefore* every friction that is not the intended challenge must
go. **QoL is not polish added if there is time — it is what buys permission to be hard**, and it
should be scoped in the same breath as the difficulty tier it is paying for (record 50 §5.1). A
hard tier shipped without its QoL budget is just the unfair column of §2 wearing a difficulty label.

## 5. What gets a hack remembered, and what sinks it

**Remembered** (record 35 §1): originality is the single most-praised quality — a real identity and
one formula-breaking hook, not a reskin. Polish ages better than ambition: a tight, coherent scope
outlives a sprawling janky one. Restraint reads as skill — strong options earned, not handed;
legendaries scarce. An original story beats canon cosplay.

**Sunk** (record 35 §2): the broken level curve first; incoherent difficulty that reads as random
rather than hard; save-threatening instability; half-finished features (worse than absent ones —
ship less, finished); unproofed dialogue; and **scope creep, the named killer of solo developers** —
decide the one thing the hack is about, write it in a sentence, and cut whatever does not serve it.

Two community norms are now first-class quality bars, both hedged as reception data (record 35 §5):

- **Completion honesty.** The valued artifact is not a "[COMPLETED]" tag but a **published,
  decomposed, honest-to-the-percent status table that names what is missing** (record 50 §6.3,
  §10.12). This lab already keeps that artifact for itself; the exemplar validates pointing it at
  players.
- **Asset provenance.** The community actively polices how content was made; the documented
  backlash case was a *trust* failure independent of gameplay. Be transparent about generated art,
  and never pass generated or borrowed assets off as hand-made (record 35 §5). See [[art-pipeline]]
  for how this project sources sprites, and note the harness-level rule that provenance constraints
  here are absolute (nothing Nintendo-derived ships, ever).

Save-breaking updates are the scene's biggest recurring resentment, and the corrected finding is
that breaking saves is a **design choice with known, shipped mitigations**, not a platform
inevitability (record 52 §4 item 35-4). The mechanics live in [[save-system]].

## 6. Creature design

The discipline is an ordering: **concept → typing → stat limits → stat spread → ability → movepool**,
each layer argued against the concept before it is allowed in (record 36 §1).

- **Concept is one sentence** — a source plus one twist, abstracted past the "animal A + animal B"
  seam that is the #1 amateur tell.
- **Silhouette-first**: the design must read as a solid black shape, and the head alone should be
  recognizable. One iconic, identity-carrying element that can recombine into later forms. The
  sprite-format constraints that make this mandatory — and the pipeline that meets them — are in
  [[art-pipeline]].
- **BST is a budget.** Spend it on about two role-relevant stats; a balanced spread is a mediocre
  one. Derive numbers from benchmarks (a speed tier, a specific survival), never aesthetics — but
  set limits before spreads so counterplay survives.
- **The ability enables the role without removing interaction; the movepool withholds coverage on
  purpose.** A mon that answers all of its own checks has no counterplay.
- **At most three stages**, motif and palette continuity across them, evolution levels placed just
  before the hack's power spikes.
- **Regional variants are the highest-ROI move for a solo developer** — inherit a proven silhouette,
  design only the twist, justify it with a concrete environmental "why".
- **One deliberate off-note.** Memorability beats polish; if a design is too clean, the hook is
  often the imperfection.

## 7. Three transferable difficulty mechanisms

Design patterns, stated without source — the point of each is the shape, not the code
(record 50 §3.4, §3.6, §4.4–4.6).

**The earned, decaying level cap.** The player's cap is the *next boss's level minus an offset*, and
the offset is set to the size of the level jump when a boss falls, then decays a few points per
subsequent battle. The cap does not move when the badge is earned — it moves as the player plays.
Grinding is paced to effort instead of forbidden by fiat, and the classic failure — walking out of a
gym instantly under-levelled for the next route — cannot occur. Catching, deliberately, does not
advance it (record 50 §3.4b).

**EXP that converges to a target instead of accumulating.** Below the cap, a battle awards whatever
brings the mon *to* the cap — catch-up is nearly instant. At the cap, awards are zero: grinding is
not discouraged, it is arithmetically impossible (record 50 §3.6). The gentler variant awards a
**fixed 1 EXP at cap**, which is a deliberate product decision, not a rounding: zero freezes the EXP
bar and reads as a bug, while 1 keeps the you-fought-something feedback and keeps EV accrual alive
during at-cap play (record 50 §4.4). Either way the whole enforcement surface is tiny — one branch
in the EXP path, one in the rare-candy path. A level cap is not a system; it is two branches.

**Difficulty as coverage, not magnitude.** The strongest implementations almost never make a stat
bigger. They raise **the fraction of the opposing team that is competent** — one more slot with a
real moveset, one more with real IVs, one more mon, competence extended from key trainers to all
trainers as the tier rises. Player-facing power is unchanged; the number of things that must be
answered rises. That is a far more controllable dial than any percentage (record 50 §3.4f, §7).

**A warning that travels with all three:** difficulty tables attract silent defects. The teardown
found, across shipped and acclaimed code, a dead branch whose two guards tested the same condition,
an "off" setting that silently fell through to the default curve, and a declared automation flag no
reader ever consulted (record 50 §3.10; record 52 §1). None was visible in play. Difficulty-derived
values — computed IVs, party sizes, behaviour tiers — are precisely the surface a harness must
assert rather than trust. See [[verification-discipline]].

## 8. Region, town and dungeon design

From record 36 §5; authoring mechanics and the engine's silent map constraints are in
[[maps-and-tilesets]].

- **Gate softly, never with invisible walls.** Every block on the critical path is a diegetic gate —
  an NPC, a tree, a ledge, something asleep — so the rail reads as choice.
- **Default to a loop layout**; loops generate the returns and loop-backs region fans praise most.
- **Biome cadence:** change the dominant biome every one or two towns; never three same-mechanic
  routes in a row; alternate dungeon corridors with open air.
- **The three-part town rubric: a unique aesthetic, content beyond the gym, and lore that explains
  the aesthetic.** No gym-only towns; dense-and-small beats large-and-empty; if a landmark is shown,
  it is enterable and filled.
- **Dungeons keep the player stuck, never lost** — always a legible landmark to re-orient by.
  Fail-able puzzles, earned rewards, and if it is a maze, a low encounter rate or a short run;
  long maze plus high encounters is the #1 tedium generator.
- **Backtracking, the good kind, is a triple:** gated behind a new capability, rewarded concretely,
  and *shorter on the way back* than it was outbound.
- **One-screen legibility.** The visible window is about 15×10 metatiles, so landmarks and exits
  must read within a single screen; a route that requires off-screen memory is where "lost" comes
  from. Contrast for paths, leading lines, landmarks for wayfinding.
- **Depth-per-location beats breadth.** Fully realized few over hollow many.

## 9. Battle-system design principles

This is the design layer only. Record 36 §2's mechanical claims about the pinned engine were the
most heavily corrected in the corpus — its damage-modifier ordering is wrong in a way that changes
results, its recommended AI flags do not exist, and its "prediction flags" describe machinery that
is one unflagged line (record 52 §5). Mechanics belong to [[battle-engine]]; what survives here is
the design reading.

- **The damage formula's design meaning survives the corrected ordering:** attack over defense is a
  ratio, so hyper-offense and hyper-defense are both viable while balanced spreads are mediocre —
  the formula itself pushes role specialization. Level advantage is real but not overwhelming, which
  is why level-cap difficulty works at all (record 36 §2, surviving clause).
- **Type-chart restraint:** a small chart — 6–10 types built from 2–3 triangles, plus one or two
  deliberate offense/defense asymmetries and at least one immunity — beats a big one; hand-tuning
  cost scales with the square of the type count, and at the pin the table is a literal dense array,
  so adding a type is a full-row-and-column edit, not an append (record 36 §2; record 52 §3 item
  34-9).
- **Statuses: degrade over lockout.** Model new statuses on damage-plus-suppression with
  counterplay, not remove-from-play. Shipping sleep means shipping a clause or a cap.
- **Tune KOs to roughly 2–3 hits.** A trivial sweep and an unbreakable stall are the same disease:
  the outcome known before the turn is played.
- **Speed is the highest-leverage stat and the most dangerous to leave unanswered** — every fast
  threat needs an existing counter; setup moves need answers or they are the trivial sweep.
- **Field effects match battle length.** Hazards pay off only in long, switch-heavy battles; short
  trainer fights want turn-limited effects instead.
- **Battle speed is a design pillar, not polish** — a monster-battler runs hundreds of fights.
- **AI fairness is about information, not scoring strength** — the principle from record 36 stands
  after its named flags were corrected away. The real dial is which knowledge behaviours are granted
  to whom, tiered by trainer importance and progress; and the baseline's own leaks (§2 above) mean
  the fairness claim must be verified, not assumed (record 52 §5.2, §7.1).

## 10. Narrative craft

From record 36 §6. Line-level writing — voice, register, the measured pixel budget that replaced
the old "two lines, ≈34 characters" figure — lives in [[dialogue-voice]]; the superseded character
count should not be cited (record 52 §5.2 item 36-13).

- **A villain team is one philosophy, not a heist.** Write the boss's worldview in a sentence;
  grunts are that sentence scaled down. Root the ideology in a personal wound — the wound *is* the
  ideology — and give the cause enough merit that winning is not clean.
- **For a deep villain, split it in two:** a sincere idealist the player is made to like, so the
  ideology gets a fair hearing, plus a cynic whose reveal recontextualizes everything and supplies a
  clean final fight.
- **The rival recipe shows change in party data, not monologue:** a cause for the cruelty, one
  public humbling as the hinge, then a party whose composition itself proves the growth — the
  canonical example is an evolution that can only happen via friendship. Type-disadvantaged starter
  signals a friendly rival; type-advantaged signals a threat.
- **The eight gyms are a pre-built three-act spine:** act one establishes world, rival and the
  team's existence via a low-stakes first crime; act two escalates through a mid-game twist; act
  three is gym 8 through the League. Route the antagonist through the League if the ending must
  land. Skippable cutscenes; story gated at area boundaries, not mid-route.
- **Two-tier lore:** a thin mandatory spine (a crisis that must be resolved) plus a thick optional
  web — lore rooms, decode-it-yourself inscriptions left deliberately unresolved, deteriorating
  journals whose emotional arc lives in the sequence.
- **The scene-memorability checklist:** real permanent cost; restraint; a sympathetic antagonist; a
  bittersweet or unresolved edge; **mechanics gating the emotional beat**; atmosphere doing
  narrative work; big stakes anchored to one intimate image. Forgettable stories are the exact
  inverse.

## 11. Economy and rewards

The thesis in one line: **starve the player in battle, never in preparation** (record 36 §4).
Scarcity as difficulty works on the battle axis — item clauses, set mode — while consumables stay
cheap and available outside it. Fighting the economy is tedium; fighting the trainers is the game.

- **The no-bag-in-trainer-battles clause is the highest-impact, lowest-effort difficulty lever** —
  it deletes the heal-race outright. Record 36 attributed it to a config symbol that does not exist
  (`B_VAR_NO_BAG_USE`, with tiered wild/trainer semantics — neither the name nor the tiers are
  real; the pin has a single plain flag, record 52 §5.2 item 36-7). The design survives the missing
  symbol: the exemplar that ships this rule implements it as a scripted change of roughly ten lines
  across two files (record 50 §4.3).
- **The gym is a stacked reward event** — badge, specialty TM, money, a traversal unlock, story —
  and it is the pacing anchor. Layer reward frequencies under it: small (every trainer), medium
  (every route), large (every gym), with variable finds between the fixed beats. Audit for dead
  stretches — no segment both long and empty.
- **Money stops mattering mid-game; do not fight it.** Give the endgame a skill-earned second
  currency that buys what cash cannot — Emerald's own Battle Frontier already ships exactly this.
- **Gate TM access, not quantity.** Reusable TMs weaken commitment, so preserve their reward value
  by placing build-defining moves behind gyms and late routes rather than the early mart. Reusable
  and buyable are independent axes.

## 12. Side content and the post-game

**The mission-system architecture** is the most complete side-content structure in the teardown set,
and it is almost entirely flags plus a list (record 50 §6.2):

- **A two-symbol overworld vocabulary:** one marker for "mission available", a distinct one for
  "complete but unclaimed". Availability and claimability visually distinct — two symbols carry the
  whole quest-state machine on the map.
- **Three gate types and no others:** count gates ("complete N missions"), progress gates (badges,
  post-game), and prerequisite chains. Compound gates combine them; the location where a mission is
  *accepted* is not a gate.
- **Hub plus diaspora:** one hub supplies volume, the scattered rest supply discovery.
- **Roughly three in ten missions sit behind the credits** — the post-game as a second content
  phase, not an epilogue.
- **A stated no-permanently-missable invariant, with its exceptions published.** A declared
  invariant plus a named exception is a better artifact than either an unstated invariant or a
  claim of perfection — the same shape as this corpus's own honesty rules.
- Rewards are heterogeneous, and the best single idea is a side quest that upgrades a **core system
  verb**, not just inventory.

**The post-game is not optional.** A thin post-game is a recurring letdown even for polished hacks
(record 35 §2) — and an Emerald hack inherits, for free, the exact robust post-game an official
remake was pilloried for cutting: **the Battle Frontier is in the base ROM** (record 36 §7). A
**secret superboss** is the proven high-value, low-content-cost payoff on top.

**Fair walls are knowable walls.** What makes a wall-hard boss a puzzle rather than a memorisation
tax paid in resets is **information availability** — the team must be knowable in advance. In the
scene that knowledge comes variously from developer-published data or community transcription (the
corrected finding: it has to *exist*, not to come from the developer — and community transcriptions
are demonstrably fallible, record 50 §5.3, §10.2). For a single-player lab game with no community to
write a wiki, the equivalent is an in-game or in-repo affordance: a scouting item, a pre-battle team
preview, or a generated boss-team page beside the design doc.

---

## The one-paragraph distillation

Difficulty is a small number of load-bearing knobs plus a lot of authored detail — a preset over an
orthogonal settings space, chosen up front, demoting honestly to CUSTOM, with the level relationship
(a cap *and* a player-relative element) as the axis that makes the rest matter, and coverage rather
than magnitude as the dial (record 50 §0, §7). The player's contract is written down per tier, unfair
only where declared. QoL is the budget that pays for the hard parts. The curve is fixed by adding
trainers; every gym has a catchable answer; the gym is the reward anchor; the post-game is a phase,
not an epilogue. And every number a difficulty table derives is a number the harness asserts, because
that table is exactly where shipped, acclaimed code has been found silently wrong.
