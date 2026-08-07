#!/usr/bin/env python3
"""Static dialogue contract-check for the Pokémon Thing mode.

The content phase's fifth tool, and the one doc 70 §4 asks for. The user's
report was *"the characters talk like AI"*, and they were right -- but "talks
like AI" is not something a screenshot rule can catch, because BAD DIALOGUE
RENDERS PERFECTLY. Every string in this hack prints in the right box, in the
right font, at the right moment. There is no wrong number anywhere. That puts
it in the same class as an oversize map (doc 68) and an unterminated player
name (doc 68 §6.2): a fault only a check that runs BEFORE the build can see.

WHY THIS CAN BE A TOOL AND NOT AN OPINION. The entire corpus Game Freak wrote
for Emerald is sitting in the fork -- 4,362 conversations across 468 map
scripts. So every threshold here is MEASURED FROM THE ORIGINAL'S OWN DATA at
run time, never hardcoded and never a matter of taste. Same discipline as
make_card_panel.py replaying the engine's vertex maths and new_map.py refusing
invented metatile ids: derive the rule from the thing you are imitating.

WHAT IT CHECKS, in two severities.

FAIL -- the box renders wrong, silently:

  1. LINE TOO WIDE. The standard text box is 27 tiles (src/menu.c's
     sStandardTextBox_WindowTemplates), and the font is variable-width, so
     "how many characters fit" has no answer. This measures the real thing:
     each line's width in pixels through gFontNormalLatinGlyphWidths, the
     table src/text.c:1958 itself indexes, with charmap.txt supplying the
     glyph ids. The ceiling is the widest line the ORIGINAL ever shipped.
     Past it, the tail of the line is drawn outside the window.

  2. THREE LINES ON A TWO-LINE PAGE. The field box shows two lines; a third
     needs `\\l`, which scrolls. A page whose pre-scroll block holds three
     `\\n`-separated lines draws the third off the bottom. Across all 8,490
     vanilla pages this happens exactly 20 times, every one of them a Battle
     Frontier MOVE DESCRIPTION printed in a taller window of its own -- so the
     invariant is clean on real dialogue, and the exception has a name.

WARN -- the voice drifts from the corpus. Each threshold is a percentile of
the corpus's own distribution, so a WARN means "no NPC Game Freak wrote does
this", not "I would have written it differently":

  3. TOO MANY PAGES for one conversation (corpus p95).
  4. READS NUMBERS ALOUD. Only 4.4% of vanilla conversations contain a digit
     at all. Ours contained one in 29% of them -- the single sharpest tell,
     and the direct cause of the coach sounding like a status readout.
  5. STATES THE RULE. `must` / `cannot` / `can't` / `if you` appears in 7.2%
     of the corpus. A conversation that BOTH states a rule AND quotes a number
     is the systems-explaining register in its pure form.
  6. TOO MANY SENTENCES (corpus p90). The median vanilla NPC says TWO.

And a PROFILE table at the end, comparing the checked text against the corpus
on the axes that make the register: how often the speaker says `I`, how often
they say `you`, how often anyone trails off into an ellipsis, how often a
digit appears. Those are aggregate facts about a body of writing, not faults
in any one line, so they are reported rather than flagged.

WHAT IT CANNOT DO. It cannot tell you a line is boring, wrong for the
character, or a plot hole. It measures SHAPE and REGISTER. A voice card per
speaker (design/<hack>/narrative.md) is where the character judgment lives;
this is the part that can be automated, and automating it is what keeps the
judgment from having to be re-made every time a line is written.

USAGE
    python3 tools/check_dialogue.py --hack hacks/reps
    python3 tools/check_dialogue.py --hack hacks/reps RustboroCity
    python3 tools/check_dialogue.py --hack hacks/reps --all

With no map arguments it checks every map script that DIFFERS from the pin,
i.e. exactly the text this hack wrote. `--all` scores the whole tree (mostly
useful for re-deriving the corpus figures). Exit 0 = clean, 1 = findings,
2 = cannot run.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

import hx

# The standard field text box, src/menu.c sStandardTextBox_WindowTemplates.
BOX_TILES = 27
TILE_PX = 8

# Control codes that consume no pixels. `\p` new page, `\n` new line,
# `\l` scroll-and-new-line, `\xNN` a raw byte.
CTRL_RE = re.compile(r"\\(?:[nlp]|[0-9A-Fa-f]{2})")
PLACEHOLDER_RE = re.compile(r"\{[^}]*\}")
STRING_RE = re.compile(r'^\s*\.string\s+"(.*)"\s*$')
LABEL_RE = re.compile(r"^(\w+)::?\s*$")

# A digit that is part of prose, not of a symbol name or a placeholder.
DIGIT_RE = re.compile(r"(?<![A-Za-z_}])\d")
RULE_RE = re.compile(r"\bmust\b|cannot|can't|\bif you\b", re.I)
SELF_RE = re.compile(r"\bI\b|\bI'|\bme\b|\bmy\b")
YOU_RE = re.compile(r"\byou\b|\byour\b", re.I)
ELLIPSIS_RE = re.compile(r"…|\.\.\.")


def die(msg: str):
    sys.exit(f"check_dialogue.py: cannot run: {msg}")


# ------------------------------------------------------------ the engine's own tables

def load_charmap(hack: Path) -> dict[str, int]:
    """charmap.txt maps a literal to the byte the preprocessor emits."""
    path = hack / "charmap.txt"
    if not path.is_file():
        die(f"missing {path} -- is --hack a pokeemerald fork?")
    out: dict[str, int] = {}
    for line in path.read_text(errors="replace").splitlines():
        line = line.split("@")[0].strip()
        m = re.match(r"^(.*?)\s*=\s*([0-9A-Fa-f]{2})\s*$", line)
        if not m:
            continue
        lit = m.group(1)
        if len(lit) >= 3 and lit.startswith("'") and lit.endswith("'"):
            lit = lit[1:-1]
        if lit:
            out[lit] = int(m.group(2), 16)
    if not out:
        die("charmap.txt parsed to nothing -- its format moved")
    return out


def load_glyph_widths(hack: Path) -> dict[int, int]:
    """gFontNormalLatinGlyphWidths -- the table src/text.c:1958 indexes."""
    src = hack / "src/fonts.c"
    if not src.is_file():
        die(f"missing {src}")
    m = re.search(r"gFontNormalLatinGlyphWidths\[\]\s*=\s*\{(.*?)\n\};",
                  src.read_text(errors="replace"), re.S)
    if not m:
        die("gFontNormalLatinGlyphWidths not found in src/fonts.c")
    body = re.sub(r"//.*", "", m.group(1))
    widths = {int(mm.group(1), 0): int(mm.group(2))
              for mm in re.finditer(r"\[(0x[0-9A-Fa-f]+|\d+)\]\s*=\s*(\d+)", body)}
    if not widths:
        widths = dict(enumerate(int(x) for x in re.findall(r"\b(\d+)\b", body)))
    if not widths:
        die("gFontNormalLatinGlyphWidths parsed to nothing")
    return widths


class Font:
    def __init__(self, hack: Path):
        self.charmap = load_charmap(hack)
        self.widths = load_glyph_widths(hack)
        # Longest first: multi-character literals like "PKMN" are one glyph.
        self.literals = sorted(self.charmap, key=len, reverse=True)
        self.default = statistics.median(self.widths.values())

    def width(self, line: str) -> int:
        """Pixel width of one printed line, the way the engine adds it up.

        A {PLACEHOLDER} is skipped: its width is not knowable statically, and
        pretending otherwise would make every line holding one un-checkable.
        Lines with placeholders are reported separately instead.
        """
        total, i = 0, 0
        while i < len(line):
            if line[i] == "{":
                j = line.find("}", i)
                i = j + 1 if j > 0 else i + 1
                continue
            m = CTRL_RE.match(line, i)
            if m:
                i = m.end()
                continue
            for lit in self.literals:
                if line.startswith(lit, i):
                    total += self.widths.get(self.charmap[lit], self.default)
                    i += len(lit)
                    break
            else:
                i += 1
        return total


# ------------------------------------------------------------ the corpus

def parse_scripts(path: Path) -> list[tuple[str, str]]:
    """A scripts.inc -> [(label, joined .string text)], in file order."""
    out, label, buf = [], None, []
    for line in path.read_text(errors="replace").splitlines():
        lm = LABEL_RE.match(line)
        if lm:
            if buf:
                out.append((label, "".join(buf)))
                buf = []
            label = lm.group(1)
            continue
        sm = STRING_RE.match(line)
        if sm:
            buf.append(sm.group(1))
        elif buf and line.strip() and not line.strip().startswith("@"):
            out.append((label, "".join(buf)))
            buf = []
    if buf:
        out.append((label, "".join(buf)))
    return [(lab or "?", t[:-1] if t.endswith("$") else t) for lab, t in out if t.strip()]


def printed(text: str) -> str:
    return PLACEHOLDER_RE.sub("", CTRL_RE.sub("", text))


def pages(text: str) -> list[str]:
    return text.split(r"\p")


def page_lines(page: str) -> list[str]:
    return [ln for ln in re.split(r"\\[nl]", page) if ln.strip()]


def prescroll_lines(page: str) -> list[str]:
    """Lines drawn before the first `\\l`, i.e. what must fit in two rows."""
    return [ln for ln in page.split(r"\l")[0].split(r"\n") if ln.strip()]


def sentences(text: str) -> int:
    return len([s for s in re.split(r"[.!?…]+", printed(text)) if s.strip()])


class Corpus:
    """Measured from a tree's own map scripts. Nothing here is hardcoded."""

    def __init__(self, root: Path, font: Font):
        self.convos = []
        for f in sorted((root / "data/maps").glob("*/scripts.inc")):
            for lab, text in parse_scripts(f):
                self.convos.append((f.parent.name, lab, text))
        if len(self.convos) < 100:
            die(f"{root} yielded only {len(self.convos)} conversations -- "
                "is it a pokeemerald tree?")
        self.font = font
        widths, self.page_counts, self.sentence_counts = [], [], []
        for _, _, t in self.convos:
            self.page_counts.append(len(pages(t)))
            self.sentence_counts.append(sentences(t))
            for pg in pages(t):
                widths += [font.width(ln) for ln in page_lines(pg)]
        self.max_line_px = max(widths)
        self.p95_pages = int(self._q(self.page_counts, 95))
        self.p90_sentences = int(self._q(self.sentence_counts, 90))
        self.rates = self._rates(self.convos)

    @staticmethod
    def _q(vals, p):
        return statistics.quantiles(sorted(vals), n=100)[p - 1]

    @staticmethod
    def _rates(convos):
        n = len(convos)
        txt = [printed(t) for _, _, t in convos]
        return {
            "says I/me/my": 100 * sum(1 for t in txt if SELF_RE.search(t)) / n,
            "says you/your": 100 * sum(1 for t in txt if YOU_RE.search(t)) / n,
            "trails off (…)": 100 * sum(1 for t in txt if ELLIPSIS_RE.search(t)) / n,
            "quotes a number": 100 * sum(1 for t in txt if DIGIT_RE.search(t)) / n,
            "states a rule": 100 * sum(1 for t in txt if RULE_RE.search(t)) / n,
        }


# ------------------------------------------------------------ checks

class Findings(list):
    def fail(self, where, check, msg):
        self.append(("FAIL", where, check, msg))

    def warn(self, where, check, msg):
        self.append(("WARN", where, check, msg))


def check_conversation(where, label, text, font, corpus, findings):
    at = f"{where}:{label}"
    for i, pg in enumerate(pages(text)):
        for ln in page_lines(pg):
            w = font.width(ln)
            if w > corpus.max_line_px:
                findings.fail(
                    at, "line-width",
                    f'page {i + 1}: {w} px > {corpus.max_line_px} px, the widest line '
                    f'the original ever shipped ({BOX_TILES}-tile box = '
                    f'{BOX_TILES * TILE_PX} px): the tail is drawn outside the '
                    f'window. "{printed(ln).strip()}"')
        head = prescroll_lines(pg)
        if len(head) > 2:
            findings.fail(
                at, "page-lines",
                f"page {i + 1} puts {len(head)} lines in a two-line box before any "
                f"\\l: the third is drawn off the bottom. Use \\l to scroll, or "
                f"\\p for a new page.")

    n_pages = len(pages(text))
    if n_pages > corpus.p95_pages:
        findings.warn(at, "length",
                      f"{n_pages} pages; the corpus 95th percentile is "
                      f"{corpus.p95_pages}. Nobody in the original talks this long.")

    n_sent = sentences(text)
    if n_sent > corpus.p90_sentences:
        findings.warn(at, "sentences",
                      f"{n_sent} sentences; the corpus 90th percentile is "
                      f"{corpus.p90_sentences} and its MEDIAN is 2.")

    body = printed(text)
    digits = len(DIGIT_RE.findall(body))
    if digits and RULE_RE.search(body):
        findings.warn(at, "systems-voice",
                      f"states a rule AND quotes {digits} number(s) in one "
                      f"conversation. Only {corpus.rates['quotes a number']:.1f}% of "
                      f"the corpus contains a digit at all and "
                      f"{corpus.rates['states a rule']:.1f}% states a rule; doing both "
                      f"at once is the register the player called 'talks like AI'.")
    elif digits >= 3:
        findings.warn(at, "numbers",
                      f"{digits} numbers in one conversation, where only "
                      f"{corpus.rates['quotes a number']:.1f}% of the corpus contains "
                      f"even one.")


# ------------------------------------------------------------ entry

def our_conversations(hack: Path, pin: Path):
    """Every conversation this hack WROTE, per label, and only those.

    Scoping by FILE is too coarse: adding one NPC to Rustboro pulls all 60 of
    Nintendo's own conversations in with it, and they then dominate the voice
    profile the tool exists to compute -- the hack's register vanishes into
    the corpus it is being compared against. So the unit is the conversation:
    a label whose text is not byte-identical to the pin's is ours. Same
    baseline discipline as check_map.py, one level finer.
    """
    out = []
    for f in sorted((hack / "data/maps").glob("*/scripts.inc")):
        base = pin / "data/maps" / f.parent.name / "scripts.inc"
        vanilla = dict(parse_scripts(base)) if base.is_file() else {}
        for label, text in parse_scripts(f):
            if vanilla.get(label) != text:
                out.append((f.parent.name, label, text))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hack", default=str(hx.default_hack()), help="hack root (a pokeemerald fork)")
    ap.add_argument("--corpus", default=str(hx.ENGINE),
                    help="tree the thresholds are measured from; the pinned engine")
    ap.add_argument("--all", action="store_true",
                    help="check every map script, not only the ones that differ from the pin")
    ap.add_argument("--strict", action="store_true", help="exit 1 on WARNs too")
    ap.add_argument("maps", nargs="*", help="map dir names; default: what the hack changed")
    args = ap.parse_args()

    hack, pin = Path(args.hack), Path(args.corpus)
    font = Font(hack)
    corpus = Corpus(pin, font)

    if args.maps or args.all:
        files = ([hack / "data/maps" / m / "scripts.inc" for m in args.maps]
                 if args.maps else sorted((hack / "data/maps").glob("*/scripts.inc")))
        for p in files:
            if not p.is_file():
                die(f"no map script at {p}")
        checked = [(p.parent.name, lab, t) for p in files for lab, t in parse_scripts(p)]
        scope = f"{len(files)} script(s)"
    else:
        checked = our_conversations(hack, pin)
        scope = "everything this hack wrote"
        if not checked:
            print("no conversation differs from the pin -- nothing of ours to check")
            return 0

    findings = Findings()
    for where, label, text in checked:
        check_conversation(where, label, text, font, corpus, findings)

    for sev, where, check, msg in findings:
        print(f"{sev} {where} [{check}] {msg}")

    if checked:
        print(f"\nVOICE PROFILE -- {len(checked)} conversation(s) ({scope}), "
              f"against {len(corpus.convos)} in the original")
        mine = Corpus._rates(checked)
        print(f"  {'axis':22s} {'ours':>8s} {'corpus':>8s}   ratio")
        for k in corpus.rates:
            m, c = mine[k], corpus.rates[k]
            ratio = f"{m / c:.1f}x" if c else "--"
            flag = "  <--" if c and (m / c > 2 or m / c < 0.5) else ""
            print(f"  {k:22s} {m:7.1f}% {c:7.1f}%  {ratio:>6s}{flag}")

    fails = sum(1 for f in findings if f[0] == "FAIL")
    warns = len(findings) - fails
    print(f"\nchecked {len(checked)} conversation(s); ceiling {corpus.max_line_px} px, "
          f"p95 {corpus.p95_pages} pages, p90 {corpus.p90_sentences} sentences: "
          f"{fails} FAIL, {warns} WARN")
    return 1 if fails or (warns and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
