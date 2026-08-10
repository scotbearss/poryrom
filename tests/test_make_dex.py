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

import hashlib
import json
import os
import pathlib
import shutil
import struct
import sys
import tempfile
import time
import unittest
import unittest.mock

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


MOVES_SNIPPET = r"""
    [MOVE_TACKLE] =
    {
        .name = COMPOUND_STRING("Tackle"),
        .description = COMPOUND_STRING(
            "Charges the foe with a\n"
            "full-body tackle."),
        .power = 40,
        .effect = EFFECT_HIT,
        .type = TYPE_NORMAL,
        .accuracy = 100,
        .pp = 35,
        .priority = 0,
        .category = DAMAGE_CATEGORY_PHYSICAL,
    },

    [MOVE_THUNDER_PUNCH] =
    {
        .name = HANDLE_EXPANDED_MOVE_NAME("ThunderPunch", "Thunder Punch"),
        .power = 75,
        .type = TYPE_ELECTRIC,
        .accuracy = 100,
        .pp = 15,
        .category = DAMAGE_CATEGORY_PHYSICAL,
    },
"""


class MoveParserTests(unittest.TestCase):

    def setUp(self):
        self.parsed = md.parse_moves_info(MOVES_SNIPPET)

    def test_name_type_category_power_accuracy_pp_priority(self):
        mv = self.parsed["MOVE_TACKLE"]
        self.assertEqual(mv["name"], "Tackle")
        self.assertEqual(mv["type"], "TYPE_NORMAL")
        self.assertEqual(mv["category"], "Physical")
        self.assertEqual(mv["power"], 40)
        self.assertEqual(mv["accuracy"], 100)
        self.assertEqual(mv["pp"], 35)
        self.assertEqual(mv["priority"], 0)

    def test_description_literals_join(self):
        self.assertEqual(self.parsed["MOVE_TACKLE"]["description"],
                         "Charges the foe with a full-body tackle.")

    def test_expanded_move_name_takes_the_long_name_not_a_concatenation(self):
        # Regression: join_strings would produce "ThunderPunchThunder Punch"
        # -- HANDLE_EXPANDED_MOVE_NAME(short, long) is two ALTERNATIVE
        # names, not adjacent string-literal text to concatenate.
        self.assertEqual(self.parsed["MOVE_THUNDER_PUNCH"]["name"],
                         "Thunder Punch")


ABILITIES_SNIPPET = r"""
    [ABILITY_NONE] =
    {
        .name = _("-------"),
        .description = COMPOUND_STRING("No special ability."),
        .aiRating = 0,
    },

    [ABILITY_STURDY] =
    {
        .name = _("Sturdy"),
        .description = COMPOUND_STRING("Negates 1-hit KO attacks."),
        .aiRating = 6,
        .breakable = TRUE,
    },
"""


class AbilityParserTests(unittest.TestCase):

    def test_name_and_description(self):
        parsed = md.parse_abilities_info(ABILITIES_SNIPPET)
        self.assertEqual(parsed["ABILITY_STURDY"]["name"], "Sturdy")
        self.assertEqual(parsed["ABILITY_STURDY"]["description"],
                         "Negates 1-hit KO attacks.")
        self.assertEqual(parsed["ABILITY_NONE"]["name"], "-------")


ITEMS_SNIPPET = r"""
static const u8 sFullHealDesc[] = _(
    "Heals all the\n"
    "status problems of\n"
    "one Pokémon.");

const struct Item gItemsInfo[] =
{
    [ITEM_NONE] =
    {
        .name = _("????????"),
        .price = 0,
        .description = sQuestionMarksDesc,
        .pocket = POCKET_ITEMS,
    },

    [ITEM_POKE_BALL] =
    {
        .name = _("Poké Ball"),
        .price = 200,
        .description = COMPOUND_STRING(
            "A tool used for\n"
            "catching wild\n"
            "Pokémon."),
        .pocket = POCKET_POKE_BALLS,
    },

    [ITEM_FULL_HEAL] =
    {
        .name = _("Full Heal"),
        .price = 400,
        .description = sFullHealDesc,
        .pocket = POCKET_ITEMS,
    },

    [ITEM_RAGE_CANDY_BAR] =
    {
        .name = HANDLE_EXPANDED_ITEM_NAME("RageCandyBar", "Rage Candy Bar"),
        .price = 0,
        .pocket = POCKET_ITEMS,
    },
};
"""

ITEM_ORDER_SNIPPET = r"""
#define ITEM_NONE 0
#define ITEM_POKE_BALL 1
#define ITEM_FULL_HEAL 2
#define ITEM_RAGE_CANDY_BAR 3
#define FIRST_BALL ITEM_POKE_BALL
"""


class ItemParserTests(unittest.TestCase):

    def setUp(self):
        self.parsed = md.parse_items_info(ITEMS_SNIPPET)

    def test_name_price_pocket(self):
        it = self.parsed["ITEM_POKE_BALL"]
        self.assertEqual(it["name"], "Poké Ball")
        self.assertEqual(it["price"], 200)
        self.assertEqual(it["pocket"], "POCKET_POKE_BALLS")

    def test_inline_description_literal(self):
        self.assertEqual(self.parsed["ITEM_POKE_BALL"]["description"],
                         "A tool used for catching wild Pokémon.")

    def test_description_symbol_resolves_to_this_files_own_shared_text(self):
        # items.h keeps its shared sXDesc[] strings in the same file, unlike
        # species (a separate shared_dex_text.h) -- both must resolve.
        self.assertEqual(self.parsed["ITEM_FULL_HEAL"]["description"],
                         "Heals all the status problems of one Pokémon.")

    def test_an_unresolvable_shared_symbol_is_simply_absent(self):
        self.assertNotIn("description", self.parsed["ITEM_NONE"])

    def test_expanded_item_name_takes_the_long_name(self):
        self.assertEqual(self.parsed["ITEM_RAGE_CANDY_BAR"]["name"],
                         "Rage Candy Bar")

    def test_item_order_follows_the_constants_file_not_gItemsInfo_order(self):
        order = md.parse_item_order(ITEM_ORDER_SNIPPET)
        self.assertEqual(order["ITEM_FULL_HEAL"], 2)
        self.assertEqual(order["ITEM_RAGE_CANDY_BAR"], 3)
        # FIRST_BALL is an alias, not an ITEM_ constant -- must not appear.
        self.assertNotIn("FIRST_BALL", order)


class GenericClassifyTests(unittest.TestCase):
    """classify() generalized (Track A1) to any fields list, not just
    species'."""

    def test_a_custom_fields_list_diffs_only_those_fields(self):
        status, diffs = md.classify(
            {"name": "Tackle", "power": 40, "pp": 35},
            {"name": "Tackle", "power": 35, "pp": 35},
            md.MOVE_COMPARE_FIELDS)
        self.assertEqual(status, "changed")
        self.assertEqual(diffs, [("Power", 35, 40)])


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


class TrainerParserTests(unittest.TestCase):
    """Format-faithful to trainers.h at the 1.9.4 pin: trainerproc's #line
    markers between every field, a party behind a cast, and a mon whose moves
    are a nested brace list."""

    TRAINERS = r"""
#line 1 "src/data/trainers.party"
#line 76
    [TRAINER_NONE] =
    {
        .trainerClass = TRAINER_CLASS_PKMN_TRAINER_1,
        .partySize = 0,
        .party = (const struct TrainerMon[])
        {
        },
    },
#line 84
    [TRAINER_ROXANNE_1] =
    {
        .trainerName = _("ROXANNE"),
#line 86
        .trainerClass = TRAINER_CLASS_LEADER,
        .trainerPic = TRAINER_PIC_LEADER_ROXANNE,
        .encounterMusic_gender =
F_TRAINER_FEMALE |
            TRAINER_ENCOUNTER_MUSIC_FEMALE,
        .items = { ITEM_POTION, ITEM_POTION },
        .doubleBattle = FALSE,
        .partySize = 2,
        .party = (const struct TrainerMon[])
        {
            {
            .species = SPECIES_GEODUDE,
            .gender = TRAINER_MON_RANDOM_GENDER,
#line 94
            .lvl = 12,
            .moves = {
                MOVE_TACKLE,
                MOVE_ROCK_TOMB,
                MOVE_NONE,
            },
            },
            {
            .species = SPECIES_NOSEPASS,
            .heldItem = ITEM_ORAN_BERRY,
            .lvl = 15,
            .isShiny = TRUE,
            },
        },
    },
"""

    CLASSES = r"""
const struct TrainerClass gTrainerClasses[TRAINER_CLASS_COUNT] =
{
    TRAINER_CLASS(PKMN_TRAINER_1, "{PKMN} TRAINER"),
    TRAINER_CLASS(LEADER, "LEADER", 25),
    TRAINER_CLASS(POKEMANIAC, "POKéMANIAC", 15),
};
"""

    def setUp(self):
        self.t = md.parse_trainers(self.TRAINERS)

    def test_every_entry_parses_including_the_empty_slot(self):
        self.assertEqual(set(self.t), {"TRAINER_NONE", "TRAINER_ROXANNE_1"})

    def test_name_class_items_and_double_battle(self):
        r = self.t["TRAINER_ROXANNE_1"]
        self.assertEqual(r["name"], "ROXANNE")
        self.assertEqual(r["class"], "TRAINER_CLASS_LEADER")
        self.assertEqual(r["items"], ["ITEM_POTION", "ITEM_POTION"])
        self.assertFalse(r["double"])

    def test_the_party_survives_the_cast_and_the_line_markers(self):
        party = self.t["TRAINER_ROXANNE_1"]["party"]
        self.assertEqual([m["species"] for m in party],
                         ["SPECIES_GEODUDE", "SPECIES_NOSEPASS"])
        self.assertEqual([m["lvl"] for m in party], [12, 15])
        self.assertEqual(self.t["TRAINER_ROXANNE_1"]["maxLevel"], 15)

    def test_moves_drop_the_empty_slot_and_held_items_are_read(self):
        party = self.t["TRAINER_ROXANNE_1"]["party"]
        self.assertEqual(party[0]["moves"], ["MOVE_TACKLE", "MOVE_ROCK_TOMB"])
        self.assertEqual(party[1]["heldItem"], "ITEM_ORAN_BERRY")
        self.assertTrue(party[1]["shiny"])
        self.assertEqual(party[1]["moves"], [])

    def test_an_empty_party_is_empty_not_a_phantom_mon(self):
        self.assertEqual(self.t["TRAINER_NONE"]["party"], [])

    def test_one_level_moving_makes_a_trainer_changed(self):
        # The real fork has not touched a trainer, so the changed path is
        # proved here: a re-tuned team is the whole point of the page.
        ours = self.t["TRAINER_ROXANNE_1"]
        stock = md.parse_trainers(
            self.TRAINERS.replace(".lvl = 15,", ".lvl = 14,"))
        status, diffs = md.classify(ours, stock["TRAINER_ROXANNE_1"],
                                    md.TRAINER_COMPARE_FIELDS)
        self.assertEqual(status, "changed")
        self.assertEqual([d[0] for d in diffs], ["Party"])

    def test_an_untouched_trainer_is_same(self):
        stock = md.parse_trainers(self.TRAINERS)
        self.assertEqual(
            md.classify(self.t["TRAINER_ROXANNE_1"],
                        stock["TRAINER_ROXANNE_1"],
                        md.TRAINER_COMPARE_FIELDS)[0], "same")

    def test_trainer_classes_come_from_the_games_own_table(self):
        cls = md.parse_trainer_classes(self.CLASSES)
        self.assertEqual(cls["TRAINER_CLASS_LEADER"], "LEADER")
        self.assertEqual(cls["TRAINER_CLASS_PKMN_TRAINER_1"], "{PKMN} TRAINER")

    def test_the_games_shouting_is_read_for_the_web(self):
        self.assertEqual(md.prettify_caps("ROXANNE"), "Roxanne")
        self.assertEqual(md.prettify_caps("TEAM AQUA"), "Team Aqua")
        self.assertEqual(md.prettify_caps("{PKMN} TRAINER"), "Pokémon Trainer")
        # é is not ASCII, so the word still tests as shouted.
        self.assertEqual(md.prettify_caps("POKéMANIAC"), "Pokémaniac")
        # A name the game already wrote in mixed case is left alone.
        self.assertEqual(md.prettify_caps("Anna & Meg"), "Anna & Meg")
        # Each run of letters is cased on its own, so a joined name reads.
        self.assertEqual(md.prettify_caps("TATE&LIZA"), "Tate&Liza")


class WildEncounterTests(unittest.TestCase):

    ENC = json.dumps({"wild_encounter_groups": [{
        "label": "gWildMonHeaders", "for_maps": True,
        "fields": [
            {"type": "land_mons", "encounter_rates": [60, 30, 10]},
            {"type": "fishing_mons", "encounter_rates": [70, 30, 100],
             "groups": {"old_rod": [0, 1], "good_rod": [2]}},
        ],
        "encounters": [{
            "map": "MAP_ROUTE101", "base_label": "gRoute101",
            "land_mons": {"encounter_rate": 20, "mons": [
                {"min_level": 2, "max_level": 3, "species": "SPECIES_WURMPLE"},
                {"min_level": 4, "max_level": 4, "species": "SPECIES_WURMPLE"},
                {"min_level": 5, "max_level": 5, "species": "SPECIES_ZIGZAGOON"},
            ]},
            "fishing_mons": {"encounter_rate": 30, "mons": [
                {"min_level": 5, "max_level": 10, "species": "SPECIES_MAGIKARP"},
                {"min_level": 5, "max_level": 10, "species": "SPECIES_TENTACOOL"},
                {"min_level": 20, "max_level": 25, "species": "SPECIES_MAGIKARP"},
            ]},
        }],
    }]})

    def setUp(self):
        self.e = md.parse_wild_encounters(self.ENC)["MAP_ROUTE101"]

    def test_slots_of_the_same_species_sum_into_one_line(self):
        walking = self.e["methods"]["Walking"]["slots"]
        self.assertEqual([s["species"] for s in walking],
                         ["SPECIES_WURMPLE", "SPECIES_ZIGZAGOON"])
        self.assertAlmostEqual(walking[0]["pct"], 90.0)
        self.assertAlmostEqual(walking[1]["pct"], 10.0)

    def test_the_level_range_spans_every_slot_the_species_holds(self):
        wurmple = self.e["methods"]["Walking"]["slots"][0]
        self.assertEqual((wurmple["min"], wurmple["max"]), (2, 4))

    def test_fishing_is_three_methods_and_each_rod_sums_to_its_own_hundred(self):
        self.assertIn("Old Rod", self.e["methods"])
        self.assertIn("Good Rod", self.e["methods"])
        old = self.e["methods"]["Old Rod"]["slots"]
        self.assertAlmostEqual(old[0]["pct"], 70.0)
        self.assertAlmostEqual(old[1]["pct"], 30.0)
        good = self.e["methods"]["Good Rod"]["slots"]
        self.assertAlmostEqual(good[0]["pct"], 100.0)

    def test_a_rods_share_of_one_fishing_rate_is_not_restated_per_rod(self):
        self.assertEqual(self.e["methods"]["Walking"]["rate"], 20)
        self.assertIsNone(self.e["methods"]["Old Rod"]["rate"])

    def test_unparseable_json_yields_nothing_rather_than_raising(self):
        self.assertEqual(md.parse_wild_encounters("{ not json"), {})

    def test_a_swapped_encounter_slot_makes_its_place_changed(self):
        # Encounters are compared as part of the place they belong to, so
        # one page carries every reason a location differs from stock.
        stock = md.parse_wild_encounters(
            self.ENC.replace("SPECIES_ZIGZAGOON", "SPECIES_POOCHYENA"))
        ours = {"encounters": self.e["methods"]}
        theirs = {"encounters": stock["MAP_ROUTE101"]["methods"]}
        status, diffs = md.classify(ours, theirs, md.MAP_COMPARE_FIELDS)
        self.assertEqual(status, "changed")
        self.assertEqual([d[0] for d in diffs], ["Encounters"])

    def test_map_labels_split_digits_but_keep_floors(self):
        self.assertEqual(md.map_label("MAP_ROUTE101"), "Route 101")
        self.assertEqual(md.map_label("MAP_CAVE_OF_ORIGIN_1F"),
                         "Cave of Origin 1F")
        self.assertEqual(md.map_label("MAP_ABANDONED_SHIP_ROOMS_B1F"),
                         "Abandoned Ship Rooms B1F")


class MapDataTests(unittest.TestCase):
    """Track A3's readers. Everything here is a real format the fork ships;
    the awkward cases are the ones that bit during the build."""

    GRAPHICS = r"""
const u32 gTilesetTiles_General[] = INCBIN_U32("data/tilesets/primary/general/tiles.4bpp.lz");
const u16 gTilesetPalettes_General[][16] =
{
    INCBIN_U16("data/tilesets/primary/general/palettes/00.gbapal"),
    INCBIN_U16("data/tilesets/primary/general/palettes/01.gbapal"),
};
const u32 gTilesetTiles_SecretBaseBlueCave[] = INCBIN_U32("data/tilesets/secondary/secret_base/blue_cave/tiles.4bpp");
const u16 gTilesetPalettes_SecretBaseBlueCave[][16] =
{
    INCBIN_U16("data/tilesets/secondary/secret_base/blue_cave/palettes/00.gbapal"),
};
"""
    METATILES = r"""
const u16 gMetatiles_General[] = INCBIN_U16("data/tilesets/primary/general/metatiles.bin");
const u16 gMetatiles_SecretBaseSecondary[] = INCBIN_U16("data/tilesets/secondary/secret_base/metatiles.bin");
"""
    HEADERS = r"""
const struct Tileset gTileset_General =
{
    .isCompressed = TRUE,
    .isSecondary = FALSE,
    .tiles = gTilesetTiles_General,
    .palettes = gTilesetPalettes_General,
    .metatiles = gMetatiles_General,
};

const struct Tileset gTileset_SecretBaseBlueCave =
{
    .isSecondary = TRUE,
    .tiles = gTilesetTiles_SecretBaseBlueCave,
    .palettes = gTilesetPalettes_SecretBaseBlueCave,
    .metatiles = gMetatiles_SecretBaseSecondary,
};
"""

    def test_a_tilesets_three_parts_are_followed_not_assumed(self):
        ts = md.parse_tileset_paths(self.GRAPHICS, self.METATILES, self.HEADERS)
        gen = ts["gTileset_General"]
        self.assertEqual(gen["tiles"], "data/tilesets/primary/general/tiles.png")
        self.assertEqual(gen["palettes"], "data/tilesets/primary/general/palettes")
        self.assertEqual(gen["metatiles"],
                         "data/tilesets/primary/general/metatiles.bin")

    def test_a_shared_metatiles_file_is_read_from_where_the_header_says(self):
        # The bug this test exists for: every secret base shares one
        # metatiles.bin a directory ABOVE its own art, and assuming siblings
        # drew two dozen maps as nothing at all.
        cave = md.parse_tileset_paths(self.GRAPHICS, self.METATILES,
                                      self.HEADERS)["gTileset_SecretBaseBlueCave"]
        self.assertEqual(cave["tiles"],
                         "data/tilesets/secondary/secret_base/blue_cave/tiles.png")
        self.assertEqual(cave["metatiles"],
                         "data/tilesets/secondary/secret_base/metatiles.bin")

    def test_an_uncompressed_tileset_still_resolves_its_png(self):
        ts = md.parse_tileset_paths(self.GRAPHICS, self.METATILES, self.HEADERS)
        self.assertTrue(ts["gTileset_SecretBaseBlueCave"]["tiles"].endswith(".png"))

    MAP = json.dumps({
        "id": "MAP_ROUTE102", "name": "Route102", "layout": "LAYOUT_ROUTE102",
        "region_map_section": "MAPSEC_ROUTE_102", "map_type": "MAP_TYPE_ROUTE",
        "weather": "WEATHER_SUNNY",
        "connections": [{"map": "MAP_OLDALE_TOWN", "offset": 0,
                         "direction": "right"}],
        "object_events": [
            {"graphics_id": "OBJ_EVENT_GFX_YOUNGSTER", "x": 33, "y": 14,
             "trainer_type": "TRAINER_TYPE_NORMAL",
             "trainer_sight_or_berry_tree_id": "3",
             "script": "Route102_EventScript_Calvin"},
            {"graphics_id": "OBJ_EVENT_GFX_ITEM_BALL", "x": 11, "y": 15,
             "trainer_type": "TRAINER_TYPE_NONE",
             "trainer_sight_or_berry_tree_id": "ITEM_POTION",
             "script": "Common_EventScript_FindItem"},
            {"graphics_id": "OBJ_EVENT_GFX_BOY_1", "x": 4, "y": 4,
             "trainer_type": "TRAINER_TYPE_NONE",
             "trainer_sight_or_berry_tree_id": "0", "script": "Chat"},
        ],
        "warp_events": [{"x": 1, "y": 1, "dest_map": "MAP_PETALBURG_CITY",
                         "dest_warp_id": "0"}],
        "bg_events": [
            {"type": "hidden_item", "x": 7, "y": 7, "item": "ITEM_SUPER_POTION"},
            {"type": "sign", "x": 2, "y": 2, "script": "Route102_Sign"},
        ],
    })

    def setUp(self):
        self.m = md.parse_map_json(self.MAP)

    def test_an_item_ball_names_its_item_in_the_sight_radius_field(self):
        # The engine overloads that field, which is the only reason a ground
        # item is derivable from map.json at all.
        ground = {g["item"]: g for g in self.m["ground"]}
        self.assertEqual(ground["ITEM_POTION"]["hidden"], False)
        self.assertEqual((ground["ITEM_POTION"]["x"],
                          ground["ITEM_POTION"]["y"]), (11, 15))

    def test_hidden_items_come_from_the_background_events(self):
        ground = {g["item"]: g for g in self.m["ground"]}
        self.assertTrue(ground["ITEM_SUPER_POTION"]["hidden"])

    def test_a_sign_is_not_an_item_and_a_chatty_npc_is_not_a_trainer(self):
        self.assertEqual(len(self.m["ground"]), 2)
        self.assertEqual(len(self.m["trainers"]), 1)
        self.assertEqual(self.m["npcs"], 1)

    def test_connections_and_warps_are_kept_apart(self):
        self.assertEqual(self.m["connections"][0]["map"], "MAP_OLDALE_TOWN")
        self.assertEqual(self.m["warps"], ["MAP_PETALBURG_CITY"])

    def test_a_map_that_is_not_a_map_is_refused(self):
        self.assertIsNone(md.parse_map_json("{ not json"))
        self.assertIsNone(md.parse_map_json('{"no": "id"}'))

    SCRIPTS = """
Route102_EventScript_Calvin::
\ttrainerbattle_single TRAINER_CALVIN, Route102_Text_A, Route102_Text_B
\tmsgbox Route102_Text_C
\trelease
\tend

Route102_EventScript_Sign::
\tmsgbox Route102_Text_Sign, MSGBOX_SIGN
\tend

Route102_EventScript_Empty::
\ttrainerbattle_single TRAINER_NONE
\tend
"""

    def test_a_script_label_resolves_to_the_trainer_it_battles(self):
        s = md.parse_script_trainers(self.SCRIPTS)
        self.assertEqual(s["Route102_EventScript_Calvin"], "TRAINER_CALVIN")

    def test_a_label_that_names_no_trainer_is_absent_not_guessed(self):
        s = md.parse_script_trainers(self.SCRIPTS)
        self.assertNotIn("Route102_EventScript_Sign", s)
        self.assertNotIn("Route102_EventScript_Empty", s)

    def test_layouts_are_keyed_by_their_own_id(self):
        lay = md.parse_layouts(json.dumps({"layouts": [
            {"id": "LAYOUT_ROUTE102", "width": 50, "height": 20},
            {"no_id": True}]}))
        self.assertEqual(list(lay), ["LAYOUT_ROUTE102"])
        self.assertEqual(lay["LAYOUT_ROUTE102"]["width"], 50)

    def test_a_redrawn_place_is_a_changed_place(self):
        ours = dict(self.m, terrain="aaaa", size=(50, 20), encounters={},
                    scripts={}, dir="Route102")
        stock = dict(ours, terrain="bbbb")
        status, diffs = md.classify(ours, stock, md.MAP_COMPARE_FIELDS)
        self.assertEqual(status, "changed")
        self.assertEqual([d[0] for d in diffs], ["Terrain"])

    def test_the_fieldmap_split_is_read_from_the_fork_not_assumed(self):
        c = md.parse_defines_int("#define NUM_TILES_IN_PRIMARY 640\n",
                                 md.FIELDMAP_DEFAULTS)
        self.assertEqual(c["NUM_TILES_IN_PRIMARY"], 640)
        # ...and what the header does not say keeps the engine's own value.
        self.assertEqual(c["NUM_PALS_IN_PRIMARY"], 6)


class GameTextTests(unittest.TestCase):
    """Track A4: the game's own words, and the one hop from a battle macro
    to the lines it speaks."""

    TEXT = """
Route102_Text_CalvinIntro:
\t.string "If you have POKéMON with you, then\\n"
\t.string "you're an official TRAINER!\\p"
\t.string "You can't say no!$"

Route102_Text_CalvinDefeated::
\t.string "Arrgh, I lost…$"

@ a comment between passages must not join them
RustboroCity_TrainingAnnex_Text_Coach:
\t.string "{STR_VAR_1} minutes banked.$"
"""

    SCRIPTS = """
Route102_EventScript_Calvin::
\ttrainerbattle_single TRAINER_CALVIN_1, Route102_Text_CalvinIntro, Route102_Text_CalvinDefeated, Route102_EventScript_After
\tend

Route104_EventScript_Gift::
\tgiveitem ITEM_CHESTO_BERRY
\tgiveitem ITEM_WHITE_HERB
\tend

SomeMap_EventScript_Pair::
\ttrainerbattle_double TRAINER_GINA_AND_MIA_1, SomeMap_Text_Intro, SomeMap_Text_Defeat, SomeMap_Text_NotEnough
\tend
"""

    def setUp(self):
        self.texts = md.parse_text_labels(self.TEXT)

    def test_string_lines_join_into_one_passage_per_label(self):
        self.assertEqual(len(self.texts), 3)
        self.assertTrue(self.texts["Route102_Text_CalvinIntro"].endswith("$"))

    def test_one_colon_and_two_colons_are_both_labels(self):
        self.assertIn("Route102_Text_CalvinDefeated", self.texts)

    def test_game_string_reads_the_control_codes_a_box_would(self):
        paras = md.game_string(self.texts["Route102_Text_CalvinIntro"])
        self.assertEqual(paras, ["If you have POKéMON with you, then "
                                 "you're an official TRAINER!",
                                 "You can't say no!"])

    def test_a_variable_is_quoted_not_named(self):
        # Inventing a value for {STR_VAR_1} would be writing dialogue
        # rather than quoting it.
        paras = md.game_string(self.texts["RustboroCity_TrainingAnnex_Text_Coach"])
        self.assertEqual(paras, ["{STR_VAR_1} minutes banked."])

    def test_a_battle_macro_names_the_lines_its_trainer_speaks(self):
        b = md.parse_trainerbattles(self.SCRIPTS)
        self.assertEqual(b["TRAINER_CALVIN_1"],
                         ["Route102_Text_CalvinIntro",
                          "Route102_Text_CalvinDefeated"])

    def test_a_following_script_argument_is_not_mistaken_for_dialogue(self):
        b = md.parse_trainerbattles(self.SCRIPTS)
        self.assertNotIn("Route102_EventScript_After", b["TRAINER_CALVIN_1"])

    def test_a_double_battle_keeps_all_three_of_its_texts(self):
        b = md.parse_trainerbattles(self.SCRIPTS)
        self.assertEqual(len(b["TRAINER_GINA_AND_MIA_1"]), 3)

    def test_scripts_that_hand_something_over(self):
        self.assertEqual(md.parse_giveitems(self.SCRIPTS),
                         {"ITEM_CHESTO_BERRY", "ITEM_WHITE_HERB"})

    def test_a_longer_map_name_keeps_its_own_lines(self):
        # RustboroCity is a prefix of RustboroCity_TrainingAnnex; the
        # separator is what stops the city stealing the annex's writing.
        g = md.group_texts(self.texts)
        self.assertEqual([lab for lab, _ in g["RustboroCity_TrainingAnnex"]],
                         ["RustboroCity_TrainingAnnex_Text_Coach"])
        self.assertNotIn("RustboroCity", g)

    def test_an_unresolvable_label_yields_nothing_rather_than_a_guess(self):
        self.assertEqual(md.game_string(None), [])
        self.assertEqual(md.game_string("$"), [])


class MapRenderTests(unittest.TestCase):
    """One tiny hand-built tileset, rendered. This is the only test that can
    catch a palette, a flip or a layer being read the wrong way round."""

    def setUp(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        self.Image = Image
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        ts = self.tmp / "data/tilesets/primary/t"
        (ts / "palettes").mkdir(parents=True)
        # Two 8x8 tiles: tile 0 all colour 1, tile 1 left half colour 2.
        img = Image.new("P", (16, 8), 0)
        # An explicit palette of DISTINCT colours: Pillow merges indices that
        # share a colour when it writes the file, and the default P palette
        # would quietly turn index 2 into index 1 on the way to disk.
        img.putpalette([0, 0, 0, 255, 0, 0, 0, 0, 255] + [7, 7, 7] * 13)
        for y in range(8):
            for x in range(8):
                img.putpixel((x, y), 1)
                img.putpixel((8 + x, y), 2 if x < 4 else 0)
        img.save(ts / "tiles.png")
        (ts / "palettes/00.pal").write_text(
            "JASC-PAL\r\n0100\r\n16\r\n0 0 0\r\n255 0 0\r\n0 0 255\r\n"
            + "0 0 0\r\n" * 13)
        # One metatile: bottom layer four of tile 0, top layer tile 1 in the
        # first corner (x-flipped) and nothing anywhere else.
        words = [0] * 8
        words[4] = 1 | 0x400
        (ts / "metatiles.bin").write_bytes(
            struct.pack(f"<{len(words)}H", *words))
        self.dirs = {"gTileset_T": {
            "tiles": "data/tilesets/primary/t/tiles.png",
            "palettes": "data/tilesets/primary/t/palettes",
            "metatiles": "data/tilesets/primary/t/metatiles.bin"}}
        self.r = md.MapRenderer(self.tmp, self.dirs, md.FIELDMAP_DEFAULTS,
                                md.MAPGRID_DEFAULTS, lambda m: None)
        self.r.available()

    def test_the_bottom_layer_paints_colour_zero_as_a_colour(self):
        img = self.r.block_image("gTileset_T", "gTileset_T", 0)
        # Bottom-right 8x8 is bottom-layer tile 0: solid palette colour 1.
        self.assertEqual(img.getpixel((12, 12)), (255, 0, 0, 255))

    def test_the_top_layer_treats_colour_zero_as_a_hole(self):
        img = self.r.block_image("gTileset_T", "gTileset_T", 0)
        # Top-left tile is tile 1, x-flipped: its transparent half is now on
        # the LEFT, so the bottom layer shows through there...
        self.assertEqual(img.getpixel((1, 1)), (255, 0, 0, 255))
        # ...and its opaque half is on the right of that 8x8 cell.
        self.assertEqual(img.getpixel((6, 1)), (0, 0, 255, 255))

    def test_a_layout_renders_at_sixteen_pixels_a_block(self):
        blocks = self.tmp / "data/layouts/T/map.bin"
        blocks.parent.mkdir(parents=True)
        blocks.write_bytes(struct.pack("<6H", *([0] * 6)))
        img = self.r.render({"width": 3, "height": 2,
                             "primary_tileset": "gTileset_T",
                             "secondary_tileset": "gTileset_T",
                             "blockdata_filepath": "data/layouts/T/map.bin"})
        self.assertEqual(img.size, (48, 32))

    def test_a_layout_whose_block_data_is_short_is_refused_not_half_drawn(self):
        blocks = self.tmp / "data/layouts/T/short.bin"
        blocks.parent.mkdir(parents=True)
        blocks.write_bytes(struct.pack("<2H", 0, 0))
        self.assertIsNone(self.r.render(
            {"width": 3, "height": 2, "primary_tileset": "gTileset_T",
             "secondary_tileset": "gTileset_T",
             "blockdata_filepath": "data/layouts/T/short.bin"}))

    def test_a_jasc_palette_reads_its_triples_and_ignores_its_header(self):
        pal = md.read_jasc_pal(
            self.tmp / "data/tilesets/primary/t/palettes/00.pal")
        self.assertEqual(pal[0], (0, 0, 0))
        self.assertEqual(pal[1], (255, 0, 0))
        self.assertEqual(len(pal), 16)


class BuildHealthTests(unittest.TestCase):
    """Track B1's dashboard inputs. These read a real (tiny) tree on disk
    rather than a string fixture, because what they are being trusted to get
    right IS the filesystem reading: which files a build wrote, which the
    game's author wrote, and which of the two the backup carries."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fork = self.tmp / "hacks/reps"
        self.engine = self.tmp / "engine"
        for root in (self.fork, self.engine):
            (root / "src").mkdir(parents=True)

    def write(self, root, rel, text, mtime=None):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    # -- ages and sizes ---------------------------------------------------

    def test_human_age_picks_one_unit_and_never_goes_negative(self):
        self.assertEqual(md.human_age(-500), "just now")
        self.assertEqual(md.human_age(10), "just now")
        self.assertEqual(md.human_age(60), "1 minute ago")
        self.assertEqual(md.human_age(3600), "1 hour ago")
        self.assertEqual(md.human_age(86400 * 3), "3 days ago")
        self.assertEqual(md.human_age(86400 * 200), "7 months ago")

    def test_human_size(self):
        self.assertEqual(md.human_size(512), "512 B")
        self.assertEqual(md.human_size(1 << 21), "2.0 MiB")

    # -- generated vs authored --------------------------------------------

    def test_the_engines_own_gitignore_names_what_the_build_wrote(self):
        (self.engine / ".gitignore").write_text(
            "# comment\n*.4bpp\n*.rl\nbuild/\nsound/**/*.bin\n!data/*.gba\n")
        pats = md.generated_patterns(self.engine)
        self.assertTrue(md.is_generated("graphics/x.4bpp", "x.4bpp", pats))
        self.assertTrue(md.is_generated("graphics/x.rl", "x.rl", pats))
        self.assertTrue(md.is_generated("sound/cries/a.bin", "a.bin", pats))
        # A path pattern must not become a basename pattern: map.bin is source.
        self.assertFalse(md.is_generated("data/layouts/m/map.bin", "map.bin", pats))
        self.assertFalse(md.is_generated("src/main.c", "main.c", pats))

    def test_export_hacks_own_exclusions_are_reused_not_restated(self):
        pats = md.generated_patterns(None)
        self.assertTrue(md.is_generated("data/maps/X/header.inc", "header.inc", pats))
        self.assertTrue(md.is_generated("data/maps/X/connections.inc",
                                        "connections.inc", pats))

    # -- the survey --------------------------------------------------------

    def test_only_files_that_differ_from_stock_count_as_the_games_own(self):
        old, new = 1000.0, 2000.0
        self.write(self.engine, "src/shared.c", "stock\n", old)
        self.write(self.fork, "src/shared.c", "stock\n", new)      # rebuilt copy
        self.write(self.fork, "src/mine.c", "ours\n", new)         # real work
        self.write(self.fork, "src/old.c", "ours\n", old)          # before cutoff
        self.write(self.fork, "graphics/a.4bpp", "x", new)         # build output
        s = md.survey_source(self.fork, self.engine, since=1500.0,
                             pats=md.generated_patterns(None))
        self.assertEqual([r["file"] for r in s["own"]], ["src/mine.c"])
        # touched counts everything past the cutoff, own does not.
        self.assertEqual(s["touched"], 2)
        self.assertFalse(s["capped"])

    def test_a_file_the_engine_never_had_is_the_games_own(self):
        self.write(self.fork, "src/new_feature.c", "ours\n", 2000.0)
        s = md.survey_source(self.fork, self.engine, since=1500.0,
                             pats=md.generated_patterns(None))
        self.assertEqual([r["file"] for r in s["own"]], ["src/new_feature.c"])

    # -- what the backup carries -------------------------------------------

    PATCH = ("--- engine/src/a.c\t2026-01-01\n"
             "+++ hacks/reps/src/a.c\t2026-01-02\n"
             "@@ -1 +1 @@\n-x\n+y\n"
             "Binary files engine/graphics/b.png and hacks/reps/graphics/b.png differ\n")

    def test_backed_up_paths_reads_the_patch_and_the_assets_beside_it(self):
        patch = self.write(self.tmp, "patches/reps.patch", self.PATCH)
        self.write(self.tmp, "patches/assets/reps/data/layouts/M/map.bin", "b")
        carried = md.backed_up_paths(patch, self.tmp / "patches/assets", "reps")
        self.assertIn("src/a.c", carried)
        self.assertIn("graphics/b.png", carried)
        self.assertIn("data/layouts/M/map.bin", carried)
        self.assertNotIn("src/never_exported.c", carried)

    def test_a_missing_patch_carries_nothing_rather_than_raising(self):
        self.assertEqual(
            md.backed_up_paths(self.tmp / "nope.patch",
                               self.tmp / "patches/assets", "reps"), set())

    # -- the game's own checks ---------------------------------------------

    def test_specs_that_need_an_absent_savestate_are_counted_as_not_runnable(self):
        ws = self.tmp
        (ws / "verify").mkdir()
        (ws / "saves").mkdir()
        (ws / "verify/plain.json").write_text(json.dumps(
            {"name": "plain", "assert": [{"a": 1}, {"b": 2}]}))
        (ws / "verify/resumes.json").write_text(json.dumps(
            {"name": "resumes", "savestate": "party.ss1", "assert": [{"a": 1}]}))
        (ws / "verify/notaspec.json").write_text(json.dumps({"unrelated": True}))
        (ws / "verify/broken.json").write_text("{not json")
        ch = md.read_specs(ws)
        self.assertEqual(ch["specs"], 2)
        self.assertEqual(ch["asserts"], 3)
        self.assertEqual(ch["needs_state"], 1)
        self.assertEqual(ch["runnable"], 1)
        self.assertEqual(ch["missing_states"], ["party.ss1"])
        self.assertEqual(ch["unreadable"], 1)
        (ws / "saves/party.ss1").write_text("state")
        self.assertEqual(md.read_specs(ws)["runnable"], 2)

    def test_a_workspace_with_no_verify_dir_reports_zero_not_an_error(self):
        self.assertEqual(md.read_specs(self.tmp / "elsewhere")["specs"], 0)

    # -- the page itself ----------------------------------------------------

    EMPTY = {"species": {}, "moves": {}, "chart": {}, "type_order": [],
             "dex": {}, "sprite_dirs": {}, "abilities": {}, "items": {},
             "item_order": {}}

    def test_a_game_with_no_rom_no_backup_and_no_health_says_so(self):
        fork = dict(self.EMPTY, species={
            "SPECIES_NEWMON": {"const": "SPECIES_NEWMON", "name": "Newmon",
                               "order": 0, "types": ["TYPE_GRASS"]}})
        site = md.Site(fork, self.EMPTY, self.fork, self.tmp / "out", "tiny",
                       lambda m: None, "expansion/1.9.4", health={})
        site.build_dashboard()
        page = (self.tmp / "out/index.html").read_text(encoding="utf-8")
        # Nothing invented, nothing crashed: the absences are stated.
        self.assertIn("no built ROM", page)
        self.assertIn("nothing in it is backed up", page)
        # ...and a species with no art, no dex text and no learnset is not
        # allowed to look finished.
        self.assertIn("New content, finished or not", page)
        self.assertIn('<tr class="partial">', page)
        self.assertEqual(page.count('<td class="no">'), 4)

    # -- maps ---------------------------------------------------------------

    def test_only_directories_holding_a_map_json_are_counted_as_maps(self):
        for name in ("LittlerootTown", "MyNewRoute"):
            self.write(self.fork, f"data/maps/{name}/map.json", "{}")
        (self.fork / "data/maps/scratch").mkdir()
        self.write(self.engine, "data/maps/LittlerootTown/map.json", "{}")
        self.assertEqual(md.count_maps(self.fork),
                         {"LittlerootTown", "MyNewRoute"})
        self.assertEqual(md.count_maps(self.fork) - md.count_maps(self.engine),
                         {"MyNewRoute"})


class DevLogTests(unittest.TestCase):
    """Track B2's history. The half worth testing is the arithmetic BETWEEN
    two snapshots -- what a build is credited with, what it is not, and what
    the log admits it cannot see."""

    EMPTY = dict(BuildHealthTests.EMPTY)

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def species(self, const, name, **over):
        sp = {"const": const, "name": name, "order": 0, "types": ["TYPE_GRASS"],
              "baseHP": 45}
        sp.update(over)
        return sp

    def site(self, fork_species, engine_species=None, health=None):
        fork = dict(self.EMPTY, species={sp["const"]: sp
                                         for sp in fork_species})
        engine = dict(self.EMPTY, species={sp["const"]: sp
                                           for sp in (engine_species or [])})
        return md.Site(fork, engine, self.tmp / "fork", self.tmp / "out",
                       "tiny", lambda m: None, "expansion/1.9.4",
                       health=health or {"now": 1_700_000_000})

    # -- the fingerprint ---------------------------------------------------

    def test_the_digest_covers_the_compared_fields_and_nothing_else(self):
        a = {"name": "Alphamon", "baseHP": 45, "iconPalIndex": 4}
        same_where_it_counts = {"name": "Alphamon", "baseHP": 45,
                                "iconPalIndex": 9}
        moved = {"name": "Alphamon", "baseHP": 46, "iconPalIndex": 4}
        fields = [("name", "Name"), ("baseHP", "HP")]
        self.assertEqual(md.devlog_digest(a, fields),
                         md.devlog_digest(same_where_it_counts, fields))
        self.assertNotEqual(md.devlog_digest(a, fields),
                            md.devlog_digest(moved, fields))

    def test_a_new_entrys_digest_still_moves_when_it_is_edited(self):
        """The reason the digest fingerprints the entity and not the diff: a
        new species has no diff at all, so a diff-based fingerprint would go
        blind to every edit after the one that introduced it."""
        one = self.site([self.species("SPECIES_MINE", "Mine")])
        two = self.site([self.species("SPECIES_MINE", "Mine", baseHP=99)])
        a = one.devlog_entry()["categories"]["species"]["entries"]["SPECIES_MINE"]
        b = two.devlog_entry()["categories"]["species"]["entries"]["SPECIES_MINE"]
        self.assertEqual(a["status"], "new")
        self.assertEqual(b["status"], "new")
        self.assertNotEqual(a["digest"], b["digest"])
        self.assertEqual(md.devlog_delta({"categories": {"species": {
            "total": 1, "entries": {"SPECIES_MINE": a}}}},
            two.devlog_entry())["species"]["edited"], ["SPECIES_MINE"])

    # -- writing and reading ------------------------------------------------

    def entry(self, at, cats):
        return {"version": 1, "at": at,
                "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(at)),
                "categories": cats}

    def test_recording_writes_one_entry_and_explains_itself(self):
        e = self.entry(1_700_000_000, {"species": {"total": 1, "entries": {}}})
        path, note = md.record_devlog(self.tmp, e, [])
        self.assertIsNotNone(path)
        self.assertIn("recorded", note)
        self.assertTrue((self.tmp / "devlog/README.md").is_file())
        self.assertEqual(json.loads(path.read_text())["at"], 1_700_000_000)

    def test_a_build_that_moved_no_data_is_not_recorded_twice(self):
        cats = {"species": {"total": 1, "entries": {}}}
        first = self.entry(1_700_000_000, cats)
        md.record_devlog(self.tmp, first, [])
        # Same tree, later clock, different commit: the same thing said again.
        again = self.entry(1_700_009_999, cats)
        again["git"] = {"sha": "cafe123"}
        path, note = md.record_devlog(self.tmp, again, [first])
        self.assertIsNone(path)
        self.assertIn("nothing this game owns has changed", note)
        self.assertEqual(len(list((self.tmp / "devlog").glob("*.json"))), 1)

    def test_history_reads_oldest_first_and_survives_a_broken_entry(self):
        d = self.tmp / "devlog"
        d.mkdir()
        (d / "20260101-000000.json").write_text(json.dumps(
            self.entry(100, {"species": {"total": 1, "entries": {}}})))
        (d / "20260202-000000.json").write_text(json.dumps(
            self.entry(200, {"species": {"total": 2, "entries": {}}})))
        (d / "20260303-000000.json").write_text("{ this is not json")
        (d / "notes.md").write_text("prose is not an entry")
        hist = md.read_devlog(self.tmp)
        self.assertEqual([e["at"] for e in hist], [100, 200])
        self.assertEqual(hist[0]["file"], "20260101-000000.json")

    def test_no_devlog_directory_is_an_empty_history_not_an_error(self):
        self.assertEqual(md.read_devlog(self.tmp / "elsewhere"), [])

    # -- the delta ----------------------------------------------------------

    def cat(self, total, entries, capped=False):
        return {"categories": {"species": {"total": total, "capped": capped,
                                           "entries": entries}}}

    def test_the_delta_separates_started_moved_and_stopped(self):
        old = self.cat(10, {
            "SPECIES_A": {"name": "A", "status": "changed", "digest": "1"},
            "SPECIES_B": {"name": "B", "status": "new", "digest": "2"}})
        new = self.cat(10, {
            "SPECIES_A": {"name": "A", "status": "changed", "digest": "9"},
            "SPECIES_C": {"name": "C", "status": "new", "digest": "3"}})
        d = md.devlog_delta(old, new)["species"]
        self.assertEqual(d["added"], ["SPECIES_C"])
        self.assertEqual(d["edited"], ["SPECIES_A"])
        self.assertEqual(d["gone"], ["SPECIES_B"])

    def test_two_identical_snapshots_have_no_delta_at_all(self):
        snap = self.cat(10, {"SPECIES_A": {"name": "A", "status": "new",
                                           "digest": "1"}})
        self.assertEqual(md.devlog_delta(snap, snap), {})

    def test_a_deleted_stock_entry_shows_up_only_as_the_total_moving(self):
        """It never differed from stock while it existed, so it was in no
        snapshot's list. The count is the only place its going is visible."""
        d = md.devlog_delta(self.cat(10, {}), self.cat(9, {}))["species"]
        self.assertEqual((d["added"], d["edited"], d["gone"]), ([], [], []))
        self.assertEqual((d["from"], d["to"]), (10, 9))

    def test_a_capped_snapshot_marks_its_delta_as_incomplete(self):
        d = md.devlog_delta(self.cat(10, {}, capped=True),
                            self.cat(10, {"SPECIES_A": {"name": "A",
                                                        "status": "new",
                                                        "digest": "1"}}))
        self.assertTrue(d["species"]["partial"])

    def test_the_cap_shortens_the_naming_and_never_the_counts(self):
        mons = [self.species(f"SPECIES_M{i}", f"M{i}", order=i)
                for i in range(md.DEVLOG_CAP + 3)]
        cats = self.site(mons).devlog_entry()["categories"]["species"]
        self.assertEqual(cats["new"], md.DEVLOG_CAP + 3)
        self.assertEqual(len(cats["entries"]), md.DEVLOG_CAP)
        self.assertTrue(cats["capped"])

    def test_human_delta_signs_the_cost_and_says_nothing_about_zero(self):
        self.assertEqual(md.human_delta(608), "+608 B")
        self.assertEqual(md.human_delta(-2048), "−2.0 KiB")
        self.assertEqual(md.human_delta(0), "")

    # -- the page -----------------------------------------------------------

    def test_with_no_history_the_page_says_so_and_invents_nothing(self):
        site = self.site([self.species("SPECIES_MINE", "Mine")])
        site.build_devlog()
        page = (self.tmp / "out/devlog.html").read_text(encoding="utf-8")
        self.assertIn("No build has been recorded yet", page)
        self.assertNotIn("logcat", page)

    def test_the_page_credits_the_build_that_moved_a_thing(self):
        site = self.site([self.species("SPECIES_MINE", "Mine")])
        cur = site.devlog_entry()
        was = json.loads(json.dumps(cur))
        was["at"], was["date"] = cur["at"] - 86400, "2026-01-01 09:00"
        was["categories"]["species"]["entries"].pop("SPECIES_MINE")
        was["categories"]["species"]["new"] = 0
        # ...and a species the log named that has since left the tree.
        was["categories"]["species"]["entries"]["SPECIES_GONE"] = {
            "name": "Gonermon", "status": "new", "digest": "z"}
        site.history, site.entry = [was], cur
        site.build_devlog()
        page = (self.tmp / "out/devlog.html").read_text(encoding="utf-8")
        self.assertIn("Since the last recorded build", page)
        self.assertIn('<a href="pokemon/mine.html">Mine</a>', page)
        # The name the log wrote down survives; the dead link does not.
        self.assertIn("Gonermon", page)
        self.assertNotIn("gone.html", page)
        self.assertIn("no longer in the tree", page)

    def test_the_dashboard_line_names_the_build_it_measures_from(self):
        site = self.site([self.species("SPECIES_MINE", "Mine")],
                         health={"now": 1_700_000_000})
        cur = site.devlog_entry()
        was = json.loads(json.dumps(cur))
        was["date"] = "2026-01-01 09:00"
        was["categories"]["species"]["entries"].pop("SPECIES_MINE")
        site.history, site.entry = [was], cur
        site.build_dashboard()
        page = (self.tmp / "out/index.html").read_text(encoding="utf-8")
        self.assertIn("Since the last build", page)
        self.assertIn("1 species", page)
        self.assertIn("2026-01-01 09:00", page)


class DesignDocTests(unittest.TestCase):
    """Track B3. Every shape below is one a REAL design doc wrote, including
    the two that broke the first parser: a heading line carrying two sections
    because the doc is held to a 60-line budget, and a status field that used
    a word the plan never defined."""

    INDEX = """\
# tiny — Design Index

## Identity

- **Name:** tiny
- **Archetype:** monster-collector
- **Pitch:** A hack about one idea, carried all the way.
- **Core loop:** Read the matchup, pick the move.

## Phase

- **Phase:** build
- **Entered:** 2026-07-26

## Locked decisions

| Date | Decision | Why (pointer) |
|---|---|---|
| 2026-07-26 | The save layout is FINAL | docs 59 |

## Open questions (max 5) — none. ## Next actions (max 3, ordered)

1. SPEND THE ARENA. Nothing is queued behind a wall,
   so the debts come first.
2. REDRAW MOOCALF SMALL.
"""

    SCOPE = """\
# Scope Ledger

## Slice plan

Status: `planned | building | done | cut`.

### Slice 1: the ceiling only training raises

- **Status:** **done** 2026-07-26 — build record `docs/59`.
  Everything in Build landed.
- **Soul (one sentence):** a mon that hits the ceiling visibly stops gaining.
- **Failure condition:** a Pokémon levels past the ceiling.

### Slice 2: the gym door with two locks

- **Status:** planned
- **Soul:** the door still says no, and you know why.

### Slice 3: the training card

- **Status:** BUILT 2026-07-30, verified, **NOT visually finished**
- **Soul:** one glance tells you where you are lopsided.

### Slice 4: the rep ball

- **Status:** cut
- **Soul:** ITEM_REP_BALL catches what you earned.

### Slice 5: make it a thing you'd want to hold

- **Status:** **done** 2026-08-02 — including the device session.
- **Soul:** a set runs itself from across the room.

## Cut list

| Date | What was cut | Why | Revisit? |
|---|---|---|---|
| 2026-07-26 | Gyms 2–8 | Content, not design | Yes, after slice 4 |
"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "design").mkdir()
        (self.tmp / "design/index.md").write_text(self.INDEX, encoding="utf-8")
        (self.tmp / "design/scope.md").write_text(self.SCOPE, encoding="utf-8")
        self.design = md.load_design(self.tmp)

    # -- the shapes the doc already had -------------------------------------

    def test_one_heading_line_can_carry_two_sections(self):
        """A doc under a hard line budget squashes them, and the earlier
        one's answer ends up in the heading itself."""
        secs = md.split_sections(self.INDEX)
        titles = [s["title"] for s in secs]
        self.assertIn("Open questions (max 5) — none", titles)
        self.assertTrue(any(t.startswith("Next actions") for t in titles))
        # The body went to the LAST section named on the line.
        self.assertEqual(md.find_section(secs, "open questions"), [])
        self.assertTrue(md.find_section(secs, "next actions"))

    def test_a_sections_subsections_come_with_it_when_asked_for(self):
        """The slice plan's slices are headings of their own, so without
        this the plan is an empty section with four orphans under it."""
        secs = md.split_sections(self.SCOPE)
        self.assertEqual(len(md.parse_slices(md.find_section(
            secs, "slice plan"))), 0)
        self.assertEqual(len(md.parse_slices(md.find_section(
            secs, "slice plan", deep=True))), 5)

    def test_a_field_value_folds_its_continuation_lines(self):
        fields = md.parse_md_fields([
            "- **Status:** **done** 2026-07-26 — build record `docs/59`.",
            "  Everything in Build landed.",
            "- **Soul:** short."])
        self.assertEqual(fields["status"],
                         "done 2026-07-26 — build record docs/59. "
                         "Everything in Build landed.")
        self.assertEqual(fields["soul"], "short.")

    def test_a_list_drops_the_placeholders_the_template_ships_with(self):
        self.assertEqual(md.parse_md_list(["- none yet", "- TBD", "- real"]),
                         ["real"])

    def test_a_table_loses_its_header_and_its_dashes(self):
        rows = md.parse_md_table(["| Date | What |", "|---|---|",
                                  "| 2026-07-26 | Gyms 2–8 |"])
        self.assertEqual(rows, [["2026-07-26", "Gyms 2–8"]])

    # -- what it read -------------------------------------------------------

    def test_the_identity_block_and_the_plan_are_read_whole(self):
        d = self.design
        self.assertTrue(d["found"])
        self.assertEqual(d["pitch"], "A hack about one idea, carried all the way.")
        self.assertEqual(d["phase"], "build")
        self.assertEqual([s["n"] for s in d["slices"]],
                         ["1", "2", "3", "4", "5"])
        self.assertEqual([s["status"] for s in d["slices"]],
                         ["done", "planned", "", "cut", "done"])
        self.assertEqual(d["next"][0].split(".")[0], "SPEND THE ARENA")
        self.assertEqual(len(d["decisions"]), 1)
        self.assertEqual(len(d["cuts"]), 1)

    def test_a_status_outside_the_plans_own_vocabulary_is_kept_not_guessed(self):
        card = self.design["slices"][2]
        self.assertEqual(card["status"], "")
        self.assertIn("BUILT 2026-07-30", card["status_raw"])

    def test_a_workspace_with_no_design_doc_is_read_as_having_none(self):
        d = md.load_design(self.tmp / "elsewhere")
        self.assertFalse(d["found"])
        self.assertEqual(d["slices"], [])

    # -- what it noticed ----------------------------------------------------

    def test_a_planned_slice_above_a_done_one_contradicts_the_plans_own_rule(self):
        warns = md.design_contradictions(self.design, set())
        self.assertTrue(any("Slice 2 is marked planned" in w for w in warns))
        self.assertFalse(any("Slice 1" in w for w in warns))

    def test_a_status_the_plan_never_defined_is_reported_as_unreadable(self):
        warns = md.design_contradictions(self.design, set())
        self.assertTrue(any("Slice 3's status reads" in w for w in warns))

    def test_an_unbuilt_slice_naming_something_the_tree_has_is_flagged(self):
        """§6.3: a roadmap item claiming what the tree already contains is a
        bug in the doc, not a fact the site should paper over."""
        warns = md.design_contradictions(self.design, {"ITEM_REP_BALL"})
        self.assertTrue(any("Slice 4 is marked cut" in w and "ITEM_REP_BALL" in w
                            for w in warns))
        self.assertFalse(any("ITEM_REP_BALL" in w for w
                             in md.design_contradictions(self.design, set())))

    def test_clip_cuts_at_a_word(self):
        self.assertEqual(md.clip("one two three four", 9), "one two…")
        self.assertEqual(md.clip("short", 40), "short")

    # -- the page -----------------------------------------------------------

    def site(self, design):
        site = md.Site(dict(BuildHealthTests.EMPTY), dict(BuildHealthTests.EMPTY),
                       self.tmp / "fork", self.tmp / "out", "tiny",
                       lambda m: None, "expansion/1.9.4", health={})
        site.design = design
        return site

    def test_the_roadmap_labels_itself_authored_and_dashes_the_unbuilt(self):
        site = self.site(self.design)
        site.build_roadmap()
        page = (self.tmp / "out/roadmap.html").read_text(encoding="utf-8")
        self.assertIn("From the design doc, not from the game", page)
        self.assertIn('<div class="slice planned">', page)
        self.assertIn('<div class="slice unclear">', page)
        # The page reports the mark; it never claims to have checked it.
        self.assertIn("this page reports that mark, it does not check it", page)
        self.assertIn("Where the doc no longer agrees with itself", page)

    def test_a_game_with_no_design_doc_gets_an_empty_roadmap_not_an_invented_one(self):
        site = self.site(md.load_design(self.tmp / "elsewhere"))
        site.build_roadmap()
        page = (self.tmp / "out/roadmap.html").read_text(encoding="utf-8")
        self.assertIn("no design doc yet", page)
        self.assertNotIn("Slice plan", page)

    def test_the_changes_page_carries_the_pitch_above_the_derived_diff(self):
        site = self.site(self.design)
        site.build_changes()
        page = (self.tmp / "out/changes.html").read_text(encoding="utf-8")
        pitch = page.index("A hack about one idea")
        self.assertLess(pitch, page.index("New species"))
        self.assertIn("From the design doc, not from the game", page)
        self.assertIn("Everything below this box is read from the source tree",
                      page)


class RouteOrderTests(unittest.TestCase):
    """Track C1. The order is authored and never derived (§11.4); the graph
    is walked only for what hangs off the route and what it never reaches.
    These test that split, because getting it wrong in the other direction
    -- letting the site invent a route -- is the failure that matters."""

    ROUTE = """\
## Route order

The critical path in play order.

1. **Out of Littleroot** — take what the lab will give you.
   - **Gate:** none — this is the opening
   - Littleroot Town — two houses and a lab.
   - Route 101
   - Oldale Town — the first place that sells anything.

2. **The compact form** — a spine before anyone writes prose.
   - **Places:** Route 102, Ashfall Caverns, Littleroot Town
"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def mapr(self, mid, **over):
        rec = {"id": mid, "layout": "L", "terrain": "d", "size": (10, 10),
               "encounters": {}, "trainers": [], "ground": [], "npcs": 0,
               "connections": [], "warps": [], "weather": "", "type": "",
               "text": [], "scripts": {}}
        rec.update(over)
        return rec

    WORLD = None

    def site(self, maps, route):
        fork = dict(BuildHealthTests.EMPTY,
                    maps={m["id"]: m for m in maps},
                    layouts={}, trainers={}, encounters={})
        site = md.Site(fork, dict(BuildHealthTests.EMPTY, maps={}),
                       self.tmp / "fork", self.tmp / "out", "tiny",
                       lambda m: None, "expansion/1.9.4", health={})
        site.design = {"found": True, "route": route}
        return site

    # -- reading the doc ----------------------------------------------------

    def test_both_forms_of_a_beat_are_read(self):
        beats = md.parse_route(self.ROUTE.splitlines())
        self.assertEqual([b["title"] for b in beats],
                         ["Out of Littleroot", "The compact form"])
        self.assertEqual(beats[0]["sentence"], "take what the lab will give you.")
        self.assertEqual(beats[0]["gate"], "none — this is the opening")
        self.assertEqual([p["name"] for p in beats[0]["places"]],
                         ["Littleroot Town", "Route 101", "Oldale Town"])
        # The sentence after a place's dash is that place's own note (C2).
        self.assertEqual(beats[0]["places"][0]["note"], "two houses and a lab.")
        self.assertEqual(beats[0]["places"][1]["note"], "")
        # ...and the compact comma list carries order without prose.
        self.assertEqual([p["name"] for p in beats[1]["places"]],
                         ["Route 102", "Ashfall Caverns", "Littleroot Town"])

    def test_a_line_with_no_dash_is_all_name(self):
        self.assertEqual(md.split_dash("Route 101"), ("Route 101", ""))
        self.assertEqual(md.split_dash("Route 101 — the first grass"),
                         ("Route 101", "the first grass"))

    def test_the_route_is_read_out_of_the_narrative_doc(self):
        (self.tmp / "design").mkdir()
        (self.tmp / "design/narrative.md").write_text(self.ROUTE, encoding="utf-8")
        self.assertEqual(len(md.load_design(self.tmp)["route"]), 2)

    # -- resolving it against the world -------------------------------------

    def test_a_place_resolves_by_label_by_constant_and_by_neither_exactly(self):
        site = self.site([self.mapr("MAP_LITTLEROOT_TOWN")], [])
        idx = site.place_index()
        for form in ("littleroottown", "maplittleroottown", "littleroottown"):
            self.assertEqual(idx[form], "MAP_LITTLEROOT_TOWN")

    def test_a_second_visit_is_marked_and_never_merged(self):
        maps = [self.mapr("MAP_LITTLEROOT_TOWN"), self.mapr("MAP_ROUTE101")]
        route = [{"n": "1", "title": "a", "sentence": "", "gate": "",
                  "places": [{"name": "Littleroot Town", "note": ""},
                             {"name": "Route 101", "note": ""}]},
                 {"n": "2", "title": "b", "sentence": "", "gate": "",
                  "places": [{"name": "Littleroot Town", "note": ""}]}]
        beats = self.site(maps, route).route_thread()["beats"]
        self.assertIsNone(beats[0]["stops"][0]["first"])
        self.assertEqual(beats[1]["stops"][0]["first"], "1")
        self.assertEqual(len(beats[1]["stops"]), 1)

    def test_a_place_the_tree_does_not_have_resolves_to_nothing(self):
        route = [{"n": "1", "title": "a", "sentence": "", "gate": "",
                  "places": [{"name": "Ashfall Caverns", "note": "planned"}]}]
        stop = self.site([self.mapr("MAP_X")], route)["beats"] \
            if False else self.site([self.mapr("MAP_X")], route).route_thread()
        self.assertIsNone(stop["beats"][0]["stops"][0]["id"])

    # -- the graph, used for coverage and never for order --------------------

    def world(self):
        """A → B → C on the route; B opens onto a two-room cave; F is three
        hops out and G is joined to nothing."""
        link = lambda *ids: [{"direction": "up", "map": i} for i in ids]
        return [
            self.mapr("MAP_A", connections=link("MAP_B")),
            self.mapr("MAP_B", connections=link("MAP_A", "MAP_C"),
                      warps=["MAP_CAVE1"]),
            self.mapr("MAP_C", connections=link("MAP_B")),
            self.mapr("MAP_CAVE1", warps=["MAP_B", "MAP_CAVE2"]),
            self.mapr("MAP_CAVE2", warps=["MAP_CAVE1", "MAP_FAR"]),
            self.mapr("MAP_FAR", warps=["MAP_CAVE2"]),
            self.mapr("MAP_LONELY"),
        ]

    def on_route(self):
        return [{"n": "1", "title": "a", "sentence": "", "gate": "",
                 "places": [{"name": "A", "note": ""}, {"name": "B", "note": ""},
                            {"name": "C", "note": ""}]}]

    def test_the_pocket_holds_what_hangs_off_the_route_and_stops(self):
        """Bounded on purpose: an unbounded fill puts the whole rest of a
        connected world in the first beat's pocket, which is not an
        excursion, it is the game."""
        t = self.site(self.world(), self.on_route()).route_thread()
        self.assertEqual(t["beats"][0]["pocket"], ["MAP_CAVE1", "MAP_CAVE2"])

    def test_what_the_route_never_reaches_is_reported_with_how_it_connects(self):
        t = self.site(self.world(), self.on_route()).route_thread()
        got = {u["id"]: u["near"] for u in t["unreached"]}
        self.assertEqual(got, {"MAP_FAR": "MAP_CAVE2", "MAP_LONELY": None})

    def test_a_place_belongs_to_the_first_beat_that_reaches_it(self):
        route = [{"n": "1", "title": "a", "sentence": "", "gate": "",
                  "places": [{"name": "A", "note": ""}]},
                 {"n": "2", "title": "b", "sentence": "", "gate": "",
                  "places": [{"name": "C", "note": ""}]}]
        t = self.site(self.world(), route).route_thread()
        self.assertIn("MAP_B", t["beats"][0]["pocket"])
        self.assertNotIn("MAP_B", t["beats"][1]["pocket"])

    # -- the page -----------------------------------------------------------

    def page(self, maps, route):
        site = self.site(maps, route)
        site.build_thread()
        return (self.tmp / "out/thread.html").read_text(encoding="utf-8")

    def test_with_no_route_the_page_says_so_and_walks_nothing(self):
        page = self.page(self.world(), [])
        self.assertIn("No route order has been written", page)
        self.assertIn("the generator will not guess", page)
        self.assertNotIn('class="beat"', page)

    def test_the_page_counts_what_was_written_and_estimates_nothing(self):
        """The prototype's terminus read "3 of an estimated 9 beats". Nothing
        can know how many beats a finished route has."""
        page = self.page(self.world(), self.on_route())
        self.assertIn("1 beat written", page)
        self.assertNotIn("estimated", page)

    def test_an_unbuilt_place_wears_the_roadmaps_dashed_language(self):
        route = [{"n": "1", "title": "a", "sentence": "", "gate": "",
                  "places": [{"name": "Ashfall Caverns", "note": ""}]}]
        page = self.page(self.world(), route)
        self.assertIn('<div class="place unbuilt">', page)
        self.assertIn("does not exist in the game yet", page)
        self.assertIn("nothing to derive until the place exists", page)

    def test_a_revisit_claims_nothing_about_the_game(self):
        """"Nothing here changes on a revisit" would be a claim about the
        GAME and can be false; a story flag can move an NPC. What is true is
        about this page."""
        route = [{"n": "1", "title": "a", "sentence": "", "gate": "",
                  "places": [{"name": "A", "note": ""}]},
                 {"n": "2", "title": "b", "sentence": "", "gate": "",
                  "places": [{"name": "A", "note": ""}]}]
        page = self.page(self.world(), route)
        self.assertIn("nothing new here to derive for a second visit", page)
        self.assertNotIn("nothing here changes", page)

    def test_a_place_with_no_drawn_map_states_the_absence(self):
        page = self.page(self.world(), self.on_route())
        self.assertIn("Map not drawn", page)
        self.assertIn("Everything else about this place is unaffected", page)

    def test_trainers_are_labelled_with_the_order_they_are_actually_in(self):
        """Position is derivable; the order a player walks past them is not."""
        maps = self.world()
        maps[0]["trainers"] = [{"x": 1, "y": 9, "script": "sB"},
                               {"x": 1, "y": 1, "script": "sA"}]
        maps[0]["scripts"] = {"sA": "TRAINER_A", "sB": "TRAINER_B"}
        site = self.site(maps, self.on_route())
        site.trainers = {"TRAINER_A": {"const": "TRAINER_A", "name": "Ann",
                                       "party": [], "items": [], "class": ""},
                         "TRAINER_B": {"const": "TRAINER_B", "name": "Bob",
                                       "party": [], "items": [], "class": ""}}
        site.build_thread()
        page = (self.tmp / "out/thread.html").read_text(encoding="utf-8")
        self.assertIn("in reading order, top-left first", page)
        self.assertNotIn("in the order you meet them", page)
        self.assertLess(page.index("Ann"), page.index("Bob"))


class CuratedNoteTests(unittest.TestCase):
    """Track C2. Prose a human wrote about a species or a place, read from
    the shape the design doc already keeps it in, and never mixed in with
    the derived data it sits above."""

    ART = """\
# Art

## Species art briefs — the canonical description travels with every generation

**Rule: every species carries ONE canonical brief.**

### Alphamon (SPECIES_ALPHAMON, 1524)

**Drawn-content target: 1,200-1,500 px². Currently 2,408 — REDRAW PENDING.**

> A small quadruped with a seed on its back.
> Pale cream coat, two nub horns.

### Betamon (stage 2, Grass/Poison)

> A bipedal adolescent frozen mid-squat.

### The line, designed back-to-front

Prose about the design of the line, with no blockquote, which is the author
talking to themselves rather than about an animal.

### Gammamon (SPECIES_NOT_IN_THIS_TREE)

> A creature this game does not have.
"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def briefs(self):
        return md.parse_species_briefs(
            md.find_section(md.split_sections(self.ART), "art brief", deep=True))

    def site(self, design):
        fork = dict(BuildHealthTests.EMPTY, species={
            "SPECIES_ALPHAMON": dict(
                {"const": "SPECIES_ALPHAMON", "name": "Alphamon", "order": 0,
                 "types": ["TYPE_GRASS"]},
                **{k: 50 for k in ("baseHP", "baseAttack", "baseDefense",
                                   "baseSpAttack", "baseSpDefense",
                                   "baseSpeed")}),
            "SPECIES_BETAMON": {"const": "SPECIES_BETAMON", "name": "Betamon",
                                "order": 1, "types": ["TYPE_GRASS"]}})
        site = md.Site(fork, dict(BuildHealthTests.EMPTY),
                       self.tmp / "fork", self.tmp / "out", "tiny",
                       lambda m: None, "expansion/1.9.4", health={})
        site.design = design
        return site

    # -- reading ------------------------------------------------------------

    def test_only_the_blockquote_is_the_brief(self):
        """The rest of a brief's section is pixel targets and REDRAW
        PENDING -- the author talking to themselves, not about the animal."""
        got = {b["name"]: b["text"] for b in self.briefs()}
        self.assertEqual(got["Alphamon"],
                         "A small quadruped with a seed on its back. "
                         "Pale cream coat, two nub horns.")
        self.assertNotIn("REDRAW", got["Alphamon"])
        self.assertNotIn("The line, designed back-to-front", got)

    def test_a_heading_names_its_constant_or_it_does_not(self):
        got = {b["name"]: b["const"] for b in self.briefs()}
        self.assertEqual(got["Alphamon"], "SPECIES_ALPHAMON")
        self.assertIsNone(got["Betamon"])

    # -- attaching ----------------------------------------------------------

    def test_a_brief_matches_by_constant_then_by_name(self):
        notes = self.site({"briefs": self.briefs()}).species_notes()
        self.assertIn("SPECIES_ALPHAMON", notes)       # by its constant
        self.assertIn("SPECIES_BETAMON", notes)        # by its name
        self.assertEqual(len(notes), 2)                # and Gammamon by neither

    def test_the_species_page_puts_the_note_above_the_data(self):
        site = self.site({"briefs": self.briefs()})
        site.build_species_pages()
        page = (self.tmp / "out/pokemon/alphamon.html").read_text(encoding="utf-8")
        self.assertIn("From the design doc, not from the game", page)
        self.assertIn("a seed on its back", page)
        self.assertLess(page.index("a seed on its back"), page.index("Base stats"))

    def test_a_place_keeps_the_sentence_the_route_gave_it(self):
        route = [{"n": "1", "title": "a", "sentence": "", "gate": "",
                  "places": [{"name": "Alpha Town", "note": "two houses."}]},
                 {"n": "2", "title": "b", "sentence": "", "gate": "",
                  "places": [{"name": "Alpha Town", "note": "written twice."}]}]
        site = self.site({"route": route})
        site.maps = {"MAP_ALPHA_TOWN": {"id": "MAP_ALPHA_TOWN"}}
        site.maps_ordered = [site.maps["MAP_ALPHA_TOWN"]]
        notes = site.place_notes()
        # The first mention wins: a revisit does not overwrite the note.
        self.assertEqual(notes["MAP_ALPHA_TOWN"], ("two houses.", "1"))

    def test_a_note_never_arrives_without_saying_it_was_written(self):
        site = self.site({"briefs": self.briefs()})
        self.assertIn("not from the game", site.authored_note("x"))


class GymTests(unittest.TestCase):
    """§12.3's first blocked item. The whole risk here is the DEFINITION:
    every convenient marker in the tree selects the wrong set of places, so
    each test below pins one place the parse must not be fooled by."""

    RUSTBORO = """\
RustboroCity_Gym_EventScript_Roxanne::
\ttrainerbattle_single TRAINER_ROXANNE_1, Text_Intro, Text_Defeat, RustboroCity_Gym_EventScript_RoxanneDefeated, NO_MUSIC
\tend

RustboroCity_Gym_EventScript_RoxanneDefeated::
\tmessage RustboroCity_Gym_Text_ReceivedStoneBadge
\tcall Common_EventScript_PlayGymBadgeFanfare
\tsetflag FLAG_DEFEATED_RUSTBORO_GYM
\tsetflag FLAG_BADGE01_GET
\tend

RustboroCity_Gym_Text_ReceivedStoneBadge:
\t.string "{PLAYER} received the STONE BADGE\\n"
\t.string "from ROXANNE.$"
"""

    # Petalburg fights and hands the badge over in ONE label, with no jump.
    PETALBURG = """\
PetalburgCity_Gym_EventScript_NormanBattle::
\tmsgbox PetalburgCity_Gym_Text_NormanIntro, MSGBOX_DEFAULT
\ttrainerbattle_no_intro TRAINER_NORMAN_1, PetalburgCity_Gym_Text_NormanDefeat
\tmessage PetalburgCity_Gym_Text_ReceivedBalanceBadge
\tsetflag FLAG_DEFEATED_PETALBURG_GYM
\tsetflag FLAG_BADGE05_GET
\tend

PetalburgCity_Gym_Text_ReceivedBalanceBadge:
\t.string "{PLAYER} received the BALANCE BADGE\\n"
\t.string "from NORMAN.$"
"""

    def gym(self, text):
        return md.parse_gym(text, md.parse_text_labels(text))

    def test_the_badge_is_what_makes_a_gym_a_gym(self):
        g = self.gym(self.RUSTBORO)
        self.assertIsNotNone(g)
        self.assertEqual(g["badge"], 1)
        self.assertEqual(g["leader"], "TRAINER_ROXANNE_1")
        self.assertEqual(g["defeated_flag"], "FLAG_DEFEATED_RUSTBORO_GYM")

    def test_a_room_that_merely_uses_the_gym_battle_scene_is_not_a_gym(self):
        """The stock engine puts MAP_BATTLE_SCENE_GYM on thirteen Battle
        Pyramid squares. The map header is a tempting definition and a
        wrong one; awarding a badge is the right one, and a Pyramid square
        awards nothing."""
        pyramid = ("BattlePyramidSquare01_EventScript_Trainer::\n"
                   "\ttrainerbattle_single TRAINER_SOMEONE, T1, T2\n"
                   "\tend\n")
        self.assertIsNone(self.gym(pyramid))

    def test_a_gyms_other_floor_is_not_a_second_gym(self):
        """Lavaridge and Sootopolis are two maps each; only the floor that
        awards the badge is the gym, so the badge is never double-counted."""
        b1f = ("LavaridgeTown_Gym_B1F_EventScript_Cook::\n"
               "\ttrainerbattle_single TRAINER_COOK, T1, T2\n"
               "\tend\n")
        self.assertIsNone(self.gym(b1f))

    def test_the_leader_is_found_when_battle_and_award_share_a_label(self):
        g = self.gym(self.PETALBURG)
        self.assertEqual(g["badge"], 5)
        self.assertEqual(g["leader"], "TRAINER_NORMAN_1")

    def test_the_badge_name_is_lifted_from_the_game_or_left_out(self):
        self.assertEqual(self.gym(self.RUSTBORO)["badge_name"], "Stone Badge")
        self.assertEqual(self.gym(self.PETALBURG)["badge_name"],
                         "Balance Badge")
        # No table in the tree holds badge names, so a gym that congratulates
        # you in some other phrasing gets no name rather than a guessed one.
        odd = self.RUSTBORO.replace("received the STONE BADGE",
                                    "are hereby certified")
        self.assertIsNone(self.gym(odd)["badge_name"])

    def test_a_leader_that_cannot_be_traced_is_absent_not_guessed(self):
        orphan = ("Somewhere_EventScript_Award::\n"
                  "\tsetflag FLAG_BADGE03_GET\n"
                  "\tend\n")
        g = self.gym(orphan)
        self.assertEqual(g["badge"], 3)
        self.assertIsNone(g["leader"])

    # -- what a place reads about your progress ---------------------------

    def test_progress_checks_read_tests_and_never_the_setting(self):
        text = ("Route104_EventScript_Florist::\n"
                "\tgoto_if_unset FLAG_BADGE03_GET, Route104_EventScript_Hide\n"
                "\tcall_if_set FLAG_DEFEATED_RUSTBORO_GYM, Route104_Thing\n"
                "\tsetflag FLAG_BADGE07_GET\n")
        got = md.parse_progress_checks(text)
        self.assertIn("FLAG_BADGE03_GET", got)
        self.assertIn("FLAG_DEFEATED_RUSTBORO_GYM", got)
        # Setting a flag is not reading one: only tests are checks.
        self.assertNotIn("FLAG_BADGE07_GET", got)

    def test_badge_number_reads_the_flag_and_nothing_else(self):
        self.assertEqual(md.badge_number("FLAG_BADGE01_GET"), 1)
        self.assertEqual(md.badge_number("FLAG_BADGE08_GET"), 8)
        self.assertIsNone(md.badge_number("FLAG_DEFEATED_RUSTBORO_GYM"))


class BackupMarkerTests(unittest.TestCase):
    """§9.7 and §12.4's first parked item. The dashboard could not tell an
    unexported edit from a tree restored out of the very same patch. These
    are the two cases, and the third where there is nothing to check with."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fork = self.tmp / "fork"
        (self.fork / "src").mkdir(parents=True)

    def owned(self, rel, text):
        p = self.fork / rel
        p.write_text(text, encoding="utf-8")
        return {"file": rel, "mtime": 1_700_000_000}

    def digest(self, text):
        return hashlib.sha256(text.encode()).hexdigest()

    def test_a_restored_tree_is_not_reported_as_unsaved_work(self):
        """Same bytes the export proved, newer clock. This is the case that
        made the old dashboard hedge, and it is not a warning at all."""
        rec = self.owned("src/thing.c", "the exported content")
        marker = {"src/thing.c": self.digest("the exported content")}
        self.assertEqual(md.unexported(self.fork, marker, [rec]), [])

    def test_a_real_edit_is_reported_by_name(self):
        rec = self.owned("src/thing.c", "content with an edit in it")
        marker = {"src/thing.c": self.digest("the exported content")}
        moved = md.unexported(self.fork, marker, [rec])
        self.assertEqual([r["file"] for r in moved], ["src/thing.c"])

    def test_with_no_marker_it_declines_to_answer(self):
        """None, not []. An empty list would read as "nothing has moved",
        which is a claim this cannot make without digests to check."""
        rec = self.owned("src/thing.c", "whatever")
        self.assertIsNone(md.unexported(self.fork, {}, [rec]))

    def test_the_dashboard_says_which_of_the_two_it_is(self):
        rec = self.owned("src/thing.c", "edited since the export")
        health = {
            "now": 1_700_000_000,
            "patch": {"name": "tiny.patch", "size": 10, "mtime": 1_600_000_000},
            "source": {"own": [rec], "capped": False},
            "backed_up": {"src/thing.c"},
            "marker": {"src/thing.c": self.digest("the exported content")},
            "fork_root": self.fork,
        }
        fork = dict(BuildHealthTests.EMPTY, species={})
        site = md.Site(fork, dict(BuildHealthTests.EMPTY), self.fork,
                       self.tmp / "out", "tiny", lambda m: None,
                       "expansion/1.9.4", health=health)
        page = "\n".join(site.health_section())
        self.assertIn("has changed since the backup was verified", page)
        self.assertNotIn("timestamps cannot tell those apart", page)


class DevLogDeletionTests(unittest.TestCase):
    """§12.4's second parked item. A stock entry deleted outright differed
    from stock at no point while it existed, so it appeared in no snapshot's
    list and only the category total ever recorded that it went."""

    EMPTY = dict(BuildHealthTests.EMPTY)

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def species(self, const, name):
        return {"const": const, "name": name, "order": 0,
                "types": ["TYPE_GRASS"], "baseHP": 45}

    def site(self, fork_species, engine_species):
        f = dict(self.EMPTY, species={s["const"]: s for s in fork_species})
        e = dict(self.EMPTY, species={s["const"]: s for s in engine_species})
        return md.Site(f, e, self.tmp / "fork", self.tmp / "out", "tiny",
                       lambda m: None, "expansion/1.9.4",
                       health={"now": 1_700_000_000})

    def test_a_deleted_stock_entry_is_named_and_not_merely_counted(self):
        stock = [self.species("SPECIES_A", "Ay"),
                 self.species("SPECIES_B", "Bee")]
        before = self.site(stock, stock).devlog_entry()
        after = self.site([self.species("SPECIES_A", "Ay")],
                          stock).devlog_entry()
        d = md.devlog_delta(before, after)["species"]
        self.assertEqual(d["deleted"], ["SPECIES_B"])
        # The old readings all stay empty -- this is exactly the case none
        # of them could see, which is why the total used to be the only clue.
        self.assertEqual((d["added"], d["edited"], d["gone"]), ([], [], []))
        self.assertEqual((d["from"], d["to"]), (2, 1))

    def test_a_snapshot_from_before_this_existed_is_not_read_as_empty(self):
        """The trap: an old record has no `removed` key. Treating that as
        an empty list would credit this build with every deletion the game
        ever made."""
        stock = [self.species("SPECIES_A", "Ay"),
                 self.species("SPECIES_B", "Bee")]
        after = self.site([self.species("SPECIES_A", "Ay")],
                          stock).devlog_entry()
        old = json.loads(json.dumps(after))
        old["categories"]["species"].pop("removed")
        self.assertEqual(md.devlog_delta(old, after).get("species", {})
                         .get("deleted", []), [])

    def test_the_page_names_the_cut_entry(self):
        stock = [self.species("SPECIES_A", "Ay"),
                 self.species("SPECIES_B", "Bee")]
        before = self.site(stock, stock).devlog_entry()
        site = self.site([self.species("SPECIES_A", "Ay")], stock)
        after = site.devlog_entry()
        before["date"], before["at"] = "2026-01-01 09:00", 1_699_000_000
        site.history, site.entry = [before, after], after
        site.build_devlog()
        page = (self.tmp / "out/devlog.html").read_text(encoding="utf-8")
        self.assertIn("Bee", page)
        self.assertIn("stock entry removed from the tree", page)
        # It has no page, so it must not be linked to one.
        self.assertNotIn('href="pokemon/bee.html"', page)


class PublishModeTests(unittest.TestCase):
    """Track D1. Every test here is a PAIR: the same tree, rendered twice,
    asserting that a builder-facing fact is present in one and absent in the
    other. A one-sided test would pass just as well against a generator that
    had quietly stopped producing the fact at all, which is the failure this
    feature is most likely to have."""

    EMPTY = dict(BuildHealthTests.EMPTY)

    HEALTH = {
        "now": 1_700_000_000,
        "title": "POKEMON TINY",
        "rom": {"name": "tiny.gba", "size": 1 << 24, "mtime": 1_699_000_000},
        "patch": {"name": "tiny.patch", "size": 4096, "mtime": 1_699_000_000},
        "git": {"sha": "abc1234", "branch": "main", "dirty": 0,
                "epoch": 1_699_000_000, "subject": "a commit"},
        "checks": {"specs": 4, "runnable": 4, "asserts": 40,
                   "missing_states": []},
        "source": {"own": [], "capped": False},
        "backed_up": set(),
    }

    DESIGN = {
        "found": True,
        "pitch": "A hack about a thing.",
        "loop": "Read, pick, climb.",
        "phase": "building",
        "entered": "2026-01-02",
        "decisions": [["2026-01-03", "The level cap is the body"]],
        "next": ["Draw the second gym"],
        "questions": ["Does the bar read as a bar?"],
        "cuts": [["2026-01-04", "Fishing", "Not the point", "no"]],
        "slices": [
            {"n": "1", "title": "the gym door", "status": "done",
             "status_raw": "**done** 2026-01-05", "soul": "a door that says no",
             "failure_condition": "", "fake": "", "do_not_fake": ""},
            {"n": "2", "title": "the bar that fills", "status": "building",
             "status_raw": "**building** since 2026-01-06",
             "soul": "you know how much you owe",
             "failure_condition": "", "fake": "", "do_not_fake": ""},
            {"n": "3", "title": "the long climb", "status": "planned",
             "status_raw": "**planned**", "soul": "the ceiling moves",
             "failure_condition": "", "fake": "", "do_not_fake": ""},
            {"n": "4", "title": "the fishing rod", "status": "cut",
             "status_raw": "**cut** 2026-01-07", "soul": "never mind",
             "failure_condition": "", "fake": "", "do_not_fake": ""},
        ],
        "route": [], "briefs": [], "questions_inline": "", "archetype": "",
        "name": "tiny",
    }

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def site(self, publish, design=None, history=None):
        sp = {"const": "SPECIES_NEWMON", "name": "Newmon", "order": 0,
              "types": ["TYPE_GRASS"], "baseHP": 45}
        fork = dict(self.EMPTY, species={"SPECIES_NEWMON": sp})
        out = self.tmp / ("publish" if publish else "dex")
        site = md.Site(fork, self.EMPTY, self.tmp / "fork", out, "tiny",
                       lambda m: None, "expansion/1.9.4",
                       health=dict(self.HEALTH), publish=publish)
        site.design = dict(self.DESIGN if design is None else design)
        site.history = history or []
        site.entry = site.devlog_entry()
        return site

    def rendered(self, site, name):
        return (site.out / name).read_text(encoding="utf-8")

    def both(self, build, name, design=None, history=None):
        """Render one page in both modes. Returns (private, publish)."""
        out = []
        for publish in (False, True):
            site = self.site(publish, design=design, history=history)
            getattr(site, build)()
            out.append(self.rendered(site, name))
        return out

    # -- the home page ------------------------------------------------------

    def test_the_instrument_panel_is_the_whole_of_what_publish_drops(self):
        priv, pub = self.both("build_dashboard", "index.html")
        for builder_only in ("Build health", "tiny.gba", "abc1234",
                             "assertions", "Since the last build",
                             "finished or not", "meant to happen next",
                             "Draw the second gym"):
            self.assertIn(builder_only, priv)
            self.assertNotIn(builder_only, pub)

    def test_what_the_game_contains_is_in_both_because_it_is_the_game(self):
        priv, pub = self.both("build_dashboard", "index.html")
        for shared in ("Species", "1 new", "expansion/1.9.4"):
            self.assertIn(shared, priv)
            self.assertIn(shared, pub)

    def test_the_publish_home_leads_with_the_pitch_and_says_where_to_go(self):
        _priv, pub = self.both("build_dashboard", "index.html")
        self.assertIn("A hack about a thing.", pub)
        self.assertIn("Read, pick, climb.", pub)
        self.assertIn('href="thread.html"', pub)

    def test_a_publish_home_with_no_design_doc_still_renders(self):
        site = self.site(True, design={"found": False})
        site.build_dashboard()
        page = self.rendered(site, "index.html")
        self.assertIn("What's in it", page)
        self.assertIn("Species", page)

    # -- what is unfinished -------------------------------------------------

    def test_how_much_is_unfinished_is_a_fact_about_the_workbench(self):
        """The species has no sprite in either render. Only the builder's
        one counts them, because "3 without art" answers a question about
        the work and not about the game."""
        priv, pub = self.both("build_dashboard", "index.html")
        self.assertIn("without art", priv)
        self.assertNotIn("without art", pub)

    # -- the nav ------------------------------------------------------------

    def test_the_bar_renames_two_destinations_and_moves_neither(self):
        priv, pub = self.both("build_types", "types.html")
        self.assertIn(">Dev log<", priv)
        self.assertIn(">Roadmap<", priv)
        self.assertIn(">Patch notes<", pub)
        self.assertIn(">What&#x27;s next<", pub)
        # Same files in both, so every cross-link in the body stays right.
        for href in ('href="devlog.html"', 'href="roadmap.html"'):
            self.assertIn(href, priv)
            self.assertIn(href, pub)

    # -- what's next --------------------------------------------------------

    def test_the_teaser_shows_what_is_coming_and_never_its_status(self):
        _priv, pub = self.both("build_roadmap", "roadmap.html")
        self.assertIn("the bar that fills", pub)      # building
        self.assertIn("the long climb", pub)          # planned
        self.assertIn("you know how much you owe", pub)
        self.assertNotIn("the gym door", pub)         # done: already shipped
        self.assertNotIn("the fishing rod", pub)      # cut: not a promise
        for ledger in ("2026-01-05", "2026-01-06", "2026-01-07", "building",
                       "planned", "Slice", "Open questions", "Next actions",
                       "Cut, on purpose"):
            self.assertNotIn(ledger, pub)

    def test_the_builders_roadmap_keeps_every_one_of_those(self):
        priv, _pub = self.both("build_roadmap", "roadmap.html")
        for ledger in ("the gym door", "the fishing rod", "Slice plan",
                       "planned", "Open questions", "Next actions",
                       "Cut, on purpose", "2026-01-04"):
            self.assertIn(ledger, priv)

    def test_a_slice_the_doc_argues_with_is_never_advertised(self):
        """Slice 2 is marked building but slice 3 below it is marked done,
        and the plan's rule is that slices land in order -- so the doc's own
        evidence says slice 2 has probably shipped. The builder's page prints
        both the slice and the doubt; the published one cannot print doubt
        without printing status, so it withholds the promise."""
        design = dict(self.DESIGN)
        design["slices"] = [dict(s) for s in design["slices"]]
        design["slices"][2]["status"] = "done"      # the long climb landed
        priv, pub = self.both("build_roadmap", "roadmap.html", design=design)
        self.assertIn("the bar that fills", priv)
        self.assertIn("One of the two is out of date", priv)
        self.assertNotIn("the bar that fills", pub)
        self.assertIn("Nothing here is promised", pub)

    def test_a_plan_with_nothing_left_in_it_promises_nothing(self):
        design = dict(self.DESIGN)
        design["slices"] = [s for s in design["slices"]
                            if s["status"] not in ("planned", "building")]
        site = self.site(True, design=design)
        site.build_roadmap()
        page = self.rendered(site, "roadmap.html")
        self.assertIn("Nothing here is promised", page)
        self.assertNotIn("the gym door", page)

    def test_no_design_doc_at_all_is_the_same_empty_page(self):
        site = self.site(True, design={"found": False})
        site.build_roadmap()
        self.assertIn("Nothing here is promised",
                      self.rendered(site, "roadmap.html"))

    # -- patch notes --------------------------------------------------------

    def baseline(self):
        """A recorded build from before this game had Newmon in it."""
        was = json.loads(json.dumps(self.site(False).devlog_entry()))
        was["date"] = "2026-01-01 09:00"
        was["at"] = 1_699_000_000
        was["categories"]["species"]["entries"].pop("SPECIES_NEWMON", None)
        was["categories"]["species"]["new"] = 0
        return was

    def history_of_two(self):
        """Two recorded builds, the second of which added Newmon -- so there
        is a real credited change to check survives publishing. A single
        entry would not do: the first record is a baseline and credits
        nothing to anybody."""
        then = self.baseline()
        now = json.loads(json.dumps(self.site(False).devlog_entry()))
        now["date"], now["at"] = "2026-01-02 09:00", 1_699_500_000
        now["rom"] = {"size": 1 << 23}
        now["checks"] = {"asserts": 30, "specs": 3}
        now["git"] = {"sha": "def5678", "subject": "wired the second gym"}
        return [then, now]

    def test_patch_notes_keep_the_change_and_drop_the_three_numbers(self):
        hist = self.history_of_two()
        priv, pub = self.both("build_devlog", "devlog.html", history=hist)
        # What moved is the point of the page, and survives publishing.
        for kept in ("2026-01-02 09:00", "Newmon"):
            self.assertIn(kept, priv)
            self.assertIn(kept, pub)
        # The commit, the byte cost and the assertion count do not.
        for dropped in ("def5678", "wired the second gym", "ROM ", "assertions",
                        "buildmeta"):
            self.assertIn(dropped, priv)
            self.assertNotIn(dropped, pub)

    def test_patch_notes_never_show_the_unbuilt_present(self):
        """The tree has a species the last recorded build did not. That is
        work in progress -- the builder's log leads with it, and a released
        page must not mention it at all."""
        priv, pub = self.both("build_devlog", "devlog.html",
                              history=[self.baseline()])
        self.assertIn("Since the last recorded build", priv)
        self.assertNotIn("Since the last recorded build", pub)
        self.assertNotIn("next green build", pub)

    def test_with_no_history_each_mode_says_so_in_its_own_words(self):
        priv, pub = self.both("build_devlog", "devlog.html", history=[])
        self.assertIn("No build has been recorded yet", priv)
        self.assertIn("nothing to report changed", pub)
        self.assertIn("Patch notes", pub)

    # -- the changes page ---------------------------------------------------

    def test_the_pitch_survives_publishing_and_the_dated_ledger_does_not(self):
        priv, pub = self.both("build_changes", "changes.html")
        self.assertIn("A hack about a thing.", priv)
        self.assertIn("A hack about a thing.", pub)
        self.assertIn("The level cap is the body", priv)
        self.assertNotIn("The level cap is the body", pub)
        self.assertNotIn("2026-01-03", pub)

    # -- the command --------------------------------------------------------

    def test_publishing_and_recording_together_is_refused(self):
        argv = ["make_dex.py", "--publish", "--record"]
        with unittest.mock.patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit) as caught:
                md.main()
        self.assertIn("publish on purpose", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
