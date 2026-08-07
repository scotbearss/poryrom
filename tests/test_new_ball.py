#!/usr/bin/env python3
"""Unit tests for tools/new_ball.py, on a synthetic mini-fork.

No docker, no ROM, no pokeemerald tree. The fixture is the smallest thing that
has the SHAPES the tool depends on -- a contiguous item-id block with use-type
defines living below ITEMS_COUNT, a ball enum terminated by POKEBALL_COUNT,
single-line and multi-line `[BALL_X] =` initializer rows, and a donor PNG plus
a CRLF JASC palette.

    python3 -m unittest discover -s tests -v

The two tests worth reading first are
UseTypeDefinesAreNotShifted (the bug the tool's own contiguity guard caught on
its first real run) and EveryDonorRowIsCloned (the one that would have caught
three missed tables by hand).
"""

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import new_ball  # noqa: E402

ITEMS_H = """\
#ifndef GUARD_CONSTANTS_ITEMS_H
#define GUARD_CONSTANTS_ITEMS_H

#define ITEM_NONE 0

// Poke Balls
#define ITEM_POKE_BALL 1
#define ITEM_GREAT_BALL 2
#define ITEM_CHERISH_BALL 3

#define FIRST_BALL ITEM_POKE_BALL
#define LAST_BALL  ITEM_CHERISH_BALL

// Medicine
#define ITEM_POTION 4
#define ITEM_ELIXIR 5
#define ITEM_ELIXER ITEM_ELIXIR // Pre-Gen III name

#define ITEMS_COUNT 6
#define ITEM_FIELD_ARROW ITEMS_COUNT
#define ITEM_LIST_END 0xFFFF

// Item type IDs -- NOT item ids, and they must never be renumbered.
#define ITEM_USE_MAIL             0
#define ITEM_USE_PARTY_MENU       1
#define ITEM_USE_BAG_MENU         4
#define ITEM_USE_PARTY_MENU_MOVES 5

#endif  // GUARD_CONSTANTS_ITEMS_H
"""

POKEBALL_H = """\
#ifndef GUARD_POKEBALL_H
#define GUARD_POKEBALL_H

enum
{
    BALL_POKE,
    BALL_GREAT,
    BALL_CHERISH,
    POKEBALL_COUNT
};

#endif
"""

POKEBALL_C = """\
#include "global.h"

#define GFX_TAG_POKE_BALL    55000
#define GFX_TAG_GREAT_BALL   55001
#define GFX_TAG_CHERISH_BALL 55002

const struct CompressedSpriteSheet gBallSpriteSheets[POKEBALL_COUNT] =
{
    [BALL_POKE]    = {gBallGfx_Poke,    384, GFX_TAG_POKE_BALL},
    [BALL_GREAT]   = {gBallGfx_Great,   384, GFX_TAG_GREAT_BALL},
    [BALL_CHERISH] = {gBallGfx_Cherish, 384, GFX_TAG_CHERISH_BALL},
};

const struct CompressedSpritePalette gBallSpritePalettes[POKEBALL_COUNT] =
{
    [BALL_POKE]    = {gBallPal_Poke,    GFX_TAG_POKE_BALL},
    [BALL_GREAT]   = {gBallPal_Great,   GFX_TAG_GREAT_BALL},
    [BALL_CHERISH] = {gBallPal_Cherish, GFX_TAG_CHERISH_BALL},
};

const struct SpriteTemplate gBallSpriteTemplates[POKEBALL_COUNT] =
{
    [BALL_POKE] =
    {
        .tileTag = GFX_TAG_POKE_BALL,
        .paletteTag = GFX_TAG_POKE_BALL,
        .callback = SpriteCB_BallThrow,
    },
    [BALL_GREAT] =
    {
        .tileTag = GFX_TAG_GREAT_BALL,
        .paletteTag = GFX_TAG_GREAT_BALL,
        .callback = SpriteCB_BallThrow,
    },
};

void LoadBallGfx(u8 ballId)
{
    switch (ballId)
    {
    case BALL_POKE ... BALL_GREAT:
    case BALL_CHERISH:
        var = GetSpriteTileStartByTag(gBallSpriteSheets[ballId].tag);
        break;
    }
}
"""

ANIM_C = """\
#include "global.h"

static const struct CompressedSpriteSheet sBallParticleSpriteSheets[] =
{
    [BALL_POKE]    = {gGfx_Particles, 0x100, TAG_PARTICLES_POKEBALL},
    [BALL_GREAT]   = {gGfx_Particles, 0x100, TAG_PARTICLES_GREATBALL},
    [BALL_CHERISH] = {gGfx_Particles, 0x100, TAG_PARTICLES_CHERISHBALL},
};

static const u8 sBallParticleAnimNums[POKEBALL_COUNT] =
{
    [BALL_POKE]    = 0,
    [BALL_GREAT]   = 0,
    [BALL_CHERISH] = 0,
};

static const struct SpriteTemplate sBallParticleSpriteTemplates[POKEBALL_COUNT] =
{
    [BALL_POKE] = {
        .tileTag = TAG_PARTICLES_POKEBALL,
        .callback = SpriteCallbackDummy,
    },
    [BALL_GREAT] = {
        .tileTag = TAG_PARTICLES_GREATBALL,
        .callback = SpriteCallbackDummy,
    },
};

u8 GetBallIdFromItemId(u16 itemId)
{
    switch (itemId)
    {
    case ITEM_GREAT_BALL:
        return BALL_GREAT;
    case ITEM_CHERISH_BALL:
        return BALL_CHERISH;
    default:
        return BALL_POKE;
    }
}
"""

DATA_ITEMS_H = """\
const struct Item gItemsInfo[] =
{
    [ITEM_CHERISH_BALL] =
    {
        .name = _("Cherish Ball"),
        .pocket = POCKET_POKE_BALLS,
        .secondaryId = ITEM_CHERISH_BALL - FIRST_BALL,
    },

// Medicine

    [ITEM_POTION] =
    {
        .name = _("Potion"),
    },
};
"""

GRAPHICS_H = """\
#ifndef GUARD_GRAPHICS_H
#define GUARD_GRAPHICS_H

extern const u32 gBallGfx_Poke[];

#endif //GUARD_GRAPHICS_H
"""

SPEC = {
    "id": "REP_BALL",
    "name": "Rep Ball",
    "price": 600,
    "description": ["A Ball that gets", "stronger with the", "work you put in."],
    "file_stem": "rep",
    "icon_stem": "rep_ball",
    "throw_donor": "poke",
    "icon_donor": "poke_ball",
    "particle_donor": "BALL_POKE",
    "throw_palette": {"1": "#0a3d1c"},
    "icon_palette": {"7": "#2a5236"},
}


def make_png(path, colours):
    from PIL import Image
    im = Image.new("P", (8, 8), 0)
    flat = []
    for rgb in colours:
        flat += list(rgb)
    flat += [0, 0, 0] * (256 - len(colours))
    im.putpalette(flat)
    im.save(path)


class Fork:
    """A synthetic pokeemerald fork with only what new_ball.py touches."""

    def __init__(self, tmp, items_h=ITEMS_H, anim_c=ANIM_C):
        self.root = pathlib.Path(tmp)
        files = {
            "include/constants/items.h": items_h,
            "include/pokeball.h": POKEBALL_H,
            "include/graphics.h": GRAPHICS_H,
            "src/pokeball.c": POKEBALL_C,
            "src/battle_anim_throw.c": anim_c,
            "src/data/items.h": DATA_ITEMS_H,
            "src/data/graphics/items.h": "// icons\n",
            "src/data/graphics/pokeballs.h": "// balls\n",
        }
        for rel, text in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        for rel in ("graphics/balls", "graphics/items/icons",
                    "graphics/items/icon_palettes"):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        pal = [(255, 255, 255), (131, 0, 0), (172, 0, 0), (213, 41, 41),
               (255, 156, 123), (255, 255, 255), (148, 148, 148),
               (65, 65, 65), (24, 24, 24)]
        make_png(self.root / "graphics/balls/poke.png", pal)
        make_png(self.root / "graphics/items/icons/poke_ball.png", pal)
        new_ball.write_jasc(
            self.root / "graphics/items/icon_palettes/poke_ball.pal", pal)

    def run(self, spec=None):
        """Invoke the tool as a subprocess; returns CompletedProcess."""
        spec_path = self.root / "spec.json"
        spec_path.write_text(json.dumps(spec or SPEC))
        return subprocess.run(
            [sys.executable, str(TOOLS / "new_ball.py"),
             "--hack", str(self.root), str(spec_path)],
            capture_output=True, text=True)

    def read(self, rel):
        return (self.root / rel).read_text()


class ItemIdShift(unittest.TestCase):
    def test_the_ball_takes_the_slot_after_the_last_ball(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            r = f.run()
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            h = f.read("include/constants/items.h")
            self.assertIn("#define ITEM_REP_BALL 4", h)
            self.assertIn("#define LAST_BALL  ITEM_REP_BALL", h)

    def test_ids_at_or_above_the_ball_shift_and_lower_ones_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            h = f.read("include/constants/items.h")
            self.assertIn("#define ITEM_CHERISH_BALL 3", h)   # unmoved
            self.assertIn("#define ITEM_POTION 5", h)         # was 4
            self.assertIn("#define ITEM_ELIXIR 6", h)         # was 5
            self.assertIn("#define ITEMS_COUNT 7", h)         # was 6

    def test_symbolic_aliases_are_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            self.assertIn("#define ITEM_ELIXER ITEM_ELIXIR",
                          f.read("include/constants/items.h"))


class UseTypeDefinesAreNotShifted(unittest.TestCase):
    """The bug the tool's contiguity guard caught on its first real run.

    `ITEM_[A-Z0-9_]+ <number>` also matches ITEM_USE_PARTY_MENU_MOVES 5 and
    friends, which live BELOW ITEMS_COUNT and are use-type ids. Renumbering
    those changes what every item in the game DOES, and the build stays green.
    """

    def test_the_use_type_block_survives_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            h = f.read("include/constants/items.h")
            for line in ("#define ITEM_USE_MAIL             0",
                         "#define ITEM_USE_PARTY_MENU       1",
                         "#define ITEM_USE_BAG_MENU         4",
                         "#define ITEM_USE_PARTY_MENU_MOVES 5"):
                self.assertIn(line, h)

    def test_ITEM_LIST_END_is_not_a_number_it_shifts(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            self.assertIn("#define ITEM_LIST_END 0xFFFF",
                          f.read("include/constants/items.h"))


class RefusalsHappenBeforeAnyWrite(unittest.TestCase):
    def test_a_duplicate_ball_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            self.assertEqual(f.run().returncode, 0)
            before = f.read("include/pokeball.h")
            r = f.run()
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("already exists", r.stderr)
            self.assertEqual(before, f.read("include/pokeball.h"))

    def test_non_contiguous_ids_are_refused(self):
        gappy = ITEMS_H.replace("#define ITEM_ELIXIR 5",
                                "#define ITEM_ELIXIR 9")
        gappy = gappy.replace("#define ITEMS_COUNT 6", "#define ITEMS_COUNT 10")
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp, items_h=gappy)
            r = f.run()
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("not contiguous", r.stderr)
            self.assertEqual(gappy, f.read("include/constants/items.h"))

    def test_a_wrong_ITEMS_COUNT_is_refused(self):
        wrong = ITEMS_H.replace("#define ITEMS_COUNT 6", "#define ITEMS_COUNT 7")
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp, items_h=wrong)
            r = f.run()
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("ITEMS_COUNT", r.stderr)

    def test_an_id_that_is_not_UPPER_SNAKE_BALL_is_refused(self):
        spec = dict(SPEC, id="repball")
        with tempfile.TemporaryDirectory() as tmp:
            r = Fork(tmp).run(spec)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("_BALL", r.stderr)

    def test_an_overlong_description_line_is_refused(self):
        spec = dict(SPEC, description=["x" * 40])
        with tempfile.TemporaryDirectory() as tmp:
            r = Fork(tmp).run(spec)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("chars", r.stderr)

    def test_an_unknown_particle_donor_is_refused(self):
        spec = dict(SPEC, particle_donor="BALL_NO_SUCH")
        with tempfile.TemporaryDirectory() as tmp:
            r = Fork(tmp).run(spec)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("no [BALL_NO_SUCH] row", r.stderr)


class EveryDonorRowIsCloned(unittest.TestCase):
    """Listing the ball tables by hand missed three of nine on the real tree."""

    def test_every_table_with_a_donor_row_gains_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            r = f.run()
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            # 3 in pokeball.c (sheets, palettes, sprite templates)
            # 3 in battle_anim_throw.c (particle sheets, anim nums, templates)
            self.assertEqual(f.read("src/pokeball.c").count("[BALL_REP]"), 3)
            self.assertEqual(
                f.read("src/battle_anim_throw.c").count("[BALL_REP]"), 3)

    def test_a_multi_line_row_is_cloned_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            c = f.read("src/pokeball.c")
            i = c.index("[BALL_REP] =\n")
            block = c[i:c.index("},", i)]
            self.assertIn(".callback = SpriteCB_BallThrow", block)

    def test_the_clone_points_at_its_OWN_art_not_the_donors(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            # The clone keeps the donor's column alignment, so match on tokens
            # rather than on exact spacing.
            c = f.read("src/pokeball.c")
            rows = [l for l in c.splitlines() if "[BALL_REP]" in l]
            self.assertTrue(any("gBallGfx_Rep" in l and "GFX_TAG_REP_BALL" in l
                                for l in rows), rows)
            self.assertTrue(any("gBallPal_Rep" in l and "GFX_TAG_REP_BALL" in l
                                for l in rows), rows)
            for l in rows:
                self.assertNotIn("gBallGfx_Poke", l)
                self.assertNotIn("gBallPal_Poke", l)
                self.assertNotIn("GFX_TAG_POKE_BALL", l)
            # ...and the donor's own rows are untouched.
            self.assertIn("[BALL_POKE]    = {gBallGfx_Poke,    384, "
                          "GFX_TAG_POKE_BALL}", c)

    def test_the_post_condition_sweep_catches_a_missed_table(self):
        # A table the tool does not rewrite (BALL_SOURCES lists two files) but
        # the sweep does read. This is the guard against a table moving house.
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            stray = f.root / "src" / "stray_ball_table.c"
            stray.write_text("const u8 sThing[] =\n{\n"
                             "    [BALL_POKE]    = 1,\n};\n")
            r = f.run()
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("missing a row the donor has", r.stderr)

    def test_the_item_to_ball_switch_case_is_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            c = f.read("src/battle_anim_throw.c")
            self.assertIn("case ITEM_REP_BALL:", c)
            self.assertIn("return BALL_REP;", c)

    def test_the_open_overlay_case_follows_the_donor(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            self.assertIn("case BALL_REP:", f.read("src/pokeball.c"))


class GeneratedDeclarationsAndEntry(unittest.TestCase):
    def test_ball_enum_lands_before_the_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            h = f.read("include/pokeball.h")
            self.assertLess(h.index("BALL_REP"), h.index("POKEBALL_COUNT"))

    def test_externs_are_declared_inside_the_include_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            h = f.read("include/graphics.h")
            for name in ("gBallGfx_Rep", "gBallPal_Rep",
                         "gItemIcon_RepBall", "gItemIconPalette_RepBall"):
                self.assertIn(f"extern const u32 {name}[];", h)
                self.assertLess(h.index(name), h.index("#endif"))

    def test_the_item_entry_uses_the_new_ball_as_its_own_secondaryId(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            d = f.read("src/data/items.h")
            self.assertIn("[ITEM_REP_BALL] =", d)
            self.assertIn(".secondaryId = ITEM_REP_BALL - FIRST_BALL,", d)
            self.assertIn('"A Ball that gets\\n"', d)
            # placed after the previous last ball, before the Medicine block
            self.assertLess(d.index("[ITEM_REP_BALL]"), d.index("[ITEM_POTION]"))

    def test_the_gfx_tag_continues_the_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            self.assertIn("#define GFX_TAG_REP_BALL 55003",
                          f.read("src/pokeball.c"))


class Art(unittest.TestCase):
    def test_named_indices_change_and_the_rest_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            pal = new_ball.png_palette(f.root / "graphics/balls/rep.png")
            self.assertEqual(pal[1], (0x0a, 0x3d, 0x1c))     # remapped
            self.assertEqual(pal[2], (172, 0, 0))            # donor's, kept
            self.assertEqual(pal[0], (255, 255, 255))        # key, untouched

    def test_the_icon_palette_is_a_JASC_file_with_CRLF(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            f.run()
            raw = (f.root / "graphics/items/icon_palettes/rep_ball.pal"
                   ).read_bytes()
            self.assertTrue(raw.startswith(b"JASC-PAL\r\n"))
            self.assertNotIn(b"\n\n", raw)
            self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))
            colours = new_ball.read_jasc(
                f.root / "graphics/items/icon_palettes/rep_ball.pal")
            self.assertEqual(colours[7], (0x2a, 0x52, 0x36))
            self.assertEqual(colours[8], (24, 24, 24))

    def test_remapping_the_transparency_key_is_refused(self):
        spec = dict(SPEC, throw_palette={"0": "#123456"})
        with tempfile.TemporaryDirectory() as tmp:
            r = Fork(tmp).run(spec)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("transparency key", r.stderr)

    def test_a_bad_colour_is_refused(self):
        spec = dict(SPEC, throw_palette={"1": "not-a-colour"})
        with tempfile.TemporaryDirectory() as tmp:
            r = Fork(tmp).run(spec)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("#rrggbb", r.stderr)


class DumpPalette(unittest.TestCase):
    def test_it_prints_both_palettes_and_says_index_0_is_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fork(tmp)
            r = subprocess.run(
                [sys.executable, str(TOOLS / "new_ball.py"),
                 "--hack", str(f.root), "--dump-palette", "poke"],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("#830000", r.stdout)          # throw sprite
            self.assertIn("JASC", "JASC")
            self.assertIn("transparency key", r.stdout)


class WarnsAboutTheSaveVisibleShift(unittest.TestCase):
    def test_the_run_says_so_out_loud(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = Fork(tmp).run()
            self.assertIn("shifted by one", r.stdout)
            self.assertIn("Start a new save", r.stdout)


if __name__ == "__main__":
    unittest.main()
