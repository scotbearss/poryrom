# devkitARM has no version number to pin (rolling pacman-distributed toolchain) —
# pin the Docker tag instead. See docs/research/04-gba-rom-architecture.md and
# docs/validated-build-plan-rev0.3.html for why this specific tag was chosen.
FROM devkitpro/devkitarm:20260610

ENV DEVKITARM=/opt/devkitpro/devkitARM
ENV PATH=${DEVKITARM}/bin:${PATH}
ENV BN_DIR=/opt/butano/butano

# Butano pinned to release 9.5.0 (latest as of 2026-07-11) for reproducible builds.
RUN git clone --depth 1 --branch 9.5.0 https://github.com/GValiente/butano.git /opt/butano

# mgba-headless: a true headless verification target with zero SDL/Qt dependency,
# confirmed by reading mGBA's own CMakeLists.txt/source directly (no prebuilt package
# exists anywhere — building it ourselves is the one unverified inference in
# docs/research/03-mgba-headless-harness.md, smoke-tested here). Pinned to a
# commit SHA, not a release tag — see the CORRECTION comment below for why.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpng-dev libsqlite3-dev zlib1g-dev liblua5.4-dev \
    && rm -rf /var/lib/apt/lists/*

# libzip's Debian cmake config is broken (references a zipcmp binary the -dev
# package doesn't ship), so USE_LIBZIP is explicitly disabled rather than
# installed — we don't need zipped-ROM loading for the verification harness.
#
# CORRECTION to docs/research/03-mgba-headless-harness.md: BUILD_HEADLESS does
# not exist in ANY tagged mGBA release (checked 0.9.3 through the current
# latest, 0.10.5, tagged 2025-03-08 — headless-main.c is absent from all of
# them). It only exists on the unreleased master branch. Pinning a commit SHA
# on master instead of a tag, for the same reason devkitARM gets a Docker tag
# pinned instead of a toolchain version: there's no released version to pin.
# mgba-headless never calls core->setVideoBuffer() (confirmed by reading
# src/platform/headless-main.c directly), so the software renderer has nowhere
# to draw and emu:screenshotToImage() returns nil from Lua scripts, always.
# Other in-tree headless tools (src/platform/test/fuzz-main.c) allocate one
# themselves; patch the same pattern into headless-main.c so screenshots work.
#
# SECOND PATCH, added 2026-08-04 — mgba-headless never attaches a SAVE FILE.
# Read from this exact pinned source: main() does mCoreLoadFile -> core->reset
# -> optionally mCoreLoadStateNamed, and nothing else. Every other frontend
# (src/platform/sdl/main.c:210) calls mCoreAutoloadSave right after
# mCoreLoadFile; this one does not, so its emulated flash has never touched a
# file and no .sav can survive the process. That made "a save written by one
# build is read by a LATER LAUNCH" structurally impossible to test here — the
# limit recorded in pokemon/docs/61 §7 and re-derived the hard way in slice 4,
# where a well-formed proof could never go green because of the instrument
# rather than the subject.
#
# GATED ON AN ENV VAR ON PURPOSE. Unset — which is every pre-existing run in
# both game/ and pokemon/ — the binary behaves exactly as it did before, so
# this cannot quietly change results that were already recorded. mCoreAutoloadSave
# opens <rom>.sav beside the ROM with O_CREAT, so the caller must also arrange
# for the ROM to sit somewhere writable (verify_hack.py's persist_dir does).
#
# THIRD PATCH, added 2026-08-05 — mgba-headless produces NO AUDIO AT ALL.
# `mgba-headless --help` lists no audio option, and main() never calls
# setAVStream, so nothing this harness has ever run could be listened to. That
# makes the whole audio subsystem unverifiable here in the strongest sense:
# doc 67 slate item J's failure mode is a note being cut off, and this project's
# two instruments are a RAM probe (which cannot hear) and a screenshot (which
# cannot hear). The mixer's own state IS probeable — gSoundInfo.chans[] is a
# plain global — but "5 voices were active" and "the music sounded right" are
# different claims, and only one of them was reachable.
#
# THE SAME MOVE AS THE SAVE PATCH, AND FOR THE SAME REASON: the limit was
# attributed to the emulator, and the emulator is ours. mCore exposes
# setAVStream (include/mgba/core/core.h:85) and struct mAVStream carries
# postAudioFrame(stream, int16_t left, int16_t right) — so a stereo PCM tap is
# a callback, not a fork. Samples go out as raw s16le; the rate is read from
# core->audioSampleRate() and written to a sidecar, so the WAV header is built
# from what the core actually ran at rather than from an assumption.
#
# GATED, like the other two. Unset — every pre-existing run in both game/ and
# pokemon/ — this costs one null check per frame and changes no result.
#
# ALL THREE seds are ASSERTED. A sed whose anchor stops matching exits 0 and
# leaves the file untouched, so an un-applied patch would present as a working
# build with a silently missing feature — the same shape as the edit script that
# asserted only "the file changed" and shipped a screen with no draw block.
RUN git clone https://github.com/mgba-emu/mgba.git /opt/mgba-src \
    && git -C /opt/mgba-src checkout 5157ce208a5965e8a47bf5b48b5aae5198c22a5e \
    && sed -i \
        's|mCoreLoadConfig(core);|mCoreLoadConfig(core);\n\tvoid* headlessVideoBuffer = malloc(256 * 256 * 4);\n\tcore->setVideoBuffer(core, headlessVideoBuffer, 256);|' \
        /opt/mgba-src/src/platform/headless-main.c \
    && sed -i \
        's|\tcore->reset(core);|\tif (getenv("MGBA_HEADLESS_AUTOLOAD_SAVE")) {\n\t\tmCoreAutoloadSave(core);\n\t}\n\tcore->reset(core);|' \
        /opt/mgba-src/src/platform/headless-main.c \
    && sed -i \
        's|^int main(int argc, char \* argv\[\]) {|static FILE* _headlessAudioOut = NULL;\nstatic void _headlessAudioFrame(struct mAVStream* stream, int16_t l, int16_t r) {\n\tUNUSED(stream);\n\tif (_headlessAudioOut) {\n\t\tfwrite(\&l, 2, 1, _headlessAudioOut);\n\t\tfwrite(\&r, 2, 1, _headlessAudioOut);\n\t}\n}\nstatic void _headlessAudioClose(void) {\n\tif (_headlessAudioOut) {\n\t\tfclose(_headlessAudioOut);\n\t\t_headlessAudioOut = NULL;\n\t}\n}\nstatic struct mAVStream _headlessAVStream = { .postAudioFrame = _headlessAudioFrame };\n\nint main(int argc, char * argv[]) {|' \
        /opt/mgba-src/src/platform/headless-main.c \
    && sed -i \
        's|\tmStandardLoggerInit(\&_logger);|\tconst char* headlessAudioPath = getenv("MGBA_HEADLESS_AUDIO_OUT");\n\tif (headlessAudioPath) {\n\t\t_headlessAudioOut = fopen(headlessAudioPath, "wb");\n\t\tif (_headlessAudioOut) {\n\t\t\tatexit(_headlessAudioClose);\n\t\t\tcore->setAVStream(core, \&_headlessAVStream);\n\t\t\tchar ratePath[1024];\n\t\t\tsnprintf(ratePath, sizeof(ratePath), "%s.rate", headlessAudioPath);\n\t\t\tFILE* rf = fopen(ratePath, "w");\n\t\t\tif (rf) {\n\t\t\t\tfprintf(rf, "%u\\n", core->audioSampleRate(core));\n\t\t\t\tfclose(rf);\n\t\t\t}\n\t\t}\n\t}\n\tmStandardLoggerInit(\&_logger);|' \
        /opt/mgba-src/src/platform/headless-main.c \
    && grep -q 'setVideoBuffer' /opt/mgba-src/src/platform/headless-main.c \
    && grep -q 'MGBA_HEADLESS_AUTOLOAD_SAVE' /opt/mgba-src/src/platform/headless-main.c \
    && grep -q 'MGBA_HEADLESS_AUDIO_OUT' /opt/mgba-src/src/platform/headless-main.c \
    && grep -q 'setAVStream' /opt/mgba-src/src/platform/headless-main.c \
    && cmake -S /opt/mgba-src -B /opt/mgba-build -G Ninja \
        -DBUILD_HEADLESS=ON -DENABLE_SCRIPTING=ON -DUSE_PNG=ON \
        -DBUILD_QT=OFF -DBUILD_SDL=OFF -DUSE_FFMPEG=OFF -DUSE_DISCORD_RPC=OFF \
        -DUSE_LIBZIP=OFF -DUSE_MINIZIP=OFF -DUSE_EDITLINE=OFF \
        -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /opt/mgba-build --target mgba-headless -j"$(nproc)" \
    && cp /opt/mgba-build/mgba-headless /usr/local/bin/mgba-headless \
    && cp -P /opt/mgba-build/libmgba.so* /usr/local/lib/ \
    && ldconfig \
    && rm -rf /opt/mgba-build /opt/mgba-src

WORKDIR /project
