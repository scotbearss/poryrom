#!/usr/bin/env python3
"""Prove that a .gba and a .sym came from the SAME build.

WHY THIS EXISTS
---------------
`tools/verify_hack.py` resolves every probe address by name out of a
`pokeemerald.sym`. Until this module existed, `--rom` and `--sym` were
*unlinked*: `--rom <hack>/pokeemerald.gba` with no `--sym` silently resolved
every symbol out of `engine/pokeemerald.sym` -- a DIFFERENT build's
symbol table -- and reported PASS (doc 57 §5).

That was harmless only for as long as the two `.sym` files happened to be
byte-identical, which is true of a pure data-value edit and false of anything
that adds, removes or reorders code or data. The moment a symbol moves, every
probe reads the wrong address and the tool says nothing. The verdict is then
whatever unrelated memory happens to hold -- which can be a FAIL, but can just
as easily be a PASS, and a PASS obtained that way is a lie.

Existence of a sibling `.sym` is NOT proof of a pair: `make` alone rebuilds the
ROM and leaves a stale `.sym` sitting next to it (the `.sym` is a separate
`make syms` target, doc 54 §2). So this module does not check names or
directories. It checks CONTENT.

WHAT "MATCHED" MEANS HERE, AND WHY
----------------------------------
The build gives us a third artifact that both of the others are derived from,
and that is what makes a strong check possible at all. From the pinned
Makefile:

    $(ROM): $(ELF) ;  $(OBJCOPY) -O binary $< $@ ; $(FIX) $@ -p --silent
    $(SYM): $(ELF) ;  $(OBJDUMP) -t $< | sort -u | grep -E "^0[2389]" | ...

Both the ROM and the `.sym` are pure functions of `pokeemerald.elf`. So the
pair is verified by chaining through it:

  A. ELF -> ROM.  Every PT_LOAD segment's file bytes must appear verbatim in the
     ROM at `p_paddr - 0x08000000`. This is exactly what `objcopy -O binary`
     produces; `gbafix -p` only pads the tail. A byte-exact comparison of ~25 MB
     of image, not a hash of a name.

  B. ELF -> SYM.  Every line of the `.sym` must name a symbol that exists in the
     ELF's `.symtab` at that exact address with that exact size, AND the ELF's
     eligible symbols must nearly all appear in the `.sym` (so a truncated
     `.sym` is caught too, not just a wrong one).

A and B together mean: this `.sym` describes the layout of the code and data
that is actually inside this ROM. That is the property every probe address
depends on, stated directly, rather than inferred from a filename.

HONEST LIMITS
-------------
  * If the ELF is absent, this module CANNOT establish a pair. It says so and
    refuses; it does not fall back to a filename heuristic and call it proof.
    `verify_hack.py --allow-unmatched-sym` is the escape hatch, and it prints
    what is being given up.
  * Check B's reverse direction (ELF -> SYM coverage) is the one tolerant part:
    the `.sym` is produced by a `grep`+`perl` pipeline over `objdump` text, so
    reproducing its filter exactly would be re-implementing objdump's output
    format. Instead the reverse direction excludes ARM mapping symbols
    (`$a`/`$t`/`$d`, which that pipeline drops) and requires >= 99% coverage of
    what remains. It used to measure 98,782/98,862 = 99.92% because of the
    80-line shortfall described next; since that was fixed it is 100%. So the
    floor's 1% is slack: a `.sym` missing under 1% of its symbols would pass B.
    The forward direction admits no slack at all, and a spec naming a symbol
    that is absent is rejected downstream by resolve_probes() anyway.

  * FIXED 2026-08-03; kept because the shape recurs. Exactly 80 lines of the
    pinned engine's own `.sym` were unparseable by this mode's tooling: the
    Makefile's perl `s///` does not match objdump's rendering of WEAK symbols
    or `.hidden` names, so those lines survive in raw objdump form --

        081c7a68  w    F .text\t0000001c RandomUniform
        0834f8e0 g     F lib_text\t00000000 .hidden __aeabi_uidiv

    -- and every parser here skipped them, so `RandomUniform`,
    `gTestRunnerEnabled` and 78 others could not be named by a spec at all.
    `parse_sym_line()` below now accepts both forms. Two things learned:

      - The RNG entry points were reachable the whole time under a DIFFERENT
        NAME. `RandomUniform` is a weak alias sitting at the same address and
        size as the strong `RandomUniformDefault`, which always parsed. Only 4
        of the 80 have such a twin; the other 76 (libgcc arithmetic helpers)
        and `gTestRunnerEnabled` (weak, no twin) were genuinely unreachable.
        So "the RNG cannot be probed" was true of the NAME and false of the
        ADDRESS -- check for an alias before calling a symbol unreachable.
      - A grammar written down three times is a grammar that rots. Two copies
        were identical and the third had drifted; all three now call
        parse_sym_line().
  * Two builds that produce identical loadable bytes and identical symbols are
    treated as the same build. They are, for every purpose this harness has.
  * This says nothing about whether the ELF is the one you *meant* to build. It
    proves internal consistency of a triple, not intent.
"""

import pathlib
import re
import struct

GBA_ROM_BASE = 0x08000000

# ELF constants, spelled out so the parser reads as the spec does.
ELF_MAGIC = b"\x7fELF"
ELFCLASS32 = 1
ELFDATA2LSB = 1
EM_ARM = 40
PT_LOAD = 1
SHT_SYMTAB = 2
STT_FUNC = 2
STT_SECTION = 3

# The Makefile's `grep -E "^0[2389]"` keeps symbols whose 8-hex-digit address
# begins 02/03/08/09 -- EWRAM, IWRAM, ROM and the second ROM bank.
SYM_ELIGIBLE_BANKS = (0x02, 0x03, 0x08, 0x09)

# Reverse-coverage floor. See HONEST LIMITS.
COVERAGE_FLOOR = 0.99

# The two line forms a pokeemerald.sym can contain.
#
# 1. REWRITTEN -- what the Makefile's perl `s///` produces, and what every line
#    was assumed to be until 2026-08-03:
#
#        08000458 g 0000000c AgbMain
#
# 2. RAW -- objdump's own rendering, surviving untouched because the perl
#    pattern does not match it. Two disjoint causes, both real at our pin:
#    a WEAK symbol prints a space where a global prints `g`, and a hidden
#    symbol prints `.hidden ` in front of its name, so the trailing `(\S+)$`
#    sees two words:
#
#        081c7a68  w    F .text\t0000001c RandomUniform
#        0834f8e0 g     F lib_text\t00000000 .hidden __aeabi_uidiv
#
#    Accepting these is what makes `RandomUniform` (and `gTestRunnerEnabled`,
#    and the 78 libgcc arithmetic helpers) nameable by a spec at all.
SYM_LINE_RE = re.compile(r"^([0-9a-f]{8}) (\w) ([0-9a-f]{8}) (\S+)$")
SYM_RAW_RE = re.compile(
    r"^([0-9a-f]{8}) "          # address
    r"(.)"                      # binding: l/g/u/! or ' ' for weak
    r".{6}"                     # the rest of objdump's 7-char flag field
    r" \S+\t"                   # section name, then the tab objdump emits
    r"([0-9a-f]{8}) "           # size
    r"(?:\.hidden )?"           # visibility marker, when there is one
    r"(\S+)$"                   # name
)


def parse_sym_line(line):
    """One grammar for both `.sym` line forms -> (addr, flag, size, name).

    Returns None for anything else (blank lines, objdump's `$a`/`$t`/`$d`
    mapping symbols, or a form we have not seen). Deliberately the ONLY place
    this grammar is written down: it lived in three copies until 2026-08-03,
    two of which were the same regex pasted twice, and the third rotted.
    """
    m = SYM_LINE_RE.match(line) or SYM_RAW_RE.match(line)
    if not m:
        return None
    addr, flag, size, name = m.groups()
    return int(addr, 16), flag, int(size, 16), name


class PairError(Exception):
    """The ROM and the .sym are not, or cannot be shown to be, one build."""


class Elf:
    """The little of ELF32-LE we need: PT_LOAD segments and .symtab."""

    def __init__(self, path):
        self.path = path
        self.data = path.read_bytes()
        d = self.data
        if d[:4] != ELF_MAGIC:
            raise PairError(f"{path} is not an ELF file")
        if d[4] != ELFCLASS32 or d[5] != ELFDATA2LSB:
            raise PairError(f"{path} is not a little-endian 32-bit ELF")
        (_type, machine, _ver, _entry, phoff, shoff, _flags, _ehsize,
         phentsize, phnum, shentsize, shnum, shstrndx
         ) = struct.unpack_from("<HHIIIIIHHHHHH", d, 16)
        if machine != EM_ARM:
            raise PairError(f"{path}: e_machine is {machine}, expected ARM ({EM_ARM})")

        self.segments = []          # (paddr, file_offset, filesz)
        for i in range(phnum):
            (p_type, p_off, _p_vaddr, p_paddr, p_filesz, _p_memsz, _fl, _al
             ) = struct.unpack_from("<IIIIIIII", d, phoff + i * phentsize)
            if p_type == PT_LOAD and p_filesz:
                self.segments.append((p_paddr, p_off, p_filesz))
        if not self.segments:
            raise PairError(f"{path}: no loadable PT_LOAD segments with content")

        self.sections = [struct.unpack_from("<IIIIIIIIII", d,
                                            shoff + i * shentsize)
                         for i in range(shnum)]
        self._shstr_off = self.sections[shstrndx][4]

    # -- names -------------------------------------------------------------
    def _cstr(self, base, offset):
        end = self.data.index(b"\0", base + offset)
        return self.data[base + offset:end].decode("utf-8", "replace")

    def _section_name(self, index):
        return self._cstr(self._shstr_off, self.sections[index][0])

    # -- symbols -----------------------------------------------------------
    def symbols(self):
        """Yield (name, addr, size) the way `objdump -t` would print them.

        Two details matter and both were confirmed against the pinned build
        rather than assumed:
          * ARM Thumb function symbols carry the low bit SET in st_value
            (`AgbMain` is 0x08000459 in the ELF, 0x08000458 in the .sym).
            objdump masks it for STT_FUNC, so we do too -- otherwise every
            Thumb function in the engine looks like a mismatch.
          * Section symbols have st_name == 0; objdump prints the section's
            name instead (`.text`, `.ewram`, ...). Without this, 21 lines of a
            real .sym look unexplainable.
        """
        symtab = next((s for s in self.sections if s[1] == SHT_SYMTAB), None)
        if symtab is None:
            raise PairError(f"{self.path}: no .symtab (was it stripped?)")
        strtab = self.sections[symtab[6]]
        off, size, entsize = symtab[4], symtab[5], symtab[9]
        if not entsize:
            raise PairError(f"{self.path}: .symtab has zero entry size")
        str_off = strtab[4]
        d = self.data
        for i in range(size // entsize):
            (st_name, st_value, st_size, st_info, _other, st_shndx
             ) = struct.unpack_from("<IIIBBH", d, off + i * entsize)
            stype = st_info & 0xF
            if st_name:
                name = self._cstr(str_off, st_name)
            elif stype == STT_SECTION and st_shndx < len(self.sections):
                name = self._section_name(st_shndx)
            else:
                continue                      # unnamed, and not a section
            addr = (st_value & ~1) if stype == STT_FUNC else st_value
            yield name, addr, st_size


def parse_sym(sym_path):
    """Parse a pokeemerald.sym into a set of (addr, size, name).

    Same line grammar boot_proof.load_symbols() uses; kept separate because
    that one builds a lookup table and this one needs the raw triples.
    """
    out = set()
    lines = 0
    for line in sym_path.read_text(errors="replace").splitlines():
        parsed = parse_sym_line(line)
        if parsed is None:
            continue
        addr, _flag, size, name = parsed
        lines += 1
        out.add((addr, size, name))
    if not lines:
        raise PairError(f"{sym_path} contains no parseable symbol lines")
    return out


def sibling(rom, suffix, fallback_stem="pokeemerald"):
    """The build artifact that should sit next to `rom`.

    Tries `<rom stem>.<suffix>` first so a renamed build keeps its own
    artifacts, then the canonical `pokeemerald.<suffix>` so the documented
    `--rom modified.gba` case (doc 55 §9.2 -- a byte-poked copy of the engine
    ROM) still finds the pair it belongs to. Returns the first that exists, or
    the preferred name if neither does, so the error message names the thing
    the caller most likely meant.
    """
    preferred = rom.with_suffix(f".{suffix}")
    canonical = rom.parent / f"{fallback_stem}.{suffix}"
    for cand in (preferred, canonical):
        if cand.exists():
            return cand
    return preferred


def check_elf_matches_rom(elf, rom_bytes, rom_name):
    """A: every loadable ELF byte must appear verbatim in the ROM image."""
    base = min(paddr for paddr, _, _ in elf.segments)
    problems = []
    image_end = 0
    for paddr, off, filesz in elf.segments:
        start = paddr - base
        image_end = max(image_end, start + filesz)
        if start + filesz > len(rom_bytes):
            problems.append(
                f"segment at {paddr:#010x} (+{filesz} bytes) runs past the end "
                f"of {rom_name} ({len(rom_bytes)} bytes)")
            continue
        want = elf.data[off:off + filesz]
        got = rom_bytes[start:start + filesz]
        if got != want:
            first = next(i for i in range(len(want)) if want[i] != got[i])
            ndiff = sum(1 for a, b in zip(want, got) if a != b)
            problems.append(
                f"segment at {paddr:#010x}: {ndiff} byte(s) differ, first at "
                f"ROM offset {start + first:#x} "
                f"(elf {want[first]:#04x} vs rom {got[first]:#04x})")
    if base != GBA_ROM_BASE:
        problems.append(
            f"lowest loadable address is {base:#010x}, not {GBA_ROM_BASE:#010x}"
            f" -- this does not look like a GBA ROM image")
    return problems, image_end


def check_elf_matches_sym(elf, sym_triples):
    """B: the .sym must describe this ELF's symbol table, both directions."""
    by_name = {}
    eligible = set()
    for name, addr, size in elf.symbols():
        by_name.setdefault(name, set()).add((addr, size))
        # Mapping symbols ($a/$t/$d) are ARM ABI markers that the Makefile's
        # objdump|grep|perl pipeline drops. Excluding them makes the reverse
        # direction exact on the pinned engine (98,782 == 98,782).
        if (addr >> 24) in SYM_ELIGIBLE_BANKS and not name.startswith("$"):
            eligible.add((addr, size, name))

    problems = []

    # Forward: no slack. A single .sym line the ELF cannot account for means
    # this .sym is not this build's.
    unexplained = [t for t in sym_triples
                   if (t[0], t[1]) not in by_name.get(t[2], ())]
    if unexplained:
        shown = sorted(unexplained)[:5]
        detail = "; ".join(f"{a:08x} {s:08x} {n}" for a, s, n in shown)
        problems.append(
            f"{len(unexplained)} of {len(sym_triples)} .sym entries are not in "
            f"the ELF at that address/size (e.g. {detail})")

    # Reverse: catches a truncated or partial .sym, which the forward
    # direction would happily accept.
    covered = len(eligible & sym_triples)
    ratio = covered / len(eligible) if eligible else 0.0
    if ratio < COVERAGE_FLOOR:
        problems.append(
            f".sym covers only {covered}/{len(eligible)} ({ratio:.2%}) of the "
            f"ELF's eligible symbols -- looks truncated or from a partial build")
    return problems, covered, len(eligible)


def verify_pair(rom, sym, elf=None):
    """Prove rom and sym are one build. Raise PairError if they are not.

    Returns a list of human-readable evidence lines on success -- the caller
    prints them, because a check nobody can see the result of is a check nobody
    trusts.
    """
    elf = elf or sibling(rom, "elf")
    if not elf.exists():
        raise PairError(
            f"cannot verify that {rom} and {sym} are the same build: no ELF at "
            f"{elf}.\n"
            f"  The ROM and the .sym are both derived from pokeemerald.elf, and "
            f"that is the only thing that links them.\n"
            f"  Rebuild the tree (the ELF is a normal build product), or pass "
            f"--allow-unmatched-sym to run anyway and accept that every probe "
            f"address is unverified.")

    parsed = Elf(elf)
    rom_bytes = rom.read_bytes()
    rom_problems, image_end = check_elf_matches_rom(parsed, rom_bytes, rom.name)
    sym_problems, covered, eligible = check_elf_matches_sym(parsed,
                                                            parse_sym(sym))

    if rom_problems or sym_problems:
        lines = [f"ROM and .sym are NOT from the same build.",
                 f"    rom  {rom}",
                 f"    sym  {sym}",
                 f"    elf  {elf}"]
        for p in rom_problems:
            lines.append(f"  [rom vs elf] {p}")
        for p in sym_problems:
            lines.append(f"  [sym vs elf] {p}")
        lines.append(
            "  Every probe address in the spec comes from that .sym, so a "
            "verdict from this pair would be meaningless --")
        lines.append(
            "  it would read whatever unrelated memory the wrong addresses "
            "happen to land on, and could PASS by accident.")
        lines.append(
            f"  Fix: use the .sym built alongside this ROM "
            f"(--sym {sibling(rom, 'sym')}), or rebuild it with "
            f"`make syms CPP=\"arm-none-eabi-cpp -std=gnu17\"`.")
        raise PairError("\n".join(lines))

    return [
        f"rom/sym pair VERIFIED via {elf.name}",
        f"    elf -> rom  {image_end:,} bytes of loadable image byte-identical",
        f"    elf -> sym  {covered:,}/{eligible:,} symbols "
        f"({covered / eligible:.2%} coverage), 0 unexplained entries",
    ]


def describe_unverified(rom, sym):
    """What we can say when --allow-unmatched-sym skips the real check."""
    def stamp(p):
        try:
            return f"{p.stat().st_size:,} bytes, mtime {int(p.stat().st_mtime)}"
        except OSError:
            return "missing"
    return [
        "rom/sym pair NOT VERIFIED (--allow-unmatched-sym).",
        f"    rom  {rom}  ({stamp(rom)})",
        f"    sym  {sym}  ({stamp(sym)})",
        "    Same-directory and mtime ordering are heuristics, not evidence: "
        "`make` alone rebuilds the ROM and leaves a stale .sym beside it.",
        "    If the two are not one build, every probe reads the wrong address "
        "and this run's verdict -- PASS or FAIL -- means nothing.",
    ]


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        description="Check that a .gba and a .sym came from the same build.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("rom")
    ap.add_argument("sym", nargs="?")
    ap.add_argument("--elf", default=None)
    a = ap.parse_args()
    rom_p = pathlib.Path(a.rom)
    sym_p = pathlib.Path(a.sym) if a.sym else sibling(rom_p, "sym")
    try:
        for line in verify_pair(rom_p, sym_p,
                                pathlib.Path(a.elf) if a.elf else None):
            print(line)
    except PairError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
