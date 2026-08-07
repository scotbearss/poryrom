#!/usr/bin/env python3
"""Unit tests for check_dialogue.py -- the static dialogue contract-check.

Every check gets BOTH directions, for the reason test_check_map.py already
gives: a contract-check whose failure direction was never executed is the same
mistake as a spec with no counterfactual.

The fixture is a synthetic mini-tree: a charmap, a glyph-width table and two
map scripts, one standing in for the pin and one for the hack. Small, but
format-faithful, so a drift in how the real engine writes either table shows
up here as a loud sys.exit rather than a quiet wrong answer.

The glyph widths are DELIBERATELY UNIFORM (6 px each) in the fixture, which
makes every expected pixel width in this file hand-checkable. The real table
is variable-width; that is measured against the real corpus, not here.

    python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import pathlib
import string
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import check_dialogue as cd  # noqa: E402

GLYPH_PX = 6

# 100 conversations of two pages, two lines, two sentences -- a corpus whose
# every percentile is known by construction, so a threshold that comes out
# wrong is visible rather than merely different.
FILLER = "".join(
    f"Vanilla_Text_{i}:\n"
    f'\t.string "I said a thing.\\n"\n'
    f'\t.string "So did you.\\p"\n'
    f'\t.string "Then I left.\\n"\n'
    f'\t.string "Bye now.$"\n\n'
    for i in range(120)
)


def build_fixture(root: pathlib.Path):
    # Quoted literals, exactly as the real charmap.txt writes them -- the
    # space is `' ' = 00` there, and an unquoted one would parse to nothing.
    GLYPHS = string.ascii_letters + " .!?,'0123456789"
    charmap = "\n".join(f"'{c}'  = {0x40 + i:02X}" for i, c in enumerate(GLYPHS))
    widths = ",\n".join(f"    [0x{0x40 + i:02X}] = {GLYPH_PX}"
                        for i in range(len(GLYPHS)))
    for rel, text in {
        "charmap.txt": charmap + "\n",
        "src/fonts.c": ("ALIGNED(4) const u8 gFontNormalLatinGlyphWidths[] = {\n"
                        + widths + ",\n};\n"),
    }.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    write_script(root, "TestTown", FILLER)


def write_script(root: pathlib.Path, name: str, body: str):
    p = root / "data/maps" / name / "scripts.inc"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def convo(label, *lines):
    body = "".join(f'\t.string "{l}"\n' for l in lines)
    return f"{label}:\n{body}\n"


class CheckDialogueTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.pin = self.root / "pin"
        self.hack = self.root / "hack"
        build_fixture(self.pin)
        build_fixture(self.hack)
        self.addCleanup(self._tmp.cleanup)
        self.font = cd.Font(self.hack)
        self.corpus = cd.Corpus(self.pin, self.font)

    # -- plumbing --------------------------------------------------------

    def add(self, body, name="TestTown"):
        """Append a conversation to the HACK's copy only, so it reads as ours."""
        p = self.hack / "data/maps" / name / "scripts.inc"
        p.write_text(p.read_text() + body)

    def run_tool(self, argv_extra=()):
        argv = ["check_dialogue.py", "--hack", str(self.hack),
                "--corpus", str(self.pin), *argv_extra]
        old, sys.argv = sys.argv, argv
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = cd.main()
        finally:
            sys.argv = old
        return code, buf.getvalue()

    def findings(self, check):
        f = cd.Findings()
        for where, label, text in cd.our_conversations(self.hack, self.pin):
            cd.check_conversation(where, label, text, self.font, self.corpus, f)
        return [x for x in f if x[2] == check]

    # -- the parsed tables -----------------------------------------------

    def test_glyph_widths_come_from_the_fork(self):
        self.assertEqual(self.font.width("abc"), 3 * GLYPH_PX)

    def test_a_missing_width_table_is_loud_not_silent(self):
        p = self.hack / "src/fonts.c"
        p.write_text("const u8 gSomethingElse[] = {1, 2};\n")
        with self.assertRaises(SystemExit) as cm:
            cd.Font(self.hack)
        self.assertIn("gFontNormalLatinGlyphWidths", str(cm.exception))

    def test_control_codes_and_placeholders_cost_no_pixels(self):
        self.assertEqual(self.font.width(r"ab\ncd"), 4 * GLYPH_PX)
        self.assertEqual(self.font.width(r"ab{STR_VAR_1}cd"), 4 * GLYPH_PX)

    def test_corpus_thresholds_are_measured_not_assumed(self):
        # The filler is two pages / four sentences per conversation by
        # construction, and its widest line is "I said a thing." = 15 glyphs.
        self.assertEqual(self.corpus.max_line_px, 15 * GLYPH_PX)
        self.assertEqual(self.corpus.p95_pages, 2)
        self.assertEqual(self.corpus.p90_sentences, 4)

    def test_a_corpus_that_is_not_a_pokeemerald_tree_is_refused(self):
        thin = self.root / "thin"
        (thin / "data/maps").mkdir(parents=True)
        with self.assertRaises(SystemExit) as cm:
            cd.Corpus(thin, self.font)
        self.assertIn("conversations", str(cm.exception))

    # -- scoping: our text, not Nintendo's -------------------------------

    def test_only_conversations_that_differ_from_the_pin_are_ours(self):
        self.assertEqual(cd.our_conversations(self.hack, self.pin), [])
        self.add(convo("Ours_Text_Hi", "Hi.$"))
        ours = cd.our_conversations(self.hack, self.pin)
        self.assertEqual([lab for _, lab, _ in ours], ["Ours_Text_Hi"])

    def test_an_edited_vanilla_line_counts_as_ours(self):
        # Scoping by FILE would drag in all 120 of the pin's conversations;
        # scoping by LABEL must pick up exactly the one that changed.
        p = self.hack / "data/maps/TestTown/scripts.inc"
        p.write_text(p.read_text().replace("Bye now.$", "Farewell.$", 1))
        ours = cd.our_conversations(self.hack, self.pin)
        self.assertEqual([lab for _, lab, _ in ours], ["Vanilla_Text_0"])

    # -- each check, both directions -------------------------------------

    def test_line_width(self):
        wide = "a" * 16          # 96 px, one glyph over the corpus's 90
        fits = "a" * 15          # exactly the corpus maximum: clean
        self.add(convo("Ours_Text_Fits", f"{fits}$"))
        self.assertEqual(self.findings("line-width"), [])
        self.add(convo("Ours_Text_Wide", f"{wide}$"))
        found = self.findings("line-width")
        self.assertEqual([f[0] for f in found], ["FAIL"])
        self.assertIn("outside the", found[0][3])

    def test_page_lines(self):
        # Two lines before a scroll: fine. A third with \n: drawn off the box.
        self.add(convo("Ours_Text_Two", r"one\n", r"two$"))
        self.assertEqual(self.findings("page-lines"), [])
        # ...and a third reached by \l is the CORRECT way, so it must stay clean.
        self.add(convo("Ours_Text_Scroll", r"one\n", r"two\l", r"three$"))
        self.assertEqual(self.findings("page-lines"), [])
        self.add(convo("Ours_Text_Three", r"one\n", r"two\n", r"three$"))
        found = self.findings("page-lines")
        self.assertEqual([f[0] for f in found], ["FAIL"])
        self.assertIn("off the bottom", found[0][3])

    def test_length_and_sentences(self):
        self.add(convo("Ours_Text_Short", r"I went.\n", r"You came.$"))
        self.assertEqual(self.findings("length"), [])
        self.assertEqual(self.findings("sentences"), [])
        self.add(convo("Ours_Text_Long", r"a. b.\p", r"c. d.\p", r"e.$"))
        self.assertEqual([f[0] for f in self.findings("length")], ["WARN"])
        self.assertEqual([f[0] for f in self.findings("sentences")], ["WARN"])

    def test_systems_voice_needs_BOTH_a_rule_and_a_number(self):
        # A number alone, or a rule alone, is ordinary. Together they are the
        # register the player named.
        self.add(convo("Ours_Text_JustNumber", "I have 3 of them.$"))
        self.add(convo("Ours_Text_JustRule", "You must be brave.$"))
        self.assertEqual(self.findings("systems-voice"), [])
        self.add(convo("Ours_Text_Both", "You must be level 15.$"))
        found = self.findings("systems-voice")
        self.assertEqual([f[0] for f in found], ["WARN"])
        self.assertIn("talks like AI", found[0][3])

    def test_bare_number_pile_up(self):
        self.add(convo("Ours_Text_Two", "I ran 5 laps in 9 minutes.$"))
        self.assertEqual(self.findings("numbers"), [])
        self.add(convo("Ours_Text_Three", "I ran 5 laps in 9 minutes on 3 days.$"))
        self.assertEqual([f[0] for f in self.findings("numbers")], ["WARN"])

    def test_a_symbol_name_is_not_a_number(self):
        # STR_VAR_1 and FLAG_2 contain digits and are not the NPC counting.
        self.add(convo("Ours_Text_Var", "You must find {STR_VAR_1}.$"))
        self.assertEqual(self.findings("systems-voice"), [])

    # -- the profile and the exit code -----------------------------------

    def test_the_profile_reports_the_ratio_against_the_corpus(self):
        self.add(convo("Ours_Text_Cold", "You must be 15.$"))
        code, out = self.run_tool()
        self.assertIn("VOICE PROFILE", out)
        self.assertIn("quotes a number", out)
        self.assertIn("1 conversation(s)", out)
        self.assertEqual(code, 0)          # WARNs alone do not fail the run

    def test_strict_makes_warnings_fail_and_a_fail_always_does(self):
        self.add(convo("Ours_Text_Cold", "You must be level 15.$"))
        self.assertEqual(self.run_tool(("--strict",))[0], 1)
        self.add(convo("Ours_Text_Wide", "a" * 16 + "$"))
        self.assertEqual(self.run_tool()[0], 1)

    def test_a_clean_hack_says_so_and_exits_zero(self):
        code, out = self.run_tool()
        self.assertEqual(code, 0)
        self.assertIn("nothing of ours to check", out)


if __name__ == "__main__":
    unittest.main()
