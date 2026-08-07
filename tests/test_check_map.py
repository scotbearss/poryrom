#!/usr/bin/env python3
"""Unit tests for check_map.py -- the static map contract-check.

Every check gets BOTH directions: a fixture that passes and a mutation that
must produce the finding. A contract-check whose failure direction was never
executed is the same mistake as a spec with no counterfactual -- and this tool
is exactly the kind of code an edit script's "the file changed" assertion
once faked its way past (CLAUDE.md, 2026-07-30).

The fixture is a synthetic mini-hack built in a tempdir: just enough of the
pokeemerald tree (five headers, three C stubs, one tileset, two maps) for
every parser in the tool to run for real -- the C parsing included, so a
format drift in the real engine shows up here as a loud sys.exit, not a quiet
wrong answer. Real-data coverage is separate: the tool has been run over all
518 maps of the pinned engine (see the 2026-08-02 log entry).

    python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import pathlib
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import check_map as cm  # noqa: E402


# --------------------------------------------------------------- fixture

FIELDMAP_H = """
#define NUM_METATILES_IN_PRIMARY 512
#define MAX_MAP_DATA_SIZE 10240
#define MAP_OFFSET 7
#define MAP_OFFSET_W (MAP_OFFSET * 2 + 1)
#define MAP_OFFSET_H (MAP_OFFSET * 2)
"""

GLOBAL_H = """
#define OBJECT_EVENTS_COUNT 16
#define OBJECT_EVENT_TEMPLATES_COUNT 64
"""

GLOBAL_FIELDMAP_H = """
#define METATILE_ATTR_BEHAVIOR_MASK 0x00FF // Bits 0-7
#define MAPGRID_COLLISION_MASK   0x0C00 // Bits 10-11
#define MAPGRID_COLLISION_SHIFT  10
"""

CONFIG_OVERWORLD_H = """
#define OW_FOLLOWERS_ENABLED FALSE
"""

METATILE_BEHAVIORS_H = """
#define MB_NORMAL 0x00
#define MB_LADDER 0x61
#define MB_NON_ANIMATED_DOOR 0x62
#define MB_WATER_DOOR 0x63
#define MB_ANIMATED_DOOR 0x69
#define MB_NORTH_ARROW_WARP 0x6B
"""

# IsWarpMetatileBehavior gates on two predicates; one predicate (IsNonAnimDoor)
# holds two constants, and the arrow gate exercises the second entry point.
FIELD_CONTROL_C = """
static bool8 IsWarpMetatileBehavior(u16 metatileBehavior)
{
    if (MetatileBehavior_IsWarpDoor(metatileBehavior) != TRUE
     && MetatileBehavior_IsNonAnimDoor(metatileBehavior) != TRUE)
        return FALSE;
    return TRUE;
}

static bool8 IsArrowWarpMetatileBehavior(u16 metatileBehavior, u8 direction)
{
    switch (direction)
    {
    case DIR_NORTH:
        return MetatileBehavior_IsNorthArrowWarp(metatileBehavior);
    }
    return FALSE;
}
"""

# IsWarpDoor nests a second predicate call, exercising the recursive expansion.
METATILE_BEHAVIOR_C = """
bool8 MetatileBehavior_IsWarpDoor(u8 metatileBehavior)
{
    if (metatileBehavior == MB_ANIMATED_DOOR)
        return TRUE;
    if (MetatileBehavior_IsLadderLike(metatileBehavior) == TRUE)
        return TRUE;
    return FALSE;
}

bool8 MetatileBehavior_IsLadderLike(u8 metatileBehavior)
{
    if (metatileBehavior == MB_LADDER)
        return TRUE;
    else
        return FALSE;
}

bool8 MetatileBehavior_IsNonAnimDoor(u8 metatileBehavior)
{
    if (metatileBehavior == MB_NON_ANIMATED_DOOR
     || metatileBehavior == MB_WATER_DOOR)
        return TRUE;
    else
        return FALSE;
}

bool8 MetatileBehavior_IsNorthArrowWarp(u8 metatileBehavior)
{
    if (metatileBehavior == MB_NORTH_ARROW_WARP)
        return TRUE;
    else
        return FALSE;
}
"""

EVENT_OBJECT_MOVEMENT_C = """
void TrySpawnObjectEvents(s16 cameraX, s16 cameraY)
{
    if (gMapHeader.events != NULL)
    {
        s16 left = gSaveBlock1Ptr->pos.x - 2;
        s16 right = gSaveBlock1Ptr->pos.x + MAP_OFFSET_W + 2;
        s16 top = gSaveBlock1Ptr->pos.y;
        s16 bottom = gSaveBlock1Ptr->pos.y + MAP_OFFSET_H + 2;
    }
}
"""

TILESET_HEADERS_H = """
const struct Tileset gTileset_TestPrimary =
{
    .isSecondary = FALSE,
    .metatileAttributes = gMetatileAttributes_TestPrimary,
};

const struct Tileset gTileset_TestSecondary =
{
    .isSecondary = TRUE,
    .metatileAttributes = gMetatileAttributes_TestSecondary,
};
"""

TILESET_METATILES_H = """
const u16 gMetatileAttributes_TestPrimary[] = INCBIN_U16("data/tilesets/primary/test/metatile_attributes.bin");
const u16 gMetatileAttributes_TestSecondary[] = INCBIN_U16("data/tilesets/secondary/test/metatile_attributes.bin");
"""

W, H = 12, 10          # fixture layout, well under the size ceiling
DOOR_TILE = (2, 2)     # metatile 1: MB_ANIMATED_DOOR
SEC_DOOR_TILE = (4, 4) # metatile 512: secondary index 0, MB_NON_ANIMATED_DOOR


def build_fixture(root: pathlib.Path):
    """A minimal but format-faithful hack tree the whole tool can run on."""
    files = {
        "include/fieldmap.h": FIELDMAP_H,
        "include/constants/global.h": GLOBAL_H,
        "include/global.fieldmap.h": GLOBAL_FIELDMAP_H,
        "include/config/overworld.h": CONFIG_OVERWORLD_H,
        "include/constants/metatile_behaviors.h": METATILE_BEHAVIORS_H,
        "src/field_control_avatar.c": FIELD_CONTROL_C,
        "src/metatile_behavior.c": METATILE_BEHAVIOR_C,
        "src/event_object_movement.c": EVENT_OBJECT_MOVEMENT_C,
        "src/data/tilesets/headers.h": TILESET_HEADERS_H,
        "src/data/tilesets/metatiles.h": TILESET_METATILES_H,
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    # Primary attrs: metatile 0 = MB_NORMAL, 1 = MB_ANIMATED_DOOR (0x69).
    # Secondary attrs: index 0 = MB_NON_ANIMATED_DOOR (0x62).
    prim = root / "data/tilesets/primary/test/metatile_attributes.bin"
    prim.parent.mkdir(parents=True, exist_ok=True)
    prim.write_bytes(struct.pack("<512H", 0x0000, 0x0069, *([0] * 510)))
    sec = root / "data/tilesets/secondary/test/metatile_attributes.bin"
    sec.parent.mkdir(parents=True, exist_ok=True)
    sec.write_bytes(struct.pack("<8H", 0x0062, *([0] * 7)))

    # Blockdata: metatile 0 everywhere, a primary door at DOOR_TILE and a
    # secondary-tileset door (metatile 512) at SEC_DOOR_TILE.
    grid = [[0] * W for _ in range(H)]
    grid[DOOR_TILE[1]][DOOR_TILE[0]] = 1
    grid[SEC_DOOR_TILE[1]][SEC_DOOR_TILE[0]] = 512
    lay = root / "data/layouts/TestTown"
    lay.mkdir(parents=True, exist_ok=True)
    (lay / "map.bin").write_bytes(
        b"".join(struct.pack("<H", t) for row in grid for t in row))

    (root / "data/layouts/layouts.json").write_text(json.dumps({
        "layouts": [{
            "id": "LAYOUT_TEST_TOWN", "name": "TestTown_Layout",
            "width": W, "height": H,
            "primary_tileset": "gTileset_TestPrimary",
            "secondary_tileset": "gTileset_TestSecondary",
            "blockdata_filepath": "data/layouts/TestTown/map.bin",
        }]}))

    write_map(root, "TestTown", warps=[warp(*DOOR_TILE)])
    write_map(root, "TestDest", warps=[warp(*DOOR_TILE)])


def set_collision(root, x, y, collision, layout="TestTown"):
    """Set a tile's collision bits in place, keeping its metatile id."""
    p = root / "data/layouts" / layout / "map.bin"
    data = bytearray(p.read_bytes())
    off = (y * W + x) * 2
    v = struct.unpack_from("<H", data, off)[0]
    struct.pack_into("<H", data, off, (v & ~0x0C00) | (collision << 10))
    p.write_bytes(bytes(data))


def warp(x, y, dest="MAP_TEST_DEST", dest_id="0"):
    return {"x": x, "y": y, "elevation": 0, "dest_map": dest, "dest_warp_id": dest_id}


def npc(x, y, flag="0"):
    return {"graphics_id": "OBJ_EVENT_GFX_WOMAN_5", "x": x, "y": y, "elevation": 3,
            "movement_type": "MOVEMENT_TYPE_NONE", "trainer_type": "TRAINER_TYPE_NONE",
            "script": "0x0", "flag": flag}


def write_map(root, name, warps=(), objects=(), layout="LAYOUT_TEST_TOWN"):
    ident = "MAP_" + "".join("_" + c if c.isupper() and i else c
                             for i, c in enumerate(name)).upper()
    d = root / "data/maps" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "map.json").write_text(json.dumps({
        "id": ident, "name": name, "layout": layout,
        "object_events": list(objects), "warp_events": list(warps),
    }))


class CheckMapTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.hack = pathlib.Path(self._tmp.name) / "hack"
        build_fixture(self.hack)
        self.addCleanup(self._tmp.cleanup)

    # -- plumbing shared by the cases ------------------------------------

    def run_tool(self, maps=("TestTown",)):
        consts = cm.parse_defines(
            (self.hack / "include/fieldmap.h").read_text(),
            ["MAP_OFFSET", "MAP_OFFSET_W", "MAP_OFFSET_H",
             "MAX_MAP_DATA_SIZE", "NUM_METATILES_IN_PRIMARY"])
        consts |= cm.parse_defines(
            (self.hack / "include/constants/global.h").read_text(),
            ["OBJECT_EVENTS_COUNT", "OBJECT_EVENT_TEMPLATES_COUNT"])
        consts |= cm.parse_defines(
            (self.hack / "include/global.fieldmap.h").read_text(),
            ["METATILE_ATTR_BEHAVIOR_MASK",
             "MAPGRID_COLLISION_MASK", "MAPGRID_COLLISION_SHIFT"])
        consts |= cm.parse_defines(
            (self.hack / "include/config/overworld.h").read_text(),
            ["OW_FOLLOWERS_ENABLED"])
        accepted = cm.warp_behavior_set(self.hack)
        win_w, win_h = cm._spawn_window_dims(self.hack, consts)
        world = cm.World(self.hack)
        targets = [world.maps[m] for m in maps]
        return cm._run_checks(world, targets, consts, win_w, win_h, accepted)

    def findings_for(self, check, findings):
        return [f for f in findings if f[2] == check]

    # -- the parsers -----------------------------------------------------

    def test_constants_resolve_expressions(self):
        consts = cm.parse_defines(FIELDMAP_H, ["MAP_OFFSET", "MAP_OFFSET_W", "MAP_OFFSET_H"])
        self.assertEqual((consts["MAP_OFFSET_W"], consts["MAP_OFFSET_H"]), (15, 14))

    def test_warp_behavior_set_expands_nested_predicates(self):
        accepted = cm.warp_behavior_set(self.hack)
        # Door, nested ladder-like, both non-anim doors, and the arrow gate.
        self.assertEqual(
            set(accepted.values()),
            {"MB_ANIMATED_DOOR", "MB_LADDER", "MB_NON_ANIMATED_DOOR",
             "MB_WATER_DOOR", "MB_NORTH_ARROW_WARP"})

    def test_spawn_window_dims_and_tamper_guard(self):
        consts = cm.parse_defines(FIELDMAP_H, ["MAP_OFFSET", "MAP_OFFSET_W", "MAP_OFFSET_H"])
        self.assertEqual(cm._spawn_window_dims(self.hack, consts), (20, 17))
        # If the engine's window ever changes shape, the tool must refuse to
        # run rather than silently check the wrong window.
        eom = self.hack / "src/event_object_movement.c"
        eom.write_text(eom.read_text().replace("pos.x - 2", "pos.x - 3"))
        with self.assertRaises(SystemExit):
            cm._spawn_window_dims(self.hack, consts)

    # -- each check, both directions -------------------------------------

    def test_clean_map_has_no_findings(self):
        self.assertEqual(list(self.run_tool()), [])

    def test_map_size_ceiling(self):
        lay = json.loads((self.hack / "data/layouts/layouts.json").read_text())
        lay["layouts"][0]["height"] = 400   # (12+15)*(400+14) far over 10240
        (self.hack / "data/layouts/layouts.json").write_text(json.dumps(lay))
        found = self.findings_for("map-size", self.run_tool())
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], "FAIL")
        self.assertIn("solid void", found[0][3])

    def test_blockdata_length_mismatch(self):
        p = self.hack / "data/layouts/TestTown/map.bin"
        p.write_bytes(p.read_bytes()[:-2])
        found = self.findings_for("blockdata", self.run_tool())
        self.assertEqual([f[0] for f in found], ["FAIL"])

    def test_template_count_ceiling(self):
        write_map(self.hack, "TestTown", objects=[npc(1, 1)] * 65)
        found = self.findings_for("template-count", self.run_tool())
        self.assertEqual([f[0] for f in found], ["FAIL"])
        self.assertIn("SaveBlock1", found[0][3])
        write_map(self.hack, "TestTown", objects=[npc(1, 1)] * 64)
        self.assertEqual(self.findings_for("template-count", self.run_tool()), [])

    def test_spawn_window_budget(self):
        # 15 always-visible in one cluster: at budget, clean.
        write_map(self.hack, "TestTown", objects=[npc(i % 4, i // 4) for i in range(15)])
        self.assertEqual(self.findings_for("spawn-window", self.run_tool()), [])
        # A 16th always-visible object: FAIL.
        write_map(self.hack, "TestTown", objects=[npc(i % 4, i // 4) for i in range(16)])
        found = self.findings_for("spawn-window", self.run_tool())
        self.assertEqual([f[0] for f in found], ["FAIL"])
        # 15 always-visible plus a flag-gated 16th: WARN, not FAIL.
        objs = [npc(i % 4, i // 4) for i in range(15)] + [npc(0, 4, flag="FLAG_TEST")]
        write_map(self.hack, "TestTown", objects=objs)
        found = self.findings_for("spawn-window", self.run_tool())
        self.assertEqual([f[0] for f in found], ["WARN"])
        # Same 16 objects spread beyond one 20x17 window: clean.
        objs = [npc((i % 4) * 30, (i // 4) * 30) for i in range(16)]
        write_map(self.hack, "TestTown", objects=objs)
        self.assertEqual(self.findings_for("spawn-window", self.run_tool()), [])

    def test_warp_behavior(self):
        # On the primary door and the secondary-tileset door: clean.
        write_map(self.hack, "TestTown", warps=[warp(*DOOR_TILE), warp(*SEC_DOOR_TILE)])
        self.assertEqual(self.findings_for("warp-behavior", self.run_tool()), [])
        # On plain ground (MB_NORMAL): the warp does nothing -> FAIL.
        write_map(self.hack, "TestTown", warps=[warp(5, 5)])
        found = self.findings_for("warp-behavior", self.run_tool())
        self.assertEqual([f[0] for f in found], ["FAIL"])
        self.assertIn("nothing happens", found[0][3])

    def test_warp_bounds(self):
        write_map(self.hack, "TestTown", warps=[warp(W, H - 1)])
        found = self.findings_for("warp-bounds", self.run_tool())
        self.assertEqual([f[0] for f in found], ["FAIL"])

    def test_warp_destination(self):
        # Missing destination map.
        write_map(self.hack, "TestTown", warps=[warp(*DOOR_TILE, dest="MAP_NOWHERE")])
        found = self.findings_for("warp-dest", self.run_tool())
        self.assertEqual([f[0] for f in found], ["FAIL"])
        # Destination warp id past the end of the dest map's warp list.
        write_map(self.hack, "TestTown", warps=[warp(*DOOR_TILE, dest_id="7")])
        found = self.findings_for("warp-dest", self.run_tool())
        self.assertEqual([f[0] for f in found], ["FAIL"])
        self.assertIn("garbage", found[0][3])
        # MAP_DYNAMIC is the engine's escape hatch: skipped.
        write_map(self.hack, "TestTown", warps=[warp(*DOOR_TILE, dest="MAP_DYNAMIC")])
        self.assertEqual(self.findings_for("warp-dest", self.run_tool()), [])
        # A symbolic dest_warp_id is not statically checkable: WARN, not FAIL.
        write_map(self.hack, "TestTown",
                  warps=[warp(*DOOR_TILE, dest_id="WARP_ID_SECRET_BASE")])
        found = self.findings_for("warp-dest", self.run_tool())
        self.assertEqual([f[0] for f in found], ["WARN"])

    def test_object_on_impassable_tile(self):
        # doc 70 §1: the annex's 5x5 stamp landed on top of RustboroCity's
        # BOY_1, and nothing anywhere refused it. Both directions on the same
        # NPC: only the TILE under him changes.
        write_map(self.hack, "TestTown", warps=[warp(*DOOR_TILE)], objects=[npc(6, 6)])
        self.assertEqual(self.findings_for("object-collision", self.run_tool()), [])
        set_collision(self.hack, 6, 6, 1)
        found = self.findings_for("object-collision", self.run_tool())
        self.assertEqual([f[0] for f in found], ["FAIL"])
        self.assertIn("(6,6)", found[0][3])
        self.assertIn("collision 1", found[0][3])

    def test_object_on_impassable_tile_covers_flag_gated_and_all_collisions(self):
        # A flag-gated NPC is just as stuck when its flag is clear, and
        # collision 2/3 are impassable too -- the check is != 0, not == 1.
        write_map(self.hack, "TestTown", warps=[warp(*DOOR_TILE)],
                  objects=[npc(6, 6, flag="FLAG_TEST"), npc(7, 6)])
        set_collision(self.hack, 6, 6, 3)
        set_collision(self.hack, 7, 6, 2)
        found = self.findings_for("object-collision", self.run_tool())
        self.assertEqual([f[0] for f in found], ["FAIL", "FAIL"])
        self.assertIn("collision 3", found[0][3])
        self.assertIn("collision 2", found[1][3])

    def test_object_out_of_bounds(self):
        write_map(self.hack, "TestTown", warps=[warp(*DOOR_TILE)], objects=[npc(W, 0)])
        found = self.findings_for("object-bounds", self.run_tool())
        self.assertEqual([f[0] for f in found], ["FAIL"])
        # ...and an out-of-bounds object is not ALSO reported as on-collision,
        # which would be a read past the end of the blockdata.
        self.assertEqual(self.findings_for("object-collision", self.run_tool()), [])

    # -- baseline suppression --------------------------------------------

    def test_baseline_suppresses_vanilla_quirks_only(self):
        # Baseline = the fixture with one deliberate quirk (warp on plain
        # ground). Hack = same quirk plus a NEW bad warp. Only the new one
        # must survive suppression.
        base = pathlib.Path(self._tmp.name) / "base"
        shutil.copytree(self.hack, base)
        write_map(base, "TestTown", warps=[warp(5, 5)])
        write_map(self.hack, "TestTown", warps=[warp(5, 5), warp(6, 5)])

        argv = ["check_map.py", "--hack", str(self.hack), "--baseline", str(base), "TestTown"]
        old_argv, sys.argv = sys.argv, argv
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
                cm.main()
        finally:
            sys.argv = old_argv
        self.assertEqual(ctx.exception.code, 1)  # the new warp still FAILs
        self.assertIn("(6,5)", out.getvalue())       # the NEW warp is reported
        self.assertNotIn("(5,5)", out.getvalue())    # the vanilla quirk is not
        self.assertIn("1 vanilla quirk(s) suppressed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
