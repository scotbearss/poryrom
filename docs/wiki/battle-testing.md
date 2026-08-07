# Battle testing

The engine's own `make check` framework: what the DSL macros actually compile to, how the rigged RNG decides every number the suite asserts, and the operational crumbs that make the suite usable as a gate. This page is about the engine's **internal** test framework — the C DSL that ships inside the pinned expansion and runs as a second ROM. The project's own **external** harness (inert JSON specs, a Lua driver that asserts nothing, judgement outside the emulator) is a different instrument with a different trust model; that method lives in [[verification-discipline]], which also records the measured baseline for running this suite as a gate (§11 there). Siblings: [[battle-engine]], [[build-system]].

## 1. The DSL is re-execution, not coroutines

`GIVEN` / `WHEN` / `SCENE` / `THEN` / `FINALLY` look like a scripting language and are nothing of the kind. Each is a `for` loop over a one-shot boolean owned by the runner state, and **the test function is executed from the top repeatedly — around six times — with a different phase flag set on each pass** (record 46 §1.3). One pass counts parameters to schedule the test, one sizes the results array, one builds the parties and queues the turn record and SCENE expectations before handing control to the real battle, and a final pass — after the battle — runs only the `THEN`/`FINALLY` blocks.

`PARAMETRIZE` is the same trick: not a loop but a **re-execution selector**, `if (parametersCount++ == i)`. On run *k* the *k*-th block executes and the others are skipped, while the count is recomputed every pass to learn the total (record 46 §1.3).

**Locals survive across battles because the stack is not the stack.** The test function is invoked through hand-written ARM that points `sp` at a private buffer in EWRAM, so a plain local written in `GIVEN` is still live thousands of frames later when the battle ends and `THEN` runs — this is the whole mechanism behind `captureDamage: &damage`. That buffer is **1024 bytes** (`BATTLE_TEST_STACK_SIZE`), and the header's own warning applies verbatim: if the stack is too small the test runner will probably crash or loop. A test that recurses or declares large locals does not fail politely (record 46 §1.3).

The rest of the runner state is equally scavenged: it lives in an **aliased map-backup buffer** (20,480 bytes of EWRAM) rather than the heap, with the results array carved out of the tail of the same buffer — that budget is the hard ceiling on parameter count × results size (record 46 §1.3).

Structure limits, all hard: **`MAX_TURNS` 16** (exceeding it is a hard error), **`MAX_QUEUED_EVENTS` 30** for SCENE, `MAX_EXPECTED_ACTIONS` 10 (record 46 §1.5b).

Two more mechanics worth knowing when reading a test file:

- **Named arguments are a preprocessor trick, not a language feature.** `MOVE(player, MOVE_TACKLE, criticalHit: TRUE)` works because a variadic macro appends a bare `TRUE` after every argument and every value field in the context structs is immediately followed by its own `explicit…` flag — the trailing `TRUE` lands on the flag. It requires GCC 10+ and the structs' field ordering is load-bearing (record 46 §1.4).
- **Turn actions are recorded-battle bytes, not inputs.** `TURN`/`MOVE`/`SWITCH` push bytes into a recorded-battle script; singles tests run as a recorded link battle against a link opponent. The read path is instrumented *against the test author*: the engine asking for an action the script never offered is reported as an illegal move, and a turn ending with actions unread is reported as incomplete. Turn order is inferred from source order via implicit descending speeds unless speeds are explicit — and if any Speed is explicit, all must be (record 46 §1.8).

## 2. What pass and fail actually mean

Three facts the framework's own prose does not state, and all three matter for how far a green run can be trusted (record 46 §1.5):

- **A test passes by not failing.** The result is initialised to PASS when the test is assigned and only ever moved away from it by a failing assertion, the leak audit, the timeout, or a crash. There is no "assertions ran" counter and no positive pass signal.
- **Every assertion is fatal to the run.** `EXPECT`, `EXPECT_EQ` and the rest all end in a hand-rolled longjmp that never returns; the first failing assertion ends the test and the remaining assertions never execute. The GTest-style `EXPECT`/`ASSERT` distinction the names imply **does not exist** — the only difference between `EXPECT` and `ASSUME` is whether the run reports red or yellow.
- **The vacuity guards are battle-DSL-only.** Unmatched SCENE events, declared-but-unrun `TURN`s, a `PASSES_RANDOMLY` tag that never fired — all of that rejection machinery lives in the battle runner. The generic runner has **none of it**: an assertion-free plain `TEST("x") { }` reports PASS and is indistinguishable from a test that asserts everything (record 46 §1.5).

Two adjacent semantics complete the picture (record 46 §1.5b): a file-scope `ASSUMPTIONS` failure sets a skip on the whole file, so **every test in that file** returns yellow, not red; and `KNOWN_FAILING` inverts the expectation — a test so marked that *passes* is reported as `KNOWN_FAILING_PASS` and nags. A disabled species in a party is an assumption failure, not a test failure — the framework is deliberately tolerant of hacks that cut content (record 46 §1.8).

This is exactly the failure class [[verification-discipline]] exists to close from the outside — a spec that cannot fail is not a proof — so treat a plain `TEST()` as unaudited until its body has been read.

## 3. SCENE: an ordered queue, matched live

`SCENE` does not run after the battle; it runs *before* it, appending expected events into a 30-slot queue. During the battle, recorder hooks try to match each event against the **current head** of the queue and advance it. Consequences (record 46 §1.6):

- **Ordering is real but one-directional.** `NOT` is **literally an alias of `NONE_OF`**, so `NOT X; Y` asserts "Y happened and X did not happen *before* Y" — it does **not** assert X never happened. Anyone reading a test as a spec for design math needs this: a `NOT MESSAGE` line is a statement about sequence, not absence.
- Unmatched leftovers fail at the end, as does a mismatch between `TURN`s declared and turns run.
- The one footgun the framework does catch is consecutive bare `NOT`s, rejected with a did-you-mean pointing at `NONE_OF { }` — narrower than the header's own warning suggests.
- `MESSAGE` matching is fuzzy in exactly one way: a space in the pattern matches space or any line-break control, and a trailing paragraph break is consumed. Everything else is exact against the rendered charmap string.
- `HP_BAR` overloads one 28-bit field: values that fit in 16 bits are an *expected* number, larger values are a *pointer* the observed value is written through — which is the entire implementation of `captureDamage:`, and why it depends on the EWRAM stack of §1 (record 46 §1.6).

## 4. The rigged RNG — and the 85 % fact

The test link overrides the game's weak-aliased `Random*` functions wholesale, so every tagged random call in the battle engine is silently answered by the framework (record 46 §1.7). Defaults, when a tag is neither pinned by `WITH_RNG` nor selected by `PASSES_RANDOMLY`:

| Roll | Default |
|---|---|
| Damage modifier | **minimum roll — 85 %** |
| Accuracy | always hits |
| Critical hits | never |
| Secondary effects | always proc |
| Other weighted calls | highest non-zero-weight index |

**The framework's own documentation is wrong about the damage roll.** It says tests "always roll the same damage modifier"; the exact behaviour is the *minimum* roll — the rigged uniform returns its upper bound, which the damage formula subtracts, landing on **85 %**. Every damage number asserted anywhere in the suite is a min-roll number. **Anyone checking a test's asserted damage against design math must multiply by 0.85 first**, or the arithmetic will disagree with a correct engine (record 46 §1.7).

`WITH_RNG(tag, value)` overrides a tag per turn, keyed off the acting battler, and is consulted **before** the `PASSES_RANDOMLY` tag and before the accuracy/crit/secondary special cases (record 46 §1.7).

`PASSES_RANDOMLY(passes, trials, tag)` with a tag is **exhaustive, not sampled**: the tagged call's range becomes the trial count and the framework enumerates every possible RNG outcome exactly once, accumulating the observed ratio. The verdict tolerance is **±2 percentage points**. If the tag never fired and the expectation is not 0 or 1, the test is INVALID — a real anti-vacuity guard, and one of the few (record 46 §1.7). Without a tag it falls back to 50 seeded trials, which the header itself calls very slow and to be avoided.

## 5. Operational crumbs

- **`make check TESTS="X"` is a prefix match on the test name string** — not a regex, not a filename. Empty `TESTS` matches everything; file-scope `ASSUMPTIONS` bypass the filter so prerequisites still gate a filtered run. The test ELF target is `.PHONY`, so a filtered run **relinks but does not recompile** — which is why changing `TESTS` takes effect immediately and why the fixed cost of any filtered run is one link (record 46 §2.3).
- **`make pokeemerald-test.elf TESTS="X"` builds a UI-openable test ROM** — the same tests, not headless, runnable in a windowed emulator for watching a failure happen (record 46 §2.8).
- **A nondeterministic cost estimate can silently drop tests.** Every parallel worker runs the same list and independently decides which tests are "its" by a greedy cost assignment; the code's own comment warns that an inconsistent cost estimate across processes means some tests may not run — with no error (record 46 §2.7).
- **The 55-second timeout is 55 seconds of *emulated* GBA time, not wall clock.** The watchdog counts emulated cycles, and under a headless runner going as fast as the host allows, the corresponding wall-clock budget is whatever the host's emulation speed makes it. A slow but progressing test (parameter, trial, or battle turn advanced) gets another 55 emulated seconds; in UI mode the timeout is disabled entirely. Do not read "55 s" as a bound on how long a hung test blocks a run (record 46 §2.7).

## 6. Where this framework sits

Its boundary is stated in [[verification-discipline]] §11 and holds: a headless black-box battle tester — nothing drawn, no input, no overworld, no save. Use it for what it graded 2,080 real tests on — battle mechanics — and use the external harness for everything the second ROM cannot see. When a battle test's asserted number disagrees with a design document, check the min-roll rig (§4) and the fatal-assertion semantics (§2) before suspecting either the engine or the design.
