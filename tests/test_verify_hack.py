#!/usr/bin/env python3
"""Unit tests for verify_hack.py's PURE evaluation logic -- no docker, no ROM.

Why this file exists: every check in verify_hack.py is only as trustworthy as
the code that evaluates it, and that code is the one part of the harness a
future agent building a hack could quietly weaken. The end-to-end specs prove
the checks that the specs happen to use; they prove nothing about the ones they
do not. When Slice 1's three build lanes landed, the following were implemented
but had NEVER ONCE EXECUTED:

    non_decreasing, in_range, sample_count, symbol_at with op in/not_in,
    symbol_sequence with op equals, the `at` selectors "first"/"any"/<frame>,
    and the entire signed (s8/s16/s32) sign-extension path.

Each of those has a test below, plus a negative test -- a case that must FAIL --
for every check. A test that only ever asserts the passing direction is the same
mistake as a spec with no counterfactual.

    python3 -m unittest discover -s tests -v
"""

import pathlib
import tempfile
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import verify_hack as vh  # noqa: E402


# A tiny symbol table in the .sym format's parsed shape: (addr, size, name).
SYMS = [
    (0x02000000, 0x100, "gAlpha"),
    (0x02000100, 0x100, "gBeta"),
    (0x08000000, 0x40, "FuncOne"),
    (0x08000040, 0x40, "FuncTwo"),
]

BY_NAME = {
    "gMain": (0x030036CC, 0x43C),
    "gPlayerParty": (0x02036108, 0x258),
    "gPlayerPartyCount": (0x02036105, 0x1),
    "gSaveBlock1Ptr": (0x03007224, 0x4),
}


def probe(pid="p", ptype="u32", **kw):
    """A resolved-probe dict shaped like resolve_probes() emits."""
    base = {"id": pid, "symbol": "gMain", "sym_addr": 0, "addr": 0,
            "offset": 0, "base_offset": 0, "deref": False, "type": ptype,
            "size": vh.TYPE_SIZES[ptype], "length": 0, "every": 0, "at": [],
            "why": ""}
    base.update(kw)
    return base


def samples_from(pid, values, ptype="u32", ptrs=None, syms=SYMS):
    """Build a log the way read_symbols.lua would, then parse it for real.

    Deliberately goes through parse_samples rather than hand-building sample
    dicts: the hex formatting and the sign-extension are part of what is under
    test, and hand-built dicts would skip exactly that.
    """
    p = probe(pid, ptype)
    width = (p["size"] * 2) if p["size"] else len(values[0])
    lines = []
    for i, v in enumerate(values):
        frame = (i + 1) * 30
        raw = v if isinstance(v, str) else format(v, f"0{width}x")
        if ptrs is None:
            lines.append(f"SYMPROBE frame={frame} id={pid} value={raw}")
        else:
            lines.append(f"SYMPROBE frame={frame} id={pid} "
                         f"ptr={ptrs[i]:08x} value={raw}")
    return p, vh.parse_samples("\n".join(lines), [p], syms)


def run(assertions, p, samples):
    res = vh.Result()
    vh.evaluate({"assert": assertions}, [p], samples, res)
    return res


class SignExtension(unittest.TestCase):
    """The signed path: implemented at Slice 1, never once executed."""

    def test_s8_negative(self):
        p, s = samples_from("p", ["ff", "80", "7f"], "s8")
        self.assertEqual([x["value"] for x in s["p"]], [-1, -128, 127])

    def test_s16_negative(self):
        p, s = samples_from("p", ["ffff", "8000", "7fff"], "s16")
        self.assertEqual([x["value"] for x in s["p"]], [-1, -32768, 32767])

    def test_s32_negative(self):
        p, s = samples_from("p", ["ffffffff", "80000000"], "s32")
        self.assertEqual([x["value"] for x in s["p"]], [-1, -2147483648])

    def test_u8_is_not_sign_extended(self):
        p, s = samples_from("p", ["ff"], "u8")
        self.assertEqual(s["p"][0]["value"], 255)

    def test_negative_compares_as_a_number_not_a_bit_pattern(self):
        # The bug this guards: -1 read as 0xffffffff would satisfy "> 0".
        p, s = samples_from("p", ["ffffffff"], "s32")
        res = run([{"probe": "p", "check": "compare", "at": "all",
                    "op": "<", "value": 0}], p, s)
        self.assertTrue(res.ok)
        res = run([{"probe": "p", "check": "compare", "at": "all",
                    "op": ">", "value": 0}], p, s)
        self.assertFalse(res.ok)


class NeverRunChecks(unittest.TestCase):
    """Checks that shipped without ever having been evaluated."""

    def test_non_decreasing_passes_on_a_plateau(self):
        p, s = samples_from("p", [1, 1, 2, 2, 3])
        self.assertTrue(run([{"probe": "p", "check": "non_decreasing"}],
                            p, s).ok)

    def test_non_decreasing_fails_on_a_dip(self):
        p, s = samples_from("p", [1, 2, 1])
        self.assertFalse(run([{"probe": "p", "check": "non_decreasing"}],
                             p, s).ok)

    def test_non_decreasing_is_weaker_than_strictly_increases(self):
        p, s = samples_from("p", [1, 1, 2])
        self.assertTrue(run([{"probe": "p", "check": "non_decreasing"}],
                            p, s).ok)
        self.assertFalse(run([{"probe": "p", "check": "strictly_increases"}],
                             p, s).ok)

    def test_in_range_inclusive_both_ends(self):
        p, s = samples_from("p", [15, 20, 25])
        self.assertTrue(run([{"probe": "p", "check": "in_range", "at": "all",
                              "min": 15, "max": 25}], p, s).ok)

    def test_in_range_fails_just_outside(self):
        p, s = samples_from("p", [26])
        self.assertFalse(run([{"probe": "p", "check": "in_range", "at": "all",
                               "min": 15, "max": 25}], p, s).ok)

    def test_sample_count(self):
        p, s = samples_from("p", [1, 2, 3])
        self.assertTrue(run([{"probe": "p", "check": "sample_count",
                              "value": 3}], p, s).ok)
        self.assertFalse(run([{"probe": "p", "check": "sample_count",
                               "value": 4}], p, s).ok)
        self.assertTrue(run([{"probe": "p", "check": "sample_count",
                              "op": ">=", "value": 2}], p, s).ok)

    def test_symbol_at_op_in(self):
        p, s = samples_from("p", [0x08000004])
        want = ["FuncOne", "FuncTwo"]
        self.assertTrue(run([{"probe": "p", "check": "symbol_at", "at": "all",
                              "op": "in", "value": want}], p, s).ok)
        self.assertFalse(run([{"probe": "p", "check": "symbol_at", "at": "all",
                               "op": "in", "value": ["gAlpha"]}], p, s).ok)

    def test_symbol_at_op_not_in(self):
        p, s = samples_from("p", [0x08000004])
        self.assertTrue(run([{"probe": "p", "check": "symbol_at", "at": "all",
                              "op": "not_in", "value": ["gAlpha"]}], p, s).ok)
        self.assertFalse(run([{"probe": "p", "check": "symbol_at", "at": "all",
                               "op": "not_in", "value": ["FuncOne"]}],
                             p, s).ok)

    def test_symbol_sequence_equals_is_exact(self):
        p, s = samples_from("p", [0x08000000, 0x08000040])
        exact = ["FuncOne", "FuncTwo"]
        self.assertTrue(run([{"probe": "p", "check": "symbol_sequence",
                              "op": "equals", "value": exact}], p, s).ok)
        # contains_in_order would accept a subsequence; equals must not.
        short = ["FuncOne"]
        self.assertTrue(run([{"probe": "p", "check": "symbol_sequence",
                              "op": "contains_in_order", "value": short}],
                            p, s).ok)
        self.assertFalse(run([{"probe": "p", "check": "symbol_sequence",
                               "op": "equals", "value": short}], p, s).ok)

    def test_symbol_sequence_contains_in_order_rejects_wrong_order(self):
        p, s = samples_from("p", [0x08000000, 0x08000040])
        self.assertFalse(run([{"probe": "p", "check": "symbol_sequence",
                               "op": "contains_in_order",
                               "value": ["FuncTwo", "FuncOne"]}], p, s).ok)

    # symbol_never -- slice 3's negative screen assertion ("the training
    # screen must NOT open on a declined challenge"). PASS iff none of the
    # named symbols was ever observed.

    def test_symbol_never_passes_when_absent(self):
        p, s = samples_from("p", [0x08000000, 0x08000000])
        self.assertTrue(run([{"probe": "p", "check": "symbol_never",
                              "value": ["FuncTwo"]}], p, s).ok)

    def test_symbol_never_fails_on_a_single_hit(self):
        p, s = samples_from("p", [0x08000000, 0x08000040, 0x08000000])
        self.assertFalse(run([{"probe": "p", "check": "symbol_never",
                               "value": ["FuncTwo"]}], p, s).ok)

    def test_symbol_never_fails_if_any_of_several_hits(self):
        p, s = samples_from("p", [0x08000040])
        self.assertFalse(run([{"probe": "p", "check": "symbol_never",
                               "value": ["gAlpha", "FuncTwo"]}], p, s).ok)

    def test_symbol_never_unresolved_samples_do_not_match(self):
        # An unresolved address can never equal a named symbol: the safe
        # direction for a NEGATIVE check is to keep passing.
        p, s = samples_from("p", [0x03FFFFF0])
        self.assertTrue(run([{"probe": "p", "check": "symbol_never",
                              "value": ["FuncOne", "FuncTwo"]}], p, s).ok)


class AtSelectors(unittest.TestCase):
    """"first", "any" and an explicit frame number: all previously unused."""

    def test_at_first(self):
        p, s = samples_from("p", [5, 99, 99])
        self.assertTrue(run([{"probe": "p", "check": "compare", "at": "first",
                              "op": "==", "value": 5}], p, s).ok)

    def test_at_last_is_the_default(self):
        p, s = samples_from("p", [5, 99, 7])
        self.assertTrue(run([{"probe": "p", "check": "compare",
                              "op": "==", "value": 7}], p, s).ok)

    def test_at_any_passes_if_one_sample_matches(self):
        p, s = samples_from("p", [1, 2, 3])
        self.assertTrue(run([{"probe": "p", "check": "compare", "at": "any",
                              "op": "==", "value": 2}], p, s).ok)

    def test_at_any_fails_if_none_match(self):
        p, s = samples_from("p", [1, 2, 3])
        self.assertFalse(run([{"probe": "p", "check": "compare", "at": "any",
                               "op": "==", "value": 9}], p, s).ok)

    def test_at_all_needs_every_sample(self):
        p, s = samples_from("p", [2, 2, 3])
        self.assertFalse(run([{"probe": "p", "check": "compare", "at": "all",
                               "op": "==", "value": 2}], p, s).ok)

    def test_at_explicit_frame(self):
        p, s = samples_from("p", [1, 2, 3])       # frames 30, 60, 90
        self.assertTrue(run([{"probe": "p", "check": "compare", "at": 60,
                              "op": "==", "value": 2}], p, s).ok)

    def test_at_a_frame_that_was_never_sampled_FAILS(self):
        # Must not pass vacuously: no sample is not the same as no violation.
        p, s = samples_from("p", [1, 2, 3])
        self.assertFalse(run([{"probe": "p", "check": "compare", "at": 45,
                               "op": "==", "value": 2}], p, s).ok)


class VacuousPassGuards(unittest.TestCase):
    """The failure mode that matters most: an assertion that cannot fail."""

    def test_no_samples_at_all_fails(self):
        p = probe("p")
        self.assertFalse(run([{"probe": "p", "check": "compare",
                               "op": "==", "value": 1}], p, {"p": []}).ok)

    def test_unreadable_sample_fails_compare(self):
        p, s = samples_from("p", ["invalid"], "u32")
        self.assertIsNone(s["p"][0]["value"])
        self.assertFalse(run([{"probe": "p", "check": "compare", "at": "all",
                               "op": "==", "value": 0}], p, s).ok)

    def test_always_valid_catches_an_invalid_deref(self):
        p, s = samples_from("p", ["invalid"], "u32", ptrs=[0])
        self.assertFalse(run([{"probe": "p", "check": "always_valid"}],
                             p, s).ok)

    def test_strictly_increases_rejects_a_single_sample(self):
        # One sample trivially satisfies "all pairs rise" -- it must not.
        p, s = samples_from("p", [1])
        self.assertFalse(run([{"probe": "p", "check": "strictly_increases"}],
                             p, s).ok)

    def test_spec_with_no_assertions_is_rejected(self):
        p = probe("p")
        with self.assertRaises(SystemExit) as cm:
            vh.validate_assertions({"assert": []}, [p])
        self.assertEqual(cm.exception.code, 2)


class OfSelector(unittest.TestCase):
    """`of` must mean the same thing on every probe (the mid-build fix)."""

    def test_of_defaults_to_value_even_on_a_deref_probe(self):
        p, s = samples_from("p", [0x08000004], ptrs=[0x02000000])
        # value resolves to FuncOne, ptr resolves to gAlpha. Default must be
        # the value; a per-probe default would silently flip this.
        self.assertTrue(run([{"probe": "p", "check": "symbol_at", "at": "all",
                              "op": "==", "value": "FuncOne"}], p, s).ok)

    def test_of_ptr_looks_at_the_pointer(self):
        p, s = samples_from("p", [0x08000004], ptrs=[0x02000000])
        self.assertTrue(run([{"probe": "p", "check": "symbol_at", "of": "ptr",
                              "at": "all", "op": "==", "value": "gAlpha"}],
                            p, s).ok)


class ResolverEdges(unittest.TestCase):
    def test_thumb_low_bit_is_cleared(self):
        self.assertEqual(vh.resolve(SYMS, 0x08000001), "FuncOne")

    def test_address_outside_every_symbol(self):
        self.assertIsNone(vh.resolve(SYMS, 0x0F000000))

    def test_zero_size_shadow_does_not_hide_the_real_symbol(self):
        # gSaveblock3 is a zero-size symbol sharing gSaveblock2's address at
        # this pin; the resolver must step past it and name the real one.
        syms = sorted(SYMS + [(0x02000000, 0, "gShadow")], key=lambda t: t[0])
        self.assertEqual(vh.resolve(syms, 0x02000010), "gAlpha")


class SpecStaticValidation(unittest.TestCase):
    """Malformed specs must die with exit 2 BEFORE a docker run is spent."""

    def timeline(self):
        return vh.resolve_timeline([{"name": "a", "frames": 100, "keys": []}],
                                   None)

    def bad(self, spec_probes):
        with self.assertRaises(SystemExit) as cm:
            vh.resolve_probes({"probes": spec_probes}, BY_NAME,
                              self.timeline(), 100, False)
        self.assertEqual(cm.exception.code, 2)

    def test_unknown_symbol(self):
        self.bad([{"id": "x", "symbol": "gNoSuchThing", "type": "u8"}])

    def test_offset_past_end_of_symbol(self):
        self.bad([{"id": "x", "symbol": "gPlayerPartyCount", "offset": 4,
                   "type": "u8"}])

    def test_unknown_type(self):
        self.bad([{"id": "x", "symbol": "gMain", "type": "u24"}])

    def test_duplicate_probe_id(self):
        self.bad([{"id": "x", "symbol": "gMain", "type": "u8"},
                  {"id": "x", "symbol": "gMain", "type": "u8"}])

    def test_base_offset_without_deref(self):
        self.bad([{"id": "x", "symbol": "gMain", "base_offset": 4,
                   "type": "u8"}])

    def test_base_offset_zero_without_deref_is_accepted(self):
        # Documented, not a bug: the guard is `if base_offset and not deref`,
        # so a base_offset of 0 falls through. It is a no-op at 0 -- the probe
        # reads the same address either way -- but the asymmetry is worth
        # pinning so nobody "fixes" it into a hard error and breaks a spec.
        got = vh.resolve_probes(
            {"probes": [{"id": "x", "symbol": "gMain", "base_offset": 0,
                         "type": "u8"}]}, BY_NAME, self.timeline(), 100, False)
        self.assertEqual(got[0]["addr"], BY_NAME["gMain"][0])

    def test_sample_frame_outside_the_run(self):
        self.bad([{"id": "x", "symbol": "gMain", "type": "u8",
                   "sample": {"at": [500]}}])

    def test_bytes_needs_a_length(self):
        self.bad([{"id": "x", "symbol": "gMain", "type": "bytes"}])

    def test_a_legal_probe_survives(self):
        got = vh.resolve_probes(
            {"probes": [{"id": "lvl", "symbol": "gPlayerParty", "offset": 84,
                         "type": "u8", "sample": {"every": 30}}]},
            BY_NAME, self.timeline(), 100, False)
        self.assertEqual(got[0]["addr"], 0x02036108 + 84)

    def test_counterfactual_shift_moves_the_address(self):
        got = vh.resolve_probes(
            {"probes": [{"id": "lvl", "symbol": "gPlayerParty", "offset": 84,
                         "type": "u8", "sample": {"every": 30}}]},
            BY_NAME, self.timeline(), 100, True)
        self.assertEqual(got[0]["addr"],
                         0x02036108 + 84 + vh.COUNTERFACTUAL_SHIFT)

    def test_unknown_key_in_timeline(self):
        with self.assertRaises(SystemExit) as cm:
            vh.resolve_timeline([{"name": "a", "frames": 10, "keys": ["X"]}],
                                None)
        self.assertEqual(cm.exception.code, 2)

    def test_empty_timeline(self):
        with self.assertRaises(SystemExit) as cm:
            vh.resolve_timeline([], None)
        self.assertEqual(cm.exception.code, 2)

    def test_assertion_referencing_a_missing_probe(self):
        p = probe("real")
        with self.assertRaises(SystemExit) as cm:
            vh.validate_assertions(
                {"assert": [{"probe": "ghost", "check": "constant"}]}, [p])
        self.assertEqual(cm.exception.code, 2)

    def test_unknown_check_name(self):
        p = probe("real")
        with self.assertRaises(SystemExit) as cm:
            vh.validate_assertions(
                {"assert": [{"probe": "real", "check": "vibes"}]}, [p])
        self.assertEqual(cm.exception.code, 2)


class MashTimelineSteps(unittest.TestCase):
    """The `mash` step type (doc 59 §9.5's fix for 1,700-line specs).

    Emerald reads JOY_NEW, so a held button registers once and every text beat
    needs a real press/release cycle. Spelling that out per step made three
    shipped specs ~1,700 lines each. Expansion now happens in the ONE shared
    evaluator, which is also why it needs its own tests: a spec can no longer
    see how its own mash is built.
    """

    def mash(self, **kw):
        step = {"name": "m", "mash": "A", "frames": 100}
        step.update(kw)
        return vh.resolve_timeline([step], None)

    def test_frame_total_is_exact(self):
        # The budget is the contract: a mash that overran would push samples
        # past the end of the run.
        for frames in (1, 5, 6, 7, 20, 99, 100, 2600):
            got = self.mash(frames=frames)
            self.assertEqual(sum(s["frames"] for s in got), frames, frames)
            self.assertEqual(got[-1]["end"], frames)

    def test_it_alternates_press_and_release(self):
        # 6+14+6+14 lands exactly on 40, so it ends on a release run.
        got = self.mash(frames=40, on=6, off=14)
        self.assertEqual([s["keys"] for s in got], [["A"], [], ["A"], []])
        self.assertEqual([s["frames"] for s in got], [6, 14, 6, 14])
        # One frame more starts a fifth, pressed, run.
        self.assertEqual([s["keys"] for s in self.mash(frames=41, on=6, off=14)],
                         [["A"], [], ["A"], [], ["A"]])

    def test_it_starts_pressed(self):
        # Matches make_savestate.py's op_mash, which these specs were ported
        # from -- if this flipped, every ported timeline would shift by `on`
        # frames and the EXP values in reps-cap-bites-* would move.
        self.assertEqual(self.mash(frames=100)[0]["keys"], ["A"])

    def test_last_run_is_truncated_not_overrun(self):
        got = self.mash(frames=10, on=6, off=14)
        self.assertEqual([s["frames"] for s in got], [6, 4])
        self.assertEqual(got[-1]["keys"], [])

    def test_substeps_are_contiguous_and_start_at_one(self):
        got = self.mash(frames=50)
        self.assertEqual(got[0]["start"], 1)
        for a, b in zip(got, got[1:]):
            self.assertEqual(b["start"], a["end"] + 1)

    def test_substeps_keep_the_parent_name_so_at_step_end_works(self):
        got = self.mash(frames=100)
        self.assertTrue(all(s["name"] == "m" for s in got))
        # start = first sub-step, end = LAST. This asymmetry is the whole
        # reason a mash is addressable by "at_step_end".
        self.assertEqual(vh.step_frame(got, "m", "start"), 1)
        self.assertEqual(vh.step_frame(got, "m", "end"), 100)

    def test_it_composes_with_ordinary_steps(self):
        got = vh.resolve_timeline(
            [{"name": "pre", "frames": 30, "keys": ["L"]},
             {"name": "m", "mash": "A", "frames": 40},
             {"name": "post", "frames": 10, "keys": []}], None)
        self.assertEqual(got[0]["keys"], ["L"])
        self.assertEqual(got[-1]["name"], "post")
        self.assertEqual(got[-1]["end"], 80)
        self.assertEqual(vh.step_frame(got, "m", "start"), 31)
        self.assertEqual(vh.step_frame(got, "m", "end"), 70)

    def test_display_collapses_a_mash_to_one_line(self):
        got = self.mash(frames=2600)
        self.assertGreater(len(got), 100)
        shown = vh.collapse_mash_for_display(got)
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0]["end"], 2600)

    # --- the failure modes ------------------------------------------------

    def test_unknown_mash_key_is_rejected(self):
        with self.assertRaises(SystemExit) as cm:
            self.mash(mash="X")
        self.assertEqual(cm.exception.code, 2)

    def test_mash_plus_keys_is_rejected(self):
        # Ambiguous: a mash drives exactly one key, so silently ignoring the
        # other would be a spec that does not do what it says.
        with self.assertRaises(SystemExit) as cm:
            self.mash(keys=["B"])
        self.assertEqual(cm.exception.code, 2)

    def test_zero_on_or_off_is_rejected(self):
        for kw in ({"on": 0}, {"off": 0}, {"on": -1}):
            with self.assertRaises(SystemExit) as cm:
                self.mash(**kw)
            self.assertEqual(cm.exception.code, 2, kw)

    def test_ordinary_steps_are_untouched_by_the_new_path(self):
        got = vh.resolve_timeline(
            [{"name": "a", "frames": 10, "keys": ["A"]}], None)
        self.assertEqual(len(got), 1)
        self.assertNotIn("mash", got[0])



class ScratchLockIsExclusive(unittest.TestCase):
    """The shared scratch directory must admit exactly one run.

    Doc 66 lost time to two concurrent runs producing a confident wrong answer
    (the second reads the first's probe data); it happened AGAIN on 2026-08-04,
    to somebody who had read that entry. A rule this project has been bitten by
    twice is a rule that has to be executable -- so this is the executable half.

    Everything here runs against a TEMPDIR, never engine/build, so the
    test suite itself can never take the real lock out from under a live run.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.build = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_second_holder_is_refused_not_queued(self):
        first = vh.ScratchLock(self.build)
        first.__enter__()
        self.addCleanup(first.__exit__)
        with self.assertRaises(SystemExit) as cm:
            vh.ScratchLock(self.build).__enter__()
        self.assertIn("Run specs serially", str(cm.exception))

    def test_the_lock_is_released_on_exit(self):
        first = vh.ScratchLock(self.build)
        first.__enter__()
        first.__exit__()
        second = vh.ScratchLock(self.build)
        second.__enter__()          # must not raise
        second.__exit__()

    def test_a_leftover_lock_FILE_does_not_block(self):
        # The file surviving a crash is not the lock; the flock is. A stale
        # file that blocked would turn one killed run into a wedged tool.
        (self.build / ".verify_lock").write_text("pid 99999\n")
        lock = vh.ScratchLock(self.build)
        lock.__enter__()
        lock.__exit__()

class ShippedSpecsAreWellFormed(unittest.TestCase):
    """Every spec in verify/ must parse and statically validate.

    Cheap, and it means a spec cannot rot unnoticed between ROM runs.
    """

    def test_all_specs(self):
        import json
        spec_dir = pathlib.Path(__file__).resolve().parents[1] / "verify"
        found = sorted(spec_dir.glob("*.json"))
        self.assertTrue(found, "no specs found")
        for path in found:
            with self.subTest(spec=path.name):
                spec = json.loads(path.read_text())
                tl = vh.resolve_timeline(spec["timeline"],
                                         __import__("random").Random(1))
                total = tl[-1]["end"]
                by_name = symbols_for(spec)   # may skipTest, see below
                try:
                    probes = vh.resolve_probes(spec, by_name, tl, total,
                                               False)
                    vh.validate_assertions(spec, probes)
                except SystemExit:
                    # verify_hack.fail() exits rather than raising, so a lint
                    # miss lands here as SystemExit. Against a REAL .sym that is
                    # a genuine failure and must propagate. Against the stub it
                    # only means the stub lacks a symbol -- and since the stub is
                    # used ONLY when engine/ is absent, that is a statement about
                    # a fresh clone, not about the spec. It used to surface as
                    # six hard errors in a tree that had simply not built the
                    # engine yet (doc 82 §2.4), which reads as breakage.
                    if _stub_in_use():
                        self.skipTest(
                            "engine/ is not built here, and the stub symbol "
                            "table does not carry every symbol this spec names")
                    raise
                self.assertTrue(spec.get("assert"))

    def test_symbols_from_names_a_real_fork_dir(self):
        """A `symbols_from` typo must not turn into a silent skip.

        The skip in symbols_for() is legitimate only for a fork that has not
        been BUILT. A fork that does not exist at all is a broken spec.
        """
        import json
        root = pathlib.Path(__file__).resolve().parents[1]
        known = json.loads((root / "fixtures.json").read_text())["forks"]
        for path in sorted((root / "verify").glob("*.json")):
            fork = json.loads(path.read_text()).get("symbols_from")
            if not fork or fork == "engine":
                continue
            with self.subTest(spec=path.name):
                # A TYPO and AN UNBUILT FIXTURE ARE DIFFERENT THINGS, and the
                # old all-or-nothing guard ("if hacks/ exists, every fork must")
                # could not tell them apart -- it failed 27 times on a fresh
                # clone that legitimately held only the game (doc 82 §5.4).
                # A name this repo has never heard of is still a typo and still
                # fails; a known fixture that simply has not been regenerated
                # here skips, and says how to bring it back.
                self.assertIn(fork, known,
                              f"{path.name}: symbols_from={fork!r} is not a "
                              f"fork this repo knows about -- typo, or add it "
                              f"to fixtures.json")
                if not (root / "hacks" / fork).is_dir():
                    raise unittest.SkipTest(
                        f"fork {fork!r} is not built here; regenerate with: "
                        f"{known[fork]['regenerate']}")

    def test_every_spec_declares_symbols_from(self):
        """No spec may leave the question unanswered.

        A spec with no `symbols_from` falls through to the engine ROM by
        accident rather than by declaration -- which on 2026-08-06 meant a batch
        run judged two specs against the wrong game and seven crashed this suite
        in a fresh clone (doc 82 F1, §2.4). The fix was to write the answer down
        in all 114; this keeps it written down.
        """
        import json
        root = pathlib.Path(__file__).resolve().parents[1]
        undeclared = [p.name for p in sorted((root / "verify").glob("*.json"))
                      if "symbols_from" not in json.loads(p.read_text())]
        self.assertEqual(undeclared, [],
                         "these specs do not say which ROM they need; use "
                         '"engine" for the pinned base or a fork name')


def symbols_for(spec):
    """The symbol table a shipped spec's probes must resolve against.

    Most specs probe symbols the PINNED ENGINE has, so the engine's .sym is
    right for them. A spec can instead probe symbols that exist ONLY IN A FORK
    -- verify/e1-{fixed,buggy}.json probe gE1Probe*, lab instrumentation
    that pokeemerald-expansion has never heard of. Such a spec declares

        "symbols_from": "<hack fork name under hacks/>"

    and this resolves it against THAT build's .sym. verify_hack.py ignores the
    key entirely; the .sym it actually uses comes from --rom/--sym and is
    adjudicated by rom_pair.py. This is a lint affordance, not a second source
    of truth for a real run.

    Forks are gitignored, so on a tree where the fork has not been built there
    is no table to resolve against. That case SKIPS -- loudly, with a reason --
    rather than passing quietly, because a lint that silently validates nothing
    is worse than no lint (docs/research/06).
    """
    fork = spec.get("symbols_from")
    if not fork or fork == "engine":
        # "engine" == the pinned base ROM, and is now WRITTEN OUT rather than
        # left absent (doc 82 F1). Every shipped spec declares one or the other,
        # so the missing-key branch below is legacy tolerance, not a state any
        # spec is allowed to be in -- test_every_spec_declares_symbols_from
        # enforces that.
        return BY_NAME_FULL()
    sym = (pathlib.Path(__file__).resolve().parents[1]
           / "hacks" / fork / "pokeemerald.sym")
    if not sym.exists():
        raise unittest.SkipTest(
            f"symbols_from={fork!r}: {sym} not built, so this spec's symbols "
            f"cannot be resolved here (build the fork to lint it)")
    return vh.load_symbols(sym)[1]


def _stub_in_use():
    """True when there is no built engine, so BY_NAME_FULL falls back to the stub."""
    return not (pathlib.Path(__file__).resolve().parents[1]
                / "engine" / "pokeemerald.sym").exists()


def BY_NAME_FULL():
    """Real symbol table if the engine is built; the stub otherwise.

    The stub keeps this test runnable with no engine tree present -- but it
    only carries the symbols the shipped specs actually name, so a spec that
    starts using a new symbol will fail here until the entry is added or a
    real .sym is available. That is the intended nudge, not an accident.
    """
    sym = (pathlib.Path(__file__).resolve().parents[1]
           / "engine" / "pokeemerald.sym")
    if sym.exists():
        return vh.load_symbols(sym)[1]
    return dict(BY_NAME, **{
        "gSaveBlock2Ptr": (0x03007228, 0x4),
        "gSaveblock1": (0x0200C95C, 0x3D50),
        "gSaveblock2": (0x0200B9B0, 0xFAC),
    })


if __name__ == "__main__":
    unittest.main()
