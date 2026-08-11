#!/usr/bin/env python3
"""Rip readable dialogue/text strings out of a Gen 3 Pokémon ROM (any of them,
including closed-source hacks) without running it.

Every Gen 3 Pokémon game -- official or hacked -- stores text in the same custom
8-bit encoding pret's decomp projects call the "charmap". A hack that reskins
the game almost never touches this encoding, because doing so would require
hand-patching every font-rendering routine. So the charmap this repo already
has (from the pinned pokeemerald-expansion clone) reads a closed ROM's text
correctly in the overwhelming majority of cases -- this is a static-analysis
technique, not a guess: every control-code byte and its exact skip-length below
is transcribed from src/text.c's own width-calculating parser (see
GetStringWidth's EXT_CTRL_CODE_BEGIN switch), not reverse-engineered by trial.

What this can and cannot tell you (docs/records/87 explains the full method):
  - CAN: every line of dialogue, sign, and menu string in the ROM, verbatim.
  - CANNOT: which script triggers which string, or in what order -- that is
    bytecode, not text, and needs a different tool. Read the strings as a
    word-cloud of what the game says, not a transcript of what happens when.

Usage:
    python3 tools/dump_rom_text.py path/to/hack.gba > strings.txt
    python3 tools/dump_rom_text.py path/to/hack.gba --charmap other_charmap.txt
"""

import argparse
import pathlib
import re
import sys

DEFAULT_CHARMAP = (
    pathlib.Path.home() / ".poryrom" / "engines" / "expansion-1.9.4" / "charmap.txt"
)

EOS = 0xFF
CHAR_NEWLINE = 0xFE
CHAR_PROMPT_SCROLL = 0xFA
CHAR_PROMPT_CLEAR = 0xFB
CHAR_EXTRA_SYMBOL = 0xF9
EXT_CTRL_CODE_BEGIN = 0xFC
PLACEHOLDER_BEGIN = 0xFD
CHAR_DYNAMIC = 0xFC  # unused as a standalone case here; kept for reference

# Transcribed from src/text.c GetStringWidth(): how many param bytes follow
# each EXT_CTRL_CODE_BEGIN subcode, including the C switch's fallthroughs.
EXT_CTRL_PARAM_LEN = {
    0x01: 1,  # COLOR
    0x02: 1,  # HIGHLIGHT
    0x03: 1,  # SHADOW
    0x04: 2,  # COLOR_HIGHLIGHT_SHADOW (falls through 2 cases)
    0x05: 1,  # PALETTE
    0x06: 1,  # FONT
    0x07: 0,  # RESET_FONT
    0x08: 1,  # PAUSE
    0x09: 0,  # PAUSE_UNTIL_PRESS
    0x0A: 0,  # WAIT_SE
    0x0B: 2,  # PLAY_BGM (falls through 2 cases)
    0x0C: 1,  # ESCAPE
    0x0D: 1,  # SHIFT_RIGHT
    0x0E: 1,  # SHIFT_DOWN
    0x0F: 0,  # FILL_WINDOW
    0x10: 2,  # PLAY_SE (falls through 2 cases)
    0x11: 1,  # CLEAR
    0x12: 1,  # SKIP
    0x13: 1,  # CLEAR_TO
    0x14: 1,  # MIN_LETTER_SPACING
    0x15: 0,  # JPN
    0x16: 0,  # ENG
}

WORD_RE = re.compile(r"[A-Za-z]{4,}")

LINE_RE = re.compile(
    r"""^\s*(?:'((?:\\'|[^'])+)'|([A-Za-z0-9_]+))\s*=\s*([0-9A-Fa-f]{2})\s*(?:@.*)?$"""
)
PLACEHOLDER_RE = re.compile(
    r"""^\s*([A-Za-z0-9_]+)\s*=\s*FD\s+([0-9A-Fa-f]{2})\s*(?:@.*)?$"""
)


def load_charmap(path):
    """Single-byte glyph table plus a name for every FD-prefixed placeholder.

    Deliberately skips multi-byte glyph macros (e.g. PKMN = 53 54) -- those
    are two independently-mapped single bytes combined at the call site, not
    a new byte value, and including them here would double-map 0x53/0x54.
    """
    chars = {0x00: " "}
    placeholders = {}
    for line in path.read_text(errors="replace").splitlines():
        if line.strip().startswith("@") or not line.strip():
            continue
        m = PLACEHOLDER_RE.match(line)
        if m:
            name, byte = m.groups()
            val = int(byte, 16)
            if val not in placeholders:
                # FD-prefixed IDs are reused across contexts (overworld text
                # names PLAYER/RIVAL; battle-string text renames the same IDs
                # B_BUFF1/B_COPY_VAR_1/...). First definition in the file wins,
                # same rule as the glyph table below -- it is a display label,
                # not a claim about which context produced a given string.
                placeholders[val] = name
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        quoted, name, byte = m.groups()
        val = int(byte, 16)
        if val in (EOS, CHAR_NEWLINE, CHAR_PROMPT_SCROLL, CHAR_PROMPT_CLEAR,
                   CHAR_EXTRA_SYMBOL, EXT_CTRL_CODE_BEGIN, PLACEHOLDER_BEGIN):
            continue  # control bytes are handled structurally, not as glyphs
        if val in chars:
            continue  # first definition wins (Latin block precedes Katakana etc.)
        chars[val] = quoted if quoted is not None else f"{{{name}}}"
    return chars, placeholders


def decode_rom(data, chars, placeholders, min_letters=4, max_run=2000):
    """Yields (file_offset, decoded_text) for every plausible string.

    A run accumulates decoded glyphs until EOS terminates it (a real string)
    or an unmapped byte breaks it (almost certainly non-text data) or it hits
    max_run (a safety valve against pathological byte luck in binary data).
    """
    i = 0
    n = len(data)
    while i < n:
        start = i
        out = []
        letters = 0
        while i < n and (i - start) < max_run:
            b = data[i]
            if b == EOS:
                i += 1
                break
            if b == CHAR_NEWLINE or b == CHAR_PROMPT_SCROLL or b == CHAR_PROMPT_CLEAR:
                out.append("\n")
                i += 1
                continue
            if b == CHAR_EXTRA_SYMBOL:
                out.append("[SYM]")
                i += 1
                continue
            if b == PLACEHOLDER_BEGIN:
                if i + 1 >= n:
                    break
                pid = data[i + 1]
                out.append("{" + placeholders.get(pid, f"VAR_{pid:02X}") + "}")
                i += 2
                continue
            if b == EXT_CTRL_CODE_BEGIN:
                if i + 1 >= n:
                    break
                sub = data[i + 1]
                skip = EXT_CTRL_PARAM_LEN.get(sub, 0)
                i += 2 + skip
                continue
            if b in chars:
                ch = chars[b]
                out.append(ch)
                if len(ch) == 1 and ch.isalpha():
                    letters += 1
                i += 1
                continue
            # unmapped byte: not text. End the run WITHOUT consuming it, so
            # the outer loop re-scans from here for the next candidate run.
            break
        else:
            # hit max_run without EOS -- almost certainly not a real string.
            # `i` is already start+max_run (the inner loop only exits here by
            # exhausting its own condition); resuming from start+1 instead
            # would rescan the same dead stretch one byte at a time and turn
            # a single padding/graphics block into an O(n * max_run) scan.
            continue

        if i == start:
            i += 1  # made no progress (e.g. immediate unmapped byte); advance
            continue

        text = "".join(out).strip("\n")
        if letters < min_letters or not text:
            continue
        # Compressed graphics data sitting next to a string table often
        # decodes cleanly (no EOS, no unmapped byte) into charmap-valid noise,
        # which glues onto the real string that follows it as one run. Trim to
        # the first real word and require the trimmed text to be mostly
        # letters/space/punctuation -- cheap, and it is what a human skimming
        # the dump would do by eye anyway.
        # Skip matches inside a {TOKEN} label -- SUPER_RE, PLAYER, etc. are
        # all 4+ letter runs themselves and would otherwise satisfy WORD_RE
        # from a token that appears before any real prose.
        word = None
        for cand in WORD_RE.finditer(text):
            before = text[cand.start() - 1] if cand.start() > 0 else ""
            after = text[cand.end()] if cand.end() < len(text) else ""
            if before == "{" or after == "}":
                continue
            word = cand
            break
        if not word:
            continue
        text = text[word.start():]
        letter_count = sum(1 for c in text if c.isalpha())
        if letter_count / max(len(text), 1) < 0.5:
            continue
        yield start, text


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom", type=pathlib.Path)
    ap.add_argument("--charmap", type=pathlib.Path, default=DEFAULT_CHARMAP)
    ap.add_argument("--min-letters", type=int, default=4,
                     help="minimum alphabetic characters to keep a run (default 4)")
    args = ap.parse_args()

    if not args.charmap.exists():
        print(f"charmap not found: {args.charmap}", file=sys.stderr)
        sys.exit(1)
    chars, placeholders = load_charmap(args.charmap)

    data = args.rom.read_bytes()
    count = 0
    for offset, text in decode_rom(data, chars, placeholders, min_letters=args.min_letters):
        count += 1
        first_line = text.split("\n", 1)[0]
        print(f"0x{offset:06X}\t{first_line}")
        for extra in text.split("\n")[1:]:
            print(f"\t\t{extra}")
    print(f"# {count} strings extracted from {args.rom.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
