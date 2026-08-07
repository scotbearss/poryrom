#!/usr/bin/env python3
"""Unit tests for make_dex.py -- the static dex-site generator.

Only the PURE functions are tested here: the species-info parser fed a small
inline C fixture (two species covering single- and dual-type MON_TYPES, an
EVOLUTION, a config ternary, a COMPOUND_STRING description and a P_FAMILY
guard), the learnset parser, and the new/changed/same diff logic. The
end-to-end run against a real fork is a manual verification step, because a
real pokeemerald tree does not belong in this repo.

    python3 -m unittest discover -s tests -v
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import make_dex as md  # noqa: E402

# Format-faithful to species_info/*.h at the 1.9.4 pin: designated
# initializers, a P_FAMILY guard, macro noise between fields, and both
# MON_TYPES arities.
SNIPPET = r"""
#if P_FAMILY_ALPHAMON
    [SPECIES_ALPHAMON] = // new_species.py
    {
        .baseHP        = 45,
        .baseAttack    = 49,
        .baseDefense   = 50,
        .baseSpeed     = 45,
        .baseSpAttack  = 65,
        .baseSpDefense = 64,
        .types = MON_TYPES(TYPE_GRASS),
        .catchRate = 45,
        .expYield = (P_UPDATED_EXP_YIELDS >= GEN_5) ? 142 : 141,
        .genderRatio = PERCENT_FEMALE(12.5),
        .eggGroups = MON_EGG_GROUPS(EGG_GROUP_MONSTER, EGG_GROUP_GRASS),
        .abilities = { ABILITY_OVERGROW, ABILITY_NONE, ABILITY_CHLOROPHYLL },
        .speciesName = _("Alphamon"),
        .natDexNum = NATIONAL_DEX_ALPHAMON,
        .categoryName = _("Seed"),
        .height = 7,
        .weight = 69,
        .description = COMPOUND_STRING(
            "It naps in bright sunlight.\n"
            "There is a seed on its back."),
        .iconPalIndex = 4,
        FOOTPRINT(Alphamon)
        .levelUpLearnset = sAlphamonLevelUpLearnset,
        .teachableLearnset = sAlphamonTeachableLearnset,
        // a comment quoting EVO_LEVEL 99 must not pollute the parse
        .evolutions = EVOLUTION({EVO_LEVEL, 16, SPECIES_BETAMON}),
    },

    [SPECIES_BETAMON] =
    {
        .baseHP        = 60,
        .baseAttack    = 62,
        .baseDefense   = 63,
        .baseSpeed     = 60,
        .baseSpAttack  = 80,
        .baseSpDefense = 80,
        .types = MON_TYPES(TYPE_GRASS, TYPE_POISON),
        .catchRate = 45,
        .expYield = 142,
        .genderRatio = MON_GENDERLESS,
        .eggGroups = MON_EGG_GROUPS(EGG_GROUP_MONSTER),
        .abilities = { ABILITY_OVERGROW, ABILITY_NONE, ABILITY_NONE },
        .speciesName = HANDLE_EXPANDED_SPECIES_NAME("Betamn", "Betamon"),
        .natDexNum = NATIONAL_DEX_BETAMON,
        .categoryName = _("Seed"),
        .height = 10,
        .weight = 130,
        .description = COMPOUND_STRING("Its bulb grew."),
        .levelUpLearnset = sBetamonLevelUpLearnset,
    },
#endif // P_FAMILY_ALPHAMON
"""

LEARNSET = r"""
static const struct LevelUpMove sAlphamonLevelUpLearnset[] = {
    LEVEL_UP_MOVE( 1, MOVE_TACKLE),
    LEVEL_UP_MOVE( 7, MOVE_LEECH_SEED),
    LEVEL_UP_MOVE(13, MOVE_VINE_WHIP),
    LEVEL_UP_END
};
"""


class SpeciesParserTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.parsed = md.parse_species_text(SNIPPET)

    def test_both_species_parse_despite_the_P_FAMILY_guard(self):
        # The guard is stripped, not evaluated -- the documented limitation.
        self.assertEqual(sorted(self.parsed),
                         ["SPECIES_ALPHAMON", "SPECIES_BETAMON"])

    def test_base_stats(self):
        a = self.parsed["SPECIES_ALPHAMON"]
        self.assertEqual(
            [a["baseHP"], a["baseAttack"], a["baseDefense"],
             a["baseSpAttack"], a["baseSpDefense"], a["baseSpeed"]],
            [45, 49, 50, 65, 64, 45])

    def test_single_and_dual_MON_TYPES(self):
        self.assertEqual(self.parsed["SPECIES_ALPHAMON"]["types"],
                         ["TYPE_GRASS"])
        self.assertEqual(self.parsed["SPECIES_BETAMON"]["types"],
                         ["TYPE_GRASS", "TYPE_POISON"])

    def test_config_ternary_takes_the_first_branch(self):
        # (P_UPDATED_EXP_YIELDS >= GEN_5) ? 142 : 141 -> 142, the modern
        # default -- and GEN_5's digit must not be mistaken for the value.
        self.assertEqual(self.parsed["SPECIES_ALPHAMON"]["expYield"], 142)

    def test_description_literals_join_into_one_line(self):
        self.assertEqual(self.parsed["SPECIES_ALPHAMON"]["description"],
                         "It naps in bright sunlight. "
                         "There is a seed on its back.")

    def test_evolution_method_param_and_target(self):
        self.assertEqual(self.parsed["SPECIES_ALPHAMON"]["evolutions"],
                         [("EVO_LEVEL", "16", "SPECIES_BETAMON")])
        self.assertNotIn("evolutions", self.parsed["SPECIES_BETAMON"])

    def test_expanded_name_macro_takes_the_long_name(self):
        self.assertEqual(self.parsed["SPECIES_BETAMON"]["name"], "Betamon")
        self.assertEqual(self.parsed["SPECIES_ALPHAMON"]["name"], "Alphamon")

    def test_abilities_egg_groups_and_gender(self):
        a = self.parsed["SPECIES_ALPHAMON"]
        self.assertEqual(a["abilities"],
                         ["ABILITY_OVERGROW", "ABILITY_NONE",
                          "ABILITY_CHLOROPHYLL"])
        self.assertEqual(a["eggGroups"],
                         ["EGG_GROUP_MONSTER", "EGG_GROUP_GRASS"])
        self.assertEqual(md.gender_text(a["genderRatio"]),
                         "87.5% male, 12.5% female")
        self.assertEqual(
            md.gender_text(self.parsed["SPECIES_BETAMON"]["genderRatio"]),
            "Genderless")

    def test_a_comment_never_pollutes_the_parse(self):
        # The comment above .evolutions quotes "EVO_LEVEL 99".
        self.assertNotIn(
            "99", str(self.parsed["SPECIES_ALPHAMON"]["evolutions"]))

    def test_learnset_references_are_symbols(self):
        self.assertEqual(self.parsed["SPECIES_ALPHAMON"]["levelUpLearnset"],
                         "sAlphamonLevelUpLearnset")


class MacroExpansionTests(unittest.TestCase):
    """File-local #defines carry real data at the 1.9.4 pin: BEEDRILL_ATTACK
    is a stat, ARCEUS_SPECIES_INFO is a whole entry. Both must parse."""

    MACRO_SNIPPET = r"""
#define GAMMAMON_ATTACK (P_UPDATED_STATS >= GEN_6 ? 90 : 80)

#define GAMMAMON_SPECIES_INFO(type, suffix)      \
    {                                            \
        .baseHP        = 120,                    \
        .baseAttack    = GAMMAMON_ATTACK,        \
        .baseDefense   = 120,                    \
        .baseSpeed     = 120,                    \
        .baseSpAttack  = 120,                    \
        .baseSpDefense = 120,                    \
        .types = MON_TYPES(type),                \
        .speciesName = _("Gammamon"),            \
        .frontPic = gMonFrontPic_Gammamon ##suffix, \
    }

    [SPECIES_GAMMAMON_FIRE] = GAMMAMON_SPECIES_INFO(TYPE_FIRE, Fire),
"""

    def test_a_whole_entry_built_by_a_macro_parses(self):
        parsed = md.parse_species_text(self.MACRO_SNIPPET)
        sp = parsed["SPECIES_GAMMAMON_FIRE"]
        self.assertEqual(sp["baseHP"], 120)
        self.assertEqual(sp["types"], ["TYPE_FIRE"])
        self.assertEqual(sp["name"], "Gammamon")

    def test_an_object_macro_stat_resolves_to_its_modern_branch(self):
        parsed = md.parse_species_text(self.MACRO_SNIPPET)
        self.assertEqual(parsed["SPECIES_GAMMAMON_FIRE"]["baseAttack"], 90)

    def test_token_pasting_concatenates(self):
        parsed = md.parse_species_text(self.MACRO_SNIPPET)
        self.assertEqual(parsed["SPECIES_GAMMAMON_FIRE"]["frontPic"],
                         "gMonFrontPic_GammamonFire")


class LearnsetParserTests(unittest.TestCase):

    def test_level_up_moves_in_order(self):
        parsed = md.parse_level_up_learnsets(LEARNSET)
        self.assertEqual(parsed["sAlphamonLevelUpLearnset"],
                         [(1, "MOVE_TACKLE"), (7, "MOVE_LEECH_SEED"),
                          (13, "MOVE_VINE_WHIP")])


class DiffTests(unittest.TestCase):
    """new vs changed vs same, the classification the whole site exists for."""

    def setUp(self):
        self.stock = md.parse_species_text(SNIPPET)

    def test_a_species_absent_from_stock_is_new(self):
        status, diffs = md.classify(self.stock["SPECIES_ALPHAMON"], None)
        self.assertEqual((status, diffs), ("new", []))

    def test_an_identical_species_is_same(self):
        ours = md.parse_species_text(SNIPPET)
        status, diffs = md.classify(ours["SPECIES_ALPHAMON"],
                                    self.stock["SPECIES_ALPHAMON"])
        self.assertEqual((status, diffs), ("same", []))

    def test_a_stat_edit_is_changed_with_old_and_new_values(self):
        ours = md.parse_species_text(
            SNIPPET.replace(".baseAttack    = 49,", ".baseAttack    = 60,"))
        status, diffs = md.classify(ours["SPECIES_ALPHAMON"],
                                    self.stock["SPECIES_ALPHAMON"])
        self.assertEqual(status, "changed")
        self.assertEqual(diffs, [("Attack", 49, 60)])

    def test_a_type_edit_is_changed(self):
        ours = md.parse_species_text(
            SNIPPET.replace("MON_TYPES(TYPE_GRASS)",
                            "MON_TYPES(TYPE_GRASS, TYPE_FAIRY)"))
        status, diffs = md.classify(ours["SPECIES_ALPHAMON"],
                                    self.stock["SPECIES_ALPHAMON"])
        self.assertEqual(status, "changed")
        self.assertEqual(diffs, [("Types", ["TYPE_GRASS"],
                                  ["TYPE_GRASS", "TYPE_FAIRY"])])

    def test_cosmetic_fields_do_not_count_as_changes(self):
        # iconPalIndex is presentation, not a species fact the dex compares.
        ours = md.parse_species_text(
            SNIPPET.replace(".iconPalIndex = 4,", ".iconPalIndex = 2,"))
        status, _ = md.classify(ours["SPECIES_ALPHAMON"],
                                self.stock["SPECIES_ALPHAMON"])
        self.assertEqual(status, "same")


class TypeChartTests(unittest.TestCase):

    CHART = r"""
#define X UQ_4_12
#define ______ X(1.0)
#define FIR_RS (B_UPDATED_TYPE_MATCHUPS >= GEN_2 ? X(0.5) : X(1.0))

const uq4_12_t gTypeEffectivenessTable[NUMBER_OF_MON_TYPES][NUMBER_OF_MON_TYPES] =
{
    [TYPE_FIRE]  = {X(0.5), X(2.0)},
    [TYPE_GRASS] = {FIR_RS, ______},
};
"""

    def test_chart_rows_X_values_and_rs_macros(self):
        order, chart = md.parse_type_chart(self.CHART)
        self.assertEqual(order, ["TYPE_FIRE", "TYPE_GRASS"])
        self.assertEqual(chart[("TYPE_FIRE", "TYPE_FIRE")], 0.5)
        self.assertEqual(chart[("TYPE_FIRE", "TYPE_GRASS")], 2.0)
        # FIR_RS resolves to its first (modern) branch, 0.5.
        self.assertEqual(chart[("TYPE_GRASS", "TYPE_FIRE")], 0.5)
        # Neutral entries are simply absent.
        self.assertNotIn(("TYPE_GRASS", "TYPE_GRASS"), chart)

    def test_an_unreadable_chart_is_refused_not_guessed(self):
        order, chart = md.parse_type_chart(
            self.CHART.replace("{FIR_RS, ______}", "{SOME_UNKNOWN_MACRO, ______}"))
        self.assertEqual((order, chart), ([], {}))

    def test_the_fallback_chart_is_the_standard_18(self):
        self.assertEqual(len(md.FALLBACK_ORDER), 18)
        self.assertEqual(md.FALLBACK_CHART[("TYPE_ELECTRIC", "TYPE_GROUND")], 0)


if __name__ == "__main__":
    unittest.main()
