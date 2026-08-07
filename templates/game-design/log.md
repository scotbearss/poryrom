# Log — append-only

Rules (spec: `design/living-design-doc.md`): entries are appended at the end, never
edited, never deleted. History is not rewritten — a reversed decision gets a new
SUPERSEDE entry; the original stays. Every diff to this file should be pure addition.

Entry format — a dated heading with a type tag and one-line summary, then optional
detail lines:

    ## YYYY-MM-DD — TYPE: one-line summary
    Optional detail: rationale, evidence, pointers.

Types:

- **PHASE** — a phase transition (forward or backtrack), with the gate evidence
  (e.g. the `verify_spec.py` PASS that justified leaving scaffold). Update the
  index's Phase block in the same session.
- **DECISION** — something entering the index's locked-decisions table.
- **SUPERSEDE** — a locked decision reversed. Names the original entry's date and
  the new evidence. Update the index table row; leave the old log entry alone.
- **QUESTION** / **ANSWER** — an open question raised or resolved.
- **REPORT** — a skill wrote a document to `reports/`; one line naming the file.
- **SESSION** — optional end-of-session note when work stopped mid-slice: where
  things stand, what's half-done, what the next session should know.

---
