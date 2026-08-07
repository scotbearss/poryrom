-- Scripted-input driver for the Pokémon Thing mode.
--
-- Contains ZERO assertions, by the same discipline as harness/boot_proof.lua
-- and docker/harness/run_spec.lua (see docs/research/06-ai-harness-lessons.md): the
-- emulator-side script only DRIVES input, SAMPLES state and PRINTS it. Every
-- pass/fail judgement happens outside the emulator, in tools/make_savestate.py,
-- against values this script did not produce.
--
-- Everything variable -- the input timeline, every probe address, the savestate
-- path -- is passed in from outside via a generated plan file, because those are
-- derived from the built pokeemerald.sym and from include/global.h. A stale
-- constant baked into a harness is exactly the silent drift this project keeps
-- getting bitten by, so this file never needs editing when the engine moves.
--
-- What it samples each trace tick:
--   gMain.callback2      the engine's current screen/state, as a raw pointer.
--                        Python resolves it to a NAME via pokeemerald.sym -- that
--                        naming is what makes a blind input sequence debuggable.
--   *gSaveBlock1Ptr      dereferenced EVERY sample, never cached: doc 44's ASLR
--                        correction says SaveBlock1 moves at every battle start
--                        and map load. From it: player x/y and mapGroup/mapNum.
--   gPlayerPartyCount    how many party slots are live.
--   party slot 0 raw     personality/otId/secure-block/level/hp -- printed RAW.
--                        The substructure DECRYPTION happens in Python, so the
--                        emulator side never gets to decide what a "valid mon" is.

local plan = dofile("/engine/build/_drive_plan.lua")

local frame = 0
local seg_i = 1              -- index into plan.runs, each {mask, frames}
local seg_left = 0
local shot_i = 0

local function hex32(v) return string.format("%08x", v) end

-- Read `n` bytes at `addr` as a lowercase hex string. Used for the party slot so
-- that the encrypted substructures cross the emulator boundary untouched.
local function hexdump(addr, n)
    local out = {}
    for i = 0, n - 1 do
        out[#out + 1] = string.format("%02x", emu:read8(addr + i))
    end
    return table.concat(out)
end

local function trace()
    local cb2 = emu:read32(plan.gmain + plan.off_callback2)
    local sb1 = emu:read32(plan.gsaveblock1ptr)
    local x, y, mg, mn = -1, -1, -1, -1
    -- A null/garbage pointer before the save block is allocated is normal engine
    -- behaviour during boot; print sentinels rather than reading wild addresses.
    if sb1 >= 0x02000000 and sb1 < 0x02040000 then
        x = emu:read16(sb1 + 0)
        y = emu:read16(sb1 + 2)
        mg = emu:read8(sb1 + 4)
        mn = emu:read8(sb1 + 5)
    end
    local pc = emu:read8(plan.gplayerpartycount)
    -- gSaveBlock1Ptr->pos is the CAMERA, and on a map smaller than the screen
    -- the camera cannot scroll, so it is useless as a player position indoors.
    -- The player's real tile is gObjectEvents[0].currentCoords (+MAP_OFFSET).
    local ev = plan.gobjectevents
    local px = emu:read16(ev + 0x10)
    local py = emu:read16(ev + 0x12)
    local face = emu:read8(ev + 0x18) & 0x0F
    -- Diagnostics that make "the player is not moving" answerable rather than
    -- guessable: hk proves our keypad reached the ENGINE (not just the KEYINPUT
    -- register), and pa/ps say whether the avatar is under script lock.
    local hk = emu:read16(plan.gmain + 0x2C)          -- gMain.heldKeys
    local pa = emu:read8(plan.gplayeravatar + 0x00)   -- gPlayerAvatar.flags
    local ps = emu:read8(plan.gplayeravatar + 0x06)   -- gPlayerAvatar.preventStep
    -- lk = sLockFieldControls, st = sGlobalScriptContextStatus,
    -- sp = sGlobalScriptContext.scriptPtr. Python resolves sp against the .sym
    -- to NAME the script that is holding the lock -- the same read-a-pointer-
    -- and-resolve-it mechanism boot_proof.py proved, now doing real work.
    local lk = emu:read8(plan.slockfieldcontrols)
    local st = emu:read8(plan.sglobalscriptcontextstatus)
    local sp = emu:read32(plan.sglobalscriptcontext + 0x08)
    console:log(string.format(
        "TRACE frame=%d cb2=%s sb1=%s x=%d y=%d mg=%d mn=%d pc=%d px=%d py=%d "
        .. "f=%d hk=%04x pa=%02x ps=%d lk=%d st=%d sp=%s",
        frame, hex32(cb2), hex32(sb1), x, y, mg, mn, pc, px, py, face,
        hk, pa, ps, lk, st, hex32(sp)))
end

local function dump_party()
    for slot = 0, 5 do
        local base = plan.gplayerparty + slot * plan.mon_stride
        console:log(string.format("PARTY frame=%d slot=%d raw=%s",
            frame, slot, hexdump(base, plan.mon_stride)))
    end
end

local function update()
    frame = frame + 1

    -- advance the input timeline
    if seg_left <= 0 then
        local run = plan.runs[seg_i]
        if run then
            emu:setKeys(run[1])
            seg_left = run[2]
            seg_i = seg_i + 1
        else
            emu:setKeys(0)
            seg_left = 1 << 30
        end
    end
    seg_left = seg_left - 1

    if plan.trace_every > 0 and (frame % plan.trace_every == 0 or frame == 1) then
        trace()
    end

    -- emu:screenshot(path) rather than emu:screenshotToImage()+img:save():
    -- the latter corrupts the heap when called repeatedly under this
    -- mgba-headless build (second call produced a 306-byte PNG, and the
    -- emulator died with `free(): invalid pointer` shortly after). The direct
    -- form survives hundreds of calls. Cost one failed run to find.
    if plan.shot_every > 0 and frame % plan.shot_every == 0 then
        emu:screenshot(string.format("%s/f%06d.png", plan.shot_dir, frame))
        shot_i = shot_i + 1
    end

    if frame == plan.total_frames then
        emu:setKeys(0)
        trace()
        dump_party()
        emu:screenshot(plan.final_shot)
        if plan.savestate_path ~= "" then
            local ok = emu:saveStateFile(plan.savestate_path, plan.savestate_flags)
            console:log("SAVESTATE path=" .. plan.savestate_path ..
                        " returned=" .. tostring(ok))
        end
        console:log("DRIVE complete frames=" .. frame .. " shots=" .. shot_i)
        local f = io.open("/engine/build/DONE", "w")
        f:write("done")
        f:close()
    end
end

callbacks:add("frame", update)
