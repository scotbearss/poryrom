#!/usr/bin/env python3
"""Make the battle-script RAM offsets a COMPILER-CHECKED claim instead of a hand-kept one.

THE HAZARD (docs/39 §1.5, docs/78 §5)
-----------------------------------------------------
Battle scripts read and write engine RAM through absolute addresses computed from
`struct BattleScripting`'s field offsets, written by hand in a header:

    #define sB_ANIM_TURN  (gBattleScripting + 0x18)   // animTurn

Those macros are used ONLY from `.s` files -- they are not valid C, since you cannot add
an integer to a struct -- so the compiler never sees them and never checks them. Insert one
field into `struct BattleScripting` and every macro below it silently addresses the wrong
byte. `grep` across `src/` and `test/` finds no STATIC_ASSERT or offsetof tying the two
together at this pin. The build does not complain. The scripts just read the wrong RAM.

Doc 39 called this "a first-order hazard for a hack author adding battle state and worth
encoding as a checklist item in any Pokémon-mode tooling." Doc 78 is that hack author:
LAST REP needs script-visible state. This project's standing rule is that a rule you can be
bitten by needs to be EXECUTABLE rather than remembered, so this is a tool and not a
paragraph.

WHAT IT DOES
------------
1. Rewrites the macro header into a two-line form that names the offset ONCE:

       #define sB_ANIM_TURN_OFS  0x18
       #define sB_ANIM_TURN      (gBattleScripting + sB_ANIM_TURN_OFS)   // animTurn

   The value the assembler computes is bit-for-bit what it was. This is the whole point of
   the restructure: it removes the second copy of the number, so the assertion below and the
   address the scripts use cannot disagree by construction.

2. Emits a generated header of STATIC_ASSERTs, one per macro:

       STATIC_ASSERT(sB_ANIM_TURN_OFS == offsetof(struct BattleScripting, animTurn), ...);

   Note who does which job. PYTHON does the mechanical transcription -- pairing 39 macros to
   39 field names -- because that is where a human miscounts and produces a confidently wrong
   assertion. THE COMPILER computes the offsets, because it is the only thing that knows this
   toolchain's alignment rules. (Slice 2 of `reps` was bitten by exactly that distinction:
   the fields were naturally aligned and the STRUCT still grew, because -mabi=apcs-gnu rounds
   struct size up to a multiple of 4. Right arithmetically, wrong about the machine.)

   The pairing itself is not invented here either -- it is read out of the trailing `// field`
   comments the header already carries, which are the existing single source of that mapping.

IDEMPOTENCE
-----------
Re-running on an already-converted header is a no-op that still verifies. Per this project's
rule, every check asserts the END STATE ("is this line now correct?") rather than a CHANGE
("did this line change?") -- the change-assertion version dies on input that is already right.

USAGE
    check_battle_offsets.py <fork>            # convert + emit + verify
    check_battle_offsets.py <fork> --check    # verify only, write nothing (exit 1 on drift)
"""

import argparse
import re
import sys
from pathlib import Path

MACRO_HEADER = Path("include/constants/battle_script_commands.h")
STRUCT_HEADER = Path("include/battle.h")
OUT_HEADER = Path("include/battle_script_offsets_check.h")

STRUCT_NAME = "BattleScripting"

# `#define sNAME (gBattleScripting + 0xNN) // fieldName`  -- the original, pre-conversion form.
RE_MACRO_ORIG = re.compile(
    r"^#define\s+(?P<macro>s[A-Z0-9_]+)\s+\(gBattleScripting\s*\+\s*"
    r"(?P<offset>0x[0-9A-Fa-f]+)\)\s*//\s*(?P<field>\w+)\s*$"
)
# `#define sNAME_OFS 0xNN` -- the converted form's first line.
RE_MACRO_OFS = re.compile(
    r"^#define\s+(?P<macro>s[A-Z0-9_]+)_OFS\s+(?P<offset>0x[0-9A-Fa-f]+)\s*//\s*(?P<field>\w+)\s*$"
)


class Fail(Exception):
    pass


def read(fork: Path, rel: Path) -> str:
    p = fork / rel
    if not p.is_file():
        raise Fail(f"missing {rel} under {fork} -- is this a pokeemerald fork?")
    return p.read_text(encoding="utf-8")


def parse_macros(text: str):
    """Return [(macro, offset_int, field, already_converted)] in file order.

    Accepts both the original and the converted form so the tool is idempotent.
    """
    out = []
    for line in text.splitlines():
        m = RE_MACRO_ORIG.match(line)
        if m:
            out.append((m["macro"], int(m["offset"], 16), m["field"], False))
            continue
        m = RE_MACRO_OFS.match(line)
        if m:
            out.append((m["macro"], int(m["offset"], 16), m["field"], True))
    return out


def parse_struct_fields(text: str, struct_name: str):
    """Return the ordered field names of `struct <struct_name>`.

    Only the NAMES are taken. Deliberately no offset arithmetic: computing offsets here would
    duplicate the compiler's job and get the toolchain's alignment rules wrong sooner or later.
    The compiler owns the numbers; this owns the spelling.
    """
    m = re.search(
        r"struct\s+" + re.escape(struct_name) + r"\s*\{(?P<body>.*?)\n\};",
        text,
        re.S,
    )
    if not m:
        raise Fail(f"could not find `struct {struct_name}` in {STRUCT_HEADER}")

    fields = []
    for raw in m["body"].splitlines():
        line = re.sub(r"//.*$", "", raw).strip()
        if not line or line.startswith("/*"):
            continue
        decl = line.rstrip(";").strip()
        if not decl.endswith(("]",)) and ";" not in raw:
            continue
        # `u8 multihitString[6]` -> multihitString ; `s32 painSplitHp` -> painSplitHp
        fm = re.match(r"^[A-Za-z_][\w\s\*]*?(?P<name>\w+)\s*(?:\[[^\]]*\])?$", decl)
        if fm:
            fields.append(fm["name"])
    if not fields:
        raise Fail(f"parsed `struct {struct_name}` but found no fields")
    return fields


def convert_header(text: str, macros) -> str:
    """Rewrite each macro line into the two-line _OFS form. Idempotent."""
    lines = text.splitlines(keepends=True)
    out = []
    width = max(len(mc) for mc, _, _, _ in macros) + 5
    for line in lines:
        m = RE_MACRO_ORIG.match(line.rstrip("\n"))
        if not m:
            out.append(line)
            continue
        macro, offset, field = m["macro"], m["offset"], m["field"]
        out.append(f"#define {macro + '_OFS':<{width}} {offset} // {field}\n")
        out.append(f"#define {macro:<{width}} (gBattleScripting + {macro}_OFS)\n")
    return "".join(out)


def emit_check_header(macros) -> str:
    body = [
        "// GENERATED by tools/check_battle_offsets.py -- do not edit by hand.",
        "//",
        "// Ties every battle-script RAM macro to the struct field it claims to address. The",
        "// macros are asm-only, so without this the compiler never sees them: inserting a field",
        "// into struct BattleScripting silently re-points every script below it, and the build",
        "// stays green. See docs/39 sec 1.5 and docs/78 sec 5.",
        "//",
        "// The offsets are NOT repeated here. Each assertion names the single _OFS constant the",
        "// scripts themselves assemble against, so this file cannot drift from the addresses in",
        "// use -- it can only agree with them or fail the build.",
        "",
        "#ifndef GUARD_BATTLE_SCRIPT_OFFSETS_CHECK_H",
        "#define GUARD_BATTLE_SCRIPT_OFFSETS_CHECK_H",
        "",
        '#include "battle.h"',
        '#include "constants/battle_script_commands.h"',
        "",
    ]
    for macro, _, field, _ in macros:
        body.append(
            f"STATIC_ASSERT({macro}_OFS == offsetof(struct {STRUCT_NAME}, {field}), "
            f"{macro}_moved);"
        )
    body += ["", "#endif // GUARD_BATTLE_SCRIPT_OFFSETS_CHECK_H", ""]
    return "\n".join(body)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fork", type=Path, help="path to the pokeemerald fork")
    ap.add_argument("--check", action="store_true", help="verify only; write nothing")
    args = ap.parse_args()

    fork = args.fork
    try:
        macro_text = read(fork, MACRO_HEADER)
        struct_text = read(fork, STRUCT_HEADER)

        macros = parse_macros(macro_text)
        if not macros:
            raise Fail(
                f"parsed {MACRO_HEADER} and found no gBattleScripting macros. "
                "An empty result from a pattern match is not a result -- check the file, not the count."
            )

        fields = parse_struct_fields(struct_text, STRUCT_NAME)
        known = set(fields)

        # Every macro must name a field that exists. This is the check that catches a rename,
        # and it runs before anything is written.
        unknown = [(mc, f) for mc, _, f, _ in macros if f not in known]
        if unknown:
            raise Fail(
                f"{len(unknown)} macro(s) name a field absent from struct {STRUCT_NAME}: "
                + ", ".join(f"{mc} -> {f}" for mc, f in unknown)
            )

        # Two macros addressing one field, or one field addressed twice, is a transcription
        # error in the header worth failing on -- it would silently halve the coverage.
        seen = {}
        for mc, _, f, _ in macros:
            seen.setdefault(f, []).append(mc)
        dupes = {f: ms for f, ms in seen.items() if len(ms) > 1}
        if dupes:
            raise Fail("field(s) addressed by more than one macro: " + repr(dupes))

        # A macro list that is monotonically increasing in offset is not required by anything,
        # but a DECREASE means the header's hand-kept order no longer tracks the struct, which
        # is the state this whole file exists to detect. Report it rather than assert it.
        offsets = [o for _, o, _, _ in macros]
        if offsets != sorted(offsets):
            print("WARN: macro offsets are not in ascending order in the header", file=sys.stderr)

        converted = convert_header(macro_text, macros)
        check_header = emit_check_header(macros)

        already = all(conv for _, _, _, conv in macros)
        if args.check:
            cur = (fork / OUT_HEADER).read_text(encoding="utf-8") if (fork / OUT_HEADER).is_file() else None
            drift = []
            if not already:
                drift.append(f"{MACRO_HEADER} still holds un-converted macros")
            if cur != check_header:
                drift.append(f"{OUT_HEADER} is missing or stale")
            if drift:
                for d in drift:
                    print(f"DRIFT: {d}", file=sys.stderr)
                return 1
            print(f"OK: {len(macros)} macros, {len(fields)} struct fields, guard present and current")
            return 0

        (fork / MACRO_HEADER).write_text(converted, encoding="utf-8")
        (fork / OUT_HEADER).write_text(check_header, encoding="utf-8")

        # END-STATE assertion, not a change assertion: re-read and re-parse what is now on disk
        # and require it to be right. The change-assertion version reports failure on a re-run.
        after = parse_macros((fork / MACRO_HEADER).read_text(encoding="utf-8"))
        if len(after) != len(macros):
            raise Fail(f"after writing, parsed {len(after)} macros, expected {len(macros)}")
        not_converted = [mc for mc, _, _, conv in after if not conv]
        if not_converted:
            raise Fail(f"after writing, {len(not_converted)} macro(s) still un-converted: {not_converted}")
        if [(mc, o, f) for mc, o, f, _ in after] != [(mc, o, f) for mc, o, f, _ in macros]:
            raise Fail("after writing, a macro's name/offset/field changed -- conversion was not value-preserving")

        print(f"{MACRO_HEADER}: {len(macros)} macros in _OFS form (values unchanged)")
        print(f"{OUT_HEADER}: {len(macros)} STATIC_ASSERTs emitted")
        print(f"struct {STRUCT_NAME}: {len(fields)} fields, {len(known - {f for _, _, f, _ in macros})} not script-visible")
        print("\nNow #include \"battle_script_offsets_check.h\" from one C file that builds.")
        return 0

    except Fail as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
