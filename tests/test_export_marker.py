#!/usr/bin/env python3
"""Unit tests for the backup marker -- no docker, no real engine, no replay.

WHY THIS FILE EXISTS
--------------------
dex-site-requirements.md §9.7 named an ambiguity the dashboard could not
resolve: a file stamped newer than the patch is either an edit that is not
backed up, or a tree restored out of that very patch, and a clock cannot
tell those two apart. The exact answer needed the replay, which is far too
slow to run after every build.

So the replay now writes down what it proved, file by file, and the
dashboard reads content instead of clocks. That marker is a claim about a
proof, which makes it exactly the kind of file that must not be written
optimistically -- these tests pin what it contains and, more importantly,
when it is allowed to exist at all.

The dashboard's half of this lives in tests/test_make_dex.py
(BackupMarkerTests), which covers the reading.

    python3 -m unittest discover -s tests -v
"""

import hashlib
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import export_hack as eh  # noqa: E402


class MarkerTests(unittest.TestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fork = self.tmp / "hacks/reps"
        (self.fork / "src").mkdir(parents=True)
        (self.tmp / "patches").mkdir()

    def own(self, rel, text):
        p = self.fork / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode())
        return rel

    def read_marker(self):
        return json.loads((self.tmp / "patches/reps.verified.json")
                          .read_text(encoding="utf-8"))

    def test_it_records_a_digest_for_every_file_the_replay_proved(self):
        rels = [self.own("src/a.c", "alpha"), self.own("src/b.c", "beta")]
        eh.write_marker(self.tmp, "reps", rels)
        got = self.read_marker()
        self.assertEqual(got["version"], 1)
        self.assertEqual(got["algorithm"], "sha256")
        self.assertEqual(sorted(got["files"]), ["src/a.c", "src/b.c"])
        self.assertEqual(got["files"]["src/a.c"],
                         hashlib.sha256(b"alpha").hexdigest())

    def test_the_digest_moves_when_the_content_does_and_not_before(self):
        """The whole point: this has to answer "same bytes?", not "same
        file?". A rewritten-identical file must hash the same."""
        self.own("src/a.c", "alpha")
        eh.write_marker(self.tmp, "reps", ["src/a.c"])
        first = self.read_marker()["files"]["src/a.c"]
        self.own("src/a.c", "alpha")            # rewritten, same bytes
        eh.write_marker(self.tmp, "reps", ["src/a.c"])
        self.assertEqual(self.read_marker()["files"]["src/a.c"], first)
        self.own("src/a.c", "alpha and more")
        eh.write_marker(self.tmp, "reps", ["src/a.c"])
        self.assertNotEqual(self.read_marker()["files"]["src/a.c"], first)

    def test_a_file_that_cannot_be_read_is_left_out_not_faked(self):
        """A marker is a record of a proof. An entry for a file nobody read
        would be a proof that did not happen, so absence is recorded as
        absence and the dashboard treats an unlisted file as uncarried."""
        rels = [self.own("src/a.c", "alpha"), "src/vanished.c"]
        eh.write_marker(self.tmp, "reps", rels)
        self.assertEqual(list(self.read_marker()["files"]), ["src/a.c"])

    def test_the_same_file_named_twice_is_recorded_once(self):
        """text_files and bin_src can overlap -- export_hack itself prints a
        note when an asset is also carried as text."""
        self.own("src/a.c", "alpha")
        eh.write_marker(self.tmp, "reps", ["src/a.c", "src/a.c"])
        self.assertEqual(list(self.read_marker()["files"]), ["src/a.c"])

    def test_digest_file_reports_an_unreadable_file_as_nothing(self):
        self.assertIsNone(eh.digest_file(self.fork / "not/here.c"))
        self.own("src/a.c", "alpha")
        self.assertEqual(eh.digest_file(self.fork / "src/a.c"),
                         hashlib.sha256(b"alpha").hexdigest())


if __name__ == "__main__":
    unittest.main()
