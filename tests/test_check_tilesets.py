#!/usr/bin/env python3
"""Unit tests for check_tilesets.py -- the tileset contract-check.

Every check gets BOTH directions: a tileset that is fine, and the same tileset
made not-fine by exactly one thing. A contract-check whose failure direction was
never executed is a check that always says yes, and this one exists precisely
because the failure it looks for produces a perfectly rendered screen.

The fixture is a synthetic mini-tree in a tempdir with two tilesets and one
layout pairing them, so every parser runs for real -- the makefile rule parsing,
the INCBIN mapping and the layouts.json pairing included.

    python3 -m unittest discover -s tests -v
"""

import json
import pathlib
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import check_tilesets as ct  # noqa: E402


FIELDMAP_H = "#define NUM_TILES_IN_PRIMARY 512\n#define NUM_TILES_TOTAL 1024\n"

RULES = """TILESETGFXDIR := data/tilesets

$(TILESETGFXDIR)/primary/base/tiles.4bpp: %.4bpp: %.png
\t$(GFX) $< $@ -num_tiles {prim} -Wnum_tiles

$(TILESETGFXDIR)/secondary/room/tiles.4bpp: %.4bpp: %.png
\t$(GFX) $< $@ -num_tiles {sec} -Wnum_tiles
"""

HEADERS = """
const struct Tileset gTileset_Base =
{
    .metatiles = gMetatiles_Base,
    .metatileAttributes = gMetatileAttributes_Base,
};

const struct Tileset gTileset_Room =
{
    .metatiles = gMetatiles_Room,
    .metatileAttributes = gMetatileAttributes_Room,
};
"""

INCBINS = (
    'const u16 gMetatiles_Base[] = INCBIN_U16("data/tilesets/primary/base/metatiles.bin");\n'
    'const u16 gMetatiles_Room[] = INCBIN_U16("data/tilesets/secondary/room/metatiles.bin");\n'
)


def metatile(tiles):
    """One metatile: four bottom-layer entries, four transparent top ones."""
    return struct.pack("<8H", *tiles, 0, 0, 0, 0)


def build_tree(root, *, prim_tiles=64, sec_tiles=32, room_refs=(512, 513, 514, 515),
               base_refs=(0, 1, 2, 3), attr_short=False, paired=True):
    (root / "include").mkdir(parents=True)
    (root / "src/data/tilesets").mkdir(parents=True)
    (root / "data/tilesets/primary/base").mkdir(parents=True)
    (root / "data/tilesets/secondary/room").mkdir(parents=True)
    (root / "data/layouts").mkdir(parents=True)

    (root / "include/fieldmap.h").write_text(FIELDMAP_H)
    (root / "graphics_file_rules.mk").write_text(RULES.format(prim=prim_tiles, sec=sec_tiles))
    (root / "src/data/tilesets/headers.h").write_text(HEADERS)
    (root / "src/data/tilesets/metatiles.h").write_text(INCBINS)

    for sub, refs in (("primary/base", base_refs), ("secondary/room", room_refs)):
        d = root / "data/tilesets" / sub
        (d / "metatiles.bin").write_bytes(metatile(refs))
        n = 1 if not attr_short or sub.startswith("primary") else 0
        (d / "metatile_attributes.bin").write_bytes(b"\x00\x00" * n)

    (root / "data/layouts/layouts.json").write_text(json.dumps({"layouts": [
        {"id": "LAYOUT_X",
         "primary_tileset": "gTileset_Base" if paired else "gTileset_Other",
         "secondary_tileset": "gTileset_Room"}]}))
    return root


class CheckTilesetsTests(unittest.TestCase):
    def tree(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return build_tree(pathlib.Path(tmp.name), **kw)

    def kinds(self, root):
        return sorted(k for k, _, _ in ct.scan(root))

    # ------------------------------------------------ the headline check

    def test_clean_tree_has_no_findings(self):
        self.assertEqual(self.kinds(self.tree()), [])

    def test_secondary_over_reference_is_caught(self):
        """The docs 77 §7.1b case: ships N, references past N."""
        root = self.tree(sec_tiles=2, room_refs=(512, 513, 514, 515))
        self.assertIn("over-reference", self.kinds(root))
        msg = [m for k, _, m in ct.scan(root) if k == "over-reference"][0]
        self.assertIn("ships 2 tiles", msg)
        self.assertIn("tile 3", msg)      # 515 - 512

    def test_boundary_is_exact_not_off_by_one(self):
        """Referencing the LAST shipped tile is legal; one past it is not.

        The whole tool is an off-by-one detector, so its own boundary is the
        thing most worth pinning.
        """
        self.assertEqual(self.kinds(self.tree(sec_tiles=4, room_refs=(512, 513, 514, 515))), [])
        self.assertIn("over-reference",
                      self.kinds(self.tree(sec_tiles=3, room_refs=(512, 513, 514, 515))))

    # ------------------------------------------------ the primary half

    def test_primary_over_reference_uses_the_actual_pairing(self):
        root = self.tree(prim_tiles=4, room_refs=(0, 1, 2, 9))
        self.assertIn("over-reference-primary", self.kinds(root))

    def test_primary_over_reference_is_silent_when_nothing_pairs_them(self):
        """A pairing that does not exist cannot be judged, and guessing one
        would invent findings about tilesets that never meet."""
        root = self.tree(prim_tiles=4, room_refs=(0, 1, 2, 9), paired=False)
        self.assertNotIn("over-reference-primary", self.kinds(root))

    def test_primary_drawing_from_secondary_range_is_caught(self):
        root = self.tree(base_refs=(0, 1, 2, 600))
        self.assertIn("primary-uses-secondary", self.kinds(root))

    # ------------------------------------------------ structural

    def test_attribute_count_mismatch_is_caught(self):
        self.assertIn("count-mismatch", self.kinds(self.tree(attr_short=True)))

    def test_missing_rules_file_is_a_hard_stop(self):
        root = self.tree()
        (root / "graphics_file_rules.mk").unlink()
        with self.assertRaises(SystemExit):
            ct.scan(root)

    def test_rules_with_no_num_tiles_is_a_hard_stop(self):
        """An empty parse must refuse, not report a clean tree -- docs 73's
        rule that an empty result from a filtered command is not a result."""
        root = self.tree()
        (root / "graphics_file_rules.mk").write_text("TILESETGFXDIR := data/tilesets\n")
        with self.assertRaises(SystemExit):
            ct.scan(root)

    # ------------------------------------------------ the real trees

    def test_the_pin_has_exactly_the_four_known_over_references(self):
        """Real-data coverage, and a regression pin on a finding.

        These four are upstream's, recorded in docs 77 §7.1b. If the pin moves
        and the set changes, this test is the thing that says so.
        """
        engine = pathlib.Path(__file__).resolve().parents[1] / "engine"
        if not engine.is_dir():
            self.skipTest("pinned engine clone not present (gitignored)")
        labels = sorted(label for k, label, _ in ct.scan(engine) if k == "over-reference")
        self.assertEqual(labels, [
            "gTileset_BattleFrontierOutsideEast",
            "gTileset_Lavaridge",
            "gTileset_Petalburg",
            "gTileset_PokemonSchool",
        ])

    def test_the_hack_no_longer_over_references_the_school_tileset(self):
        """docs 77 fixed this one by raising -num_tiles past what it uses."""
        hack = pathlib.Path(__file__).resolve().parents[1] / "hacks/reps"
        if not hack.is_dir():
            self.skipTest("reps fork not present (gitignored)")
        labels = [label for k, label, _ in ct.scan(hack) if k == "over-reference"]
        self.assertNotIn("gTileset_PokemonSchool", labels)


if __name__ == "__main__":
    unittest.main()
