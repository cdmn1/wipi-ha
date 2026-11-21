# Naomi patch and settings audit

**Audit date:** 2026-11-16  
**Repository branch:** `wipi-x86-port`  
**Scope:** `wipi-netbooter/`

This document separates the app's existing byte patches from upstream Naomi settings mechanisms and additional game-specific patch candidates. It is not a claim that every patch has been tested on physical hardware.

## Current app byte-patch catalogue

The current `app.py` defines the following patches. Every byte patch checks the expected bytes before replacing them. The original ROM file is not modified; patches are applied to the upload buffer.

| Game | Force Free Play offset | Silent Attract offset | Expected → replacement |
|---|---:|---:|---|
| Guilty Gear X | `0x72A28` | `0x72ABC` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Ikaruga | `0x52626` | — | `42 84 → 1A E0` |
| Illvelo / Illmatic Envelope | `0x620C6` | `0x6214E` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Karous | `0x6135A` | `0x613E0` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Marvel vs. Capcom 2 | `0x1D8138` | `0x1D81CC` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Monkey Ball | `0x6BE30` | `0x6BEC4` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Power Stone 2 | `0x158F88` | `0x15901C` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Puyo Puyo Da! | `0x44F86` | `0x4500C` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Puyo Puyo Fever | `0x37EAE` | `0x37F36` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Quiz K QMode | `0x29A58` | `0x29AEC` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Radirgy | `0x6136E` | `0x613F4` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Street Fighter Zero 3 Upper | `0xE8832` | `0xE88B8` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Tetris Kiwamemichi | `0x7FAB2` | `0x7FB38` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Trigger Heart Exelica | `0x13E522` | `0x13E5AA` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Trizeal | `0xBE782` | `0xBE808` | `42 84 → 1A E0`; `40 63 → 00 E3` |
| Under Defeat | `0x43FD6` | `0x4405C` | `42 84 → 1A E0`; `40 63 → 00 E3` |

These offsets and guards are the app's current definitions. They should continue to be treated as revision-sensitive: a failed expected-byte check means the patch must not be applied.

## Additional documented mechanisms and candidates

### 1. Naomi header fields — supported, non-byte-level API

**Mechanism:** `naomi.NaomiRom` exposes structured header properties rather than requiring hard-coded offsets:

- `defaults` — per-region EEPROM defaults.
- `players` — allowed player counts (1–4).
- `frequencies` — accepted monitor frequencies (15/31).
- `orientations` — accepted horizontal/vertical orientation.
- `servicetype` — individual/common service-button type.
- `regions` — allowed BIOS regions.
- `names`, `sequencetexts`, `serial`, and `date`.

**Identification:** parse the actual Naomi ROM header with `NaomiRom`; do not infer these fields from filenames. Keep region changes separate from normal settings. In particular, do not enable the app's SFZ3 Upper region-unlock option: the user's cabinet black-screened with that option.

**Purpose:** adjust BIOS-visible defaults and compatibility declarations using the library's serializer. These are header fields, not universal gameplay fixes. A future UI should show the current value and preserve all unedited values.

**Confidence:** high for API support; individual game compatibility remains game-dependent.

Source: https://pypi.org/project/naomiutils/0.5.4/

### 2. Per-game EEPROM settings — strong next feature

**Mechanism:** `naomi.settings.SettingsManager` reads bundled definition files, identifies a game's settings by the four-byte serial in its ROM header, and exposes valid values/defaults and dependencies. A typical flow is `from_rom(rom, region)` → edit the returned wrapper / JSON → `to_eeprom()` → `NaomiSettingsPatcher.put_eeprom()`. The patcher attaches a settings-writing stub and EEPROM to the in-memory ROM for netboot.

**Documented game examples and identification:**

| Game | ROM serial / identification | Settings documented | Confidence |
|---|---|---|---|
| Marvel vs. Capcom 2 | `BBG0` | Game and system EEPROM settings; character/game options are discussed in the project thread | High for definition existence; per-option validation should come from the bundled definition |
| Monkey Ball | `BDF0` | Difficulty, number of monkeys, ball velocity boost, and joystick calibration | High; the author documented EEPROM byte-by-byte comparison and the definition |
| Jambo Safari | Read the four-byte serial from the actual ROM header | EEPROM settings and calibration; requires the game's protection patch before header/EEPROM injection | High for the mechanism; exact serial must be read from the ROM |
| Crazy Taxi | Read the four-byte serial from the actual ROM header | EEPROM settings and calibration; requires the game's protection patch; do not use header Free Play / Silent Attract flags | High for the mechanism; exact serial must be read from the ROM |

Do not match these games by filename alone. The header serial is the authoritative definition key. The library's definition files and their valid values should be the source of truth for the editor.

**Important caveats:**
- DragonMinded documented that Monkey Ball, Jambo Safari and Crazy Taxi need joystick calibration applied again on each netboot if consistent calibration is desired.
- Crazy Taxi freezes at the SEGA logo when the Free Play / Silent Attract header flags are changed. Use the game's direct code patches instead; do not treat it like Jambo Safari.
- EEPROM settings are written by an injected stub. This is a supported project mechanism, but not an official Naomi BIOS feature. Test on an emulator first and then on hardware.

Sources:
- https://www.arcade-projects.com/threads/netboot-naomi-with-eeprom-presets.18977/
- https://www.arcade-projects.com/threads/netboot-naomi-with-eeprom-presets.18977/page-7
- https://pypi.org/project/naomiutils/0.5.4/

### 3. Ikaruga SRAM settings — documented, but score-destructive

**Mechanism:** Ikaruga stores its game settings in SRAM, not the game EEPROM. Use `NaomiSettingsPatcher.put_sram()` with a valid 32 KiB SRAM image.

**Identification:** verify the ROM is Ikaruga from its Naomi header; do not apply an EEPROM game-settings definition.

**Purpose:** carry configured Ikaruga game options into each boot.

**Warning:** attaching a prepared SRAM overwrites the board's existing SRAM contents and therefore can overwrite high scores. This should only be exposed as an explicit, warned action, never silently enabled.

**Confidence:** high for the storage mechanism; no SRAM file or app integration is currently present.

Source: https://www.arcade-projects.com/threads/netboot-naomi-with-eeprom-presets.18977/

### 4. Header-protection bypasses — Crazy Taxi and Jambo Safari

**Mechanism:** DragonMinded documented a pair of checked-in binary patches for Crazy Taxi and Jambo Safari. Their code hashes the first `0x500` bytes of the ROM header and can freeze or corrupt execution when header changes are detected. The bypass changes the position function to return zero and NOPs the following branch-delay setup instruction. The author tested settings injection with both games after applying the bypass.

**Identification:** use the exact upstream binary patch's applicability checks against the complete ROM image. The forum description does not publish numeric ROM offsets, expected bytes, replacement bytes, or exact ROM revision/serials. These must be obtained from the upstream `patches/` files before adding either patch to this app.

**Purpose:** allow safe header/EEPROM settings injection in these games.

**Confidence:** high that the two upstream patches exist and were tested by their author; insufficient data to recreate or ship the patches from this audit.

Source: https://www.arcade-projects.com/threads/netboot-naomi-with-eeprom-presets.18977/page-7

### 5. Crazy Taxi / Jambo Safari direct Free Play and Silent Attract patches

DragonMinded later documented separate direct-code Free Play / Silent Attract patches for these two games because header flags were unsuitable (especially Crazy Taxi). The forum confirms that the patches were checked in, but the discussion does not provide their patch hunks or exact ROM revision identifiers.

**Decision:** do not add guessed offsets. Retrieve the original upstream patch files and use `arcadeutils.BinaryDiff.can_patch()` before applying them. A patch must be rejected if its full expected pattern does not match.

Source: https://www.arcade-projects.com/threads/netboot-naomi-with-eeprom-presets.18977/page-6

### 6. Default game EEPROM patching — experimental

DragonMinded's `patch_default_settings` tool can search a game ROM for its compiled default EEPROM bytes and replace them with selected defaults. The project explicitly says this is not guaranteed and requires a game settings definition.

**Decision:** keep this out of the one-click patch catalogue until the game-specific default pattern is known, uniquely located, and validated against a ROM revision. It is not a generic safe patch.

Source: https://github.com/DragonMinded/netboot

## Categories not promoted

- **Generic JVS bypass:** no sufficiently specific primary-source patch, ROM identity, or expected-byte sequence was verified in this audit. Do not advertise it as a general Naomi patch category.
- **Generic character unlock byte patch:** the project discussion mentions character unlocks as an example of game EEPROM settings, not as a universal byte patch. Expose only where a particular game's definition documents the setting.
- **SFZ3 Upper region unlock:** leave disabled. The user's physical test produced a black screen.

## Implementation status

- No new binary patch was added because the upstream Crazy Taxi/Jambo Safari patch files and their exact hunks were not retrievable. No offsets or replacement bytes have been invented.
- The existing Illvelo Force Free Play implementation is unchanged.
- WiPi Netbooter 0.4.0 adds a read-only `GET /api/games/<filename>/settings` endpoint. It decompresses the selected ROM if needed, validates the Naomi header, identifies the four-byte serial and declared BIOS regions, and returns the applicable bundled `SettingsManager.from_rom()` settings as JSON. A caller may request a specific region using `?region=REGION_NAME`.
- This endpoint does not attach an EEPROM, alter Naomi ROM header defaults, write to cabinet NVRAM, or change the ROM sent to the cabinet. It is a discovery/API foundation, not yet a user-facing editor.
- CI now checks that the bundled `BBG0.settings` definition is available and that `SettingsManager.from_serial()` can serialize its wrapper. The 0.4.0 workflow run is pending at the time of this update.
- The known SFZ3 Upper region-unlock option remains untouched and must stay disabled; the user's cabinet black-screened with it.

Next implementation step: build a user-facing editor on this read-only discovery API, then add a separate explicit save/apply action using `NaomiSettingsPatcher.put_eeprom()` only after per-game protection requirements and rollback behaviour are handled.

## Recommended implementation order

1. Add a Naomi header/defaults editor using the structured `NaomiRom` and `SettingsManager` APIs; show ROM serial and region explicitly.
2. Add EEPROM settings for games only when the bundled definition file exists for the ROM serial.
3. Add Ikaruga SRAM profiles only with an explicit high-score overwrite warning and a supplied SRAM file.
4. Retrieve and vendor the exact Crazy Taxi/Jambo Safari upstream `.binpatch` files, then use `BinaryDiff.can_patch()` as a mandatory preflight before offering those patches.
5. Keep all binary patch operations on the transfer buffer and retain expected-byte / applicability checks.
