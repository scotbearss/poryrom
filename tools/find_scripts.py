#!/usr/bin/env python3
"""Reconstruct script "scenes" around known dialogue in a Gen 3 Pokémon ROM.

Companion to dump_rom_text.py. That tool proves WHAT a ROM says; this tool is an attempt at
roughly WHEN -- by disassembling the game's own bytecode around anchor points already trusted:
a text-displaying instruction whose operand points exactly at a string dump_rom_text.py already
confirmed is real. docs/records/88 has the full method writeup, its validation against a script
read directly from Emerald's own source, and the honest confidence hedges -- read that before
trusting this tool's output on a closed hack. In short: much lower confidence than the text
dump. A misaligned decode produces a plausible-looking wrong answer, not an error.

Method:
  1. Parse asm/macros/event.inc from the pinned engine into an opcode table: byte value ->
     (mnemonic, fixed operand length in bytes). Read straight from the assembler macros that
     emit each command, not guessed. Commands this parser can't resolve to a fixed length
     (vararg macros, nested macro calls) are marked UNKNOWN and never guessed at.
  2. Re-run dump_rom_text.py's own string scan against the SAME rom to get a set of confirmed
     real string offsets.
  3. Scan the whole ROM for the two byte patterns that mean "show this text":
     loadword(0, ptr) + callstd(mode)  (what the `msgbox` macro compiles to), and message(ptr)
     directly -- where ptr resolves to one of the confirmed offsets from step 2.
  4. For each anchor, try disassembling forward from a window of candidate start points before
     it; keep the earliest candidate whose forward decode lands EXACTLY on the anchor with no
     unknown-opcode failure along the way. That is the scene's start.
  5. Disassemble forward from there until a terminating instruction (end/return) or an unknown
     opcode. Resolve every text-pointer operand against the string dump so the printed scene
     shows real dialogue next to the instruction that displays it.

Usage:
    python3 tools/find_scripts.py path/to/rom.gba > scenes.txt
    python3 tools/find_scripts.py path/to/rom.gba --limit 20
"""

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import dump_rom_text as dtext  # noqa: E402

DEFAULT_ENGINE = pathlib.Path.home() / ".poryrom" / "engines" / "expansion-1.9.4"
ROM_BASE = 0x08000000

TERMINAL_OPCODES = {0x02, 0x03, 0x0C, 0x0D}  # end, return, returnram, endram

OPCODE_DECL_RE = re.compile(r"^\s*\.byte\s+(0x[0-9a-fA-F]{2})\s*(?:@.*)?$")
OPERAND_RE = re.compile(r"^\s*\.(byte|2byte|4byte)\s+\\")
MACRO_RE = re.compile(r"^\s*\.macro\s+(\S+)")
DIRECTIVE_SIZES = {"byte": 1, "2byte": 2, "4byte": 4}


def parse_opcode_table(event_inc_path):
    """opcode byte -> (mnemonic, operand_len) ; operand_len is None if not staticaly resolvable."""
    table = {}
    pending_name = None
    cur_op = None
    cur_len = 0
    cur_name = None
    cur_unresolved = False

    def finalize():
        if cur_op is not None:
            table[cur_op] = (cur_name, None if cur_unresolved else cur_len)

    for raw in event_inc_path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("@"):
            continue
        m = MACRO_RE.match(raw)
        if m:
            finalize()
            cur_op, cur_len, cur_unresolved = None, 0, False
            pending_name = m.group(1)
            continue
        if line == ".endm":
            finalize()
            cur_op, cur_len, cur_unresolved = None, 0, False
            continue
        m = OPCODE_DECL_RE.match(raw)
        if m:
            finalize()  # new opcode: e.g. an .if/.else branch of the same macro
            cur_op = int(m.group(1), 16)
            cur_len = 0
            cur_name = pending_name
            cur_unresolved = False
            continue
        if cur_op is None:
            continue  # not currently inside a recognized opcode body
        m = OPERAND_RE.match(raw)
        if m:
            cur_len += DIRECTIVE_SIZES[m.group(1)]
            continue
        if line in (".if", ".else", ".endif") or line.startswith(".if ") or line.startswith(".ifb") or line.startswith(".ifnb"):
            continue  # branch structure only; branches emit their own .byte 0xHH we catch above
        # Anything else inside an opcode body (vararg expansion, nested macro call, .string,
        # a literal non-backslash operand) is exactly the kind of encoding this parser does not
        # attempt to model -- mark unresolved rather than silently mis-sizing it.
        cur_unresolved = True
    finalize()
    return table


def load_string_offsets(rom_path, charmap_path, min_letters=4):
    data = rom_path.read_bytes()
    chars, placeholders = dtext.load_charmap(charmap_path)
    offsets = {}
    for offset, text in dtext.decode_rom(data, chars, placeholders, min_letters=min_letters):
        offsets[offset] = text
    return data, offsets


def find_text_anchors(data, string_offsets):
    """Yields (anchor_start_offset, instruction_len, resolved_text) for loadword+callstd and
    message patterns whose text pointer lands on a confirmed real string."""
    n = len(data)
    for i in range(n - 10):
        # loadword(0, ptr) [op 0x0f, destIndex 0x00, 4-byte ptr] + callstd(mode) [op 0x09, 1 byte]
        if data[i] == 0x0F and data[i + 1] == 0x00:
            ptr = int.from_bytes(data[i + 2:i + 6], "little")
            off = ptr - ROM_BASE
            if off in string_offsets and data[i + 6] == 0x09:
                yield i, 8, string_offsets[off]
                continue
        # message(ptr) [op 0x67, 4-byte ptr]
        if data[i] == 0x67:
            ptr = int.from_bytes(data[i + 1:i + 5], "little")
            off = ptr - ROM_BASE
            if off in string_offsets:
                yield i, 5, string_offsets[off]


def disasm_run(data, start, opcode_table, max_instr, stop_at=None):
    """Decode forward from `start`. Returns (instructions, ok) where ok is False if it hit an
    unknown opcode, ran off the buffer, or (when stop_at is given) never landed exactly on it."""
    instrs = []
    i = start
    n = len(data)
    for _ in range(max_instr):
        if i >= n:
            return instrs, False
        if stop_at is not None and i == stop_at:
            return instrs, True
        op = data[i]
        entry = opcode_table.get(op)
        if entry is None or entry[1] is None:
            return instrs, False
        mnemonic, oplen = entry
        if i + 1 + oplen > n:
            return instrs, False
        operand = data[i + 1:i + 1 + oplen]
        instrs.append((i, op, mnemonic, operand))
        i += 1 + oplen
        if op in TERMINAL_OPCODES:
            if stop_at is None:
                return instrs, True
            # In stop_at (backward-search) mode, hitting a terminator before reaching the
            # target is ALWAYS a failure for this candidate, even if it lands exactly on
            # stop_at: a terminator ends a script, so whatever ran from `cand` to here was a
            # complete, different, unrelated script -- not a lead-in to the anchor's own
            # scene, just something that happens to sit immediately before it in ROM.
            return instrs, False
    return instrs, stop_at is None  # exhausted max_instr


def find_scene_start(data, anchor, opcode_table, max_lookback=300, max_instr=80):
    """Try candidate start points before `anchor`, NEAREST first, and keep the first one whose
    forward decode lands exactly on `anchor` with no unknown-opcode failure along the way.

    Nearest-first matters: because real scripts sit back-to-back with no gaps, an EARLIER
    candidate that happens to be some other, unrelated script's own valid start will *also*
    decode cleanly through its own terminator and land exactly on the next script's start --
    which might be a different script than the anchor's, several scripts further back, not
    "more context" on the anchor's own scene. Searching nearest-first finds the scene that
    actually owns the anchor instruction, not the nearest thing that merely also validates.
    """
    lo = max(0, anchor - max_lookback)
    for cand in range(anchor - 1, lo - 1, -1):
        instrs, ok = disasm_run(data, cand, opcode_table, max_instr=max_instr, stop_at=anchor)
        if ok and instrs:
            return cand
    return anchor


def format_operand(mnemonic, operand, string_offsets):
    if len(operand) == 4:
        ptr = int.from_bytes(operand, "little")
        off = ptr - ROM_BASE
        if off in string_offsets:
            preview = string_offsets[off].split("\n", 1)[0][:60]
            return f"ptr=0x{off:06X} TEXT[{preview!r}]"
        return f"0x{ptr:08X}"
    if operand:
        return " ".join(f"{b:02X}" for b in operand)
    return ""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom", type=pathlib.Path)
    ap.add_argument("--engine", type=pathlib.Path, default=DEFAULT_ENGINE)
    ap.add_argument("--limit", type=int, default=0, help="cap number of scenes printed (0 = all)")
    ap.add_argument("--min-letters", type=int, default=4)
    args = ap.parse_args()

    event_inc = args.engine / "asm" / "macros" / "event.inc"
    charmap = args.engine / "charmap.txt"
    if not event_inc.exists() or not charmap.exists():
        print(f"missing engine files under {args.engine}", file=sys.stderr)
        sys.exit(1)

    opcode_table = parse_opcode_table(event_inc)
    resolved = sum(1 for _, l in opcode_table.values() if l is not None)
    print(f"# opcode table: {len(opcode_table)} commands parsed, {resolved} with a resolved "
          f"fixed length", file=sys.stderr)

    data, string_offsets = load_string_offsets(args.rom, charmap, min_letters=args.min_letters)
    print(f"# {len(string_offsets)} confirmed string offsets to anchor against", file=sys.stderr)

    anchors = list(find_text_anchors(data, string_offsets))
    print(f"# {len(anchors)} text-display anchors found", file=sys.stderr)

    shown = 0
    for anchor, ilen, text in anchors:
        if args.limit and shown >= args.limit:
            break
        start = find_scene_start(data, anchor, opcode_table)
        instrs, ok = disasm_run(data, start, opcode_table, max_instr=80)
        print(f"=== scene @ 0x{start:06X} (anchor 0x{anchor:06X}, backward-search "
              f"{'OK' if start != anchor else 'none found'}) ===")
        for off, op, mnemonic, operand in instrs:
            operand_str = format_operand(mnemonic, operand, string_offsets)
            print(f"  0x{off:06X}  {mnemonic or '?':<20} {operand_str}")
        if not ok:
            print("  ...decode stopped: unknown opcode or ran off buffer")
        print()
        shown += 1


if __name__ == "__main__":
    main()
