#!/usr/bin/env python3
"""Unit tests for the rom/sym pairing proof -- no docker, no engine, no ROM.

WHY THIS FILE EXISTS
--------------------
rom_pair.py is the thing that decides whether a verdict is allowed to mean
anything at all. If it is wrong in the permissive direction, the harness goes
back to the doc 57 §5 bug: a hack verified against a different build's symbol
table, reporting PASS. If it is wrong in the strict direction, every legitimate
run is blocked.

The end-to-end proof (docs 57 §8) exercises it against two real 32 MB builds,
which is the right way to prove it works but a terrible way to prove it FAILS
where it should -- you cannot cheaply manufacture a truncated .sym or a stripped
ELF out of a real build. So every failure mode is manufactured here, from
synthetic ELFs small enough to read.

Same discipline as test_verify_hack.py: every check gets a negative test. A
suite that only asserts the passing direction is a spec with no counterfactual.

    python3 -m unittest discover -s tests -v
"""

import pathlib
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import rom_pair  # noqa: E402
import verify_hack as vh  # noqa: E402

STT_NOTYPE, STT_OBJECT, STT_FUNC, STT_SECTION = 0, 1, 2, 3
ROM_BASE = rom_pair.GBA_ROM_BASE


# ---------------------------------------------------------------------------
# a synthetic ELF32-LE ARM executable, small enough to reason about
# ---------------------------------------------------------------------------

def make_elf(image, symbols, machine=40, elfclass=1, magic=b"\x7fELF",
             with_symtab=True):
    """Build a minimal but real ELF: one PT_LOAD, .text, .symtab, .strtab.

    `symbols` is [(name, addr, size, type)]. A name of "" means a section
    symbol for .text (st_name == 0), which is how objdump ends up printing
    section names -- the case that makes 21 lines of a real .sym look
    inexplicable if it is not handled.
    """
    image_off = 0x100
    body = bytearray(b"\0" * image_off)
    body += image

    shstr_off = len(body)
    shnames, shstr = {}, bytearray(b"\0")
    for nm in ("", ".text", ".symtab", ".strtab", ".shstrtab"):
        shnames[nm] = len(shstr) if nm else 0
        if nm:
            shstr += nm.encode() + b"\0"
    body += shstr

    str_off = len(body)
    strtab, stroffs = bytearray(b"\0"), {}
    for nm, _a, _s, _t in symbols:
        if nm:
            stroffs[nm] = len(strtab)
            strtab += nm.encode() + b"\0"
    body += strtab

    sym_off = len(body)
    syms = bytearray(struct.pack("<IIIBBH", 0, 0, 0, 0, 0, 0))   # index 0
    for nm, addr, size, typ in symbols:
        syms += struct.pack("<IIIBBH", stroffs.get(nm, 0), addr, size,
                            typ, 0, 1)
    body += syms

    sh_off = len(body)
    n_sections = 5 if with_symtab else 4

    def shdr(name, typ, flags, addr, off, size, link=0, info=0, align=1,
             entsize=0):
        return struct.pack("<IIIIIIIIII", shnames[name], typ, flags, addr, off,
                           size, link, info, align, entsize)

    sh = shdr("", 0, 0, 0, 0, 0)
    sh += shdr(".text", 1, 0x6, ROM_BASE, image_off, len(image))
    if with_symtab:
        sh += shdr(".symtab", 2, 0, 0, sym_off, len(syms), link=3, entsize=16)
        sh += shdr(".strtab", 3, 0, 0, str_off, len(strtab))
        sh += shdr(".shstrtab", 3, 0, 0, shstr_off, len(shstr))
    else:
        sh += shdr(".strtab", 3, 0, 0, str_off, len(strtab))
        sh += shdr(".shstrtab", 3, 0, 0, shstr_off, len(shstr))
    body += sh

    phdr = struct.pack("<IIIIIIII", 1, image_off, ROM_BASE, ROM_BASE,
                       len(image), len(image), 5, 4)
    ehdr = (magic + bytes([elfclass, 1, 1, 0, 0]) + b"\0" * 7
            + struct.pack("<HHIIIIIHHHHHH", 2, machine, 1, ROM_BASE,
                          52, sh_off, 0, 52, 32, 1, 40, n_sections,
                          n_sections - 1))
    out = bytearray(ehdr + phdr)
    out += b"\0" * (image_off - len(out))
    out += body[image_off:]
    return bytes(out)


def sym_text(entries):
    """Render (addr, size, name) triples in pokeemerald.sym's line format."""
    return "".join(f"{a:08x} g {s:08x} {n}\n" for a, s, n in entries)


SYMBOLS = [
    ("gAlpha", 0x02000000, 0x10, STT_OBJECT),
    ("DoThing", ROM_BASE + 0x21, 0x20, STT_FUNC),     # Thumb: low bit SET
    ("sTable", ROM_BASE + 0x40, 0x06, STT_OBJECT),
    ("", ROM_BASE, 0, STT_SECTION),                   # -> ".text"
]
SYM_LINES = [(0x02000000, 0x10, "gAlpha"),
             (ROM_BASE + 0x20, 0x20, "DoThing"),      # objdump masks the bit
             (ROM_BASE + 0x40, 0x06, "sTable"),
             (ROM_BASE, 0, ".text")]

IMAGE = bytes(range(256)) * 4


class Fixture:
    """A matched (elf, rom, sym) triple on disk, plus knobs to break it."""

    def __init__(self, tmp, image=IMAGE, symbols=SYMBOLS, lines=None, **kw):
        self.dir = pathlib.Path(tmp)
        self.elf = self.dir / "pokeemerald.elf"
        self.rom = self.dir / "pokeemerald.gba"
        self.sym = self.dir / "pokeemerald.sym"
        self.elf.write_bytes(make_elf(image, symbols, **kw))
        self.rom.write_bytes(image + b"\xff" * 64)     # gbafix -p tail padding
        self.sym.write_text(sym_text(SYM_LINES if lines is None else lines))


class MatchedPairVerifies(unittest.TestCase):
    def test_clean_triple_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            lines = rom_pair.verify_pair(f.rom, f.sym)
            self.assertTrue(any("VERIFIED" in l for l in lines), lines)

    def test_thumb_low_bit_is_masked_like_objdump(self):
        """DoThing is 0x...21 in the ELF and 0x...20 in the .sym.

        Without the STT_FUNC mask every Thumb function in the engine -- which
        is nearly all of them -- would read as a mismatch and the check would
        refuse every legitimate pair.
        """
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            found = {(a, s) for n, a, s in
                     ((n, a, s) for n, a, s in rom_pair.Elf(f.elf).symbols())
                     if n == "DoThing"}
            self.assertEqual(found, {(ROM_BASE + 0x20, 0x20)})

    def test_section_symbol_takes_its_section_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            names = {n for n, _a, _s in rom_pair.Elf(f.elf).symbols()}
            self.assertIn(".text", names)

    def test_rom_may_be_longer_than_the_image(self):
        """gbafix -p pads to a power of two; that tail is not part of the ELF."""
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.rom.write_bytes(IMAGE + b"\xff" * 4096)
            rom_pair.verify_pair(f.rom, f.sym)      # must not raise


class MismatchedPairIsRejected(unittest.TestCase):
    """The whole point. Each of these used to be a silent wrong answer."""

    def test_one_flipped_image_byte_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            poked = bytearray(f.rom.read_bytes())
            poked[0x42] ^= 0xFF                     # inside the ELF image
            f.rom.write_bytes(bytes(poked))
            with self.assertRaises(rom_pair.PairError) as cm:
                rom_pair.verify_pair(f.rom, f.sym)
            self.assertIn("rom vs elf", str(cm.exception))
            self.assertIn("0x42", str(cm.exception))

    def test_a_moved_symbol_is_caught(self):
        """The doc 57 §5 hazard in miniature: same names, shifted addresses."""
        with tempfile.TemporaryDirectory() as tmp:
            shifted = [(a + 8 if a >= ROM_BASE + 0x40 else a, s, n)
                       for a, s, n in SYM_LINES]
            f = Fixture(tmp, lines=shifted)
            with self.assertRaises(rom_pair.PairError) as cm:
                rom_pair.verify_pair(f.rom, f.sym)
            self.assertIn("sym vs elf", str(cm.exception))
            self.assertIn("sTable", str(cm.exception))

    def test_a_changed_symbol_SIZE_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            resized = [(a, s + 2 if n == "sTable" else s, n)
                       for a, s, n in SYM_LINES]
            f = Fixture(tmp, lines=resized)
            with self.assertRaises(rom_pair.PairError):
                rom_pair.verify_pair(f.rom, f.sym)

    def test_a_truncated_sym_is_caught_by_the_reverse_direction(self):
        """Forward-only checking would accept this: every line it HAS is right."""
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, lines=SYM_LINES[:1])
            with self.assertRaises(rom_pair.PairError) as cm:
                rom_pair.verify_pair(f.rom, f.sym)
            self.assertIn("covers only", str(cm.exception))

    def test_a_rom_shorter_than_the_image_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.rom.write_bytes(IMAGE[:16])
            with self.assertRaises(rom_pair.PairError) as cm:
                rom_pair.verify_pair(f.rom, f.sym)
            self.assertIn("past the end", str(cm.exception))

    def test_the_error_names_the_sym_that_would_have_been_right(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, lines=SYM_LINES[:1])
            with self.assertRaises(rom_pair.PairError) as cm:
                rom_pair.verify_pair(f.rom, f.sym)
            msg = str(cm.exception)
            self.assertIn("make syms", msg)
            self.assertIn("could PASS by accident", msg)


class CannotProveIsNotProof(unittest.TestCase):
    """Absence of evidence must not be reported as evidence."""

    def test_missing_elf_refuses_rather_than_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.elf.unlink()
            with self.assertRaises(rom_pair.PairError) as cm:
                rom_pair.verify_pair(f.rom, f.sym)
            self.assertIn("--allow-unmatched-sym", str(cm.exception))

    def test_stripped_elf_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, with_symtab=False)
            with self.assertRaises(rom_pair.PairError) as cm:
                rom_pair.verify_pair(f.rom, f.sym)
            self.assertIn("symtab", str(cm.exception))

    def test_non_elf_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, magic=b"NOPE")
            with self.assertRaises(rom_pair.PairError):
                rom_pair.verify_pair(f.rom, f.sym)

    def test_wrong_machine_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, machine=62)            # x86-64
            with self.assertRaises(rom_pair.PairError) as cm:
                rom_pair.verify_pair(f.rom, f.sym)
            self.assertIn("ARM", str(cm.exception))

    def test_elf64_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp, elfclass=2)
            with self.assertRaises(rom_pair.PairError):
                rom_pair.verify_pair(f.rom, f.sym)

    def test_empty_sym_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            f.sym.write_text("not a symbol table at all\n")
            with self.assertRaises(rom_pair.PairError) as cm:
                rom_pair.verify_pair(f.rom, f.sym)
            self.assertIn("no parseable symbol lines", str(cm.exception))

    def test_describe_unverified_says_so_in_those_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            text = "\n".join(rom_pair.describe_unverified(f.rom, f.sym))
            self.assertIn("NOT VERIFIED", text)
            self.assertIn("means nothing", text)


class SiblingLookup(unittest.TestCase):
    def test_prefers_the_roms_own_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "hackfork.sym").write_text("")
            (d / "pokeemerald.sym").write_text("")
            self.assertEqual(rom_pair.sibling(d / "hackfork.gba", "sym"),
                             d / "hackfork.sym")

    def test_falls_back_to_the_canonical_name(self):
        """doc 55 §9.2 runs `--rom modified.gba`, a poked copy of the engine
        ROM. There is no modified.sym; pokeemerald.sym is the pair, and the
        CONTENT check is what confirms it rather than the name."""
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "pokeemerald.sym").write_text("")
            self.assertEqual(rom_pair.sibling(d / "modified.gba", "sym"),
                             d / "pokeemerald.sym")

    def test_names_the_preferred_candidate_when_neither_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            self.assertEqual(rom_pair.sibling(d / "modified.gba", "sym"),
                             d / "modified.sym")


class ArtifactResolution(unittest.TestCase):
    """--sym must follow --rom. This is the defaulting half of doc 57 §5."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = pathlib.Path(self.tmp.name) / "engine"
        self.hack = pathlib.Path(self.tmp.name) / "hack"
        for d in (self.engine, self.hack):
            d.mkdir()
            (d / "pokeemerald.gba").write_bytes(b"")
            (d / "pokeemerald.sym").write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_flags_is_the_old_behaviour_exactly(self):
        rom, sym, src = vh.resolve_artifacts(None, None, engine=self.engine)
        self.assertEqual(rom, self.engine / "pokeemerald.gba")
        self.assertEqual(sym, self.engine / "pokeemerald.sym")
        self.assertEqual(src, "engine default")

    def test_rom_alone_takes_the_roms_OWN_sym(self):
        """THE BUG, as a test: this used to yield the ENGINE's .sym."""
        rom, sym, src = vh.resolve_artifacts(
            str(self.hack / "pokeemerald.gba"), None, engine=self.engine)
        self.assertEqual(sym, self.hack / "pokeemerald.sym")
        self.assertNotEqual(sym, self.engine / "pokeemerald.sym")
        self.assertEqual(src, "sibling of --rom")

    def test_explicit_absolute_sym_is_honoured(self):
        rom, sym, src = vh.resolve_artifacts(
            str(self.hack / "pokeemerald.gba"),
            str(self.engine / "pokeemerald.sym"), engine=self.engine)
        self.assertEqual(sym, self.engine / "pokeemerald.sym")
        self.assertEqual(src, "--sym")

    def test_relative_paths_still_resolve_under_the_engine(self):
        """Unchanged on purpose: every command line in docs 55 and 57 still
        means what it meant."""
        rom, sym, _ = vh.resolve_artifacts("pokeemerald.gba",
                                           "pokeemerald.sym",
                                           engine=self.engine)
        self.assertEqual(rom, self.engine / "pokeemerald.gba")
        self.assertEqual(sym, self.engine / "pokeemerald.sym")

    def test_relative_rom_in_a_subdirectory(self):
        sub = self.engine / "build"
        sub.mkdir()
        (sub / "modified.gba").write_bytes(b"")
        rom, sym, _ = vh.resolve_artifacts("build/modified.gba", None,
                                           engine=self.engine)
        self.assertEqual(rom, sub / "modified.gba")
        # No build/modified.sym and no build/pokeemerald.sym exist, so the
        # preferred candidate is named -- and will fail the existence check
        # with a message that says which file it wanted.
        self.assertEqual(sym, sub / "modified.sym")


def weak_line(addr, size, name):
    """objdump's rendering of a WEAK symbol -- a space where `g` would be."""
    return f"{addr:08x}  w    F .text\t{size:08x} {name}\n"


def hidden_line(addr, size, name):
    """objdump's rendering of a hidden symbol -- `.hidden ` before the name."""
    return f"{addr:08x} g     F lib_text\t{size:08x} .hidden {name}\n"


class SymLineGrammar(unittest.TestCase):
    """The two forms a pokeemerald.sym can contain (rom_pair.parse_sym_line).

    Every line here is copied verbatim from the pinned engine's own `.sym`.
    Until 2026-08-03 the raw forms were silently skipped, which is what made
    `RandomUniform` and `gTestRunnerEnabled` unnameable by any spec.
    """

    def test_rewritten_form(self):
        self.assertEqual(
            rom_pair.parse_sym_line("08000458 g 0000000c AgbMain"),
            (0x08000458, "g", 0x0c, "AgbMain"))

    def test_weak_function(self):
        self.assertEqual(
            rom_pair.parse_sym_line(
                "081c7a68  w    F .text\t0000001c RandomUniform"),
            (0x081c7a68, " ", 0x1c, "RandomUniform"))

    def test_weak_object(self):
        self.assertEqual(
            rom_pair.parse_sym_line(
                "08d39829  w    O .rodata\t00000001 gTestRunnerEnabled"),
            (0x08d39829, " ", 0x01, "gTestRunnerEnabled"))

    def test_hidden_name_loses_its_marker(self):
        # The name is `__udivsi3`, NOT `.hidden` -- the old trailing (\S+)$
        # captured the wrong word, which is the second, separate cause.
        self.assertEqual(
            rom_pair.parse_sym_line(
                "0834f8e0 g     F lib_text\t000000fc .hidden __udivsi3"),
            (0x0834f8e0, "g", 0xfc, "__udivsi3"))

    def test_weak_and_hidden_together(self):
        self.assertEqual(
            rom_pair.parse_sym_line(
                "0834fcf8  w    F lib_text\t00000002 .hidden __aeabi_idiv0"),
            (0x0834fcf8, " ", 0x02, "__aeabi_idiv0"))

    def test_non_symbol_lines_are_still_rejected(self):
        for junk in ("", "not a symbol line",
                     "0834f8e0 g     F lib_text",      # truncated: no size/name
                     "zzzzzzzz g 00000004 Nope",       # not an address
                     "0834f8e0 g     F lib_text 000000fc __udivsi3"):  # no tab
            self.assertIsNone(rom_pair.parse_sym_line(junk), junk)

    def test_a_raw_SECTION_symbol_parses_under_its_section_name(self):
        # Not in the pinned .sym (perl rewrites these), but the widened
        # grammar reaches it, and reading it is correct rather than junk.
        self.assertEqual(
            rom_pair.parse_sym_line("08000000 l    d  .text\t00000000 .text"),
            (0x08000000, "l", 0, ".text"))


class WidenedLinesAreCheckedNotJustAccepted(unittest.TestCase):
    """Accepting a line is only useful if the ELF check then judges it."""

    def _lines(self, render, size=0x06):
        # Same four symbols as SYM_LINES, but sTable in the raw form.
        return (sym_text([(0x02000000, 0x10, "gAlpha"),
                          (ROM_BASE + 0x20, 0x20, "DoThing"),
                          (ROM_BASE, 0, ".text")])
                + render(ROM_BASE + 0x40, size, "sTable"))

    def test_a_correct_raw_line_verifies(self):
        for render in (weak_line, hidden_line):
            with tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp)
                f.sym.write_text(self._lines(render))
                lines = rom_pair.verify_pair(f.rom, f.sym)
                self.assertTrue(any("VERIFIED" in l for l in lines),
                                (render.__name__, lines))

    def test_a_raw_line_with_the_WRONG_size_is_caught(self):
        # The counterfactual for the fix: if these lines were merely tolerated
        # and not compared, this would pass.
        for render in (weak_line, hidden_line):
            with tempfile.TemporaryDirectory() as tmp:
                f = Fixture(tmp)
                f.sym.write_text(self._lines(render, size=0x07))
                with self.assertRaises(rom_pair.PairError, msg=render.__name__):
                    rom_pair.verify_pair(f.rom, f.sym)


if __name__ == "__main__":
    unittest.main()
