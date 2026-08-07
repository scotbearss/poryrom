# The walls — measured limits, and what hitting one looks like

**Every entry here was hit on purpose or hit by accident and then measured.** None is a guess.
Cite nothing from this file in chat — translate it into one plain sentence (see `voice.md`).

**The dangerous column is the last one.** A limit that throws an error costs an hour. A limit that
renders something *plausible and wrong* costs a week, because nothing tells you. Thirteen of these
are silent.

## Maps and the overworld

| Limit | Value | What hitting it looks like |
|---|---|---|
| Map size | ceiling reached well before you expect | **SILENT.** The map draws as its own border block tiled edge to edge — indoors that reads as solid black, outdoors as a flawless empty meadow you cannot walk in. Never an error. |
| NPCs visible at once | 16-slot spawn window | **SILENT.** Beyond the window an NPC simply is not there; the map looks finished. |
| Sprite palettes on screen | 16 dynamic slots | **SILENT AND WORSE.** A refused sprite renders in full, in the right place, correctly animated — **in someone else's colours.** Reads as a design choice, not a fault. Outdoor maps are tighter: weather claims a slot too. |
| Metatile behaviours | 240/240 full | A new behaviour must RECLAIM an old slot and inherits its flags. Twelve ids look free to a search while being live in binary tileset data. |
| Shared tileset space | `gTileset_General` full at 512/512 | A tileset can also *declare* more tiles than it ships — one ships 278 and references 281. |
| NPC on an impassable tile | rule holds, with 378 deliberate exceptions in the original | Use the baseline diff; do not soften the rule. |

## Sound

| Limit | Value | What hitting it looks like |
|---|---|---|
| Simultaneous PCM voices | 5 | **SILENT, AND YOU ARE ALREADY OVER IT.** Ordinary map music steals a voice about ten times a second. Past the ceiling the mixer takes a sounding note or drops it — no error, nothing on screen. This is a floor you are standing on, not a cliff you walk off. |
| Music players | 4 | Defined in the build system, not in any source file. |

## Items, species and the save file

| Limit | Value | What hitting it looks like |
|---|---|---|
| Adding a new Poké Ball | forces its item id into a used slot | **SILENT SAVE CORRUPTION.** Renumbering shifts ~800 later ids, and the bag stores the raw id — an older save then reads every item one slot off, with a valid checksum. Costs zero save bytes and still invalidates the save. |
| Any renumbering | — | Ask what **stores** the value, not what references it. |
| Save layout change | size-preserving edits are the dangerous ones | **SILENT.** The engine loudly rejects size changes; a same-size layout change produces a save that loads, validates, and lies — a main menu identical to the correct one, minus one line. |
| Shrinking anything save-resident | — | Ask whether any field's legal **range** shrank, and who reads that field without the bound its writer applies. An old save can hand the new build a value its own code can never produce. |
| The training diary | now in checksummed sectors | Data outside a checksum is data nothing is guarding. |

## Battle engine and memory

| Limit | Value | What hitting it looks like |
|---|---|---|
| Battle-script stack | 8 deep | Walk off it on purpose to see it. |
| IWRAM | ~2.3 KB free | Loud. But new data lands in the *scarcer* pool unless you say otherwise, and a successful link never tells you which pool you spent. |
| Save-block pointers | re-rolled at every battle start and map load | Re-read the pointer every time; never cache it. |

## Things that are true about the whole engine

- **What a thing DECLARES is not what it HAS.** Tilesets, id spaces and pointer tables all lie in
  this direction; check the actual contents, not the header.
- **A comment is evidence about the version it was written for**, not about the code in front of
  you. One documented subsystem turned out to have no callers at all.
- **Ask who READS a field, not who writes it.** A field populated in 36 places and read in none is
  dead, and reading only the setters says the opposite.
- **If a fault would produce a plausible artifact, the check has to be static** — run before the
  build, not after. A screenshot cannot catch what renders correctly.
