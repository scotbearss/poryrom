#!/usr/bin/env python3
"""Export a hack fork as a patch + binary assets, and REFUSE to ship one that
does not replay.

`hacks/` is gitignored -- a fork of pokeemerald-expansion is
Nintendo-derived and cannot go into this repo -- so `patches/reps.patch`
plus `patches/assets/reps/` is the ONLY tracked copy of work that is
entirely ours. Until now producing it was a hand-run `diff` with a hand-grown
`-x` list, and `patches/README.md` named this tool as the fix.

WHY IT STOPPED BEING OPTIONAL (2026-08-03). The content phase's first map added
`data/layouts/<Map>/map.bin` -- a BINARY source. `diff -ruN` cannot carry a
binary: it prints "Binary files ... differ" and `patch` skips the line. The
hand recipe would have shipped a patch that applied cleanly, with zero rejects,
and rebuilt a ROM WITH NO BUILDING AND NO ROOM IN IT. That is the moocalf lesson
(the same failure for sprite PNGs, 2026-08-02) recurring the moment a new
binary source class appeared, which is the signature of a rule that needs to be
executable rather than remembered.

WHAT IT DOES

  1. diff -ruN engine/ hacks/<name>/ with the exclusion list below, into
     patches/<name>.patch.
  2. Every file `diff` reported as binary is classified: a GENERATED binary is
     dropped with a note, a SOURCE binary is copied into
     patches/assets/<name>/<same relative path>.
  3. THE REPLAY, and the reason this is a tool: extract the pin clean, apply the
     patch, copy the assets, and byte-compare EVERY file the patch touches plus
     every asset. Any mismatch, any reject, and the tool exits 2 leaving the
     previous patch in place.

WHAT IS EXCLUDED, AND WHY EACH ENTRY IS THERE. Two kinds only:

  * BUILD OUTPUT THAT LIVES IN THE SOURCE TREE. `mapjson` writes header.inc,
    events.inc, connections.inc, groups.inc, headers.inc, layouts.inc,
    layouts_table.inc, map_groups.h, layouts.h and map_group_count.h during a
    build; `gbagfx` writes .4bpp/.lz/.gbapal/.1bpp/fonts; `aif2pcm` writes the
    cries' .bin from their .aif. Carrying these means carrying two copies of
    the same fact, and `patch` sets both mtimes to now, so which one `make`
    believes is a coin toss.
  * BUILD ARTIFACTS AND FORK IDENTITY: build/, .git, HACK_MANIFEST.json, and
    the ROM/ELF/map/sym/sav.

Everything else travels. The rule is deliberately "generated" vs "authored",
never "text" vs "binary" -- getting those two confused is exactly how a binary
source goes missing.

USAGE
    python3 tools/export_hack.py reps
    python3 tools/export_hack.py reps --check   # verify, write nothing

Exit 0 when the patch is written AND replays; 2 on any failure.
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import hx

# Basenames/globs `diff -x` drops. Every one is written by the build.
GENERATED = [
    "build", ".git", "HACK_MANIFEST.json",
    "*.a", "*.elf", "*.gba", "*.map", "*.sym", "*.sav",
    # mapjson
    "events.inc", "header.inc", "connections.inc",
    "groups.inc", "headers.inc",
    "layouts.inc", "layouts_table.inc",
    "map_groups.h", "layouts.h", "map_group_count.h",
    # gbagfx / fonts
    "*.4bpp", "*.lz", "*.gbapal", "*.1bpp",
    "*.latfont", "*.hwjpnfont", "*.fwjpnfont",
]

# Generated BINARIES that `-x` cannot name without also naming a source: the
# cries' .bin comes from aif2pcm, but "*.bin" would swallow every map.bin too.
# Matched on the relative PATH instead, after the diff.
# Files whose class must NOT be left to diff's text/binary heuristic, and files
# that ARE text but that `patch` cannot move faithfully.
#
#  * border.bin is 8 bytes of control characters: diff calls it TEXT and emits a
#    hunk of raw control bytes, while its sibling map.bin is called binary and
#    skipped -- one layout's two files travelling by two mechanisms.
#  * .pal is JASC-PAL, which is CRLF. `patch` rewrites it LF-only: the replayed
#    moocalf palette came back 190 bytes against the fork's 209. That corruption
#    shipped from the day the first species landed and was INVISIBLE, because the
#    asset copy ran afterwards and quietly put the CRLF version back. The
#    redundancy was not redundant, it was the repair.
FORCED_ASSETS = ["map.bin", "border.bin", "*.pal"]

GENERATED_BINARY_PATHS = [
    re.compile(r"^sound/direct_sound_samples/.*\.bin$"),
]

BINARY_RE = re.compile(r"^Binary files (?P<base>\S+) and (?P<fork>\S+) differ$", re.M)


def die(msg: str):
    sys.exit(f"export_hack.py: {msg}")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


MTIME_HEADER = re.compile(r'^((?:---|\+\+\+) \S+)\t.*$', re.M)


def strip_mtimes(patch: str) -> str:
    """The patch with `diff`'s per-file timestamps removed.

    Used for COMPARING two patches. A regenerated fork has today's mtimes, so
    raw text comparison answers "were these files touched?" when the question
    is "did the content drift?". `patch` itself ignores these stamps entirely.
    """
    return MTIME_HEADER.sub(r'\1', patch)


def digest_file(path: Path) -> str | None:
    """A file's content, as a hash. None if it cannot be read -- an absence
    is recorded as an absence."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def write_marker(root: Path, hack: str, rels) -> Path:
    """Record WHAT the replay just proved, file by file.

    Why this exists. The dashboard answers "is my work backed up" from
    mtimes, and mtimes cannot tell an unexported edit from a tree restored
    out of that very patch -- both leave files stamped newer than the patch.
    The exact answer was always available, by re-running the replay, and far
    too slow to run after every build.

    So the replay writes down what it verified while it still knows. A file
    whose content still hashes to what was proved is carried, whatever its
    clock says; a file that hashes to something else is a real edit that is
    not in the backup. That turns a hedge into an answer, and costs one
    small file.

    Written only after a green replay, and only on the writing path -- a
    marker claiming a proof that did not happen would be worse than none."""
    marker = root / "patches" / f"{hack}.verified.json"
    fork = root / "hacks" / hack
    files = {}
    for rel in sorted(set(rels)):
        got = digest_file(fork / rel)
        if got:
            files[rel] = got
    marker.write_text(json.dumps(
        {"version": 1, "at": int(time.time()), "hack": hack,
         "algorithm": "sha256", "files": files}, indent=1) + "\n",
        encoding="utf-8")
    return marker


def engine_ignored(engine: Path, rels: list[str]) -> set[str]:
    """Of `rels`, the ones the ENGINE'S OWN .gitignore calls build products.

    WHY THIS IS NOT A HAND-MAINTAINED LIST (2026-08-06, doc 82 F4/D1). A clean
    rebuild deletes `tools/mgba-rom-test-hydra/mgba-rom-test-hydra` and
    `tools/patchelf/patchelf` from a fork while the engine still has its copies.
    The asymmetry then surfaces as `Binary files ... differ`, those compiled
    binaries enter the patch AS CONTENT, and staging them crashes on a file that
    no longer exists -- after the patch has already been written.

    pokeemerald already answers "is this a build product?" authoritatively, in
    `tools/*/.gitignore`. Asking it is one subprocess and cannot go stale, which
    is the same move this project made when a hand-maintained backup exception
    list became a tool. A hand list would have to be updated every time upstream
    adds a tool; this cannot.
    """
    if not rels:
        return set()
    p = run(["git", "-C", str(engine), "check-ignore", "--stdin"],
            input="\n".join(rels))
    if p.returncode not in (0, 1):        # 0 = some ignored, 1 = none. 128 = not a repo.
        die(f"could not ask {engine} what it ignores: {p.stderr.strip()[:200]}")
    return {line.strip() for line in p.stdout.splitlines() if line.strip()}


def diff_trees(root: Path, fork_rel: str) -> str:
    """diff from the mode root with RELATIVE paths.

    The path depth is load-bearing, not cosmetic: `patch -p1` run from the fork
    root must strip exactly one component and land on `test/level_caps.c`.
    Absolute paths leave `engine/test/level_caps.c` after -p1, patch cannot find
    it, and it prompts "File to patch:" -- which in a non-interactive run
    becomes a silent 6-hunk reject into Oops.rej.
    """
    cmd = ["diff", "-ruN"]
    for x in GENERATED + FORCED_ASSETS:
        cmd += ["-x", x]
    cmd += ["engine/", f"{fork_rel}/"]
    # Decode by hand rather than with text=True. A patch is a TEXT artifact, so
    # any byte here that is not UTF-8 means diff has inlined something binary,
    # and writing that into the patch would produce a corrupt backup rather than
    # a loud failure. See the diagnosis below.
    r = subprocess.run(cmd, cwd=str(root), capture_output=True)
    # diff exits 1 when it finds differences. That is success here.
    if r.returncode not in (0, 1):
        die(f"diff failed ({r.returncode}): "
            f"{r.stderr.decode('utf-8', 'replace').strip()[:400]}")
    try:
        return r.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        # AN UNDOCUMENTED PRECONDITION, found on 2026-08-06 (doc 82 §4.3): the
        # engine and the fork must be in the SAME BUILD STATE. The build writes
        # generated files INTO the source tree (gbagfx .4bpp/.gbapal, aif2pcm
        # .bin), so diffing a built fork against an unbuilt engine makes every
        # one of those look like a brand-new file -- and `diff -N` inlines the
        # ones its text/binary heuristic guesses wrong about, raw bytes and all.
        # In the old repo both trees were always built, so this never appeared.
        die(f"the diff contains non-UTF-8 bytes at offset {exc.start}, which "
            f"means a binary file was inlined into what must be a text patch.\n"
            f"Almost always this is a BUILD-STATE MISMATCH: the fork is built "
            f"and {root / 'engine'} is not (or vice versa), so build-generated "
            f"files exist on one side only.\n"
            f"Build the engine, then re-run. Nothing was written.")


def touched_text_files(patch: str) -> list:
    """Relative paths of the files the patch actually rewrites."""
    out = []
    for line in patch.splitlines():
        if line.startswith("+++ ") and line[4:].startswith("hacks/"):
            rel = line[4:].split("\t")[0]
            out.append(rel.split("/", 2)[2])
    return out


def binary_files(patch: str, fork_name: str) -> tuple:
    """(sources to carry, generated binaries to drop) as relative paths."""
    src, gen = [], []
    prefix = f"hacks/{fork_name}/"
    for m in BINARY_RE.finditer(patch):
        rel = m.group("fork")
        if not rel.startswith(prefix):
            die(f"unexpected binary path in the diff: {rel}")
        rel = rel[len(prefix):]
        (gen if any(p.match(rel) for p in GENERATED_BINARY_PATHS) else src).append(rel)
    return sorted(set(src)), sorted(set(gen))


def forced_assets(engine: Path, fork: Path) -> list:
    """Fork files matching FORCED_ASSETS that are new or differ from the pin."""
    out = []
    for pat in FORCED_ASSETS:
        for f in fork.rglob(pat):
            if "build" in f.parts or ".git" in f.parts:
                continue
            rel = str(f.relative_to(fork))
            base = engine / rel
            if not base.is_file() or not filecmp.cmp(base, f, shallow=False):
                out.append(rel)
    return sorted(out)


def materialize(engine: Path, patch_path: Path, assets: Path, dest: Path,
                asset_rels: list | None = None) -> tuple:
    """THE restore recipe: extract the pin into `dest`, apply the patch with
    `patch -p1 --forward`, copy the binary assets over the tree.

    Returns (ok, problems). ok=False means the tree in `dest` is not a working
    copy (the archive or the patch failed); ok=True with problems means the
    tree stands but named assets were missing.

    This is ONE function shared by replay() below and tools/restore_hack.py,
    deliberately: record 85 §4 found that rebuilding a fork from its backup
    meant re-deriving these steps by hand, and a recipe that exists in two
    copies is a recipe that drifts.

    `asset_rels` limits the copy to named files -- replay passes the list the
    diff just produced, so a missing asset is diagnosed by name. None copies
    everything under `assets`, the restore case, where the tracked asset tree
    itself is the manifest of what travels.
    """
    problems = []
    r = subprocess.run(["git", "-C", str(engine), "archive", "HEAD"],
                       stdout=subprocess.PIPE)
    if r.returncode != 0:
        return False, [f"git archive of the pin at {engine} failed -- "
                       f"is it a clean git clone?"]
    tar = subprocess.run(["tar", "-x", "-C", str(dest)], input=r.stdout)
    if tar.returncode != 0:
        return False, ["tar extraction of the pin failed"]

    p = run(["patch", "-p1", "--forward", "-i", str(patch_path.resolve())], cwd=dest)
    rejects = list(dest.rglob("*.rej"))
    if p.returncode != 0 or rejects:
        problems.append(f"patch did not apply cleanly: rc={p.returncode}, "
                        f"{len(rejects)} reject file(s)")
        for rej in rejects:
            problems.append(f"  reject: {rej.relative_to(dest)}")
        tail = (p.stdout + p.stderr).strip().splitlines()[-6:]
        problems += [f"  patch said: {line}" for line in tail]
        return False, problems

    if asset_rels is None:
        asset_rels = sorted(str(f.relative_to(assets))
                            for f in assets.rglob("*")
                            if f.is_file()) if assets.is_dir() else []
    for rel in asset_rels:
        src = assets / rel
        if not src.is_file():
            problems.append(f"asset missing from patches/assets: {rel}")
            continue
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return True, problems


def replay(engine: Path, patch_path: Path, assets: Path, text_files, bin_files) -> list:
    """Extract the pin clean, apply, copy assets, compare. Returns problems."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "replay"
        tree.mkdir()
        ok, problems = materialize(engine, patch_path, assets, tree,
                                   asset_rels=bin_files)
        if not ok:
            return problems

        for rel in text_files + bin_files:
            a, b = tree / rel, FORK / rel
            if not a.is_file():
                problems.append(f"replay is missing {rel}")
            elif not b.is_file():
                problems.append(f"fork is missing {rel} (stale patch?)")
            elif not filecmp.cmp(a, b, shallow=False):
                problems.append(f"replay differs from the fork: {rel}")
    return problems


def main():
    global FORK
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("hack", help="fork name under hacks/")
    # The directory holding engine/, hacks/ and patches/ -- i.e. the workspace.
    # Every path inside the patch is relative to it (diff_trees runs `diff` with
    # cwd=root), and THAT is what makes `patch -p1` the right strip depth on
    # replay. The two are one decision: change this and re-check the -p1.
    ap.add_argument("--root", default=str(hx.WORKSPACE), help="workspace root")
    ap.add_argument("--check", action="store_true",
                    help="verify the EXISTING patch replays; write nothing")
    args = ap.parse_args()

    root = Path(args.root)
    # THE ENGINE IS NO LONGER A SIBLING OF THE FORK (2026-08-06, doc 82 §6.2).
    # It lives in a cache shared by every game, outside all repos, because a
    # plugin install copies whatever sits inside it. But the patch's shape
    # depends on `engine/` and `hacks/<name>/` being siblings under one root:
    # that is what makes `patch -p1` strip exactly one component and land right.
    # So diff_trees is handed a scratch directory of SYMLINKS with the old
    # layout, and the patch text comes out byte-for-byte as it always did.
    engine = hx.ENGINE
    FORK = root / "hacks" / args.hack
    patch_path = root / "patches" / f"{args.hack}.patch"
    assets = root / "patches" / "assets" / args.hack

    for p in (engine, FORK):
        if not (p / "Makefile").is_file():
            die(f"{p} does not look like a pokeemerald tree")
    status = run(["git", "-C", str(engine), "status", "--porcelain"]).stdout.strip()
    if status:
        die(f"{engine} is dirty -- the patch would be taken against a moved base:\n{status[:400]}")

    with tempfile.TemporaryDirectory() as td:
        layout = Path(td)
        (layout / "engine").symlink_to(engine)
        (layout / "hacks").mkdir()
        (layout / "hacks" / args.hack).symlink_to(FORK)
        patch = diff_trees(layout, f"hacks/{args.hack}")
    text_files = touched_text_files(patch)
    bin_src, bin_gen = binary_files(patch, args.hack)
    bin_src = sorted(set(bin_src) | set(forced_assets(engine, FORK)))

    # Drop anything the engine itself calls a build product (doc 82 F4/D1).
    if (ignored := engine_ignored(engine, bin_src)):
        for rel in sorted(ignored):
            print(f"  dropped (engine build product)  {rel}")
        bin_src = [r for r in bin_src if r not in ignored]

    print(f"{args.hack}: {len(text_files)} file(s) in the patch, "
          f"{len(bin_src)} binary source(s), {len(bin_gen)} generated binary dropped")
    for rel in bin_gen:
        print(f"  dropped (generated)  {rel}")

    if args.check:
        if not patch_path.is_file():
            die(f"{patch_path} does not exist -- nothing to check")
        existing = patch_path.read_text()
        # COMPARE CONTENT, NOT CLOCKS (2026-08-06, doc 82 §4.4). `diff` stamps
        # every ---/+++ header with the file's mtime, and mtimes are a fact
        # about when a tree was checked out, not about what is in it. Comparing
        # raw text therefore made --check FAIL on a fork regenerated from this
        # very patch -- 296 differing lines, every one a timestamp, content
        # byte-identical -- and fail with the words "the fork has moved", which
        # was false and alarming in the one tool whose job is guarding against
        # data loss. On any fresh machine it could never have passed.
        if strip_mtimes(existing) != strip_mtimes(patch):
            die("the fork has moved since the patch was written -- re-run "
                "without --check (the difference is in CONTENT, not just "
                "timestamps)")
    else:
        # ORDER IS THE SAFETY PROPERTY (doc 82 F4/D2). The patch used to be
        # written FIRST and the assets staged after, so a failure mid-staging
        # left a NEW patch beside a half-updated asset tree -- a backup that
        # looks present and is internally inconsistent. For a tool whose entire
        # job is not losing data, that is the one failure mode it must not have.
        # So: prove every source exists, stage them all, and write the patch
        # LAST. If anything goes wrong before that final line, the previous
        # patch is still on disk, still correct, and still the one that replays.
        missing = [rel for rel in bin_src if not (FORK / rel).is_file()]
        if missing:
            die("binary source(s) named by the diff are not on disk -- nothing "
                "written:\n  " + "\n  ".join(missing[:10]))
        for rel in bin_src:
            dst = assets / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(FORK / rel, dst)
            print(f"  asset  {dst}")
        patch_path.write_text(patch)
        print(f"  wrote  {patch_path} ({len(patch.splitlines())} lines)")

    # Assets that are tracked but no longer in the fork's diff: a source that
    # was reverted upstream and never removed here would replay a stale file.
    if assets.is_dir():
        tracked = {str(p.relative_to(assets)) for p in assets.rglob("*") if p.is_file()}
        for rel in sorted(tracked - set(bin_src)):
            if rel in set(text_files):
                # Harmless: the patch already carries it as text, and the asset
                # copy lands the same bytes on top. Named anyway, because a
                # duplicate is a place two copies can drift.
                print(f"  note     patches/assets/{args.hack}/{rel} is redundant "
                      f"(the patch carries it as text)")
            else:
                print(f"  WARNING  patches/assets/{args.hack}/{rel} is in neither the "
                      f"patch nor the fork's diff -- stale, delete it")

    print("==> replaying onto a clean extraction of the pin...")
    problems = replay(engine, patch_path, assets, text_files, bin_src)
    if problems:
        print("==> REPLAY FAILED -- this patch is not a backup:")
        for p in problems:
            print(f"      {p}")
        sys.exit(2)
    print(f"==> replay OK: {len(text_files) + len(bin_src)} file(s) byte-identical "
          f"to the live fork")

    # The proof, written down while it is still true. --check deliberately
    # does not get here: its contract is that it writes nothing, and the
    # marker belongs to the patch that was just written, not to whichever
    # one happened to be on disk.
    if not args.check:
        marker = write_marker(root, args.hack, list(text_files) + list(bin_src))
        print(f"  wrote  {marker} "
              f"({len(json.loads(marker.read_text())['files'])} digests)")


if __name__ == "__main__":
    main()
