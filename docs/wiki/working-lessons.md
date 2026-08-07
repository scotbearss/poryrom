# Working lessons — how this project has learned to work

**What this page is for.** These are not facts about the engine; they are facts about *doing this
kind of work*, each one paid for by a specific failure. They are the entries that would otherwise
be rediscovered. Engine knowledge lives in [[walls-and-budgets]], [[save-system]] and their
siblings; proof technique lives in [[verification-discipline]]. This page is the rest.

---

## Instruments lie before subjects do

**Read the tool's own source before blaming the thing it measures.** A proof that a save survives
a relaunch could never pass — not because the save was broken, but because the headless emulator
never attached a save file at all. Reading its `main()` answered in minutes what a week of
theorising would not have (record 61).

**Then ask who compiles the instrument.** That same limit was filed as *structurally impossible*
and correctly cited to the emulator's source. But the emulator is built from our own Dockerfile:
the fix was six lines behind an environment-variable gate (record 73). **"Structural" is a claim
about where a boundary is — go and find the boundary before believing it.**

This has now happened four times, three of them during the extraction alone: an emulator that
could not save, a `docker image inspect` that reported a missing image the daemon was happily
running, and a backup check that compared timestamps and cried drift about identical content
(record 82). **When a verdict is surprising, suspect the verdict.**

## A rule you have been bitten by twice needs a mechanism, not a third paragraph

Two concurrent verification runs sharing a scratch directory produce a *confident wrong answer*.
That was written down in detail, with its exact tell. It then happened again — to a session that
had read the entry. The memory did not work; a lock file did.

The same shape recurs: a hand-maintained backup exception list became a tool; a remembered
"refresh the patch" step became an automatic post-build action; "which forks must exist" became
`fixtures.json` after the missing list failed a lint 27 times (record 82). **Recognising a trap is
not avoiding it. The second fall should buy executable enforcement.**

## Assert per replacement, never "the file changed"

An edit script that applies several substitutions and then checks only that the file differs will
report success when one of them silently failed to match. The extraction converted 341 sites this
way and the per-replacement assertions caught a file the original audit's list had missed
(record 82 §3.2).

Same family: a verification loop over an unquoted variable in **zsh** — which does not word-split
— checked zero files and printed exactly what success prints. And a `sed` inside a Dockerfile
whose anchor stops matching **exits 0** and leaves the file untouched, so the image builds and the
feature is silently absent. Every patch in a build file needs a `grep -q` after it (record 73).

## Predict in writing, then diff the LIST

Before a counterfactual run, write down which assertions you expect to survive. Then compare the
*list*, never the count. A prediction of "0-3, from these three probes" landed in range with
**every element wrong** (record 79); another came back 3-against-3 with two of the three different
(record 72). Both times the count concealed the finding and the list revealed it.

The corollary is that the predicted set is *derivable rather than guessable*: it is every
assertion the spec's own why-field already calls weak. See [[verification-discipline]] for the
ranking of weak forms.

## Measure before you fix, and let the fix's comment carry the numbers

A one-character change is exactly the size that tempts you to just make it. Measuring first cost
one extra build and bought a source comment reading *"tag 255, branch skipped, 255 written, field
reads 15"* instead of *"this looked wrong"* (record 80). See [[engine-defects]].

**And the strongest evidence a codebase can give you is two copies of one decision that
disagree.** One function tests `x <= 16`, another tests `x >= 16` on the identical expression, and
the source calls the second "basically a copy" of the first. You do not need to know which is
right to know that one is wrong — which is far cheaper to establish than correctness.

## Derive the artifact instead of generating it

When a generator keeps under-delivering, ask whether the thing can be *derived* from something
that already exists. This project reached that answer independently in four domains: map data
derived from a real layout, a generated UI panel replaying the engine's own arithmetic, prose
scored against the original's own corpus, and finally sprite art produced by **palette-editing an
existing official sprite**, which is lossless because every pixel stays where a professional put
it (records 74, 75). See [[art-pipeline]].

**Check whether the rule you need is already written down somewhere else in your own project.**
Three of those four existed before the fourth was found.

## Taste becomes measurable the moment you have the thing you are imitating

*"The characters talk like AI"* is a judgement until somebody counts. The corpus was sitting in the
fork: first person 23.8% against the original's 47.2%, ellipsis 0% against 25.2%, a digit 28.6%
against 4.4%. A speaker with no self, no hesitation, and a number is a status readout with a
sprite (record 71). See [[dialogue-voice]].

**Scope the measurement to the right unit.** The first version compared whole files, so adding one
NPC to a city pulled in sixty of that city's original conversations and the profile read `1.0×` on
every axis — a confident measurement of nothing.

## Prefer an absolute rule plus a measured baseline over a hedged rule

"No NPC may stand on an impassable tile" sounds absolute, and vanilla Emerald breaks it **378
times on purpose** — clerks behind counters, a legendary on its rock. Without a baseline the rule
would have been softened into uselessness. With one, the rule stays absolute and the exceptions
become *data* (record 70).

## A playtest of one artifact tests everything that shares its scaffolding

When a playtest finds something, grep for who else copied that pattern before calling it fixed. A
shortcut that skipped an intro screen left a name buffer as all zeros — not *empty*, **unterminated**
— and the identical shortcut was sitting in a second tool nobody had run yet (record 68).

**The general form: a shortcut inherits every default the step it skipped would have set, and the
ones that bite are the defaults that are zero-valid.**

## Reclaiming space you do not need is how a safe round becomes a risky one

A plan to reclaim 1,444 bytes was written down and then deliberately not done: keeping the old
field made it the migration source *and* kept the whole round a pure addition with no layout
change anywhere. Those bytes were not contended by anything (record 79). **The tidiest prediction
is often the one to abandon.**

## Choosing a base is two decisions, and design lessons cross both

**Engine choice is two independent axes: the game base (Emerald vs FireRed) AND the methodology
(decomp fork vs binary patch).** The famous FireRed hacks differ from a decomp project on *both*
axes, so their implementation techniques transfer to no decomp work — even a hypothetical FireRed
decomp would close only the first axis (record 53 §2). But design lessons are base-independent:
**never discard a design citation because its exemplar turned out to be binary-lane.** The lineage
split invalidates "here is how they built it"; it does not invalidate "here is what they built and
how players received it" (record 53 §3). And do not read the exemplars' similarity to each other as
convergent design — it is shared substrate, one common engine layer under both (record 53). The
default stands: **one base deeply understood beats two understood shallowly** (record 53 §5).

## A failure that stops reproducing when serialized is not thereby explained

**Under macOS Docker file sharing, a container started milliseconds after the host mutates a
mounted directory can transiently see that directory as missing.** Three runs died with a stable
signature; the first two coincided with concurrent harness runs, and "concurrency corrupts the
shared scratch" fit perfectly — then the third death happened in a fully serial queue and the
theory died on the data point. The hardening is an in-container `mkdir -p` on the mounted path,
forcing in-container resolution — a no-op when the mount is fresh (record 63). The transferable
half is the diagnostic rule: serializing made the failure rarer, not *explained*. A coincidence
with concurrency is a hypothesis, and it owes you a mechanism before it becomes a fix. See
[[verification-discipline]] for the harness-side twin of this rule.

## Things that are only true because someone checked

- **A design doc's derived numbers rot; its decisions do not.** Recompute anything derived at
  build time, and for a save layout make the compiler assert it.
- **A constant written twice in two bases is a second copy of the data.** A hex value hand-converted
  to decimal in a JSON spec was wrong, and failed a correct build. Harmless in that direction —
  a **false pass** in the other.
- **A hardcoded number in user-facing text is a second copy of the data too.** Two gym doors
  recited numbers a table upstairs already held.
- **Ask who allocates a struct, not how big it is.** Shrinking something reached through a
  substruct allocator frees space *inside a fixed-size arena*, which no link report can see.
- **An append-only tool's refusal is not its caller's failure.** A generator exiting non-zero on
  "this already exists" is correct for it; a wrapper that treated that as an error silently
  produced a fixture missing one of its three arms. Assert the **end state**, never the tool's
  opinion of whether it changed anything.
- **A protection that lives in a file you are not moving is a protection you lose** — silently.
  Extracting a subtree dropped every ignore rule that lived one level up, and the next commit
  would have added a save file out of a Nintendo-derived ROM (record 82 §4.5b). The same failure
  wears a second costume: a rule that *did* move can hold a **path that went stale** — the
  captured-audio rule pointed at `docs/assets/` after the assets moved under `docs/records/`,
  and matched nothing for two days. A `git check-ignore` probe is the mechanism that sees both
  costumes; run it whenever an ignore rule's subject or the rule itself changes address
  (record 85 §2).
