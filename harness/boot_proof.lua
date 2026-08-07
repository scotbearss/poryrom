-- Slice 0 boot proof for the Pokémon Thing mode.
--
-- Contains ZERO assertions, by the same discipline as docker/harness/run_spec.lua
-- (see docs/research/06-ai-harness-lessons.md): the emulator-side script only
-- SAMPLES state and prints it. Every pass/fail judgement happens outside the
-- emulator, in tools/boot_proof.py, against values it did not produce.
--
-- What it samples, and why each one is load-bearing:
--   gMain.vblankCounter1  liveness. Incremented by the VBlank interrupt handler,
--                         so a strictly rising value proves the ROM is actually
--                         executing its main loop -- not merely loaded, not stuck
--                         in a BIOS spin, not black-screened.
--   gMain.callback2       state progression. A function pointer; resolving it
--                         against pokeemerald.sym names the screen the engine is
--                         on. This is the same .sym-reading mechanism Slice 1's
--                         verification harness is built on, exercised here first
--                         on the cheapest possible target.
--   gMain.state           the sub-state counter within the current callback.
--
-- Addresses are passed in from outside (build/_boot_probe.lua) rather than
-- hardcoded here, because they are derived from the built pokeemerald.sym and
-- include/main.h -- they change with the build, and a stale constant baked into
-- a harness is exactly the kind of silent drift this project keeps getting bitten
-- by. This file never needs editing when the engine moves.

local probe = dofile("/engine/build/_boot_probe.lua")

local SAMPLE_EVERY = probe.sample_every or 60
local TOTAL_FRAMES = probe.total_frames or 600

local frame = 0

local function update()
    frame = frame + 1

    if frame % SAMPLE_EVERY == 0 or frame == 1 then
        local vbl = emu:read32(probe.vblank_counter1)
        local cb2 = emu:read32(probe.callback2)
        local state = emu:read8(probe.state)
        console:log(string.format(
            "BOOTPROBE frame=%d vblank=%d callback2=%08x state=%d",
            frame, vbl, cb2, state))
    end

    if frame == TOTAL_FRAMES then
        local img = emu:screenshotToImage()
        img:save("/engine/build/boot_screenshot.png", "png")
        console:log("BOOTPROBE complete")
        local f = io.open("/engine/build/DONE", "w")
        f:write("done")
        f:close()
    end
end

callbacks:add("frame", update)
