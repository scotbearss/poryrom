#!/usr/bin/env python3
"""Fork the pinned pokeemerald-expansion engine into a real, editable hack.

WHY THIS EXISTS
---------------
`engine/` is a READ-ONLY pinned reference clone. It is the ground truth
for every `file:line` citation in docs 39-52, so editing it silently invalidates
the corpus. A hack is therefore a FORK that lives somewhere else:

    hacks/<name>/          <- gitignored (see .gitignore)

That location is not incidental. `tools/verify_hack.py` mounts the ROM's own
directory into the container, which is what makes a ROM outside `engine/`
loadable at all (doc 55 §9.2) -- before that fix, a fork could be built but never
verified.

WHAT IT COPIES, AND WHY IT COPIES IT THAT WAY
---------------------------------------------
`git archive HEAD` piped into `tar -x`, not a filesystem copy. That gets exactly
the tracked tree at the pinned commit, which means:

  * no `.git` (the fork is not a clone; it must never be able to push upstream,
    and it must never carry the reference's history into a new place),
  * no `build/` and no `pokeemerald.gba`/`.sym`/`.map` -- those are gitignored in
    the engine clone, so they simply are not in the archive. Nothing has to be
    excluded by name, which means nothing can be forgotten,
  * no host-tool binaries under `tools/` -- they get rebuilt, costing ~30 s and
    removing any chance of a stale binary from a different tree.

The engine working tree must be CLEAN. If it is dirty, the fork's provenance
would be a commit sha that does not describe the bytes copied, and a provenance
record that can lie is worse than none. `--allow-dirty` overrides, and records
the fact in the manifest.

PROVENANCE
----------
Every fork gets `HACK_MANIFEST.json` at its root recording the base commit, the
`git describe` tag, the tree sha, the upstream remote, and the sha256 of the
engine's own built ROM/`.sym` if present. That is what lets a future session
answer "what is this a fork OF?" without trusting a directory name.

Usage:
    python3 tools/new_hack.py <name>
    python3 tools/new_hack.py <name> --force        # re-fork, wiping
    python3 tools/new_hack.py --list
"""

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys

import hx  # noqa: E402
REPO_ROOT = hx.HARNESS_ROOT
ENGINE = hx.ENGINE
HACKS = hx.HACKS
MANIFEST_NAME = "HACK_MANIFEST.json"

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def git(*args, cwd=ENGINE, check=True):
    run = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and run.returncode != 0:
        fail(f"git {' '.join(args)} failed: {run.stderr.strip()}")
    return run.stdout.strip()


def sha256_of(path):
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_hacks():
    if not HACKS.exists():
        print("no hacks yet (hacks/ does not exist)")
        return
    found = False
    for child in sorted(HACKS.iterdir()):
        if not child.is_dir():
            continue
        found = True
        man = child / MANIFEST_NAME
        if man.exists():
            m = json.loads(man.read_text())
            print(f"{child.name:<20} base {m.get('base_commit', '?')[:12]} "
                  f"({m.get('base_describe', '?')})  forked {m.get('created', '?')}")
        else:
            print(f"{child.name:<20} <no {MANIFEST_NAME} -- not made by this tool>")
    if not found:
        print("no hacks yet")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", help="hack name -> hacks/<name>/")
    ap.add_argument("--force", action="store_true",
                    help="DELETE an existing hacks/<name>/ and re-fork "
                         "it. Without this the tool refuses to touch an "
                         "existing hack, because clobbering someone's edits is "
                         "not something a scaffolding tool should do quietly.")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="fork even though the engine working tree has "
                         "uncommitted changes. The manifest records that the "
                         "base commit does not fully describe the source.")
    ap.add_argument("--list", action="store_true", help="list existing hacks")
    args = ap.parse_args()

    if args.list:
        list_hacks()
        return

    if not args.name:
        fail("give a hack name (or --list)")
    if not NAME_RE.match(args.name):
        fail(f"invalid hack name {args.name!r} -- use [a-z0-9][a-z0-9_-]*, no "
             f"path separators (the fork must land inside hacks/)")

    if not (ENGINE / ".git").exists():
        fail(f"{ENGINE} is not a git clone -- cannot record provenance. "
             f"See CLAUDE.md for the pin.")

    dirty = git("status", "--porcelain")
    if dirty and not args.allow_dirty:
        fail(f"the engine tree at {ENGINE} has uncommitted changes:\n"
             f"{dirty[:800]}\n"
             f"That means the base commit would NOT describe the bytes copied. "
             f"Clean it, or pass --allow-dirty (recorded in the manifest).\n"
             f"NOTE: engine/ is READ-ONLY by policy -- if it is dirty, "
             f"something edited the reference clone and that is the real bug.")

    base_commit = git("rev-parse", "HEAD")
    base_tree = git("rev-parse", "HEAD^{tree}")
    base_describe = git("describe", "--tags", "--always", check=False) or "<none>"
    base_remote = git("config", "--get", "remote.origin.url", check=False) or "<none>"

    dest = HACKS / args.name
    if dest.exists():
        if not args.force:
            fail(f"{dest} already exists -- pass --force to wipe and re-fork it")
        print(f"==> --force: removing existing {dest}")
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    print(f"==> forking {ENGINE}")
    print(f"    commit   {base_commit}")
    print(f"    describe {base_describe}")
    print(f"    remote   {base_remote}")
    print(f"==> into {dest}")

    # git archive, not cp: the tracked tree at HEAD and nothing else. No .git,
    # no build artifacts, no host-tool binaries -- see the module docstring.
    archive = subprocess.Popen(["git", "archive", "--format=tar", "HEAD"],
                               cwd=ENGINE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    untar = subprocess.run(["tar", "-x", "-f", "-", "-C", str(dest)],
                           stdin=archive.stdout, capture_output=True, text=True)
    archive.stdout.close()
    arch_err = archive.stderr.read().decode(errors="replace")
    archive.wait()
    if archive.returncode != 0 or untar.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        fail(f"copy failed (git archive rc={archive.returncode}, "
             f"tar rc={untar.returncode}):\n{arch_err}\n{untar.stderr}")

    files = sum(1 for _ in dest.rglob("*") if _.is_file())
    if (dest / ".git").exists():
        shutil.rmtree(dest / ".git")            # belt and braces; archive has none
    for forbidden in ("build", "pokeemerald.gba", "pokeemerald.sym"):
        if (dest / forbidden).exists():
            fail(f"{forbidden} landed in the fork -- the archive was supposed to "
                 f"contain only tracked sources. Investigate before building.")

    manifest = {
        "hack_name": args.name,
        "created": datetime.datetime.now(datetime.timezone.utc)
                   .replace(microsecond=0).isoformat(),
        "forked_by": "tools/new_hack.py",
        # THE PIN, NOT A PATH. This used to record ENGINE.relative_to(REPO_ROOT)
        # -- the literal string "pokemon/engine" -- which baked one machine's
        # directory layout into every manifest, and which raises outright once
        # the engine lives in a cache shared between game repos. What a future
        # reader needs is which upstream commit this fork came from; that is
        # base_commit/base_describe below, and now the declared ref too.
        "base_engine_ref": hx.ENGINE_REF,
        "base_engine_path": str(ENGINE),
        "base_remote": base_remote,
        "base_commit": base_commit,
        "base_tree_sha": base_tree,
        "base_describe": base_describe,
        "base_tree_dirty": bool(dirty),
        "base_rom_sha256": sha256_of(ENGINE / "pokeemerald.gba"),
        "base_sym_sha256": sha256_of(ENGINE / "pokeemerald.sym"),
        "file_count": files,
        "build_command": 'make -j"$(nproc)" CPP="arm-none-eabi-cpp -std=gnu17"',
        "syms_command": 'make syms CPP="arm-none-eabi-cpp -std=gnu17"',
        "notes": [
            "This tree is a FORK, not a clone: it has no .git and no upstream.",
            "hacks/ is gitignored. Nothing here enters this repo's git.",
            "The engine reference at engine/ is read-only; edit HERE.",
            "The build REQUIRES CPP=\"arm-none-eabi-cpp -std=gnu17\" (doc 54 §1).",
            "The .sym is a SEPARATE target: make syms (doc 54 §2).",
            "An mGBA save state made against the base ROM CANNOT be reused here "
            "-- states are pinned to an exact ROM sha256 (doc 55 §9.3). Verify a "
            "hack with a COLD-BOOT spec that reads data by symbol.",
        ],
    }
    (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"==> {files} files written, {MANIFEST_NAME} recorded")
    rel = dest.relative_to(REPO_ROOT)
    print(f"""
Next:
  # edit the fork (data-level edits first -- see docs/37)
  #   {rel}/src/...

  docker run --rm -v "{dest}:/hack" -w /hack {hx.IMAGE} \\
    bash -c 'export PATH=/opt/devkitpro/devkitARM/bin:$PATH; \\
             make -j"$(nproc)" CPP="arm-none-eabi-cpp -std=gnu17" && \\
             make syms CPP="arm-none-eabi-cpp -std=gnu17"'

  python3 tools/verify_hack.py <spec> \\
    --rom {dest}/pokeemerald.gba --sym {dest}/pokeemerald.sym
""")


if __name__ == "__main__":
    main()
