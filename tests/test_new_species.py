#!/usr/bin/env python3
"""Unit tests for new_species.py's pure logic -- spec validation, anchored
insertion, donor-metadata parsing, and entry generation.

The heavyweight file-editing path is NOT re-proven here: it ran end-to-end on
the real fork on 2026-08-02 (all 17 edits, docker build, boot spec, and the
spec's exact stats read back out of the ROM at the gSpeciesInfo symbol, with
a neighbor-entry counterfactual). These tests pin the pieces that broke or
could break silently:

  * donor_metadata once truncated MON_COORDS_SIZE(48, 48) at its inner comma
    -- caught by the compiler, pinned here forever after.
  * insert_before must refuse ambiguous anchors (0 or 2 matches), because an
    edit that picks an arbitrary match is the silent-failure shape CLAUDE.md
    warns about.
  * every load_spec validation must actually reject.

    python3 -m unittest discover -s tests -v
"""

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import new_species as ns  # noqa: E402


GOOD_SPEC = {
    "name": "Testling",
    "stats": {"hp": 41, "attack": 43, "defense": 47,
              "speed": 53, "sp_attack": 59, "sp_defense": 61},
}

DONOR_BLOCK = """
    [SPECIES_DONOR] =
    {
        .baseHP        = 40,
        .frontPic = gMonFrontPic_Donor,
        .frontPicSize = MON_COORDS_SIZE(48, 48),
        .frontPicYOffset = 8,
        .frontAnimFrames = sAnims_Donor,
        .frontAnimId = ANIM_V_SQUISH_AND_BOUNCE,
        .backPic = gMonBackPic_Donor,
        .backPicSize = MON_COORDS_SIZE(56, 48),
        .backPicYOffset = 8,
        .backAnimId = BACK_ANIM_CONCAVE_ARC_LARGE,
        .pokemonScale = 541,
        .pokemonOffset = 19,
        .trainerScale = 256,
        .trainerOffset = 0,
        .iconPalIndex = 1,
    },
"""


def write_spec(tmp, extra=None):
    p = pathlib.Path(tmp) / "spec.json"
    p.write_text(json.dumps({**GOOD_SPEC, **(extra or {})}))
    return p


class SpecTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_minimal_spec_derives_names(self):
        spec = ns.load_spec(write_spec(self._tmp.name))
        self.assertEqual((spec["Name"], spec["ID"], spec["dir"]),
                         ("Testling", "TESTLING", "testling"))
        self.assertEqual(spec["types"], ["NORMAL"])  # default applied

    def test_rejections(self):
        cases = [
            {"name": "TooLongName11"},                      # >10 chars
            {"name": "Bad Name"},                           # non-alphanumeric
            {"stats": {"hp": 1}},                           # missing stat keys
            {"types": []},                                  # empty types
            {"abilities": ["A", "B", "C", "D"]},            # >3 abilities
            {"level_up_learnset": [[0, "POUND"]]},          # level 0
            {"level_up_learnset": [[5, "pound()"]]},        # non-constant move
        ]
        for extra in cases:
            with self.assertRaises(SystemExit, msg=extra):
                ns.load_spec(write_spec(self._tmp.name, extra))


class InsertTests(unittest.TestCase):
    def test_inserts_before_unique_anchor(self):
        out = ns.insert_before("a\nANCHOR\nb\n", r"^ANCHOR$", "new\n")
        self.assertEqual(out, "a\nnew\nANCHOR\nb\n")

    def test_refuses_missing_and_ambiguous_anchors(self):
        self.assertIsNone(ns.insert_before("a\nb\n", r"^ANCHOR$", "x\n"))
        self.assertIsNone(ns.insert_before("ANCHOR\nANCHOR\n", r"^ANCHOR$", "x\n"))


class DonorTests(unittest.TestCase):
    def test_metadata_survives_commas_inside_macros(self):
        # The bug the first real build caught: MON_COORDS_SIZE(48, 48) was
        # truncated to "MON_COORDS_SIZE(48" by a comma-terminated regex.
        with tempfile.TemporaryDirectory() as tmp:
            hack = pathlib.Path(tmp)
            fam = hack / "src/data/species_info"
            fam.mkdir(parents=True)
            (fam / "gen_1_families.h").write_text(DONOR_BLOCK)
            meta = ns.donor_metadata(hack, "DONOR")
        self.assertEqual(meta["frontPicSize"], "MON_COORDS_SIZE(48, 48)")
        self.assertEqual(meta["backPicSize"], "MON_COORDS_SIZE(56, 48)")
        self.assertEqual(meta["iconPalIndex"], "1")

    def test_missing_donor_dies(self):
        with tempfile.TemporaryDirectory() as tmp:
            hack = pathlib.Path(tmp)
            (hack / "src/data/species_info").mkdir(parents=True)
            with self.assertRaises(SystemExit):
                ns.donor_metadata(hack, "NOBODY")


class EntryTests(unittest.TestCase):
    META = {k: "0" for k in
            ["frontPicYOffset", "backPicYOffset", "pokemonScale", "pokemonOffset",
             "trainerScale", "trainerOffset", "iconPalIndex"]}
    META |= {"frontPicSize": "MON_COORDS_SIZE(48, 48)",
             "backPicSize": "MON_COORDS_SIZE(56, 48)",
             "frontAnimId": "ANIM_V_SQUISH_AND_BOUNCE",
             "backAnimId": "BACK_ANIM_NONE"}

    def spec(self, extra=None):
        with tempfile.TemporaryDirectory() as tmp:
            return ns.load_spec(write_spec(tmp, extra))

    def test_entry_carries_spec_and_donor_values(self):
        entry = ns.species_entry(self.spec(), self.META)
        for expected in ["[SPECIES_TESTLING]", ".baseHP        = 41",
                         "MON_TYPES(TYPE_NORMAL)", '.speciesName = _("Testling")',
                         ".cryId = CRY_TESTLING", ".natDexNum = NATIONAL_DEX_TESTLING",
                         ".frontPicSize = MON_COORDS_SIZE(48, 48)",
                         ".levelUpLearnset = sTestlingLevelUpLearnset",
                         "FOOTPRINT(Testling)"]:
            self.assertIn(expected, entry)
        self.assertNotIn(".evolutions", entry)  # none specified -> none emitted

    def test_evolution_and_multiline_description(self):
        spec = self.spec({"evolution": {"method": "EVO_LEVEL", "param": 16,
                                        "target": "SPECIES_TREECKO"},
                          "description": "One.\nTwo."})
        entry = ns.species_entry(spec, self.META)
        self.assertIn(".evolutions = EVOLUTION({EVO_LEVEL, 16, SPECIES_TREECKO})", entry)
        self.assertIn('"One.\\n"', entry)      # continuation lines get \n
        self.assertIn('"Two."', entry)          # the last line does not

    def test_description_budget_enforced(self):
        with self.assertRaises(SystemExit):
            ns.species_entry(self.spec({"description": "a\nb\nc\nd\ne"}), self.META)
        with self.assertRaises(SystemExit):
            ns.species_entry(self.spec({"description": "x" * 43}), self.META)


if __name__ == "__main__":
    unittest.main()
