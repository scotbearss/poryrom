#!/usr/bin/env python3
"""Refuse two debug hooks that answer to the same button combination.

WHY THIS EXISTS (doc 78, 2026-08-06)
------------------------------------
`reps` drives its verification fixtures from held-button combinations in
`RepsSlice2DebugTick`. There are seventeen of them. Adding an eighteenth took a combo
`L+R+B+Up` that slice 5's below-threshold evolution arm already owned -- and because the new
block sits EARLIER in the function and every block ends in `return`, the old arm became
unreachable.

Nothing would have said so. The new specs all passed. `reps-evolve-below` would have gone on
running, starting a completely different fixture, and reporting on that instead -- a green or
red result about the wrong situation, which is this project's most-repeated failure shape and
the hardest kind to notice. There is no wrong NUMBER anywhere in it.

The check is trivial and the rule is not memorable enough to hold across sessions, so it is a
tool rather than a paragraph: the standing rule here is that a hazard you can be bitten by
needs to be EXECUTABLE.

WHAT IT CHECKS
    1. No two `held == (...)` blocks share a combination.
    2. A combination that is a strict SUPERSET of another hook. This one was learned the hard
       way: it is not a stylistic note, it is UNREACHABLE BY HAND. Human thumbs land in sequence,
       so L+R+B+Down passes through plain L+R+B, which fires and returns. Every spec still passes,
       because a scripted timeline presses the whole combo on one frame -- so this is a fault only
       a person can find, and only this check can predict.

USAGE
    check_debug_keys.py <fork>          # exit 1 on a duplicate
"""

import argparse
import re
import sys
from pathlib import Path

SOURCES = ["src/training.c"]
RE_HELD = re.compile(r"held\s*==\s*\(([^)]*)\)")
RE_BUTTON = re.compile(r"\b([A-Z_]+_BUTTON|DPAD_[A-Z]+)\b")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fork", type=Path)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on hand-unreachable combos too, not just duplicates")
    args = ap.parse_args()

    combos = {}   # frozenset -> [(file, line, raw)]
    total = 0
    for rel in SOURCES:
        p = args.fork / rel
        if not p.is_file():
            print(f"FAIL: missing {rel} under {args.fork}", file=sys.stderr)
            return 2
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            m = RE_HELD.search(line)
            if not m:
                continue
            buttons = frozenset(RE_BUTTON.findall(m.group(1)))
            if not buttons:
                continue
            total += 1
            combos.setdefault(buttons, []).append((rel, i, m.group(1).strip()))

    if not total:
        # An empty result from a pattern match is not a result.
        print(f"FAIL: parsed {SOURCES} and found no `held == (...)` blocks at all",
              file=sys.stderr)
        return 2

    dupes = {k: v for k, v in combos.items() if len(v) > 1}
    for buttons, sites in dupes.items():
        print(f"FAIL: {' | '.join(sorted(buttons))} is claimed {len(sites)} times:",
              file=sys.stderr)
        for rel, ln, raw in sites:
            print(f"         {rel}:{ln}", file=sys.stderr)
        print("       The FIRST one wins -- every later block is unreachable, silently.",
              file=sys.stderr)

    subsets = []
    keys = list(combos)
    for a in keys:
        for b in keys:
            if a is not b and a < b:
                subsets.append((a, b))
    # A SUBSET IS A REAL FAULT ON REAL HARDWARE, and both earlier versions of this file got that
    # wrong -- the first listed the pairs as trivia, the second demoted them to a counted "note".
    # A person playing found it in under a minute: holding L+R+B+Down means the game sees plain
    # L+R+B first, because human thumbs land in SEQUENCE. `held ==` is an exact compare, so the
    # subset hook fires and returns, and the superset is unreachable by hand.
    #
    # THE HARNESS STRUCTURALLY CANNOT SEE THIS. A scripted timeline presses every key of a combo
    # on the SAME FRAME, so no intermediate state ever exists and every spec passes. This is the
    # `wrong-looking screen` lesson in a new place: not something the probes got wrong, something
    # they are the wrong instrument for.
    if subsets:
        print(f"WARN: {len(subsets)} combo(s) are UNREACHABLE BY HAND -- each is a strict superset "
              f"of another hook, which fires first as the keys go down one at a time. Fine for "
              f"specs, broken for a player.", file=sys.stderr)
        for sup, blockers in sorted(
                ((b, [a for a, bb in subsets if bb == b]) for b in {b for _, b in subsets}),
                key=lambda kv: len(kv[1]), reverse=True):
            names = " + ".join(sorted(x.replace("_BUTTON", "").replace("DPAD_", "") for x in sup))
            print(f"      {names}", file=sys.stderr)
            for a in blockers:
                bn = " + ".join(sorted(x.replace("_BUTTON", "").replace("DPAD_", "") for x in a))
                print(f"          preempted by {bn}", file=sys.stderr)
        print("      WORKAROUND without a rebuild: press the keys in an order whose every "
              "intermediate state matches nothing -- for these hooks, B first, then the "
              "direction, then L and R last.", file=sys.stderr)

    if dupes:
        return 1
    if subsets and args.strict:
        return 1
    print(f"OK: {total} debug hooks, {len(combos)} distinct combinations, no collisions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
