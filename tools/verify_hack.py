#!/usr/bin/env python3
"""Generic symbol-reading verification harness for the Pokémon Thing mode.

This is Slice 1's core deliverable: the pokeemerald-side equivalent of
tools/verify_spec.py. Where the Butano side asserts against KEYPOINT lines the
*game* chose to print, this side asserts against RAM the game does not know is
being read -- resolved by name out of the ROM's own pokeemerald.sym. That is the
only mechanism available here, because we cannot make an unmodified engine
narrate itself, and it is strictly better for our purposes: state cannot be
faked by instrumenting the thing under test.

It generalises tools/boot_proof.py (three hardcoded gMain fields) into a
spec-driven harness. boot_proof.py stays as-is: it is the reference, and
verify_hack.py imports its symbol table and range resolver rather than
reimplementing them, so there is exactly one resolver in this mode.

THE DISCIPLINE (docs/research/06-ai-harness-lessons.md), restated because it is
the whole point of the design:

  * harness/read_symbols.lua contains ZERO assertions. It samples memory
    and prints. It never sees the spec's expectations.
  * Every pass/fail judgement happens HERE, outside the emulator, against values
    the Lua produced but did not interpret, and expectations the Lua never saw.
  * The spec is inert JSON. It is data, not code -- it cannot be made to pass
    itself.
  * Every proof needs a counterfactual that FAILs. Two are supported:
    --counterfactual (shift every probe's base address into unrelated memory,
    which must break any spec that reads real state) and, better, a spec file
    whose expected values are deliberately wrong.

SPEC FORMAT (hand-writable JSON; see verify/*.json)
----------------------------------------------------------
{
  "name": "...", "description": "...",
  "screenshot": true,
  "savestate": "emerald_party.ss1",   # optional: resume from saves/
                                      #   instead of cold-booting. Required for
                                      #   any assertion about GAMEPLAY state --
                                      #   see below.
  "timeline": [                       # input playback, in order
    {"name": "boot",  "frames": 600, "keys": []},
    {"name": "press", "frames": {"random_range": [20, 40]}, "keys": ["A"]}
  ],
  "probes": [
    {"id": "callback2",               # referenced by assertions
     "symbol": "gMain",               # resolved from pokeemerald.sym
     "offset": 4,                     # optional, default 0
     "type": "ptr",                   # u8|u16|u32|s8|s16|s32|ptr|bytes
     "length": 8,                     # bytes only
     "deref": false,                  # read32(symbol+base_offset), then read
     "base_offset": 0,                #   at ptr+offset. base_offset locates the
                                      #   POINTER; offset indexes past it.
     "sample": {"every": 60,          # any combination of:
                "at": [1, 300],       #   absolute frames
                "at_step_end": ["boot"],
                "at_step_start": ["press"]}}
  ],
  "assert": [ {"probe": "callback2", "check": "...", ...} ]
}

deref is REQUIRED for saveblock access. gSaveBlock1Ptr / gSaveBlock2Ptr are
re-rolled at every battle start and every map load (doc 44's ASLR correction),
so the harness re-reads the pointer on every sample and never caches it. Note
that per doc 44 SaveBlock3 is NOT ASLR'd; that changes nothing here, since
re-reading a stable pointer is merely redundant, not wrong.

CHECKS (all evaluated in this file)
    strictly_increases        values rise strictly across samples, in order
    non_decreasing            values never fall
    constant                  every sample equal
    changes_at_least          {count} consecutive-value transitions
    distinct_symbols_at_least {count} distinct resolved symbol names
    compare                   {at, op, value, tolerance}
    in_range                  {at, min, max}
    resolves                  {at, of, allow_zero} every sample names a symbol
    symbol_at                 {at, of, op: ==|!=|in|not_in, value}
    symbol_sequence           {of, op: equals|contains_in_order, value: [names]}
    always_valid              no sample was unreadable (bad deref / no sample)
    sample_count              {op, value}
  `at`  : "first" | "last" | "all" | "any" | <frame number>   (default "last")
  `of`  : "value" | "ptr"  -- on a deref probe, whether the check looks at the
          value found at the end of the chase or at the pointer that was
          chased. Defaults to "value" for every check and every probe kind.
          (strictly_increases / non_decreasing / constant / changes_at_least
          always read the value.)

SAVE STATES (how a spec reaches real gameplay)
----------------------------------------------
A spec's "savestate" key names a committed state under saves/, loaded
with mGBA's -t. Reaching a party by replaying input costs 31,000 frames AND is
not reproducible in the details that matter: the navigation path is
deterministic but the boot RNG is not, so the starter's personality, IVs and
maxHP differ on every cold boot (measured -- tools/make_savestate.py
--determinism). Booting the committed state is what makes an exact-value
gameplay assertion legitimate rather than flaky.

The state is build-specific. verify_hack.py hard-fails if the sidecar .json's
rom_sha256 disagrees with the ROM under test, because a stale state resumes
into plausible-looking nonsense rather than erroring.

ROM AND SYM ARE ONE PAIR (doc 57 §5, closed)
--------------------------------------------
--sym defaults to the ROM's OWN SIBLING .sym, and the two are then proved to be
the same build by CONTENT before any symbol is resolved -- both are derived from
pokeemerald.elf, so the ELF is what links them. See tools/rom_pair.py.
It used to default to the engine's .sym regardless of --rom, which silently
resolved a hack's probes against a different build's symbol table.

Usage:
    python3 tools/verify_hack.py <spec>            # name or path
    python3 tools/verify_hack.py <spec> --rom <hack>/pokeemerald.gba
    python3 tools/verify_hack.py <spec> --counterfactual   # must FAIL
    python3 tools/verify_hack.py <spec> --no-savestate     # must FAIL
"""

import argparse
import array
import hashlib
import fcntl
import os
import json
import pathlib
import random
import re
import shutil
import subprocess
import sys
import wave

import hx  # noqa: E402
REPO_ROOT = hx.HARNESS_ROOT
ENGINE = hx.ENGINE
HARNESS = hx.HARNESS
SPEC_DIR = hx.SPEC_DIR
SAVES = hx.SAVES
IMAGE = hx.IMAGE

# One resolver in this mode, not two. boot_proof.py owns it; this imports it.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rom_pair  # noqa: E402
from boot_proof import load_symbols, resolve  # noqa: E402

DEFAULT_ROM = "pokeemerald.gba"

GBA_KEYS = {"A", "B", "Select", "Start", "Right", "Left", "Up", "Down", "R", "L"}

TYPE_SIZES = {"u8": 1, "u16": 2, "u32": 4, "s8": 1, "s16": 2, "s32": 4,
              "ptr": 4, "bytes": 0}
SIGNED = {"s8", "s16", "s32"}

SAMPLE_RE = re.compile(
    r"SYMPROBE frame=(\d+) id=(\S+) (?:ptr=([0-9a-f]{8}) )?value=(\S+)")

OPS = {
    "==": lambda a, b, tol: a == b,
    "!=": lambda a, b, tol: a != b,
    "<": lambda a, b, tol: a < b,
    "<=": lambda a, b, tol: a <= b,
    ">": lambda a, b, tol: a > b,
    ">=": lambda a, b, tol: a >= b,
    "approx": lambda a, b, tol: abs(a - b) <= tol,
}

# The counterfactual shift: far enough past any probed struct to land in
# unrelated memory, small enough to stay inside the same RAM region (so the
# failure is "you read the wrong thing", not "the emulator refused to read").
COUNTERFACTUAL_SHIFT = 0x800


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------
# spec resolution
# --------------------------------------------------------------------------

def resolve_timeline(timeline, rng):
    """Expand a spec timeline into concrete per-step frame counts.

    Randomized-duration steps ({"frames": {"random_range": [lo, hi]}}) exist for
    the same reason they do on the Butano side: an assertion that only holds for
    one exact scripted replay is an assertion about the replay, not the game.
    """
    if not timeline:
        fail("spec timeline is empty -- nothing to run")
    resolved, start = [], 1
    for step in timeline:
        for key in step.get("keys", []):
            if key not in GBA_KEYS:
                fail(f"unknown key {key!r} (valid: {sorted(GBA_KEYS)})")
        spec_frames = step["frames"]
        if isinstance(spec_frames, dict):
            lo, hi = spec_frames["random_range"]
            frames = rng.randint(int(lo), int(hi))
        else:
            frames = int(spec_frames)
        if frames < 1:
            fail(f"timeline step {step.get('name')!r} has {frames} frames")

        if "mash" in step:
            resolved.extend(expand_mash(step, frames, start))
            start += frames
            continue

        resolved.append({"name": step.get("name"), "frames": frames,
                         "keys": step.get("keys", []),
                         "start": start, "end": start + frames - 1})
        start += frames
    return resolved


def expand_mash(step, frames, start):
    """Expand one {"mash": KEY, ...} step into alternating press/release runs.

    WHY THIS EXISTS. Emerald's field and text code reads JOY_NEW, so a HELD
    button registers exactly once -- every "advance the text" beat has to be a
    real press/release cycle. Spelling that out a step at a time made
    verify/reps-cap-bites-*.json about 1,700 lines each, ~1,560 of which
    were generated single-frame noise (doc 59 §9.5). This is the same op_mash()
    that tools/make_savestate.py has always had, moved into the shared
    evaluator so specs can say it once:

        {"name": "battle", "mash": "A", "frames": 2600, "on": 6, "off": 14}

    Expansion happens HERE, in the one fixed evaluator every spec is judged by,
    rather than in each spec -- so no spec can quietly mash differently from its
    neighbour. The sub-steps all keep the parent's NAME, which is what lets
    "at_step_end": ["battle"] mean the end of the whole mash (see step_frame).

    The frame total is exact: the last run is truncated to land on `frames`, so
    a mash never overruns its budget and a sample computed from it can never
    fall outside the run.
    """
    key = step["mash"]
    if key not in GBA_KEYS:
        fail(f"unknown mash key {key!r} (valid: {sorted(GBA_KEYS)})")
    if step.get("keys"):
        fail(f"timeline step {step.get('name')!r} sets both 'mash' and 'keys'; "
             f"a mash step drives exactly one key -- use separate steps")
    on, off = int(step.get("on", 6)), int(step.get("off", 14))
    if on < 1 or off < 1:
        fail(f"timeline step {step.get('name')!r} has on={on} off={off}; "
             f"both must be >= 1 or the mash is not a press/release cycle")

    out, spent = [], 0
    while spent < frames:
        for run_keys in ([key], []):
            if spent >= frames:
                break
            n = min(on if run_keys else off, frames - spent)
            out.append({"name": step.get("name"), "frames": n, "keys": run_keys,
                        "start": start + spent, "end": start + spent + n - 1,
                        "mash": True})
            spent += n
    return out


def step_frame(resolved_timeline, name, which):
    """First `start` or LAST `end` of the named step.

    The asymmetry is deliberate and is what makes a mash step addressable: one
    spec step expands into many resolved sub-steps that all share its name, so
    "the end of `battle`" has to mean the end of the last of them, not the first.
    For an ordinary one-to-one step both directions are the same entry, so this
    is a no-op there.
    """
    hits = [s for s in resolved_timeline if s["name"] == name]
    if not hits:
        fail(f"sample refers to timeline step {name!r}, which does not exist")
    return hits[0]["start"] if which == "start" else hits[-1]["end"]


def collapse_mash_for_display(resolved_timeline):
    """Fold each run of mash sub-steps back into one line for the run header.

    Display only -- the emulator still receives every individual press and
    release. Nothing downstream reads this.
    """
    out = []
    for step in resolved_timeline:
        if step.get("mash") and out and out[-1].get("mash") \
                and out[-1]["name"] == step["name"]:
            out[-1] = {**out[-1], "end": step["end"],
                       "keys": [f"mash {out[-1]['keys'][0]}"]
                               if out[-1]["keys"] else out[-1]["keys"]}
            continue
        out.append(dict(step))
    return out


def resolve_probes(spec, by_name, resolved_timeline, total_frames,
                   counterfactual):
    probes = []
    seen_ids = set()
    for p in spec.get("probes", []):
        pid = p["id"]
        if pid in seen_ids:
            fail(f"duplicate probe id {pid!r}")
        seen_ids.add(pid)

        ptype = p.get("type", "u32")
        if ptype not in TYPE_SIZES:
            fail(f"probe {pid!r}: unknown type {ptype!r} "
                 f"(valid: {sorted(TYPE_SIZES)})")
        size = TYPE_SIZES[ptype]
        length = int(p.get("length", 0))
        if ptype == "bytes":
            if length < 1:
                fail(f"probe {pid!r}: type 'bytes' needs a positive 'length'")
        elif length:
            fail(f"probe {pid!r}: 'length' is only meaningful for type 'bytes'")

        symbol = p["symbol"]
        if symbol not in by_name:
            fail(f"probe {pid!r}: symbol {symbol!r} not in pokeemerald.sym")
        sym_addr, sym_size = by_name[symbol]
        offset = int(p.get("offset", 0))
        base_offset = int(p.get("base_offset", 0))
        deref = bool(p.get("deref", False))
        if base_offset and not deref:
            fail(f"probe {pid!r}: base_offset is only meaningful with deref "
                 f"(it locates the pointer); use offset for a direct read")

        # Bounds guard against a typo'd offset silently reading a neighbouring
        # global. For a deref it can only check where the POINTER lives: what
        # the pointer points at is outside this symbol's extent by definition.
        span = length if ptype == "bytes" else size
        if sym_size and not p.get("allow_out_of_bounds"):
            reach, what = ((base_offset + 4, "base_offset") if deref
                           else (offset + span, "offset"))
            if reach > sym_size:
                fail(f"probe {pid!r}: {what} reaches {reach:#x} past the end of "
                     f"{symbol} (size {sym_size:#x}). Set "
                     f"\"allow_out_of_bounds\": true if that is intended.")

        addr = sym_addr + (base_offset if deref else offset)
        if counterfactual:
            addr += COUNTERFACTUAL_SHIFT

        sample = p.get("sample", {}) or {}
        every = int(sample.get("every", 0))
        at = set(int(f) for f in sample.get("at", []))
        for nm in sample.get("at_step_end", []):
            at.add(step_frame(resolved_timeline, nm, "end"))
        for nm in sample.get("at_step_start", []):
            at.add(step_frame(resolved_timeline, nm, "start"))
        if not every and not at:
            at.add(total_frames)          # default: sample once, at the end
        out_of_run = sorted(f for f in at if f < 1 or f > total_frames)
        if out_of_run:
            fail(f"probe {pid!r}: sample frames {out_of_run} lie outside the "
                 f"{total_frames}-frame run")

        probes.append({
            "id": pid, "symbol": symbol, "sym_addr": sym_addr, "addr": addr,
            "offset": offset, "base_offset": base_offset,
            "deref": deref, "type": ptype, "size": size,
            "length": length, "every": every, "at": sorted(at),
            "why": p.get("why", ""),
        })
    if not probes:
        fail("spec declares no probes")
    return probes


# Required extra keys per check, used for static validation BEFORE the ROM runs.
CHECKS = {
    "strictly_increases": (), "non_decreasing": (), "constant": (),
    "changes_at_least": ("count",), "distinct_symbols_at_least": ("count",),
    "compare": ("value",), "in_range": ("min", "max"), "resolves": (),
    "symbol_at": ("value",), "symbol_sequence": ("value",),
    "symbol_never": ("value",),
    "always_valid": (), "sample_count": ("value",),
}


def validate_assertions(spec, probes):
    """Reject a malformed spec before spending a docker run on it.

    Also catches the worst spec smell there is: no assertions at all. A spec
    that cannot fail is not a proof.
    """
    assertions = spec.get("assert", [])
    if not assertions:
        fail("spec declares no assertions -- a spec that cannot fail is not a "
             "proof")
    ids = {p["id"] for p in probes}
    for i, a in enumerate(assertions):
        where = f"assert[{i}]"
        if "probe" not in a or "check" not in a:
            fail(f"{where}: needs both 'probe' and 'check'")
        if a["probe"] not in ids:
            fail(f"{where}: no probe with id {a['probe']!r} "
                 f"(declared: {sorted(ids)})")
        if a["check"] not in CHECKS:
            fail(f"{where}: unknown check {a['check']!r} "
                 f"(valid: {sorted(CHECKS)})")
        for key in CHECKS[a["check"]]:
            if key not in a:
                fail(f"{where}: check {a['check']!r} requires {key!r}")
        op = a.get("op")
        if a["check"] in ("compare", "sample_count") and op and op not in OPS:
            fail(f"{where}: unknown op {op!r} (valid: {sorted(OPS)})")
        if a.get("of") not in (None, "value", "ptr"):
            fail(f"{where}: 'of' must be \"value\" or \"ptr\"")


def write_probe_data(probes, resolved_timeline, total_frames, screenshot, path):
    lines = ["-- generated by tools/verify_hack.py; do not hand-edit",
             "return {", "  timeline = {"]
    for step in resolved_timeline:
        keys = ", ".join(f'"{k}"' for k in step["keys"])
        lines.append(f'    {{ frames = {step["frames"]}, keys = {{ {keys} }} }},')
    lines.append("  },")
    lines.append(f"  total_frames = {total_frames},")
    lines.append(f"  screenshot = {'true' if screenshot else 'false'},")
    lines.append("  probes = {")
    for p in probes:
        at = "".join(f"[{f}]=true," for f in p["at"])
        lines.append(
            f'    {{ id = "{p["id"]}", addr = {p["addr"]}, '
            f'offset = {p["offset"]}, size = {p["size"]}, '
            f'length = {p["length"]}, '
            f'deref = {"true" if p["deref"] else "false"}, '
            f'every = {p["every"]}, at = {{{at}}} }},')
    lines.append("  },")
    lines.append("}")
    path.write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------

def check_savestate(name, rom):
    """Resolve a save-state name to a path, and refuse a stale one.

    mGBA save states are tied to the exact binary they were captured from, so a
    state made against a different build silently resumes into nonsense. The
    sidecar .json written by make_savestate.py records the ROM's sha256; if it
    disagrees with the ROM under test, that is a hard error, not a warning --
    every gameplay assertion downstream would be meaningless.
    """
    path = SAVES / name
    if not path.exists():
        fail(f"save state {path} not found -- run "
             f"`python3 tools/make_savestate.py --stage party`")
    sidecar = path.with_suffix(path.suffix + ".json")
    if sidecar.exists():
        meta = json.loads(sidecar.read_text())
        want = meta.get("rom_sha256")
        if want:
            got = hashlib.sha256(rom.read_bytes()).hexdigest()
            if got != want:
                fail(f"save state {name} was captured against ROM "
                     f"{want[:16]}... but {rom.name} is {got[:16]}... -- mGBA "
                     f"states are build-specific; regenerate the state "
                     f"(and note the regenerated one will contain a DIFFERENT "
                     f"Pokemon: the boot RNG is not pinned)")
    return path


def resolve_artifacts(rom_arg, sym_arg, engine=ENGINE):
    """Pick the ROM and the .sym, and say where each choice came from.

    THE RULE, and the bug it replaces (doc 57 §5): --sym defaults to the ROM's
    OWN SIBLING, never to the engine's. It used to default to the literal string
    "pokeemerald.sym" resolved under engine/, so

        verify_hack.py <spec> --rom <hack>/pokeemerald.gba

    resolved every probe address out of a DIFFERENT BUILD's symbol table and
    reported a verdict without a word of warning. That was survivable only while
    a hack's .sym happened to be byte-identical to the engine's, which stops
    being true the instant a hack adds, removes or reorders anything.

    A relative --sym still resolves under engine/, and an absolute one
    is used as given -- both unchanged, so every command in docs 55 and 57 still
    means what it meant. With NEITHER flag given the result is
    engine/pokeemerald.gba + engine/pokeemerald.sym, exactly as before.

    Note this only picks CANDIDATES. Naming is a guess; verify_pair() in
    rom_pair.py is what actually adjudicates, by content.
    """
    rom = engine / (rom_arg or DEFAULT_ROM)
    if sym_arg:
        sym = engine / sym_arg
        source = "--sym"
    else:
        sym = rom_pair.sibling(rom, "sym")
        source = ("sibling of --rom" if rom_arg else "engine default")
    return rom, sym, source


def persist_dir_for(name):
    """Host directory backing a spec's cross-process save, created on demand.

    Lives under saves/persist/<name>/ and is GITIGNORED along with the
    rest of saves/*.ss1's neighbours -- a .sav is emulated flash out of a
    Nintendo-derived ROM and never belongs in this repo's history.
    """
    d = SAVES / "persist" / name
    d.mkdir(parents=True, exist_ok=True)
    return d



# --------------------------------------------------------------- scratch lock

class ScratchLock:
    """Exclusive claim on the ONE shared scratch directory.

    Every run writes `_probe_data.lua`, `DONE`, `verify_stdout.log` and the
    screenshot into `engine/build/` -- even when the ROM under test
    lives elsewhere, because the engine is mounted at /engine for the Lua's
    `dofile` (doc 57). Two concurrent runs therefore do not collide loudly;
    the second one reads the FIRST one's probe data and returns a confident
    wrong answer that reads exactly like a broken feature.

    Doc 66 recorded that after losing time to it, and the recorded tell is
    `probe produced no samples at all` on probes that cannot produce zero
    samples -- a shape no honest failure has. It happened again on 2026-08-04,
    to somebody who had read that entry, which is this project's own signal
    that a rule needs to be EXECUTABLE rather than remembered (the doc 65
    backup lesson). Hence a lock rather than a third paragraph about it.

    Refuses rather than waits: a queued run is a run whose ROM may be rebuilt
    out from under it while it waits, and a spec is only meaningful against the
    binary it was resolved for.
    """

    def __init__(self, build):
        self.path = build / ".verify_lock"
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "w")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            sys.exit(
                f"another verify_hack.py run holds {self.path}.\n"
                "  The scratch directory is shared, so a second run would read the first\n"
                "  run's probe data and PASS or FAIL on it. Run specs serially.\n"
                "  (If no run is live, the lock is stale -- delete that file.)")
        self.fh.write(f"pid {os.getpid()}\n")
        self.fh.flush()
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
        finally:
            self.fh.close()


def run_rom(rom, total_frames, timeout, savestate=None, log_level=8,
            persist=None, audio=False):
    build = ENGINE / "build"
    build.mkdir(exist_ok=True)
    for stale in ("DONE", "verify_screenshot.png", "verify_stdout.log",
                  "verify_audio.pcm", "verify_audio.pcm.rate"):
        (build / stale).unlink(missing_ok=True)

    load_flag = f"-t /saves/{savestate} " if savestate else ""

    # THE EMULATOR IS MUTED BY DEFAULT AND NOTHING SAYS SO.
    #
    # `src/gba/core.c:358-361` does `gba->audio.masterVolume = core->opts.volume`,
    # and with no config file on disk -- which is every run in a container --
    # `opts.volume` is ZERO. So the APU mixes correctly, the mAVStream tap fires
    # on schedule, the sample count and the 32768 Hz rate are both exactly right,
    # and every sample is 0. The first two capture runs produced 25 s and 61 s of
    # flawless silence and PASSED, because nothing in a WAV's size or duration
    # says whether there is sound in it.
    #
    # That is the plausible-artifact class arriving in the one place this project
    # had no instrument for, and it is why write_wav_from_pcm's caller checks the
    # samples rather than the file. 256 is GBA_AUDIO_VOLUME_MAX.
    audio_flags = "-C volume=256 -C mute=0 " if audio else ""

    # CROSS-PROCESS SAVE MODE (doc 61 §7's open limit).
    #
    # Every save proof before this one wrote and read the emulated flash chip
    # INSIDE ONE EMULATOR PROCESS -- the right target for a soft reset, which is
    # what a player does, but it is not "the .sav on the host is correct and a
    # LATER LAUNCH reads it". That distinction stops being academic the moment
    # the ROM goes on a handheld and the power button is the reset.
    #
    # mGBA writes <rom-basename>.sav NEXT TO THE ROM and has no flag to put it
    # anywhere else (checked: -b -c -C -g -l -t -p -s and nothing more). The ROM
    # directory is mounted READ-ONLY here on purpose -- it is a hack fork's
    # source tree and this harness must never be able to scribble on it. So the
    # ROM is COPIED into a writable scratch mount and run from there, and the
    # .sav lands beside the copy, on the host, where a second run finds it.
    #
    # The copy is unconditional and the .sav is never touched: re-copying a
    # 32 MB ROM costs a moment, and getting the two backwards -- refreshing the
    # save and keeping a stale ROM -- would produce a sha mismatch that reads
    # like a corrupt save.
    if persist:
        rom_in_container = f"/persist/{rom.name}"
        persist_prep = f"cp /rom/{rom.name} /persist/{rom.name}\n"
    else:
        rom_in_container = f"/rom/{rom.name}"
        persist_prep = ""
    # ROM MOUNT, and why it is its own mount rather than /engine/<name>:
    #   This used to emit "/engine/{rom.name}" -- the BASENAME only. That works
    #   for the default ROM sitting at the engine root and silently breaks for
    #   anything else: `--rom build/modified.gba` passed the sha check against
    #   engine/build/modified.gba on the host, then told mGBA to open
    #   /engine/modified.gba, which does not exist. The symptom is the useless
    #   "ROM did not complete N frames" with an EMPTY log, not "no such file".
    #   It matters because the entire point of this harness is running the SAME
    #   spec against TWO builds, and a hack fork lives OUTSIDE engine/
    #   (the engine clone is read-only), so it could never be loaded at all.
    #   Mounting the ROM's own directory makes any path on the host work.
    # LOG LEVEL, and why it is 8 and not the 7 or the 15 you may have seen:
    #   -l 7  console:log from a Lua script is INVISIBLE (doc 54 §3). The
    #         harness looks like it never ran. Never use it here.
    #   -l 15 works, but adds mGBA's GBA DMA chatter at several lines per
    #         frame. On a save-state-resumed field-engine run that is a
    #         torrent, and it is what killed this harness's first gameplay
    #         run: mgba-headless aborted mid-print with
    #         "malloc(): corrupted top size" at ~frame 180. Reproducible at
    #         -l 15, gone at -l 8.
    #   -l 8  INFO alone -- exactly the bit console:log needs, nothing else.
    # Do not "tidy" this back to 7, and do not raise it to 15 to get more
    # detail without re-testing a gameplay spec end-to-end.
    script = f"""
set -e
# mkdir -p on a directory the HOST just created, on purpose: under macOS
# Docker's file sharing, a container started milliseconds after the host
# mutates a mounted directory can transiently see it as missing -- observed
# 2026-08-01 as an intermittent (~3 in 60 runs) 'No such file or directory'
# on the redirect below, once in a fully SERIAL queue, so it is not a
# concurrency bug. Forcing resolution in-container closes it; it is a no-op
# when the cache is fresh.
mkdir -p /engine/build
{persist_prep}mgba-headless {rom_in_container} {load_flag}{audio_flags}-l {log_level} --script /harness/read_symbols.lua \
    > /engine/build/verify_stdout.log 2>&1 &
PID=$!
START=$SECONDS
while [ ! -f /engine/build/DONE ] && kill -0 $PID 2>/dev/null; do
    if [ $((SECONDS - START)) -ge {timeout} ]; then
        echo 'TIMEOUT' >&2; kill -9 $PID 2>/dev/null || true; exit 1
    fi
    sleep 0.05
done
kill -SIGINT $PID 2>/dev/null || true
wait $PID 2>/dev/null || true
"""
    mounts = ["-v", f"{ENGINE}:/engine", "-v", f"{HARNESS}:/harness",
              "-v", f"{rom.parent.resolve()}:/rom:ro"]
    if savestate:
        mounts += ["-v", f"{SAVES}:/saves:ro"]
    if persist:
        # The ONLY writable mount this harness ever takes, and it holds a ROM
        # copy plus its .sav -- never a source tree.
        mounts += ["-v", f"{persist}:/persist"]
        # AND THE THING THAT MAKES THE MOUNT MEAN ANYTHING (2026-08-04).
        # Stock mgba-headless never calls mCoreAutoloadSave, so until now this
        # writable mount received a ROM copy and never a .sav -- the whole
        # cross-process save lane was well-built and structurally inert, which
        # is why reps-sav-read.json has been a written claim rather than a
        # passing one. docker/Dockerfile now patches the call in, GATED on this
        # variable so that a run without it is byte-identical to every run
        # recorded before the patch. Setting it here, and only here, keeps the
        # gate tied to the one mode that asks for a save file.
        env_flags = ["-e", "MGBA_HEADLESS_AUTOLOAD_SAVE=1"]
    else:
        env_flags = []
    if audio:
        # AUDIO CAPTURE (2026-08-05, doc 67 slate item J).
        #
        # THE HARNESS HAD NO EARS, and that is a sharper limit than it sounds.
        # Every proof in this mode is a RAM probe or a screenshot, and slate
        # item J's failure mode -- the mixer running out of voices and stealing
        # one mid-note -- is inaudible to both: the probe sees five channels
        # busy, which is CORRECT, and the screen shows nothing at all. Doc 62's
        # class with the last instrument removed.
        #
        # Stock mgba-headless has no audio option whatsoever (checked: -b -c -C
        # -g -l -t -p -s -S -R --script and nothing more). docker/Dockerfile now
        # registers an mAVStream postAudioFrame tap, GATED on this variable, so
        # a run without it is byte-identical to every run recorded before the
        # patch. Third time the answer to "the emulator cannot do that" has been
        # "the emulator is ours" -- after the video buffer and the save file.
        env_flags += ["-e", "MGBA_HEADLESS_AUDIO_OUT=/engine/build/verify_audio.pcm"]
    run = subprocess.run(
        ["docker", "run", "--rm", *mounts, *env_flags, "-w", "/engine", IMAGE,
         "bash", "-c", script],
        capture_output=True, text=True)
    log_path = build / "verify_stdout.log"
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    if not (build / "DONE").exists():
        print(log[-2000:], file=sys.stderr)
        fail(f"ROM did not complete {total_frames} frames "
             f"(docker exit {run.returncode}): {run.stderr[-500:]}")
    return log


def write_wav_from_pcm(pcm_path, wav_path):
    """Raw s16le stereo -> a .wav anyone can double-click.

    The RATE IS READ, NOT ASSUMED. The emulator writes it to a `.rate` sidecar
    from core->audioSampleRate() at the moment the stream is attached, because
    a WAV built on a guessed rate plays at the wrong speed and still plays --
    a plausible artifact, which is the class this project keeps getting caught
    by. If the sidecar is missing we refuse rather than pick a plausible number.
    """
    rate_path = pathlib.Path(str(pcm_path) + ".rate")
    if not rate_path.exists():
        fail(f"{pcm_path.name} has no .rate sidecar -- refusing to guess a "
             f"sample rate, because the wrong one produces audio that plays "
             f"fine and is simply the wrong speed.")
    rate = int(rate_path.read_text().strip())
    if not (8000 <= rate <= 96000):
        fail(f"implausible sample rate {rate} from {rate_path.name}")
    raw = pcm_path.read_bytes()
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(raw)
    return wav_path


def wav_stats(wav_path):
    """(peak, percent non-zero, seconds). The cheapest possible answer to
    'is there actually sound in this file', which is a different question from
    'does this file exist and have the right duration'."""
    with wave.open(str(wav_path)) as w:
        n, rate = w.getnframes(), w.getframerate()
        a = array.array("h")
        a.frombytes(w.readframes(n))
    if not len(a):
        return 0, 0.0, 0.0
    peak = max(abs(v) for v in a)
    nz = 100.0 * sum(1 for v in a if v != 0) / len(a)
    return peak, nz, n / rate if rate else 0.0


def parse_samples(log, probes, syms):
    """Turn SYMPROBE lines into per-probe sample lists. No judging here."""
    by_id = {p["id"]: p for p in probes}
    samples = {p["id"]: [] for p in probes}
    for frame, pid, ptr, raw in SAMPLE_RE.findall(log):
        probe = by_id.get(pid)
        if probe is None:
            continue                      # a probe id we did not ask for
        value = None
        if raw != "invalid":
            if probe["type"] == "bytes":
                value = raw
            else:
                value = int(raw, 16)
                if probe["type"] in SIGNED:
                    bits = probe["size"] * 8
                    if value >= 1 << (bits - 1):
                        value -= 1 << bits
        ptr_val = int(ptr, 16) if ptr else None
        samples[pid].append({
            "frame": int(frame),
            "ptr": ptr_val,
            "value": value,
            "raw": raw,
            "value_symbol": (resolve(syms, value)
                             if isinstance(value, int) and value else None),
            "ptr_symbol": (resolve(syms, ptr_val) if ptr_val else None),
        })
    for lst in samples.values():
        lst.sort(key=lambda s: s["frame"])
    return samples


# --------------------------------------------------------------------------
# assertions -- every one of them lives on this side of the emulator boundary
# --------------------------------------------------------------------------

class Result:
    def __init__(self):
        self.lines = []
        self.ok = True

    def add(self, passed, text):
        self.lines.append(("PASS" if passed else "FAIL", text))
        self.ok = self.ok and passed


def select(samples, at, label, res):
    """Return (selected, mode) for an `at` selector, or (None, None) on error."""
    if at is None or at == "last":
        return samples[-1:], "all"
    if at == "first":
        return samples[:1], "all"
    if at == "all":
        return samples, "all"
    if at == "any":
        return samples, "any"
    if isinstance(at, int):
        sel = [s for s in samples if s["frame"] == at]
        if not sel:
            res.add(False, f"{label}: no sample at frame {at} "
                           f"(sampled frames: {[s['frame'] for s in samples]})")
            return None, None
        return sel, "all"
    res.add(False, f"{label}: bad 'at' selector {at!r}")
    return None, None


# `of` selects WHICH number a check looks at on a deref probe: the value found
# at the end of the chase ("value", the default everywhere) or the pointer that
# was chased ("ptr"). It defaults to "value" for every check and every probe
# kind -- a per-probe default would mean the same assertion text meant different
# things on different probes, which is exactly the kind of quiet ambiguity a
# verification harness must not have. Say "of": "ptr" when you mean the pointer.
def symbol_of(sample, of, probe):
    of = of or "value"
    return sample["ptr_symbol"] if of == "ptr" else sample["value_symbol"], of


def number_of(sample, of, probe):
    return sample["ptr"] if of == "ptr" else sample["value"]


def evaluate(spec, probes, samples, res):
    by_id = {p["id"]: p for p in probes}
    assertions = spec.get("assert", [])
    if not assertions:
        res.add(False, "spec declares no assertions -- a spec that cannot fail "
                       "is not a proof")
        return

    for a in assertions:
        pid, check = a["probe"], a["check"]
        label = f"{pid}.{check}"
        probe = by_id.get(pid)
        if probe is None:
            res.add(False, f"{label}: no probe with id {pid!r}")
            continue
        got = samples[pid]
        if not got:
            res.add(False, f"{label}: probe produced no samples at all")
            continue

        vals = [s["value"] for s in got]
        unreadable = [s["frame"] for s in got if s["value"] is None]

        if check == "always_valid":
            res.add(not unreadable,
                    f"{label}: {len(got)} samples, unreadable at frames "
                    f"{unreadable or 'none'}")
            continue

        if check == "sample_count":
            op = a.get("op", "==")
            res.add(OPS[op](len(got), a["value"], 0),
                    f"{label}: {len(got)} {op} {a['value']}")
            continue

        if check in ("strictly_increases", "non_decreasing", "constant",
                     "changes_at_least"):
            if unreadable:
                res.add(False, f"{label}: unreadable samples at frames "
                               f"{unreadable}")
                continue
            if check == "strictly_increases":
                ok = len(vals) > 1 and all(b > a2 for a2, b in zip(vals, vals[1:]))
                res.add(ok, f"{label}: {vals}")
            elif check == "non_decreasing":
                ok = all(b >= a2 for a2, b in zip(vals, vals[1:]))
                res.add(ok, f"{label}: {vals}")
            elif check == "constant":
                distinct = list(dict.fromkeys(vals))   # first-seen order
                ok = len(distinct) == 1
                res.add(ok, f"{label}: {len(distinct)} distinct value(s) "
                            f"{[fmt(v) for v in distinct[:6]]}")
            else:
                changes = sum(1 for a2, b in zip(vals, vals[1:]) if a2 != b)
                res.add(changes >= a["count"],
                        f"{label}: {changes} change(s) >= {a['count']}")
            continue

        if check in ("compare", "in_range"):
            sel, mode = select(got, a.get("at", "last"), label, res)
            if sel is None:
                continue
            of = a.get("of")
            outcomes = []
            for s in sel:
                n = number_of(s, of, probe)
                if n is None:
                    outcomes.append((False, f"frame {s['frame']}: unreadable"))
                elif check == "compare":
                    op, want = a.get("op", "=="), a["value"]
                    tol = a.get("tolerance", 0)
                    outcomes.append((OPS[op](n, want, tol),
                                     f"frame {s['frame']}: {fmt(n)} {op} "
                                     f"{fmt(want)}"))
                else:
                    lo, hi = a["min"], a["max"]
                    outcomes.append((lo <= n <= hi,
                                     f"frame {s['frame']}: {fmt(n)} in "
                                     f"[{fmt(lo)}, {fmt(hi)}]"))
            ok = (any(o for o, _ in outcomes) if mode == "any"
                  else all(o for o, _ in outcomes))
            detail = "; ".join(t for o, t in outcomes if not o) or \
                     "; ".join(t for _, t in outcomes[:3])
            res.add(ok, f"{label} ({mode}): {detail}")
            continue

        if check == "resolves":
            sel, mode = select(got, a.get("at", "all"), label, res)
            if sel is None:
                continue
            allow_zero = a.get("allow_zero", False)
            of = a.get("of")
            bad = []
            for s in sel:
                name, _ = symbol_of(s, of, probe)
                n = number_of(s, of, probe)
                if n == 0 and allow_zero:
                    continue
                if name is None:
                    bad.append(f"frame {s['frame']}: {fmt(n)} <unresolved>")
            res.add(not bad, f"{label} ({len(sel)} samples): "
                             f"{'; '.join(bad) if bad else 'all resolve'}")
            continue

        if check == "symbol_at":
            sel, mode = select(got, a.get("at", "last"), label, res)
            if sel is None:
                continue
            of = a.get("of")
            op, want = a.get("op", "=="), a["value"]
            outcomes = []
            for s in sel:
                name, used = symbol_of(s, of, probe)
                if op == "==":
                    ok = name == want
                elif op == "!=":
                    ok = name != want
                elif op == "in":
                    ok = name in want
                elif op == "not_in":
                    ok = name not in want
                else:
                    res.add(False, f"{label}: bad op {op!r} for symbol_at")
                    ok = False
                outcomes.append((ok, f"frame {s['frame']}: {used}="
                                     f"{name or '<unresolved>'} {op} {want}"))
            ok = (any(o for o, _ in outcomes) if mode == "any"
                  else all(o for o, _ in outcomes))
            detail = "; ".join(t for o, t in outcomes if not o) or \
                     "; ".join(t for _, t in outcomes[:3])
            res.add(ok, f"{label} ({mode}): {detail}")
            continue

        if check in ("symbol_sequence", "distinct_symbols_at_least"):
            of = a.get("of")
            names = []
            for s in got:
                name, _ = symbol_of(s, of, probe)
                name = name or "<unresolved>"
                if not names or names[-1] != name:
                    names.append(name)
            if check == "distinct_symbols_at_least":
                real = {n for n in names if n != "<unresolved>"}
                res.add(len(real) >= a["count"],
                        f"{label}: {len(real)} distinct >= {a['count']} "
                        f"({' -> '.join(names)})")
            else:
                want, op = a["value"], a.get("op", "contains_in_order")
                if op == "equals":
                    ok = names == want
                elif op == "contains_in_order":
                    it = iter(names)
                    ok = all(any(n == w for n in it) for w in want)
                else:
                    res.add(False, f"{label}: bad op {op!r}")
                    continue
                res.add(ok, f"{label} ({op}): observed {' -> '.join(names)} "
                            f"vs wanted {' -> '.join(want)}")
            continue

        # THE NEGATIVE SCREEN ASSERTION (slice 3): PASS iff NONE of the named
        # symbols was ever observed. This is how a spec says "the training
        # screen must not open on a declined challenge" -- contains_in_order
        # cannot say it, and an `equals` against the full sequence would break
        # on every incidental transition callback. Same resolution rules as
        # symbol_sequence; an unresolved sample can never match a name, which
        # is the safe direction for a NEGATIVE check.
        if check == "symbol_never":
            of = a.get("of")
            names = []
            for s in got:
                name, _ = symbol_of(s, of, probe)
                name = name or "<unresolved>"
                if not names or names[-1] != name:
                    names.append(name)
            banned = [w for w in a["value"] if w in names]
            res.add(not banned,
                    f"{label}: observed {' -> '.join(names)}; banned "
                    f"{', '.join(a['value'])}"
                    + (f"; HIT {', '.join(banned)}" if banned else ""))
            continue

        res.add(False, f"{label}: unknown check {check!r}")


def fmt(v):
    if isinstance(v, int) and v > 0xffff:
        return f"{v:#010x}"
    return str(v)


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="spec name under verify/ or a path")
    ap.add_argument("--seed", type=int, default=None,
                    help="RNG seed for randomized timeline segments")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--log-level", type=int, default=8,
                    help="mgba-headless -l value. 8 (INFO) is what console:log "
                         "needs; see run_rom's comment before changing it.")
    ap.add_argument("--rom", default=None,
                    help=f"ROM under test. Relative paths resolve under "
                         f"engine/; absolute paths are used as given. "
                         f"Default: {DEFAULT_ROM} in the engine tree.")
    ap.add_argument("--sym", default=None,
                    help="symbol table for that ROM. DEFAULTS TO THE ROM'S OWN "
                         "SIBLING .sym, not to the engine's -- pointing --rom "
                         "at a hack while silently resolving symbols out of a "
                         "different build's table is a quiet false PASS (doc 57 "
                         "§5). The pair is then verified by CONTENT, so a wrong "
                         "--sym is rejected however it was chosen.")
    ap.add_argument("--elf", default=None,
                    help="ELF to verify the rom/sym pair against. Defaults to "
                         "the ROM's sibling pokeemerald.elf; you should not "
                         "normally need this.")
    ap.add_argument("--allow-unmatched-sym", action="store_true",
                    help="skip the rom/sym pairing proof and run anyway. Only "
                         "for a tree with no ELF. It prints, loudly, what is "
                         "being given up: with an unmatched .sym every probe "
                         "reads the wrong address and the verdict -- PASS OR "
                         "FAIL -- means nothing.")
    ap.add_argument("--savestate", default=None,
                    help="load this save state from saves/ before the "
                         "run (overrides the spec's own \"savestate\" key). "
                         "This is how a spec asserts GAMEPLAY state: the state "
                         "is a committed artifact, so the assertion is about "
                         "the engine, not about a 31,000-frame input replay "
                         "that is not bit-reproducible anyway.")
    ap.add_argument("--no-savestate", action="store_true",
                    help="COUNTERFACTUAL: ignore the spec's save state and cold-"
                         "boot instead. Any spec asserting real gameplay state "
                         "MUST fail under this -- it is the counterfactual that "
                         "is orthogonal to --counterfactual's address shift, "
                         "because every address stays correct and only the "
                         "CONTENT of memory changes.")
    ap.add_argument("--reset-persist", action="store_true",
                    help="delete the .sav in this spec's persist_dir before "
                         "running. Two uses: starting the write half of a "
                         "cross-process save proof from nothing, and running "
                         "the COUNTERFACTUAL read -- a cold boot with no save "
                         "file must read zeros, which is what proves the "
                         "passing read is coming off the disk rather than out "
                         "of a savestate or uncleared RAM (doc 61 §4).")
    ap.add_argument("--counterfactual", action="store_true",
                    help="shift EVERY probe base address by 0x800 into "
                         "unrelated memory. Any spec that genuinely reads "
                         "engine state MUST fail under this. A spec that still "
                         "passes was never reading anything.")
    ap.add_argument("--expect-fail", action="store_true",
                    help="invert the exit code: exit 0 only if the spec FAILS. "
                         "For running counterfactual specs in a script.")
    args = ap.parse_args()

    spec_path = pathlib.Path(args.spec)
    if not spec_path.exists():
        cand = SPEC_DIR / args.spec
        if cand.suffix != ".json":
            cand = SPEC_DIR / f"{args.spec}.json"
        spec_path = cand
    if not spec_path.exists():
        fail(f"no spec at {args.spec} or {spec_path}")
    spec = json.loads(spec_path.read_text())

    # `symbols_from` NOW SELECTS THE ROM (2026-08-06, doc 82 F1). It used to be
    # documentary -- 77 specs declared the fork they needed and this runner
    # ignored the key, so running one without --rom silently resolved the ENGINE
    # ROM instead. That one gap surfaced three separate ways in a single day: a
    # batch run judged two specs against the wrong game, seven specs crashed the
    # unit suite in a fresh clone, and only a savestate's ROM-sha guard caught
    # the others. A declaration a machine ignores is a comment.
    #
    # "engine" means the pinned base ROM, and is now written out rather than
    # left absent, so "which ROM does this spec want" always has an answer in
    # the file itself. An explicit --rom still wins.
    rom_arg = args.rom
    if not rom_arg:
        fork = spec.get("symbols_from")
        if fork and fork != "engine":
            rom_arg = str(hx.HACKS / fork / DEFAULT_ROM)
    rom, sym, sym_source = resolve_artifacts(rom_arg, args.sym)
    if not rom.exists():
        fail(f"{rom} not found -- build the engine first "
             f"(see docs/54 §6)")
    if not sym.exists():
        msg = [f"{sym} not found."]
        if not args.sym:
            # This is the doc 55 §9.2 shape: a ROM copied somewhere with no
            # build artifacts beside it. It used to work by silently borrowing
            # the engine's .sym, which is precisely the bug. It now needs the
            # pair named, because an isolated .gba genuinely cannot be paired.
            msg.append(f"  It was chosen as the sibling of {rom.name}, since "
                       f"--sym was not given. Either:")
            msg.append(f"    * run `make syms CPP=\"arm-none-eabi-cpp "
                       f"-std=gnu17\"` in that tree -- the .sym is a SEPARATE "
                       f"target, a plain `make` emits none (doc 54 §2); or")
            msg.append(f"    * name the pair explicitly: --sym <path> [--elf "
                       f"<path>]. The pair is verified by content either way, "
                       f"so naming the wrong one is still caught; or")
            msg.append(f"    * --allow-unmatched-sym to skip the pairing proof "
                       f"entirely and accept that the verdict means nothing.")
        else:
            msg.append(f"  Run `make syms CPP=\"arm-none-eabi-cpp -std=gnu17\"` "
                       f"in that tree (the .sym is a SEPARATE target).")
        fail("\n".join(msg))

    # THE PAIRING PROOF. Nothing below here is meaningful unless this ROM and
    # this .sym are one build, so it runs before a single symbol is resolved
    # and before a docker run is spent.
    if args.allow_unmatched_sym:
        pair_lines = rom_pair.describe_unverified(rom, sym)
        prefix = "!!! "
    else:
        try:
            pair_lines = rom_pair.verify_pair(
                rom, sym, (ENGINE / args.elf) if args.elf else None)
        except rom_pair.PairError as exc:
            fail(str(exc))
        prefix = "==> "

    syms, by_name = load_symbols(sym)
    seed = args.seed if args.seed is not None else random.randrange(2**32)
    rng = random.Random(seed)

    print(f"==> spec {spec_path.name}: {spec.get('name', '<unnamed>')}")
    if spec.get("description"):
        print(f"    {spec['description']}")
    print(f"==> rom {rom}")
    # FULL PATH, not sym.name. The old line printed a bare basename, which is
    # exactly how "98782 symbols from pokeemerald.sym" managed to describe the
    # WRONG pokeemerald.sym without anyone noticing (doc 57 §5).
    print(f"==> sym {sym}  [{sym_source}]")
    for line in pair_lines:
        print(f"{prefix}{line}")
    print(f"==> {len(syms)} symbols; seed={seed}")

    savestate = args.savestate or spec.get("savestate")
    if args.no_savestate and savestate:
        print(f"==> COUNTERFACTUAL: --no-savestate, so {savestate} is NOT "
              f"loaded; this spec MUST fail")
        savestate = None
    elif savestate:
        check_savestate(savestate, rom)
        print(f"==> save state: {savestate} (mGBA -t)")

    resolved_timeline = resolve_timeline(spec["timeline"], rng)
    total_frames = resolved_timeline[-1]["end"]
    # A mash expands into hundreds of sub-steps; print it as the one step the
    # spec actually wrote, or the run header buries everything else.
    for step in collapse_mash_for_display(resolved_timeline):
        label = f" [{step['name']}]" if step["name"] else ""
        print(f"    frames {step['start']:>5}-{step['end']:<5}{label}: "
              f"{step['keys'] or 'no input'}")

    if args.counterfactual:
        print(f"==> COUNTERFACTUAL: every probe base shifted by "
              f"+{COUNTERFACTUAL_SHIFT:#x} -- this spec MUST fail")

    probes = resolve_probes(spec, by_name, resolved_timeline,
                            total_frames, args.counterfactual)
    validate_assertions(spec, probes)
    print("==> probes")
    for p in probes:
        where = (f"*[{p['symbol']}+{p['base_offset']:#x} = {p['addr']:08x}]"
                 f" + {p['offset']:#x}" if p["deref"] else
                 f"{p['symbol']}+{p['offset']:#x} = {p['addr']:08x}")
        print(f"    {p['id']:<18} {p['type']:<6} {where}")

    build = ENGINE / "build"
    build.mkdir(exist_ok=True)
    # Held from here -- the first write into the shared scratch -- until the
    # samples have been parsed back out of it. See ScratchLock.
    scratch = ScratchLock(build)
    scratch.__enter__()
    write_probe_data(probes, resolved_timeline, total_frames,
                     spec.get("screenshot", True), build / "_probe_data.lua")

    persist = None
    if spec.get("persist_dir"):
        persist = persist_dir_for(spec["persist_dir"])
        sav = persist / (rom.stem + ".sav")
        if args.reset_persist:
            existed = sav.exists()
            sav.unlink(missing_ok=True)
            print(f"==> --reset-persist: {sav.name} "
                  f"{'DELETED' if existed else 'was already absent'}")
        before = f"{sav.stat().st_size} B" if sav.exists() else "ABSENT"
        print(f"==> cross-process save: {persist}")
        print(f"    the ROM is copied there and run from the copy, so the "
              f".sav lands on the HOST")
        print(f"    {sav.name} before the run: {before}")

    print(f"==> running {rom.name} under mgba-headless ({total_frames} frames)")
    log = run_rom(rom, total_frames, args.timeout, savestate, args.log_level,
                  persist, audio=bool(spec.get("audio", False)))
    if persist:
        sav = persist / (rom.stem + ".sav")
        print(f"==> after the run: {sav.name} "
              f"{'%d B' % sav.stat().st_size if sav.exists() else 'ABSENT'}")
    samples = parse_samples(log, probes, syms)

    total_samples = sum(len(v) for v in samples.values())
    if total_samples == 0:
        print(log[-2000:], file=sys.stderr)
        fail("no SYMPROBE lines in mgba stdout -- the Lua script did not run "
             "(is the log level -l 15?)")

    print(f"==> {total_samples} samples observed\n")
    for p in probes:
        print(f"    {p['id']}  ({p['symbol']}"
              f"{'  [deref]' if p['deref'] else ''})")
        for s in samples[p["id"]]:
            ptr = f"ptr={s['ptr']:08x} " if s["ptr"] is not None else ""
            ptr_sym = f"<{s['ptr_symbol']}> " if s["ptr_symbol"] else (
                "<unresolved> " if s["ptr"] else "")
            vsym = f" {s['value_symbol']}" if s["value_symbol"] else ""
            print(f"      frame {s['frame']:>5}  {ptr}{ptr_sym}"
                  f"value={s['raw']}{vsym}")
        print()

    res = Result()
    evaluate(spec, probes, samples, res)
    print("==> assertions (evaluated outside the emulator)")
    for tag, text in res.lines:
        print(f"  [{tag}] {text}")

    shot = build / "verify_screenshot.png"
    passed = res.ok
    print()
    if not passed and shot.exists():
        keep = build / f"FAIL_{spec_path.stem}.png"
        shutil.copyfile(shot, keep)
        print(f"    failure screenshot: {keep}")
    elif shot.exists():
        print(f"    screenshot: {shot}")

    pcm = build / "verify_audio.pcm"
    if spec.get("audio"):
        if not pcm.exists() or pcm.stat().st_size == 0:
            # Not a soft warning. A spec that asked to be listened to and was
            # not is a spec whose central claim went unmeasured, and an absent
            # file is exactly what a working-but-silent build looks like.
            fail("spec set \"audio\": true but the run produced no samples. "
                 "The image may predate the mAVStream patch -- rebuild it "
                 "(docker build -f docker/Dockerfile -t "
                 f"{IMAGE} .) and check `strings` for MGBA_HEADLESS_AUDIO_OUT.")
        wav = write_wav_from_pcm(pcm, build / f"{spec_path.stem}.wav")
        peak, nz, secs = wav_stats(wav)
        print(f"    audio: {wav}  ({secs:.1f}s, peak {peak}, {nz:.0f}% non-zero)")
        # A SILENT CAPTURE IS THE DEFAULT FAILURE HERE, NOT AN EDGE CASE.
        # mgba-headless mixes at volume 0 unless told otherwise, and the result
        # is a WAV of exactly the right duration and rate containing nothing.
        # Two runs shipped green that way before this check existed. A spec that
        # genuinely expects silence says so.
        if not spec.get("audio_expect_silence") and peak < 500:
            fail(f"\"audio\": true produced {secs:.1f}s of SILENCE (peak {peak}). "
                 f"The run is muted, not quiet. Check that -C volume=256 reached "
                 f"mgba-headless; core->opts.volume defaults to 0 with no config "
                 f"file. If silence is the point, set \"audio_expect_silence\".")
    scratch.__exit__()   # the screenshot is read out of the scratch above it

    verdict = "PASS" if passed else "FAIL"
    stream = sys.stdout if passed else sys.stderr
    print(f"==> {verdict}: {spec_path.name} (seed={seed})", file=stream)

    if args.expect_fail:
        if passed:
            print("==> UNEXPECTED PASS: this spec was run with --expect-fail "
                  "and was supposed to FAIL. The proof is vacuous.",
                  file=sys.stderr)
            sys.exit(1)
        print("==> as expected, the spec FAILED (--expect-fail)")
        sys.exit(0)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
