#!/usr/bin/env python3
"""Unit tests for new_map.py -- the append-only map codegen.

Same discipline as test_check_map.py: BOTH directions for every guard, on a
synthetic but format-faithful mini-hack in a tempdir. This tool writes six
files and two binaries, and five of the six fail SILENTLY when skipped -- a
layout with no layouts.json row is simply not built, a map absent from
map_groups.json has no MAP_* constant. "The tool ran without an exception" is
exactly the kind of evidence that once faked its way past an edit script
(CLAUDE.md, 2026-07-30), so every case here asserts the artifact, not the exit.

The round-trip test is the load-bearing one: dump an existing layout, feed the
printed plan and palette straight back in, and require the resulting map.bin to
be byte-identical. That is the property the whole derive-don't-guess authoring
loop rests on -- if dumping and packing disagree, every map built from a dump is
quietly wrong in a way no assertion downstream would notice.

    python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import pathlib
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import new_map as nm  # noqa: E402


# --------------------------------------------------------------- fixture

GLOBAL_FIELDMAP_H = """
#define MAPGRID_METATILE_ID_MASK 0x03FF // Bits 0-9
#define MAPGRID_COLLISION_MASK   0x0C00 // Bits 10-11
#define MAPGRID_ELEVATION_MASK   0xF000 // Bits 12-15
#define MAPGRID_COLLISION_SHIFT  10
#define MAPGRID_ELEVATION_SHIFT  12
"""

FIELDMAP_H = """
#define MAX_MAP_DATA_SIZE 10240
#define MAP_OFFSET 7
"""

HOST_W, HOST_H = 20, 20

SCRIPTS = ("HostTown_Annex_MapScripts::\n\t.byte 0\n\n"
           "HostTown_Annex_EventScript_Coach::\n\tend\n")


def build_fixture(root: pathlib.Path):
    for rel, text in {
        "include/global.fieldmap.h": GLOBAL_FIELDMAP_H,
        "include/fieldmap.h": FIELDMAP_H,
    }.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    # Host layout: plain ground everywhere, with a distinctive 3x3 "building"
    # at (4,4) whose bottom-middle block is the door.
    grid = [[pack(0x2BB, 0, 3) for _ in range(HOST_W)] for _ in range(HOST_H)]
    for dy in range(3):
        for dx in range(3):
            grid[4 + dy][4 + dx] = pack(0x300 + dy * 3 + dx, 1, 0)
    grid[6][5] = pack(0x21F, 1, 0)  # the door block
    lay = root / "data/layouts/HostTown"
    lay.mkdir(parents=True, exist_ok=True)
    (lay / "map.bin").write_bytes(
        b"".join(struct.pack("<H", t) for row in grid for t in row))
    (lay / "border.bin").write_bytes(struct.pack("<4H", 1, 1, 1, 1))

    (root / "data/layouts/layouts.json").write_text(json.dumps({
        "layouts_table_label": "gMapLayouts",
        "layouts": [{
            "id": "LAYOUT_HOST_TOWN", "name": "HostTown_Layout",
            "width": HOST_W, "height": HOST_H,
            "primary_tileset": "gTileset_General",
            "secondary_tileset": "gTileset_Host",
            "border_filepath": "data/layouts/HostTown/border.bin",
            "blockdata_filepath": "data/layouts/HostTown/map.bin",
        }]}, indent=2) + "\n")

    d = root / "data/maps/HostTown"
    d.mkdir(parents=True, exist_ok=True)
    (d / "map.json").write_text(json.dumps({
        "id": "MAP_HOST_TOWN", "name": "HostTown", "layout": "LAYOUT_HOST_TOWN",
        "object_events": [], "warp_events": [], "coord_events": [],
        "bg_events": [],
    }, indent=2) + "\n")

    (root / "data/maps/map_groups.json").write_text(json.dumps({
        "group_order": ["gMapGroup_Towns", "gMapGroup_Indoor"],
        "gMapGroup_Towns": ["HostTown"],
        "gMapGroup_Indoor": ["HostTown_Shop"],
        "connections_include_order": ["HostTown"],
    }, indent=2) + "\n")

    (root / "data/event_scripts.s").write_text(
        '\t.include "data/maps/HostTown/scripts.inc"\n'
        '\t.include "data/maps/HostTown_Shop/scripts.inc"\n')


def pack(metatile, collision, elevation):
    return metatile | (collision << 10) | (elevation << 12)


def base_spec(**over):
    spec = {
        "name": "HostTown_Annex",
        "group": "gMapGroup_Indoor",
        "header": {"music": "MUS_NONE", "region_map_section": "MAPSEC_HOST"},
        "layout": {
            "primary_tileset": "gTileset_General",
            "secondary_tileset": "gTileset_Host",
            "border": [1, 1, 1, 1],
            "palette": {"#": [0x200, 1, 0], ".": [0x201, 0, 3], "D": [6, 0, 0]},
            "plan": ["####", "....", "..D."],
        },
        "warp_events": [{"x": 2, "y": 2, "elevation": 0,
                         "dest_map": "MAP_HOST_TOWN", "dest_warp_id": "HOST_DOOR"}],
        "scripts": SCRIPTS,
        "host_door": {
            "map": "HostTown",
            "stamp": {"from_x": 4, "from_y": 4, "w": 3, "h": 3},
            "at": [10, 10],
            "door": [11, 12],
            "dest_warp_id": 0,
        },
    }
    spec.update(over)
    return spec


class NewMapTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.hack = self.root / "hack"
        build_fixture(self.hack)
        self.addCleanup(self._tmp.cleanup)

    # -- plumbing --------------------------------------------------------

    def run_tool(self, spec=None, argv_extra=()):
        """Run main() over a spec; returns stdout. Raises SystemExit on refusal."""
        path = self.root / "spec.json"
        path.write_text(json.dumps(spec if spec is not None else base_spec()))
        argv = ["new_map.py", "--hack", str(self.hack), *argv_extra, str(path)]
        buf = io.StringIO()
        old = sys.argv
        sys.argv = argv
        try:
            with contextlib.redirect_stdout(buf):
                nm.main()
        finally:
            sys.argv = old
        return buf.getvalue()

    def expect_refusal(self, spec, needle):
        with self.assertRaises(SystemExit) as cm:
            self.run_tool(spec)
        self.assertIn(needle, str(cm.exception))

    def host_blocks(self):
        data = (self.hack / "data/layouts/HostTown/map.bin").read_bytes()
        return list(struct.unpack(f"<{len(data)//2}H", data))

    def load(self, rel):
        return json.loads((self.hack / rel).read_text())

    # -- the block word --------------------------------------------------

    def test_masks_come_from_the_fork_not_from_a_constant(self):
        masks = nm.read_masks(self.hack)
        self.assertEqual(masks["MAPGRID_METATILE_ID_MASK"], 0x03FF)
        self.assertEqual(masks["MAPGRID_ELEVATION_SHIFT"], 12)

    def test_a_moved_block_format_is_loud_not_silent(self):
        p = self.hack / "include/global.fieldmap.h"
        p.write_text(p.read_text().replace("#define MAPGRID_COLLISION_SHIFT  10", ""))
        with self.assertRaises(SystemExit) as cm:
            nm.read_masks(self.hack)
        self.assertIn("MAPGRID_COLLISION_SHIFT", str(cm.exception))

    def test_pack_unpack_round_trip(self):
        masks = nm.read_masks(self.hack)
        for mt, co, el in [(0, 0, 0), (0x3FF, 3, 15), (0x21F, 1, 0), (513, 0, 3)]:
            word = nm.pack_block(masks, mt, co, el)
            self.assertEqual(nm.unpack_block(masks, word), (mt, co, el))

    def test_pack_refuses_an_out_of_range_metatile(self):
        masks = nm.read_masks(self.hack)
        with self.assertRaises(SystemExit) as cm:
            nm.pack_block(masks, 0x400, 0, 3)
        self.assertIn("out of range", str(cm.exception))

    # -- dump -> plan -> bin, the authoring loop's one invariant ----------

    def test_dump_layout_round_trips_to_identical_bytes(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            nm.dump_layout(self.hack, "LAYOUT_HOST_TOWN")
        dumped = json.loads(buf.getvalue())["layout"]

        masks = nm.read_masks(self.hack)
        rebuilt = [nm.pack_block(masks, *dumped["palette"][c])
                   for row in dumped["plan"] for c in row]
        self.assertEqual(rebuilt, self.host_blocks())
        self.assertEqual(len(dumped["plan"]), HOST_H)
        self.assertEqual(len(dumped["plan"][0]), HOST_W)

    def test_dump_layout_refuses_an_unknown_id(self):
        with self.assertRaises(SystemExit) as cm:
            nm.dump_layout(self.hack, "LAYOUT_NOPE")
        self.assertIn("not found", str(cm.exception))

    # -- the happy path, artifact by artifact ----------------------------

    def test_every_one_of_the_six_edits_lands(self):
        self.run_tool()

        blocks = (self.hack / "data/layouts/HostTown_Annex/map.bin").read_bytes()
        self.assertEqual(len(blocks), 4 * 3 * 2)
        self.assertEqual(
            (self.hack / "data/layouts/HostTown_Annex/border.bin").read_bytes(),
            struct.pack("<4H", 1, 1, 1, 1))

        layouts = self.load("data/layouts/layouts.json")["layouts"]
        self.assertEqual(len(layouts), 2)
        self.assertEqual(layouts[-1]["id"], "LAYOUT_HOST_TOWN_ANNEX")
        self.assertEqual((layouts[-1]["width"], layouts[-1]["height"]), (4, 3))

        m = self.load("data/maps/HostTown_Annex/map.json")
        self.assertEqual(m["id"], "MAP_HOST_TOWN_ANNEX")
        self.assertEqual(m["layout"], "LAYOUT_HOST_TOWN_ANNEX")
        self.assertEqual(m["music"], "MUS_NONE")
        self.assertEqual(m["map_type"], "MAP_TYPE_INDOOR")   # from the defaults
        self.assertEqual(m["connections"], None)

        self.assertEqual(
            (self.hack / "data/maps/HostTown_Annex/scripts.inc").read_text(), SCRIPTS)

        groups = self.load("data/maps/map_groups.json")
        self.assertEqual(groups["gMapGroup_Indoor"], ["HostTown_Shop", "HostTown_Annex"])
        self.assertEqual(groups["gMapGroup_Towns"], ["HostTown"])   # untouched

        inc = (self.hack / "data/event_scripts.s").read_text()
        self.assertEqual(inc.count('"data/maps/HostTown_Annex/scripts.inc"'), 1)
        self.assertLess(inc.index("HostTown_Shop/scripts.inc"),
                        inc.index("HostTown_Annex/scripts.inc"))

    def test_the_new_map_is_APPENDED_to_its_group_never_inserted(self):
        # A map's num is its INDEX in its group and SaveBlock1.location stores
        # that pair, so an insert teleports every existing save.
        self.run_tool()
        self.assertEqual(
            self.load("data/maps/map_groups.json")["gMapGroup_Indoor"][-1],
            "HostTown_Annex")

    def test_the_return_warp_is_pointed_at_the_host_door_it_created(self):
        self.run_tool()
        warps = self.load("data/maps/HostTown_Annex/map.json")["warp_events"]
        # The host had zero warps, so the door became warp 0 and HOST_DOOR
        # resolves to "0" -- a string, as mapjson expects.
        self.assertEqual(warps[0]["dest_warp_id"], "0")
        self.assertEqual(warps[0]["dest_map"], "MAP_HOST_TOWN")

    def test_the_host_gains_exactly_one_warp_on_the_door_tile(self):
        self.run_tool()
        warps = self.load("data/maps/HostTown/map.json")["warp_events"]
        self.assertEqual(len(warps), 1)
        self.assertEqual((warps[0]["x"], warps[0]["y"]), (11, 12))
        self.assertEqual(warps[0]["dest_map"], "MAP_HOST_TOWN_ANNEX")

    # -- the stamp -------------------------------------------------------

    def test_the_stamp_lands_exactly_and_nothing_outside_it_moves(self):
        before = self.host_blocks()
        self.run_tool()
        after = self.host_blocks()

        for dy in range(3):
            for dx in range(3):
                src = before[(4 + dy) * HOST_W + (4 + dx)]
                self.assertEqual(after[(10 + dy) * HOST_W + (10 + dx)], src)

        changed = {(i % HOST_W, i // HOST_W)
                   for i, (a, b) in enumerate(zip(before, after)) if a != b}
        self.assertEqual(changed, {(x, y) for y in range(10, 13) for x in range(10, 13)})

    def test_extra_host_tiles_are_applied_and_asserted(self):
        spec = base_spec()
        spec["host_door"]["tiles"] = [[11, 13, 0x003, 1, 0]]
        self.run_tool(spec)
        after = self.host_blocks()
        self.assertEqual(after[13 * HOST_W + 11], pack(0x003, 1, 0))

    def test_a_stamp_that_runs_off_the_map_is_refused(self):
        spec = base_spec()
        spec["host_door"]["at"] = [18, 18]
        spec["host_door"]["door"] = [19, 20]
        self.expect_refusal(spec, "runs off")

    def test_a_door_outside_the_building_is_refused(self):
        spec = base_spec()
        spec["host_door"]["door"] = [2, 2]
        self.expect_refusal(spec, "outside the stamped building")

    def test_a_dangling_destination_is_refused_before_any_write(self):
        # The engine does not bounds-check dest_warp_id (doc 47): past the end
        # is garbage coordinates, silently.
        spec = base_spec()
        spec["host_door"]["dest_warp_id"] = 5
        self.expect_refusal(spec, "indexes past")
        self.assertFalse((self.hack / "data/maps/HostTown_Annex").exists())

    # -- who was standing there (doc 70 §1) ------------------------------

    def put_host_npcs(self, *coords):
        p = self.hack / "data/maps/HostTown/map.json"
        d = json.loads(p.read_text())
        d["object_events"] = [
            {"graphics_id": "OBJ_EVENT_GFX_BOY_1", "x": x, "y": y, "elevation": 3,
             "movement_type": "MOVEMENT_TYPE_LOOK_AROUND",
             "trainer_type": "TRAINER_TYPE_NONE", "script": "0x0", "flag": "0"}
            for x, y in coords
        ]
        p.write_text(json.dumps(d, indent=2) + "\n")

    def test_a_stamp_over_a_host_npc_is_refused(self):
        # The annex was sited by searching for a 5x5 of plain GROUND, and the
        # search never asked who was standing on it. BOY_1 stood in the wall
        # for a day, past a zero-findings playtest and six specs.
        self.put_host_npcs((11, 11))
        self.expect_refusal(base_spec(), "covers 1 object event")
        # ...before any write: the host layout is untouched.
        self.assertEqual(self.host_blocks()[11 * HOST_W + 11], pack(0x2BB, 0, 3))
        self.assertFalse((self.hack / "data/maps/HostTown_Annex").exists())

    def test_the_refusal_names_who_and_where(self):
        self.put_host_npcs((10, 12), (12, 10))
        with self.assertRaises(SystemExit) as cm:
            self.run_tool()
        msg = str(cm.exception)
        self.assertIn("covers 2 object event", msg)
        self.assertIn("OBJ_EVENT_GFX_BOY_1 at (10,12)", msg)
        self.assertIn("OBJ_EVENT_GFX_BOY_1 at (12,10)", msg)

    def test_an_npc_just_outside_the_footprint_is_fine(self):
        # The four tiles ringing the 3x3 stamp at (10,10). An off-by-one here
        # would make the guard either useless or unusable.
        self.put_host_npcs((9, 10), (13, 10), (10, 9), (10, 13))
        out = self.run_tool()
        self.assertIn("clear of", out)
        self.assertNotIn("COVERED", out)

    def test_allow_covering_npcs_stamps_anyway_and_says_what_it_costs(self):
        self.put_host_npcs((11, 11))
        out = self.run_tool(argv_extra=("--allow-covering-npcs",))
        self.assertIn("COVERED", out)
        self.assertIn("OBJ_EVENT_GFX_BOY_1 at (11,11)", out)
        self.assertIn("WILL stand inside", out)
        self.assertEqual(self.host_blocks()[11 * HOST_W + 11], pack(0x304, 1, 0))

    def test_allow_covering_npcs_is_inert_on_a_clear_site(self):
        out = self.run_tool(argv_extra=("--allow-covering-npcs",))
        self.assertIn("clear of", out)
        self.assertNotIn("COVERED", out)

    # -- the refusals ----------------------------------------------------

    @staticmethod
    def _oversize_spec():
        spec = base_spec()
        spec["layout"]["plan"] = ["." * 90 for _ in range(90)]
        spec["layout"]["palette"] = {".": [1, 0, 3]}
        spec["warp_events"] = []
        spec.pop("host_door")
        return spec

    def test_the_size_ceiling_is_refused_not_discovered_after_a_build(self):
        self.expect_refusal(self._oversize_spec(), "solid void")

    def test_allow_oversize_writes_the_map_and_says_what_it_costs(self):
        # Doc 67 item C needs a map that IS over the ceiling, so the guard rail
        # has a gate. The gate must still write the map, and must say out loud
        # that the result is a void -- a silent override is worse than none.
        out = self.run_tool(self._oversize_spec(), argv_extra=("--allow-oversize",))
        self.assertIn("OVERSIZE", out)
        self.assertIn("solid void", out)
        self.assertEqual(
            len((self.hack / "data/layouts/HostTown_Annex/map.bin").read_bytes(),),
            90 * 90 * 2)
        self.assertEqual(self.load("data/layouts/layouts.json")["layouts"][-1]["height"], 90)

    def test_allow_oversize_does_not_weaken_a_legal_map(self):
        # The flag must be inert when nothing trips the ceiling, or a fixture
        # habit quietly becomes the default and the guard rail is gone.
        out = self.run_tool(argv_extra=("--allow-oversize",))
        self.assertIn("ok      size", out)
        self.assertNotIn("OVERSIZE", out)

    def test_a_ragged_plan_is_refused(self):
        spec = base_spec()
        spec["layout"]["plan"] = ["####", "..."]
        self.expect_refusal(spec, "equal-length rows")

    def test_a_plan_character_with_no_palette_entry_is_refused(self):
        spec = base_spec()
        spec["layout"]["plan"] = ["####", "..Z.", "..D."]
        self.expect_refusal(spec, "no palette entry")

    def test_an_unknown_tileset_is_refused(self):
        spec = base_spec()
        spec["layout"]["secondary_tileset"] = "gTileset_Typo"
        self.expect_refusal(spec, "used by no existing layout")

    def test_an_unknown_group_is_refused(self):
        self.expect_refusal(base_spec(group="gMapGroup_Nope"), "not in map_groups.json")

    def test_scripts_without_the_MapScripts_symbol_are_refused(self):
        # map.json's generated header points at <Name>_MapScripts; without it
        # the map links against nothing and every script pointer goes with it.
        self.expect_refusal(base_spec(scripts="Nothing::\n\tend\n"), "_MapScripts::")

    def test_both_scripts_and_scripts_file_is_refused(self):
        spec = base_spec()
        spec["scripts_file"] = "somewhere.inc"
        self.expect_refusal(spec, "exactly one of")

    def test_neither_scripts_nor_scripts_file_is_refused(self):
        spec = base_spec()
        spec.pop("scripts")
        self.expect_refusal(spec, "exactly one of")

    # -- idempotency: a re-run after a fix must be safe ------------------

    def test_a_second_run_refuses_before_the_first_write(self):
        self.run_tool()
        groups_before = (self.hack / "data/maps/map_groups.json").read_text()
        host_before = self.host_blocks()
        with self.assertRaises(SystemExit) as cm:
            self.run_tool()
        self.assertIn("already", str(cm.exception))
        self.assertEqual((self.hack / "data/maps/map_groups.json").read_text(),
                         groups_before)
        self.assertEqual(self.host_blocks(), host_before)

    def test_an_orphaned_map_dir_is_refused_rather_than_clobbered(self):
        (self.hack / "data/maps/HostTown_Annex").mkdir(parents=True)
        self.expect_refusal(base_spec(), "already exists")

    def test_an_already_present_include_is_refused(self):
        p = self.hack / "data/event_scripts.s"
        p.write_text(p.read_text() + '\t.include "data/maps/HostTown_Annex/scripts.inc"\n')
        self.expect_refusal(base_spec(), "already included")

    # -- the derived identifiers ----------------------------------------

    def test_camel_case_names_become_the_engine_s_screaming_snake(self):
        for name, want in [
            ("RustboroCity_TrainingAnnex", "MAP_RUSTBORO_CITY_TRAINING_ANNEX"),
            ("HostTown_Annex", "MAP_HOST_TOWN_ANNEX"),
            ("Route104_MrBrineysHouse", "MAP_ROUTE104_MR_BRINEYS_HOUSE"),
        ]:
            self.assertEqual(nm.derive_ids(name)[0], want)
            self.assertEqual(nm.derive_ids(name)[1], "LAYOUT_" + want[4:])


if __name__ == "__main__":
    unittest.main()
