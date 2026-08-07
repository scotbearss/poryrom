---
name: librarian
description: Keep the harness's knowledge base current — file a new numbered record after a round of work, then update the wiki pages that record touches so the distilled knowledge does not rot. Use after finishing a build round, a measurement, an investigation, or a playtest, and whenever the user says "write this up", "record what we learned", or "update the docs".
---

# Librarian

Load `../_shared/voice.md` first — the reply is plain English even though what you are writing is
rigorous.

## The two layers, and the rule between them

- **`docs/records/NN-topic.md`** — append-only. What happened, in order. **Never edited after the
  fact.** A record that turns out to be wrong is corrected by a *later* record, not by editing it.
- **`docs/wiki/<topic>.md`** — maintained. What is true now, distilled from many records, each
  fact citing the record that established it.

**A record is evidence; a wiki page is a claim.** When they disagree the record wins as history
and the page is simply stale — fix the page.

## After a round of work

**1. File the record.** Next free number, `docs/records/NN-short-slug.md`. It should contain:

- what was built or measured, and why this round rather than another
- **the numbers**, exactly, with how they were obtained
- what was predicted beforehand and whether the prediction held — including the *list*, not just
  the count (a matching count with a wrong composition is the failure this project keeps finding)
- what went wrong, including the wrong turns, because those are the expensive part to rediscover
- what is still open, stated as open rather than quietly dropped

**2. Update every wiki page the round touched.** This is the step that gets skipped, and skipping
it is how a corpus rots into a pile of session logs. Ask, explicitly:

- Did this round establish a new limit? → `walls-and-budgets`, with what hitting it *looks like*
- Correct an earlier fact? → fix the page **and** note the correction in the record
- Find a new failure mode of a check? → `verification-discipline`
- Touch the save, maps, battle, audio, art or dialogue? → those pages
- Confirm or deny an engine defect? → `engine-defects`

**3. Keep the links live.** Pages link with `[[page-name]]`. Link generously — a link to a page
that does not exist yet marks something worth writing, which is useful rather than broken.

**4. Update `docs/README.md`** only if you added a page or a whole class of record.

## What makes a wiki page good

- It answers "what is true about X" without the reader knowing any history.
- Every fact cites its record inline as `(record 74)` — numbers only, never file paths, so the
  citation survives files moving.
- **Every limit says what hitting it looks like.** Most failures in this engine render as
  plausible content rather than errors; a limit without that column is half-written.
- It distinguishes what is *established* from what is a *reading*. This project has a standing
  rule that an engine defect may not be filed on a reading alone.
- It is dense and scannable. Tables for limits, short sections, no throat-clearing.

## Two failure modes worth naming

**Writing the record and stopping.** The record is the cheap half. The wiki update is what makes
the next session faster, and nothing forces it — which is exactly why it is in this skill.

**Distilling into vagueness.** "Maps have a size limit" is worse than useless. The number, the
symptom, and the record. Precision belongs in these documents even though it never belongs in the
chat reply.
