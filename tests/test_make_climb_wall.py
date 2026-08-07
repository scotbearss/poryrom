#!/usr/bin/env python3
"""Unit tests for make_climb_wall.py -- the climbing wall's generator.

Weighted toward the three things that actually cost build cycles when this was
written (docs 77), because a test that only covers what went right is a test
written from the happy path afterwards:

  1. WHERE THE NEW TILES LAND. The first version appended at the DECLARED tile
     count and landed underneath four metatiles already in use. The rule is
     that the first free tile comes from what is REFERENCED.
  2. IDEMPOTENCE. Every write asserts the END STATE, so a second run is a
     no-op rather than a second append (docs 73).
  3. THE DERIVATION IS LOSSLESS. The wall art is the room's own wall with holds
     stamped on it: same palette, same tiles underneath, nothing invented.

Plus both directions on every refusal, since a generator that cannot say no is
one that will happily write nonsense into a gitignored tree nobody diffs.

    python3 -m unittest discover -s tests -v
"""

import json
import pathlib
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import make_climb_wall as mcw  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


def entry(tile, pal=6, hflip=0):
    return (tile & 0x3FF) | (hflip << 10) | ((pal & 0xF) << 12)


class HelperTests(unittest.TestCase):
    """The pure logic, which is where the bugs were."""

    def tree(self, meta_rows, *, num_tiles=278):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        (root / mcw.TILESET_DIR).mkdir(parents=True)
        (root / mcw.TILESET_DIR / "metatiles.bin").write_bytes(
            b"".join(struct.pack("<8H", *row) for row in meta_rows))
        (root / "graphics_file_rules.mk").write_text(
            f"{mcw.TILESET_RULE}: %.4bpp: %.png\n\t$(GFX) $< $@ -num_tiles {num_tiles} -Wnum_tiles\n")
        return root

    # ---------------------------------------------------------- the big one

    def test_highest_referenced_is_not_the_declared_count(self):
        """docs 77 §7.1b in miniature: a tileset that reaches past what it ships.

        This is the exact shape that repainted the annex's windows -- the
        declared count says 278 and a live metatile draws from 281.
        """
        rows = [
            [entry(512 + 5)] * 4 + [0] * 4,
            [entry(512 + 281)] * 4 + [0] * 4,   # reaches past -num_tiles 278
        ]
        root = self.tree(rows)
        self.assertEqual(mcw.highest_referenced_tile(root, 512, skip_from=10_000), 281)
        self.assertEqual(mcw.read_num_tiles(root), 278)

    def test_skip_from_excludes_our_own_metatiles_on_a_rerun(self):
        """On a second run the tool's own rows are the tail, and counting them
        would push the first free tile up by eight every time."""
        rows = [
            [entry(512 + 5)] * 4 + [0] * 4,
            [entry(512 + 999)] * 4 + [0] * 4,   # pretend this row is ours
        ]
        root = self.tree(rows)
        self.assertEqual(mcw.highest_referenced_tile(root, 512, skip_from=512 + 1), 5)

    def test_collision_assertion_fires_and_is_silent_when_clear(self):
        rows = [[entry(512 + 280)] * 4 + [0] * 4]
        root = self.tree(rows)
        mcw.assert_no_collision(root, 512, first=282, count=8, upto=10_000)   # clear
        with self.assertRaises(SystemExit) as ctx:
            mcw.assert_no_collision(root, 512, first=278, count=8, upto=10_000)
        self.assertIn("already draws from secondary tile 280", str(ctx.exception))

    # ---------------------------------------------------------- the source wall

    def _wall_tree(self, bottom):
        rows = [[e for e in bottom] + [0, 0, 0, 0]]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        (root / mcw.TILESET_DIR).mkdir(parents=True)
        # the source wall must be at SOURCE_WALL_METATILE, so pad up to it
        pad = b"\x00" * 16 * (mcw.SOURCE_WALL_METATILE - 512)
        (root / mcw.TILESET_DIR / "metatiles.bin").write_bytes(
            pad + b"".join(struct.pack("<8H", *r) for r in rows))
        return root

    def test_source_wall_accepted_when_it_is_the_two_tile_repeat(self):
        root = self._wall_tree([entry(517), entry(518), entry(517), entry(518)])
        pal, tiles, top = mcw.check_source_wall(root, 512, 512)
        self.assertEqual((pal, tiles), (6, [5, 6, 5, 6]))
        self.assertEqual(top, (0, 0, 0, 0))

    def test_source_wall_refused_when_it_is_not_a_vertical_repeat(self):
        root = self._wall_tree([entry(517), entry(518), entry(519), entry(520)])
        with self.assertRaises(SystemExit) as ctx:
            mcw.check_source_wall(root, 512, 512)
        self.assertIn("not the vertical two-tile repeat", str(ctx.exception))

    def test_source_wall_refused_when_it_mixes_palettes(self):
        root = self._wall_tree([entry(517, pal=6), entry(518, pal=7),
                                entry(517, pal=6), entry(518, pal=7)])
        with self.assertRaises(SystemExit) as ctx:
            mcw.check_source_wall(root, 512, 512)
        self.assertIn("mixes palettes", str(ctx.exception))

    def test_source_wall_refused_when_it_uses_flipped_tiles(self):
        """A stamped hold would come out mirrored, so the derivation would
        stop being lossless -- which is the tool's whole claim."""
        root = self._wall_tree([entry(517, hflip=1), entry(518), entry(517, hflip=1), entry(518)])
        with self.assertRaises(SystemExit) as ctx:
            mcw.check_source_wall(root, 512, 512)
        self.assertIn("flipped tiles", str(ctx.exception))

    def test_source_wall_refused_when_it_draws_from_the_primary(self):
        root = self._wall_tree([entry(5), entry(6), entry(5), entry(6)])
        with self.assertRaises(SystemExit) as ctx:
            mcw.check_source_wall(root, 512, 512)
        self.assertIn("PRIMARY", str(ctx.exception))

    # ---------------------------------------------------------- the stamp

    def test_stamp_changes_only_the_hold_pixels(self):
        """The derivation is lossless everywhere a hold is not: every other
        pixel is the professional's, exactly as docs 75's kitbash rule asks."""
        base = list(range(64))
        out = mcw.stamp(base, [(2, 1, 8)])
        changed = {i for i, (a, b) in enumerate(zip(base, out)) if a != b}
        self.assertEqual(changed, {1 * 8 + 2, 1 * 8 + 3, 2 * 8 + 2, 2 * 8 + 3})
        self.assertTrue(all(out[i] == 8 for i in changed))

    def test_stamp_clips_at_the_cell_edge(self):
        out = mcw.stamp([0] * 64, [(7, 7, 9)])
        self.assertEqual(out[7 * 8 + 7], 9)
        self.assertEqual(sum(1 for v in out if v == 9), 1)   # the other three clipped

    def test_every_hold_row_fits_a_cell_and_uses_a_real_palette_index(self):
        self.assertEqual(len(mcw.HOLDS), mcw.NEW_TILE_COUNT)
        for holds in mcw.HOLDS:
            for x, y, color in holds:
                self.assertTrue(0 <= x < 8 and 0 <= y < 8, (x, y))
                self.assertIn(color, (mcw.HOLD_GREEN, mcw.HOLD_ORANGE, mcw.HOLD_BLUE))

    # ---------------------------------------------------------- the tile count

    def test_bump_is_idempotent_and_refuses_a_moved_rule(self):
        root = self.tree([[0] * 8], num_tiles=278)
        self.assertFalse(mcw.bump_tile_count(root, 290, check=False))   # wrote
        self.assertEqual(mcw.read_num_tiles(root), 290)
        self.assertTrue(mcw.bump_tile_count(root, 290, check=False))    # already there
        (root / "graphics_file_rules.mk").write_text("nothing here\n")
        with self.assertRaises(SystemExit):
            mcw.read_num_tiles(root)


@unittest.skipIf(Image is None, "Pillow not installed")
class ArtTests(unittest.TestCase):
    def png(self, cells=288, cols=16):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        (root / mcw.TILESET_DIR).mkdir(parents=True)
        rows = (cells + cols - 1) // cols
        img = Image.new("P", (cols * 8, rows * 8), 0)
        img.putpalette([(i * 7) % 256 for i in range(768)])
        # Fill from indices that are NOT hold colours. The first draft used
        # (cell % 15) + 1, which handed cell 5 the same index as HOLD_ORANGE --
        # so the stamp was invisible and the test failed on a working tool.
        # A fixture whose values collide with the thing under test is a fixture
        # that tests the collision.
        fills = [i for i in range(1, 16)
                 if i not in (mcw.HOLD_GREEN, mcw.HOLD_ORANGE, mcw.HOLD_BLUE)]
        for cell in range(cells):
            mcw.write_cell(img, cell, [fills[cell % len(fills)]] * 64)
        img.save(root / mcw.TILESET_DIR / "tiles.png")
        return root

    def test_build_art_is_idempotent(self):
        root = self.png()
        self.assertFalse(mcw.build_art(root, [5, 6], 282, check=False))  # wrote
        self.assertTrue(mcw.build_art(root, [5, 6], 282, check=False))   # no-op
        self.assertTrue(mcw.build_art(root, [5, 6], 282, check=True))

    def test_build_art_grows_the_sheet_when_it_must(self):
        """282 + 8 does not fit 288 cells, so the sheet gains a row rather than
        the tool refusing or, worse, wrapping."""
        root = self.png(cells=288)
        with Image.open(root / mcw.TILESET_DIR / "tiles.png") as im:
            before = im.height
        mcw.build_art(root, [5, 6], 282, check=False)
        with Image.open(root / mcw.TILESET_DIR / "tiles.png") as after:
            self.assertGreater(after.height, before)
            self.assertGreaterEqual(mcw.png_cells(after), 290)

    def test_build_art_derives_from_the_named_source_cells(self):
        root = self.png()
        mcw.build_art(root, [5, 6], 282, check=False)
        with Image.open(root / mcw.TILESET_DIR / "tiles.png") as img:
            src5, src6 = mcw.read_cell(img, 5), mcw.read_cell(img, 6)
            for i in range(mcw.NEW_TILE_COUNT):
                base = src5 if i % 2 == 0 else src6
                got = mcw.read_cell(img, 282 + i)
                differing = sum(1 for a, b in zip(base, got) if a != b)
                self.assertLessEqual(differing, 8, f"tile {i} strayed from its source")
                self.assertGreater(differing, 0, f"tile {i} has no holds on it")

    def test_indexed_png_is_required(self):
        root = self.png()
        Image.new("RGB", (128, 144)).save(root / mcw.TILESET_DIR / "tiles.png")
        with self.assertRaises(SystemExit) as ctx:
            mcw.build_art(root, [5, 6], 282, check=False)
        self.assertIn("not indexed", str(ctx.exception))


class ConstantsTests(unittest.TestCase):
    def test_the_strip_sits_against_the_map_edge(self):
        """docs 77 §12.2: with the strip inboard, the route needed a one-tile
        step that stops in open space, and it drifted. Column 0 is load-bearing
        for the timeline, not a visual preference."""
        self.assertEqual(mcw.CLIMB_COLUMN, 0)

    def test_the_strip_is_impassable_to_walking(self):
        """The field move is the only way up; walking into it must bump."""
        self.assertEqual(mcw.CLIMB_COLLISION, 1)

    def test_the_upper_level_is_tall_enough_to_stand_in(self):
        self.assertGreaterEqual(mcw.UPPER_ROWS, 4)


if __name__ == "__main__":
    unittest.main()
