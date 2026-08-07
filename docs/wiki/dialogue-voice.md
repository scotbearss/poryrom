# Dialogue voice

**What this page is for.** Writing any line a character says, and knowing before the build whether it
sounds like the game it is sitting inside. The complaint that started this — *"the characters talk like
AI"* — is a taste judgement right up until somebody counts, and the thing being imitated was sitting in
the fork the whole time: **468 map scripts, 4,362 conversations**, every string Game Freak wrote for
Emerald's overworld (record 71). So the register is not a matter of ear. It is computed from the pin at
run time by `tools/check_dialogue.py`, and the numbers below are what that computation found. Bad prose
renders perfectly, which puts it in the class of faults only a **static check that runs before the
build** can see — see [[verification-discipline]].

---

## 1. The measured profile

Every figure is the share of *conversations* containing the thing at least once. "Ours" is the 21
conversations the first hack had written (an annex coach ×3, a blackboard, a sign, two gym gates, a
stipend); "corpus" is all 4,362 in the pin (record 71).

| axis | ours | corpus | |
|---|---|---|---|
| speaker says **I / me / my** | 23.8 % | **47.2 %** | half as often — our NPCs have no inner life |
| says **you / your** | 71.4 % | 48.7 % | 1.5× — they talk *at* the player |
| **trails off** (`…`) | **0.0 %** | **25.2 %** | never — nobody in the hack hesitated, once |
| **quotes a number** | 28.6 % | **4.4 %** | **6.5×** — the sharpest tell by a wide margin |
| **states a rule** (`must` / `cannot` / `if you`) | 14.3 % | 9.4 % | 1.5× |

That combination *is* the thing a reader hears. **A speaker with no first person, no hesitation, a
second-person address, a rule and a number is not a person in a town — it is a status readout with a
sprite.** Nothing about any individual line was wrong; the register was, and the register is what lands
first.

### 1.1 The register varies by role, sharply

| speaker group | n | I/me | you | `…` | digit | rule | pages | sentences |
|---|---|---|---|---|---|---|---|---|
| **gym leaders** | 67 | **64 %** | 63 % | **48 %** | **0 %** | 9 % | 3 | 4 |
| gym guide / greeter | 16 | 19 % | **75 %** | 19 % | **0 %** | 12 % | 4.5 | 5 |
| mart / shop clerks | 34 | 35 % | 29 % | 26 % | **0 %** | 6 % | 2 | 2 |
| route NPCs | 524 | 48 % | 39 % | 26 % | 10 % | 6 % | 2 | 2 |
| house NPCs | 524 | 50 % | 37 % | 27 % | 6 % | 7 % | 2 | 2 |

**Read the gym-leader row twice.** They are the most self-referential speakers in the game *and* the
most hesitant — nearly half of a gym leader's conversations trail off into an ellipsis. They are
allowed to be long (3 pages, 4 sentences, against the game's median of 2 and 2), because a boss is the
one person who has earned the airtime.

**Not one of the 83 gym-related conversations in Emerald contains a digit. Zero.** The hack's two gym
attendants were printing level numbers at the player — the single most out-of-register thing in it,
done by the two speakers whose real counterparts never do it (record 71).

---

## 2. The shape of the box

None of these were written down anywhere before they were measured (record 71):

- **Pages per conversation: median 2. 48.8 % are ONE page. 79 % are two or fewer. Only 9.7 % reach
  four.** The default length of a thing an NPC says is *one screen*.
- **Lines per page: two.** 5,761 pages of two, 1,948 of one; the 757 with three or more all get there
  through `\l` (which scrolls) rather than `\n`.
- **Sentences per conversation: median 2**, p90 5.
- **Words per printed line: median 5**, p95 8.
- **`\n` 6,542 · `\p` 4,128 · `\l` 811.** `\l` is rare — about one for every eight `\n`. The normal
  rhythm is *two lines, then a new page*, not a scrolling wall.
- **Final punctuation: `.` 36 % · `!` 31 % · `?` 16 % · `…` 11 %.** A third of everything anybody says
  ends in an exclamation mark.
- **Line width: the widest line the original ever shipped is 208 px**, in a 27-tile (216 px) box
  (`sStandardTextBox_WindowTemplates`). p95 is 196, p99 is 203. The font is variable-width
  (`gFontNormalLatinGlyphWidths`), so **"how many characters fit" has no answer** — 208 px is between
  34 and 53 characters depending on which ones.

### 2.1 The two-line invariant, and the one exception that has a name

A field page shows two lines; a third needs `\l`. Across **all 8,490 vanilla pages** the pre-scroll
block exceeds two lines exactly **20 times**, and all 20 are Battle Frontier **move descriptions**
printed in a taller window of their own. On real dialogue the invariant is clean and its single
exception is nameable — which is what makes it a check rather than a heuristic (record 71).

*This is the general shape this project prefers: an **absolute rule plus a measured baseline** beats a
hedged rule. Without the baseline the rule would have had to be softened into uselessness; with one,
the rule stays absolute and the exceptions become data. Same move as `check_map.py`'s 138 suppressed
vanilla quirks — see [[maps-and-tilesets]].*

---

## 3. The rules

Each one is a restatement of a measurement above, not a preference (record 71).

1. **One page is the default. Two is a lot. Three needs a reason.**
2. **Two lines a page, `\p` between pages, `\l` almost never.**
3. **The speaker must exist. Say `I`.** Nearly half of Emerald's lines are about the speaker, not
   about the player — that is where the town comes from.
4. **Let them trail off.** A quarter of the corpus uses `…`; among gym leaders, half. It is the
   cheapest single thing that turns a readout into a person.
5. **Do not read numbers out.** 4.4 % overall, **0 % anywhere near a gym**. If the player needs a
   number, put it in a `{STR_VAR}` a *system* fills, or let the mechanic show it — never have a
   character recite it.
6. **Do not state the rule.** `must` / `cannot` / `if you` is 9 %. Say what you *want* or what you
   *see*, and let refusal do the teaching. *Stating a mechanic* and *reciting its parameters* are
   different acts, and it is the second one that reads as machinery.
7. **Match the role.** A gym leader may be long, self-absorbed and wistful. A clerk is two sentences.
   A route NPC is two sentences. An explainer is second-person — but still never numeric.
8. **A third of everything ends in `!`.** This game is not cool. Neither should we be.

### 3.1 A hardcoded number in user-facing text is a second copy of the data

Two gym doors recited "15" and "19" while a table upstairs held both. The fix — a `{STR_VAR}` filled
from the table — satisfies rule 5 and the no-drift rule at once, and the same pattern carries the
climb wall's refusal, which prints what you have and what it wants, both from one table row (records
71, 77). See [[walls-and-budgets]] for why a threshold belongs in exactly one place.

### 3.2 Write for the screenshot

A screenshot can only photograph one page, so **if two numbers are the point, they belong on the same
page**. The annex coach's line was rewritten from three lines over two pages to
`"{STR_VAR_1} minutes banked. / Ceiling: level {STR_VAR_2}."` — tighter prose *and* photographable. The
format constraint improved the writing (record 65). Also: a mash *speeds* a page's print and then
advances it, so a dialogue screenshot needs the mash to stop — open the box, then go quiet for ~420
frames and let the page finish.

---

## 4. The tool — `tools/check_dialogue.py`

```bash
python3 tools/check_dialogue.py --hack <fork>
```

**Every threshold is measured from the pin at run time. Nothing in the tool is a constant**: the glyph
widths come from `src/fonts.c`, the glyph ids from `charmap.txt`, and the ceilings are percentiles of
the corpus's own distribution. A WARN means *no NPC Game Freak wrote does this*, which is a fact rather
than an opinion (record 71).

| Verdict | Condition | What it prevents |
|---|---|---|
| **FAIL** | a line wider than the corpus maximum | the line is **clipped outside the window** — **silent**, renders as ordinary text that stops |
| **FAIL** | three `\n` lines on a two-line page | the third line is **drawn off the bottom** — **silent** |
| **WARN** | over the corpus's p95 pages | drift toward a wall of text |
| **WARN** | over its p90 sentences | ditto |
| **WARN** | three or more numbers in one conversation | the status-readout register |
| **WARN** | **a rule and a number in the same conversation** | the pure systems register — the exact combination §1 measured |

Plus a **voice profile table** at the end: ours against the corpus on the five axes of §1.

Coverage: `tests/test_check_dialogue.py` — **16 tests**, every check in both directions, on a synthetic
tree whose glyphs are all 6 px wide so each expected pixel width is hand-checkable. Three sabotages
(each check made unconditionally silent) fail 2, 1 and 1 of them.

---

## 5. The unit is one conversation, and that is not a detail

The first version of the checker scoped **per file** — every map script that differed from the pin. So
adding one NPC to Rustboro pulled in all 60 of Nintendo's own conversations from that city, and the
hack's register vanished into the corpus it was being compared against. **The profile read `1.0×` on
every axis and said nothing** (record 71).

The unit is a **label whose text is not byte-identical to the pin's**.

**The general rule, which is not about dialogue: when a measurement of your own work comes back looking
exactly like the baseline, check what got swept into the sample before believing it.** The same shape
bit a sprite fixture whose source cells used the very palette index the tool under test was stamping
(record 77), so the edit was invisible and a working tool failed its own test. See
[[verification-discipline]].

---

## 6. What this does not do

It measures **shape and register**. It cannot tell you a line is boring, out of character, or a plot
hole. That judgement belongs in a **voice card per speaker**, written once and pasted into every future
line — the same fix as one canonical art brief per species, and for the same reason: a prompt describes
one artifact, a brief pins the character (records 70, 71). See [[art-pipeline]].

---

## 7. The rule that outlives the tool

**"It sounds wrong" is measurable whenever you have the thing you are imitating.** The corpus was in
the fork; the register could be *computed*; and what came out was four specific, individually
countable habits rather than a note about tone.

This is the house rule applied to prose: **derive the rule from the original's own tables, not from
your ear.** `make_card_panel.py` replays the engine's vertex maths; `new_map.py --dump-layout` refuses
invented metatile ids; `check_map.py` parses every constant it judges against out of the fork's own
source; `kitbash_sprite.py` edits a sprite a professional already drew. Dialogue was the fourth domain
to get it and art was the fifth (records 71, 74, 75).

Two corollaries worth keeping:

- **Bad prose renders perfectly.** There is no wrong number in it and no wrong picture. It belongs with
  the oversize map, the unterminated player name, the moved save layout and the mis-coloured sprite —
  faults a check must catch **before** the build, because nothing downstream will (records 68, 73, 74).
- **A style note becomes a tool the moment you have a baseline.** The measurement is what turns "write
  more like the original" into a threshold a build can fail on.

---

**Related:** [[verification-discipline]] · [[art-pipeline]] · [[maps-and-tilesets]] ·
[[walls-and-budgets]] · [[build-system]]
