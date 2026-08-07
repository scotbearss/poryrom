#!/usr/bin/env python3
"""Unit tests for check_behaviors.py -- the metatile-behavior census.

Every axis gets BOTH directions: an id that is genuinely free, and an id made
un-free by exactly one thing (a name in code, a range that covers it, a
tile-flag row, a byte in a tileset's attribute table). A census whose
"not free" direction was never executed would be a tool that always says yes,
which is worse than no tool -- reclaiming a live behavior id is silent, and
the whole point of this thing is that a grep cannot see the binary half.

The fixture is a synthetic mini-tree in a tempdir with an eight-id behavior
space, so every parser runs for real -- the C parsing included, so a format
drift in the real engine shows up here as a loud sys.exit rather than a quiet
wrong answer. Real-data coverage is separate: the tool has been run over the
pinned engine and over the reps fork, and the two agree exactly (2026-08-05).

    python3 -m unittest discover -s tests -v
"""

import pathlib
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import check_behaviors as cb  # noqa: E402


# --------------------------------------------------------------- fixture

BEHAVIORS_H = """
#define MB_NORMAL 0x00
#define MB_TALL_GRASS 0x01
#define MB_WATER_A 0x02
#define MB_WATER_B 0x03
#define MB_WATER_C 0x04
#define MB_UNUSED_05 0x05
#define MB_UNUSED_06 0x06
#define MB_UNUSED_07 0x07
#define NUM_METATILE_BEHAVIORS 0x08
#define MB_INVALID   0xFF
"""

GLOBAL_FIELDMAP_H = """
#define MAPGRID_METATILE_ID_MASK 0x03FF
#define METATILE_ATTR_BEHAVIOR_MASK 0x00FF
struct Tileset
{
    bool8 isCompressed;
    const u16 *metatiles;
    const u16 *metatileAttributes;
};
"""

FIELDMAP_H = "#define NUM_METATILES_IN_PRIMARY 512\n"

# MB_UNUSED_05 carries luggage; MB_TALL_GRASS is named by a predicate;
# MB_WATER_B is named by nothing but sits inside a tested range.
BEHAVIOR_C = """
static const u8 sTileBitAttributes[NUM_METATILE_BEHAVIORS] =
{
    [MB_NORMAL]      = TILE_FLAG_UNUSED,
    [MB_TALL_GRASS]  = TILE_FLAG_UNUSED | TILE_FLAG_HAS_ENCOUNTERS,
    [MB_UNUSED_05]   = TILE_FLAG_HAS_ENCOUNTERS,
};

bool8 MetatileBehavior_IsTallGrass(u8 metatileBehavior)
{
    if (metatileBehavior == MB_TALL_GRASS)
        return TRUE;
    return FALSE;
}

bool8 MetatileBehavior_IsAnyWater(u8 metatileBehavior)
{
    if (metatileBehavior >= MB_WATER_A && metatileBehavior <= MB_WATER_C)
        return TRUE;
    return FALSE;
}
"""

HEADERS_H = """
const struct Tileset gTileset_Fixture =
{
    .isCompressed = TRUE,
    .metatiles = gMetatiles_Fixture,
    .metatileAttributes = gMetatileAttributes_Fixture,
};
"""

METATILES_H = (
    'const u16 gMetatileAttributes_Fixture[] = '
    'INCBIN_U16("data/tilesets/primary/fixture/metatile_attributes.bin");\n'
)


def build_tree(root: pathlib.Path, *, tileset_behaviors=(0, 1), painted=(0,)):
    """A minimal pokeemerald-shaped tree the census can run over for real."""
    (root / "include/constants").mkdir(parents=True)
    (root / "src/data/tilesets").mkdir(parents=True)
    (root / "data/tilesets/primary/fixture").mkdir(parents=True)
    (root / "data/layouts/Fixture").mkdir(parents=True)

    (root / "include/constants/metatile_behaviors.h").write_text(BEHAVIORS_H)
    (root / "include/global.fieldmap.h").write_text(GLOBAL_FIELDMAP_H)
    (root / "include/fieldmap.h").write_text(FIELDMAP_H)
    (root / "src/metatile_behavior.c").write_text(BEHAVIOR_C)
    (root / "src/data/tilesets/headers.h").write_text(HEADERS_H)
    (root / "src/data/tilesets/metatiles.h").write_text(METATILES_H)

    ts = root / "data/tilesets/primary/fixture"
    (ts / "metatile_attributes.bin").write_bytes(
        b"".join(struct.pack("<H", b) for b in tileset_behaviors)
    )
    (ts / "metatiles.bin").write_bytes(b"\0" * (16 * len(tileset_behaviors)))

    lay = root / "data/layouts/Fixture"
    (lay / "map.bin").write_bytes(b"".join(struct.pack("<H", m) for m in painted))
    (lay / "border.bin").write_bytes(struct.pack("<H", 0))
    (root / "data/layouts/layouts.json").write_text(
        '{"layouts": [{"id": "LAYOUT_FIXTURE",'
        ' "primary_tileset": "gTileset_Fixture",'
        ' "secondary_tileset": "gTileset_Fixture",'
        ' "blockdata_filepath": "data/layouts/Fixture/map.bin",'
        ' "border_filepath": "data/layouts/Fixture/border.bin"}]}'
    )
    return root


class CensusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = build_tree(pathlib.Path(self.tmp.name))
        self.addCleanup(self.tmp.cleanup)

    def census(self, **kw):
        if kw:
            self.tmp.cleanup()
            self.tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self.tmp.cleanup)
            self.root = build_tree(pathlib.Path(self.tmp.name), **kw)
        return cb.census(self.root)

    def names(self, result, key="reclaimable"):
        return {e["name"] for e in result[key]}

    # ---------------------------------------------------------- both directions

    def test_a_clean_id_is_reclaimable(self):
        # MB_UNUSED_07: no code reference, no tile-flag row, not in any tileset.
        self.assertIn("MB_UNUSED_07", self.names(self.census()))

    def test_named_in_code_is_not_reclaimable(self):
        result = self.census()
        self.assertNotIn("MB_TALL_GRASS", self.names(result))
        self.assertTrue(result["by_id"][0x01]["code_refs"])

    def test_inside_a_tested_range_is_not_reclaimable(self):
        """The guard that stops this tool committing its own failure mode.

        MB_WATER_B is written nowhere -- only MB_WATER_A and MB_WATER_C are --
        but a predicate accepts it, so handing it back as free would give the
        new behavior a predicate that already says yes.
        """
        result = self.census()
        self.assertNotIn("MB_WATER_B", self.names(result))
        refs = result["by_id"][0x03]["code_refs"]
        self.assertTrue(any("inside range" in r for r in refs), refs)

    def test_tile_flag_row_is_luggage_not_a_reference(self):
        """A designator row disqualifies an id WITHOUT counting as a user.

        Both halves matter: MB_UNUSED_05 must be excluded (it would hand a wall
        wild encounters) but must not be reported as referenced by code, or the
        census would say the engine tests an id nothing tests.
        """
        result = self.census()
        entry = result["by_id"][0x05]
        self.assertNotIn("MB_UNUSED_05", self.names(result))
        self.assertEqual(entry["tile_flags"], "TILE_FLAG_HAS_ENCOUNTERS")
        self.assertEqual(entry["code_refs"], [])

    def test_declared_in_a_tileset_is_not_reclaimable(self):
        """The case no grep can see: a byte in a binary, zero C references."""
        clean = self.census()
        self.assertIn("MB_UNUSED_06", self.names(clean))
        dirty = self.census(tileset_behaviors=(0, 1, 6))
        self.assertNotIn("MB_UNUSED_06", self.names(dirty))
        self.assertEqual(dirty["by_id"][0x06]["declared_in"], ["gTileset_Fixture"])

    def test_painted_is_reported_and_border_counts(self):
        result = self.census(tileset_behaviors=(0, 6), painted=(1,))
        self.assertEqual(result["by_id"][0x06]["painted_in"], ["LAYOUT_FIXTURE"])
        # the border block is metatile 0, whose behavior is MB_NORMAL
        self.assertEqual(result["by_id"][0x00]["painted_in"], ["LAYOUT_FIXTURE"])

    def test_declared_but_unpainted_still_disqualifies(self):
        """A metatile does not stop existing because no map uses it today."""
        result = self.census(tileset_behaviors=(0, 1, 6), painted=(0,))
        self.assertEqual(result["by_id"][0x06]["painted_in"], [])
        self.assertNotIn("MB_UNUSED_06", self.names(result))

    # ---------------------------------------------------------- census totals

    def test_totals_and_full_space(self):
        result = self.census()
        self.assertEqual(result["defined"], 8)
        self.assertEqual(result["free_slots"], [])
        self.assertEqual(result["named_unused"], 3)

    def test_line_numbers_survive_blanking_the_flag_array(self):
        """Blanking sTileBitAttributes must not shift the lines after it."""
        result = self.census()
        ref = result["by_id"][0x01]["code_refs"][0]
        lineno = int(ref.rsplit(":", 1)[1])
        source = (self.root / "src/metatile_behavior.c").read_text().splitlines()
        self.assertIn("MB_TALL_GRASS", source[lineno - 1])

    # ---------------------------------------------------------- hard stops

    def test_unpaired_comparison_is_a_hard_stop(self):
        """A one-sided compare would make the tool guess. It must refuse."""
        path = self.root / "src/metatile_behavior.c"
        path.write_text(
            BEHAVIOR_C + "\nbool8 Loose(u8 b) { return b > MB_WATER_A; }\n"
        )
        with self.assertRaises(SystemExit) as ctx:
            cb.census(self.root)
        self.assertIn("outside a two-sided range", str(ctx.exception))

    def test_attribute_stride_guard(self):
        (self.root / "include/global.fieldmap.h").write_text(
            GLOBAL_FIELDMAP_H.replace("const u16 *metatileAttributes;",
                                      "const u32 *metatileAttributes;")
        )
        with self.assertRaises(SystemExit) as ctx:
            cb.census(self.root)
        self.assertIn("2-byte attribute stride", str(ctx.exception))

    def test_attribute_length_mismatch_guard(self):
        ts = self.root / "data/tilesets/primary/fixture"
        (ts / "metatiles.bin").write_bytes(b"\0" * 16 * 9)
        with self.assertRaises(SystemExit) as ctx:
            cb.census(self.root)
        self.assertIn("attribute format changed", str(ctx.exception))

    def test_missing_source_is_a_hard_stop(self):
        (self.root / "include/constants/metatile_behaviors.h").unlink()
        with self.assertRaises(SystemExit):
            cb.census(self.root)


if __name__ == "__main__":
    unittest.main()
