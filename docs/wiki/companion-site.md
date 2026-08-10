# companion-site

**What this page is for.** `tools/make_dex.py` generates a self-contained, static reference site
straight out of a game's own source tree — a PokemonDB-style encyclopedia and a build dashboard
in one generator, regenerated fresh every build so it can never drift from the ROM. Read this
page before you run it for the first time, before you touch its output by hand (don't — it's
gitignored and disposable), and before you reach for `--publish`, which is the one command in
this whole harness that produces something meant to leave the workbench.

The one rule everything else follows: **if it isn't derivable from the tree, it doesn't appear.**
Two labelled exceptions exist — the roadmap and the story thread — and both are visually
unmistakable for a page the tree already proves.

---

## 1. Running it

```bash
python3 tools/make_dex.py                       # workspace found by walking up for harness.json
python3 tools/make_dex.py --game ~/src/mygame    # explicit game repo
python3 tools/make_dex.py --record               # ...and log this build (build ritual only)
python3 tools/make_dex.py --publish              # render the player-facing tree instead
python3 tools/make_dex.py --out /tmp/dex --open  # custom output dir, open when done
```

It's wired into the build-and-verify ritual and regenerates after every green build automatically
— you don't normally need to run it by hand. Output lands under `<workspace>/dex/` (or
`<workspace>/publish/` for `--publish`), both gitignored: the output is a build artifact, same
class as the ROM, and it contains Nintendo-derived art that must never be committed.

Rendering the location pages' map images needs Pillow. It's imported lazily — without it every
location page keeps everything except the picture, and a warning is printed once, not a failed
run.

## 2. What it reads, and how "new" and "changed" are decided

Everything comes from the fork's own source: species, moves, abilities, items, types, trainers
and their parties, wild encounter tables, every map's block data and `scripts.inc`, dex order and
item order from the `constants/` headers. The **same parser** then reads the pinned engine clone
at the ref this repo's pin file names, and a fact is "new" or "changed" only if it differs from
that stock reading — never asserted, always diffed. This is the same discipline the rest of the
harness holds itself to: nothing is claimed that the tree doesn't prove.

The dashboard additionally reads the workspace around the fork — the built ROM's age and size,
`patches/<game>.patch`, the game repo's git HEAD, which of the game's own `verify/*.json` specs
can actually run here (a spec needing a savestate that was never generated is counted separately
from one that fails) — all read, none asserted; anything unreadable is simply absent from the
page rather than guessed at.

## 3. Page set

| Page | What it is |
|---|---|
| `index.html` | The dashboard — build health, what exists (counted against stock), new content finished or not |
| `pokedex.html` + `pokemon/<key>.html` | Every species: stats, types, defenses, evolution chain, learnsets, where it lives, who trains it |
| `moves.html`, `abilities.html`, `items.html` + per-entry pages | Sortable hubs, each reverse-linking to every species/trainer/place that uses the entry |
| `trainers.html` + `trainers/<key>.html` | Every trainer with a party: class, levels, held items, moveset, lines they speak |
| `gyms.html` | The eight (in stock) places whose own scripts award a badge — see §5 |
| `locations.html` + `locations/<key>.html` | Every map, rendered from its own block data, with its exits, wild table, trainers and ground items |
| `changes.html` | The current diff against stock, categorized |
| `devlog.html` | Build-by-build history — see §4 |
| `roadmap.html` | The design doc's own plan, read and reported, never audited — see §6 |
| `thread.html` | The game in play order — see §5 |
| `types.html` | The type chart |

Cross-linking is exhaustive: every species, move, ability, item, trainer and location name in any
table is a link.

## 4. The dev log — the one thing this site stores instead of derives

A source tree only ever shows its present state, so build-over-build history is the single fact
this generator cannot recompute if it's lost. `--record` (passed only by the build ritual, after
a green build) appends one small JSON snapshot to `<game>/devlog/`, git-**tracked** in the game
repo. Every other invocation only reads that history.

A few things worth knowing before touching this:

- **Fingerprint the entity, never its diff.** A brand-new species has no diff against stock at
  all, so a diff-based fingerprint would go blind to every edit made after the one that
  introduced it.
- **A build that moved no data writes nothing**, and the page says so. Two green builds of an
  unchanged tree are two builds and one fact, not two.
- **A stock entry deleted outright** never differed from stock while it existed, so no snapshot's
  entry list ever names it — only the category's moving total records that it went. The pinned
  engine clone, not the fork, is where a deleted entry's name is read back from.
- **Names are frozen at write time.** A species renamed since keeps the name the record was
  written with, and its link is dropped rather than pointed at a page that would now say
  something else.

## 5. The story thread and gyms

**Gyms.** The obvious markers are all wrong — the map header flag that looks like it means "gym"
also selects Battle Pyramid squares in stock, a gym's other floors don't carry any marker, and
there's no gym-leader trainer class in the data at all. The definition that actually works: **a
gym is a place whose own scripts award a badge.** From there the leader is read off whichever
script awards it, and the badge's name is lifted from the congratulation line the game hands it
over with — no table anywhere holds it as data, so a badge phrased unusually gets a number
instead of a guessed name.

**The story thread** reads a `## Route order` section from the game's own `design/narrative.md` —
see the template for the exact shape (a numbered list of beats, each naming its places in play
order, with an optional `Gate` field). This is deliberately the one place in the whole feature
where a human writes something the tree cannot derive: a world with loops has more than one valid
traversal and no way to prove which was meant, so **the order is always authored, never
computed.** What the site *does* derive from the connection graph is coverage — which places a
beat's route touches, what hangs immediately off it (bounded to two hops, so "off the path" means
a side room, not "the rest of the game"), and which places no beat reaches at all.

Gym badges and victories that a place's scripts *check* are read the same way and shown beside
each beat's authored `Gate`, never merged with it — several stock maps read a badge flag just to
move a shopkeeper, not to bar a door, and this parser can't tell those two apart. It's labelled a
check, never a gate, on purpose.

## 6. The roadmap — reported, not audited

`roadmap.html` reads the design doc's identity block, its slice plan (`### Slice N` headings with
the `- **Status:** planned | building | done | cut` field), the Phase block, Next actions, Open
questions and the Cut list — all markup the design-doc template already asks the author to write,
none of it invented for the site. **A slice is marked done by the person who wrote it, and this
page reports that mark rather than verifying it** — what the tree actually contains lives on the
dashboard and in `changes.html` instead.

Three checks run against the doc's own stated rules, because they're derivable even though the
doc's content isn't: a slice marked `planned` sitting above one marked `done` means one of the two
is stale (the plan's own ordering rule says so); a status word outside the plan's four-word
vocabulary is kept verbatim rather than rounded to the nearest known one; and an unbuilt slice
that names something the tree already contains is a contradiction worth surfacing.

## 7. Theming

Five surfaces — accent, accent-2, heading face, radius, border weight — are read from
`<workspace>/design/dex_theme.toml` if present (a flat `key = "value"` file, not real TOML parsing,
so there's no parser dependency to add). A game that sets nothing gets the built-in default look.
Fonts (Newsreader, IBM Plex Sans/Mono, both OFL-licensed — see `tools/dex_fonts/`) are vendored
into every site's `assets/fonts/` and never loaded from a CDN, so the site keeps working from
`file://` with no network access at all.

## 8. Publish mode

```bash
python3 tools/make_dex.py --publish
```

Renders the player-facing tree to `<workspace>/publish/` (or `--out`). This is **one flag on the
same generator, not a second template** — `--publish` only ever decides what a page is *allowed to
say*, never what was parsed, so the dev tree and the public tree share their facts by construction
and can only ever drift in candour, not in truth.

**Strips entirely:** the build-health section (ROM age/size, commit, backup state, checks), every
staleness sentence, byte costs and assertion counts in the dev log, the "what's still unfinished"
half of the dashboard, and the dated locked-decisions table.

**Keeps, reduced:** the roadmap becomes a "What's next" teaser — only slices marked `planned` or
`building`, by title and one sentence, no dates, no status words printed. A slice the plan's own
evidence disagrees with (see §6's ordering check) is withheld rather than shown with the
disagreement smoothed over — a short teaser costs nothing; advertising finished work as still
coming is the actual failure this mode exists to prevent.

**Keeps in full:** the entire reference (species/moves/abilities/items/trainers/locations), the
story thread, the "what's different from vanilla" page, and the dev log rendered as plain patch
notes.

**`--publish` and `--record` refuse to run together** — a render nobody built has no business
writing a dev-log entry — and publishing is never triggered by the build ritual. It's a command
the builder runs on purpose, the same posture this harness takes toward everything else that
leaves the workbench: nothing crosses without an explicit human step, and where the output goes
afterward is the builder's decision, not this tool's.

## 9. Known limitations (deliberate — this is a regex-level parser, not a compiler)

- Preprocessor conditionals aren't evaluated; a species guarded by a disabled `#if` still appears.
- Config-dependent values (ternaries keyed on build flags) take the first/modern branch, matching
  the engine's default configuration.
- A rendered map is terrain only — no NPC, item ball or warp sprite drawn on top, though all three
  are listed beside it. Water and flower tile animation isn't run; the base tile is drawn still.
- Dialogue is quoted, never resolved: control codes like `{STR_VAR_1}` stay as written, and which
  of a battle macro's arguments is the intro versus the defeat line varies by macro — the site
  shows the lines in the order the macro names them and doesn't guess which is which.
- Trainer names aren't unique in the base data (multiple "Grunt"s, duplicate rival names); every
  trainer link carries its game constant rather than an invented distinguishing name.

---

**See also:** [[build-system]] · [[maps-and-tilesets]] · [[verification-discipline]]
