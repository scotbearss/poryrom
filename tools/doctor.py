#!/usr/bin/env python3
"""doctor -- can this machine actually build and verify a game right now?

WHY. "Plug and play" is a claim about a machine you have not seen. Every failure
this harness can hit before it reaches the interesting part -- no Docker daemon,
no build image, an engine that is not a git clone, a game repo whose harness
version does not match the installed plugin -- produces an error somewhere deep
in a build log, minutes later, worded for whoever wrote the tool. This asks all
of those questions up front and answers them in one screen.

HARD vs SOFT. A hard check must pass before anything can build; a soft one only
closes off an optional road (art generation, hardware deploy). Soft failures are
reported and do not set the exit code, because a person who never generates
sprites should not be told their setup is broken.

Exit 0 = every hard check passed.  Exit 1 = at least one hard check failed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import hx

OK, WARN, BAD = "  ok  ", " warn ", " FAIL "
results: list[tuple[str, str, str, str]] = []   # (level, name, detail, fix)


def check(hard: bool, name: str, passed: bool, detail: str, fix: str = ""):
    results.append((OK if passed else (BAD if hard else WARN), name, detail, fix))
    return passed


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(*cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kw)
    except Exception:                                   # noqa: BLE001 - any failure is "no"
        return None


def main() -> int:
    print(f"harness    {hx.HARNESS_ROOT}")
    print(f"workspace  {hx.WORKSPACE}")
    print(f"game       {hx.GAME or '(none declared -- no harness.json here)'}")
    print()

    # ---- hard: the build road ------------------------------------------------
    docker = have("docker")
    check(True, "docker installed", docker, "the `docker` command",
          "install Docker Desktop")
    daemon = False
    if docker:
        r = run("docker", "info", "--format", "{{.ServerVersion}}")
        daemon = bool(r and r.returncode == 0)
        check(True, "docker daemon running", daemon,
              (r.stdout.strip() if daemon else "not responding"),
              "start Docker Desktop and wait for the whale to settle")
    if daemon:
        # `docker image ls -q`, NOT `docker image inspect`. On Docker 29.6.1
        # here, inspect answers "no such object" for an image that ls lists and
        # `docker run` happily starts -- so inspect would have reported a
        # missing build image on a machine that had just built two ROMs with it.
        # The doctor's very first run caught a false negative in its own probe;
        # read the instrument before believing the reading.
        r = run("docker", "image", "ls", "-q", hx.IMAGE)
        has_img = bool(r and r.returncode == 0 and r.stdout.strip())
        check(True, f"build image {hx.IMAGE}", has_img,
              "present" if has_img else "missing",
              f"docker build -f {hx.HARNESS_ROOT}/docker/Dockerfile "
              f"-t {hx.IMAGE} {hx.HARNESS_ROOT}/docker")

    check(True, "git installed", have("git"), "the `git` command", "install git")
    check(True, "python3 >= 3.9", sys.version_info >= (3, 9),
          ".".join(map(str, sys.version_info[:3])), "install a newer python3")

    # ---- hard: the engine ----------------------------------------------------
    eng = hx.ENGINE
    if check(True, "engine clone present", (eng / "Makefile").is_file(), str(eng),
             f"git clone https://github.com/rh-hideout/pokeemerald-expansion "
             f"{eng} && git -C {eng} checkout {hx.ENGINE_REF}"):
        # It must be a CLONE, not an unpacked tarball: new_hack.py forks via
        # `git archive` and reads describe/rev-parse for the fork's provenance.
        isrepo = (eng / ".git").exists()
        check(True, "engine is a git clone", isrepo,
              "has .git" if isrepo else "no .git -- provenance cannot be recorded",
              "re-clone it rather than copying the directory")
        if isrepo:
            r = run("git", "-C", str(eng), "describe", "--tags", "--always")
            got = r.stdout.strip() if r else "?"
            check(True, f"engine at the pin ({hx.ENGINE_REF})", got == hx.ENGINE_REF,
                  got, f"git -C {eng} checkout {hx.ENGINE_REF}")
            r = run("git", "-C", str(eng), "status", "--porcelain")
            clean = bool(r and not r.stdout.strip())
            check(True, "engine tree clean", clean,
                  "clean" if clean else "DIRTY -- it is a read-only reference",
                  f"git -C {eng} checkout -- .")

        # ---- soft: engine BUILT, not just present (record 85 §4) ------------
        # The build writes generated files INTO the source tree, and
        # export_hack.py refuses to diff a built fork against an unbuilt
        # engine (the record 82 §4.3 guard). On a fresh clone that guard fires
        # on the FIRST backup refresh after a fork build -- ~10 minutes into
        # feeling done. Its message carries the fix, so it is a speed bump,
        # not a wall; this check names the bump before anyone hits it. Soft,
        # because forking and building a hack work fine either way.
        built = (eng / "pokeemerald.gba").is_file() or \
            next(eng.rglob("*.4bpp"), None) is not None
        check(False, "engine clone built", built,
              "built (generated files present)" if built else
              "unbuilt -- the first backup refresh after a fork build will "
              "stop on export_hack.py's build-state mismatch (record 82 §4.3)",
              f'docker run --rm -v "{eng}:/src" -w /src {hx.IMAGE} bash -c '
              "'export PATH=/opt/devkitpro/devkitARM/bin:$PATH; "
              'make -j"$(nproc)" CPP="arm-none-eabi-cpp -std=gnu17"\'')

    # ---- soft: version pin ---------------------------------------------------
    cfg_ver = (hx.CONFIG.get("harness") or {}).get("version")
    if cfg_ver:
        man = hx.HARNESS_ROOT / ".claude-plugin" / "plugin.json"
        inst = json.loads(man.read_text())["version"] if man.is_file() else "?"
        check(False, "harness version matches this game's pin", cfg_ver == inst,
              f"game wants {cfg_ver}, installed is {inst}",
              "update the plugin, or change harness.version in harness.json "
              "if you have checked the difference is safe")

    # ---- soft: savestates ----------------------------------------------------
    # Doc 82 §4.5: .ss1 files are gitignored, so a fresh clone has sidecars and
    # no states, and 77 of 114 specs simply cannot run. Silence there would read
    # as "all checks passed".
    if hx.SAVES.is_dir():
        sidecars = list(hx.SAVES.glob("*.ss1.json"))
        missing = [s for s in sidecars if not s.with_suffix("").exists()]
        check(False, "savestates present", not missing,
              f"{len(sidecars) - len(missing)}/{len(sidecars)} present"
              + (f"; missing {', '.join(p.name[:-len('.ss1.json')] for p in missing[:4])}"
                 f"{'...' if len(missing) > 4 else ''}" if missing else ""),
              "python3 tools/make_savestate.py <name>  (NOTE: regenerating "
              "re-rolls the starter -- see doc 82 §4.5)")

    # ---- soft: the optional roads -------------------------------------------
    check(False, "OPENAI_API_KEY set", bool(os.environ.get("OPENAI_API_KEY")),
          "for concept art via make_reference.py",
          "export OPENAI_API_KEY in ~/.zshrc (only needed to generate art)")
    check(False, "RETRODIFFUSION_API_KEY set",
          bool(os.environ.get("RETRODIFFUSION_API_KEY")),
          "for make_pixel.py",
          "export RETRODIFFUSION_API_KEY in ~/.zshrc (optional)")

    # ---- soft: disk ----------------------------------------------------------
    try:
        free_gb = shutil.disk_usage(hx.WORKSPACE).free / 1e9
        check(False, "disk space", free_gb > 5, f"{free_gb:.1f} GB free",
              "a fork is ~0.5 GB built; the engine ~1 GB built")
    except OSError:
        pass

    # ---- report --------------------------------------------------------------
    width = max(len(n) for _, n, _, _ in results)
    for level, name, detail, fix in results:
        print(f"[{level}] {name:{width}}  {detail}")
        if level != OK and fix:
            print(f"{'':>9}-> {fix}")
    hard_fails = sum(1 for lvl, *_ in results if lvl == BAD)
    warns = sum(1 for lvl, *_ in results if lvl == WARN)
    print()
    if hard_fails:
        print(f"{hard_fails} blocking problem(s). Fix those and run doctor again.")
    elif warns:
        print(f"Ready to build. {warns} optional thing(s) not set up -- fine "
              f"unless you need them.")
    else:
        print("Everything checks out.")
    return 1 if hard_fails else 0


if __name__ == "__main__":
    sys.exit(main())
