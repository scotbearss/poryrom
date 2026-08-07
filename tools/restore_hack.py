#!/usr/bin/env python3
"""Rebuild hacks/<name>/ from its tracked backup: the patch plus the assets.

WHY THIS EXISTS. `hacks/` is gitignored -- a fork of pokeemerald-expansion is
Nintendo-derived and cannot enter any repo -- so a fresh clone of a game repo
arrives with NO working copy at all. The only tracked form of the work is
`patches/<name>.patch` plus `patches/assets/<name>/`. Record 85 §3 rehearsed
getting from that backup to an editable fork and it worked to the byte
(86 files, 0 rejects, rebuilt ROM sha 42c8d33c byte-identical) -- but only by
reading export_hack.py's replay() and performing its steps by hand. §4 filed
that as the gap this tool closes: the restore is one command, not an
archaeology exercise.

WHAT IT DOES -- exactly export_hack.py's replay recipe, via the SAME code
(export_hack.materialize), so the backup that export proved replayable is by
construction the one this restores:

  1. `git archive HEAD` of the pinned engine, extracted into a scratch dir
     inside hacks/.
  2. `patch -p1 --forward -i patches/<name>.patch` -- any reject aborts.
  3. every file under `patches/assets/<name>/` copied over the tree.
  4. ONLY THEN is the scratch dir moved into place as `hacks/<name>/`.

Step 4's ordering is the safety property, the same one export_hack.py writes
its patch last for: an existing fork is never deleted until its replacement has
fully materialized, and a failed restore leaves hacks/ exactly as it was.

MANNERS. Refuses to touch an existing hacks/<name>/ without --force, matching
new_hack.py: clobbering someone's edits is not something a tool does quietly.
A HACK_MANIFEST.json is written recording that the tree came from a restore
and which engine commit it was restored against.

USAGE
    python3 tools/restore_hack.py <name>
    python3 tools/restore_hack.py <name> --force   # replace an existing fork

Exit 0 on a clean restore; 2 on any failure (hacks/ left untouched).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import export_hack
import hx


def fail(msg: str):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def git_out(engine: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(engine), *args],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("hack", help="fork name -- restores from patches/<name>.patch")
    ap.add_argument("--root", default=str(hx.WORKSPACE), help="workspace root")
    ap.add_argument("--force", action="store_true",
                    help="REPLACE an existing hacks/<name>/. Without this the "
                         "tool refuses to touch one, because clobbering "
                         "someone's edits is not something a restore should "
                         "do quietly. Even with it, the old fork is removed "
                         "only after the replacement has fully materialized.")
    args = ap.parse_args()

    root = Path(args.root)
    engine = hx.ENGINE
    patch_path = root / "patches" / f"{args.hack}.patch"
    assets = root / "patches" / "assets" / args.hack
    dest = root / "hacks" / args.hack

    if not (engine / "Makefile").is_file():
        fail(f"{engine} does not look like a pokeemerald tree -- "
             f"run tools/doctor.py for the clone command")
    if not (engine / ".git").exists():
        fail(f"{engine} is not a git clone -- `git archive` needs one. "
             f"Re-clone it rather than copying the directory.")
    if not patch_path.is_file():
        fail(f"{patch_path} does not exist -- nothing to restore from")
    if dest.exists() and not args.force:
        fail(f"{dest} already exists -- pass --force to replace it")

    # Not fatal: `git archive HEAD` reads whatever the clone is at, so a wrong
    # checkout surfaces as rejects below. Naming the likely cause up front
    # beats leaving it to be inferred from a pile of .rej paths.
    describe = git_out(engine, "describe", "--tags", "--always")
    if describe and describe != hx.ENGINE_REF:
        print(f"WARNING: the engine is at {describe}, not the pin "
              f"{hx.ENGINE_REF} -- if the patch rejects below, this is why")

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=dest.parent, prefix=f".restore-{args.hack}."))
    try:
        print(f"==> extracting the pin at {engine}")
        print(f"==> applying {patch_path.name} and copying assets...")
        ok, problems = export_hack.materialize(engine, patch_path, assets, tmp)
        if not ok or problems:
            print("==> RESTORE FAILED -- hacks/ was not touched:")
            for p in problems:
                print(f"      {p}")
            sys.exit(2)

        patched = export_hack.touched_text_files(patch_path.read_text())
        n_assets = (sum(1 for f in assets.rglob("*") if f.is_file())
                    if assets.is_dir() else 0)

        manifest = {
            "hack_name": args.hack,
            "created": datetime.datetime.now(datetime.timezone.utc)
                       .replace(microsecond=0).isoformat(),
            "forked_by": "tools/restore_hack.py",
            "restored_from": str(patch_path.relative_to(root)),
            "base_engine_ref": hx.ENGINE_REF,
            "base_engine_path": str(engine),
            "base_remote": git_out(engine, "config", "--get",
                                   "remote.origin.url") or "<none>",
            "base_commit": git_out(engine, "rev-parse", "HEAD"),
            "base_describe": describe or "<none>",
            "build_command": 'make -j"$(nproc)" CPP="arm-none-eabi-cpp -std=gnu17"',
            "syms_command": 'make syms CPP="arm-none-eabi-cpp -std=gnu17"',
            "notes": [
                "This tree was RESTORED from the tracked patch + assets, not "
                "forked fresh -- see restored_from.",
                "hacks/ is gitignored. Nothing here enters the repo's git.",
                "The build REQUIRES CPP=\"arm-none-eabi-cpp -std=gnu17\" (doc 54 §1).",
            ],
        }
        (tmp / "HACK_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")

        if dest.exists():
            print(f"==> --force: removing the old {dest}")
            shutil.rmtree(dest)
        tmp.rename(dest)
        os.chmod(dest, 0o755)   # mkdtemp made it 0700
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)

    files = sum(1 for f in dest.rglob("*") if f.is_file())
    print(f"==> restored {dest}: {files} files "
          f"({len(patched)} from the patch, {n_assets} binary asset(s))")
    print(f"""
Next:
  docker run --rm -v "{dest}:/hack" -w /hack {hx.IMAGE} \\
    bash -c 'export PATH=/opt/devkitpro/devkitARM/bin:$PATH; \\
             make -j"$(nproc)" CPP="arm-none-eabi-cpp -std=gnu17" && \\
             make syms CPP="arm-none-eabi-cpp -std=gnu17"'
""")


if __name__ == "__main__":
    main()
