# Naomi patch and header-settings audit

**Updated:** 2026-11-23 (second-pass source and safety review)  
**Repository:** cdmn1/wipi-ha, branch wipi-x86-port  
**Scope:** wipi-netbooter/  
**App version in this change:** 0.4.4

This audit distinguishes upstream patch definitions from verified hardware behavior. The added patches are optional and remain disabled until a user selects them. No physical cabinet test is claimed.

## Summary of this update

- Added direct Crazy Taxi and Jambo Safari Force Free Play and Silent Attract patches from the upstream netboot patch tree.
- Added Crazy Taxi and Jambo Safari header-protection bypasses, which are prerequisites for EEPROM/header injection in those games.
- Added all-character-unlocked patches for Marvel vs. Capcom 2 and both named CvS2 variants.
- Added the missing original CvS, CvS2 MOTM and CvS2 MF Force Free Play / Silent Attract entries, with exact ROM-size checks.
- Switched upstream multi-hunk patches to arcadeutils BinaryDiff. It checks the declared file size and every expected byte before applying any hunk.
- Removed the SFZ3 Upper region-unlock option and its code path. Legacy saved selections are filtered out and never applied.
- Left the existing Illvelo Force Free Play definition and behavior unchanged.

## Additional Force Free Play / Silent Attract coverage

| Game | Free Play | Silent Attract | Image-size requirement |
|---|---:|---:|---:|
| Capcom vs. SNK: Millennium Fight 2000 | 0xFF358: 42 84 → 1A E0 | 0xFF3EC: 40 63 → 00 E3 | 125,829,120 bytes |
| Capcom vs. SNK 2: Mark of the Millennium 2001 | 0x116E58: 42 84 → 1A E0 | 0x116EEC: 40 63 → 00 E3 | 159,383,552 bytes |
| Capcom vs. SNK 2: Millionaire Fighting 2001 | 0x1161F8: 42 84 → 1A E0 | 0x11628C: 40 63 → 00 E3 | 159,383,552 bytes |

The original source describes these offsets as known working patches, but does not name a complete ROM revision or hash. The app requires the exact image size and checks the expected two-byte opcode. A mismatch fails closed.

Crazy Taxi and Jambo Safari use upstream multi-hunk BinaryDiff files, which also guard the ROM header game ID at 0x134:

| Game / patch | Exact preconditions and changes | Purpose | Confidence |
|---|---|---|---|
| Crazy Taxi — Force Free Play | 0x134: 42 41 43 30 → 42 41 43 30; 0x4AB5C: 42 84 → 1A E0; file size 134,217,728 | Force Free Play | High for the documented patch and image guard; not cabinet-tested here |
| Crazy Taxi — Silent Attract | 0x134: 42 41 43 30 → 42 41 43 30; 0x4AC24: 59 23 → 00 E3; file size 134,217,728 | Disable attract sound | High for the documented patch and image guard; not cabinet-tested here |
| Crazy Taxi — header-protection bypass | 0x134: 42 41 43 30 → 42 41 43 30; 0xBA0C: 0B 43 63 61 → 00 E0 09 00; file size 134,217,728 | Permit header/EEPROM modification | High for upstream definition; physical effect unverified |
| Jambo Safari — Force Free Play | 0x134: 42 41 55 30 → 42 41 55 30; 0xC90A0: 42 84 → 1A E0; file size 75,497,472 | Force Free Play | High for the documented patch and image guard; not cabinet-tested here |
| Jambo Safari — Silent Attract | 0x134: 42 41 55 30 → 42 41 55 30; 0xC9168: 59 23 → 00 E3; file size 75,497,472 | Disable attract sound | High for the documented patch and image guard; not cabinet-tested here |
| Jambo Safari — header-protection bypass | 0x134: 42 41 55 30 → 42 41 55 30; 0x946D0: 0B 43 E2 61 → 00 E0 09 00; file size 75,497,472 | Permit header/EEPROM modification | High for upstream definition; physical effect unverified |

BAC0 (Crazy Taxi) and BAU0 (Jambo Safari) are the four-byte ROM header game IDs in these patch guards. They are not the Naomi EEPROM serial exposed by NaomiRom.serial.


## Complete baseline direct-byte patch inventory

The following entries are the per-title offsets published by DragonMinded in the original Naomi patch discussion. For every listed byte patch, the preimage is 42 84 and the replacement is 1A E0 for Force Free Play, or the preimage is 40 63 and the replacement is 00 E3 for Silent Attract.

| Game | Force Free Play offset | Silent Attract offset | Source identification / revision confidence |
|---|---:|---:|---|
| Capcom vs. SNK: Millennium Fight 2000 | 0xFF358 | 0xFF3EC | Exact image size is enforced by this app (125,829,120 bytes); source gives no dump hash/revision |
| Capcom vs. SNK 2: Mark of the Millennium 2001 | 0x116E58 | 0x116EEC | Exact image size is enforced (159,383,552 bytes); source gives no dump hash/revision |
| Capcom vs. SNK 2: Millionaire Fighting 2001 | 0x1161F8 | 0x11628C | Exact image size is enforced (159,383,552 bytes); source gives no dump hash/revision |
| Guilty Gear X | 0x72A28 | 0x72ABC | Title/filename aliases plus two-byte preimage only; no source hash/revision |
| Ikaruga | 0x52626 | Not offered | Title/filename aliases plus two-byte preimage; game already disables advertise sound in its original binary |
| Illvelo | 0x620C6 | 0x6214E | Title/filename aliases plus two-byte preimage only; existing user-confirmed Force Free Play patch is unchanged |
| Karous | 0x6135A | 0x613E0 | Title/filename aliases plus two-byte preimage only; no source hash/revision |
| Marvel vs. Capcom 2 | 0x1D8138 | 0x1D81CC | Title/filename aliases plus two-byte preimage only; no source hash/revision for these two system patches |
| Monkey Ball | 0x6BE30 | 0x6BEC4 | Title/filename aliases plus two-byte preimage only; no source hash/revision |
| Power Stone 2 | 0x158F88 | 0x15901C | Title/filename aliases plus two-byte preimage only; no source hash/revision |
| Puyo Puyo Da! | 0x44F86 | 0x4500C | Title/filename aliases plus two-byte preimage only; no source hash/revision |
| Puyo Puyo Fever | 0x37EAE | 0x37F36 | Title/filename aliases plus two-byte preimage only; no source hash/revision |
| Quiz K QMode | 0x29A58 | 0x29AEC | Title/filename aliases plus two-byte preimage only; no source hash/revision |
| Radirgy | 0x6136E | 0x613F4 | Title/filename aliases plus two-byte preimage only; no source hash/revision |
| Street Fighter Zero 3 Upper | 0xE8832 | 0xE88B8 | Only these two independent system patches remain; the known-bad region-unlock patch is removed |
| Tetris Kiwamemichi | 0x7FAB2 | 0x7FB38 | Title/filename aliases plus two-byte preimage only; no source hash/revision |
| Trigger Heart Exelica | 0x13E522 | 0x13E5AA | Title/filename aliases plus two-byte preimage only; no source hash/revision |
| Trizeal | 0xBE782 | 0xBE808 | Title/filename aliases plus two-byte preimage only; no source hash/revision |
| Under Defeat | 0x43FD6 | 0x4405C | Title/filename aliases plus two-byte preimage only; no source hash/revision |

**Important revision limitation:** the 2019 source thread gives these offsets and byte pairs, but does not publish a SHA-1/CRC or a complete dump revision identifier for each title. The app therefore uses the game title/filename aliases and exact two-byte preimage; it does not claim these guards distinguish every regional/revision variant. The three Capcom/CvS entries additionally have exact image-size checks. A successful preimage check is not a substitute for a full ROM hash or a cabinet test. This is medium confidence for the documented offsets and lower confidence for unlisted ROM revisions.

## Additional game-specific unlock patches

| Game / patch | ROM identification | Exact byte changes | Purpose | Confidence |
|---|---|---|---|---|
| Marvel vs. Capcom 2 — all characters unlocked | Exactly 143,242,752 bytes; Naomi ROM serial must be BBG0; all 16 preimages must match | 0x2074C1, 0x2074D5, 0x2074E9, 0x2074FD, 0x207511, 0x207525, 0x207539, 0x20754D, 0x3EDC61, 0x3EDC75, 0x3EDC89, 0x3EDC9D, 0x3EDCB1, 0x3EDCC5, 0x3EDCD9, 0x3EDCED: each 00 → 04 | Unlock the character set | Medium-high: upstream patch plus app-enforced BBG0 serial, size and byte guards; no cabinet test |
| CvS2 Mark of the Millennium 2001 — all characters unlocked | Exactly 159,383,552 bytes; title/filename must identify this variant; all 16 preimages must match. Upstream patch has no ROM-serial guard | 0x14945C, 0x149470, 0x149484, 0x149498, 0x1494AC, 0x1494C0, 0x1494D4, 0x1494E8, 0x22D804, 0x22D818, 0x22D82C, 0x22D840, 0x22D854, 0x22D868, 0x22D87C, 0x22D890: each 00 → 03 | Unlock the character set | Medium: exact upstream size and 16 expected-byte checks, but no header serial in the upstream patch; no cabinet test |
| CvS2 Millionaire Fighting 2001 — all characters unlocked | Exactly 159,383,552 bytes; title/filename must identify this variant; all 16 preimages must match. Upstream patch has no ROM-serial guard | 0x1487FC, 0x148810, 0x148824, 0x148838, 0x14884C, 0x148860, 0x148874, 0x148888, 0x22D804, 0x22D818, 0x22D82C, 0x22D840, 0x22D854, 0x22D868, 0x22D87C, 0x22D890: each 00 → 03 | Unlock the character set | Medium: exact upstream size and 16 expected-byte checks, but no header serial in the upstream patch; no cabinet test |

The CvS2 variants have the same declared image size. Their options are matched using distinct title/filename aliases, and every expected byte must match. Do not rename an unrelated image to force an option to appear.

### Additional upstream candidates not enabled

- **Capcom vs. SNK: Millennium Fight 2000 — All characters unlocked.** Upstream file declares 125,829,120 bytes. It changes header bytes 0x134: 41 → 42 and 0x136: 43 → 54, plus these 16 bytes 00 → 07: 0x12EB9D, 0x12EBB1, 0x12EBC5, 0x12EBD9, 0x12EBED, 0x12EC01, 0x12EC15, 0x12EC29, 0x22E0C5, 0x22E0D9, 0x22E0ED, 0x22E101, 0x22E115, 0x22E129, 0x22E13D, 0x22E151. **Deferred:** it rewrites game-ID header bytes and lacks a complete revision/hash identity in the patch file.
- **Guilty Gear X — auto-initialize EEPROM/game settings.** Upstream file declares 125,829,120 bytes and contains these hunks: 0x19E8: 28 22 D6 89 → 09 00 09 00; 0x1AE6: 28 22 DF 89 → 09 00 09 00; 0x95425: 72 → 6C; 0x95427: 73 → 61; 0x95429: 20 61 6E 79 20 6B 65 79 20 54 6F 20 53 74 61 72 74 → 65 20 77 61 69 74 20 66 6F 72 20 45 45 50 52 4F 4D; 0x9543B: 44 65 66 61 75 6C 74 20 53 65 → 69 6E 69 74 69 61 6C 69 7A 61; 0x95446: 74 69 → 69 6F; 0x95449: 67 0A → 0A 00. **Deferred:** this helper is for EEPROM initialization; the current app saves profiles but does not yet attach them to outgoing ROMs.
- **Atomiswave-conversion unlock patches** (KOF Neo Wave, KOF XI, NeoGeo Battle Coliseum, The Rumble Fish, The Rumble Fish 2 and Knights of Valour: The Seven Spirits) are not included because they target Atomiswave conversions rather than native Naomi ROMs. Metal Slug 6 violent is likewise not promoted as a Naomi-native patch.
- No generic JVS-bypass patch was verified with a sufficiently specific Naomi ROM identity and expected-byte sequence.

## Supported Naomi header/configuration settings

DragonMinded's header-settings discussion documents per-region defaults in the ROM header at:

- Japan: 0x1E0
- USA: 0x1F0
- Export: 0x200

Each region has a 16-byte defaults record. The first three documented record offsets are Japan 0x1E0, USA 0x1F0 and Export 0x200. The first four bytes in the examples are:

- 01 02 00 1B: apply defaults, horizontal orientation with advertise sound disabled, common coin chute, Free Play.
- 01 03 00 1B: apply defaults, vertical orientation with advertise sound disabled, common coin chute, Free Play.

The documented first eight bytes of each 16-byte record are:

| Record byte | Meaning |
|---:|---|
| +0 | 1 enables applying the following system defaults |
| +1 | Bit 0 = vertical display; bit 1 = disable advertise sound |
| +2 | Coin chute type: 0 common, 1 individual |
| +3 | BIOS coin/credit preset number: 1–28; 27 = Free Play, 28 = manual |
| +4 | Coin 1 rate |
| +5 | Coin 2 rate |
| +6 | Credit rate |
| +7 | Bonus setting |

The last four fields are the documented manual coin/credit/bonus controls; they are not yet exposed by this app. The user's requested editor restriction remains coin-assignment #1 and #27 only; do not expose the other preset choices in the normal UI.

The NaomiRom.defaults API is the supported high-level way to read/write these per-region records. Do not hard-code raw offsets into arbitrary ROMs. The library API also exposes separate ROM-header compatibility/metadata fields: regions, players (1–4), frequencies (15/31 Hz), orientations (horizontal/vertical), servicetype (individual/common service button), names (per-region title strings), sequencetexts (coin-insertion messages), publisher, date, serial, and executable sections. These are not all user settings: players, frequencies, orientations and regions are BIOS compatibility constraints, while names/sequence texts are metadata. No generic region-unlock feature is enabled or proposed.

The supported library API is safer than writing offsets: NaomiRom.defaults reads/writes per-region NaomiEEPROMDefaults objects. NaomiRom also exposes players (allowed player counts 1–4), frequencies (15/31), orientations (horizontal/vertical), servicetype (individual/common service button), regions, names, sequencetexts, serial and date. The app does not yet expose a header editor.

**Important exception:** DragonMinded reports that Crazy Taxi freezes at the SEGA logo if its Free Play / Silent Attract header flags are changed. Use the direct Crazy Taxi game-code patches above instead. The Crazy Taxi/Jambo Safari protection bypasses are prerequisites for EEPROM/header injection, not EEPROM injection themselves.

## EEPROM and SRAM mechanisms

The bundled naomiutils settings API identifies game definitions by the four-byte ROM serial, not filename. MVC2 uses BBG0; Monkey Ball uses BDF0. SettingsManager.from_rom(rom, region) creates region-correct defaults; to_eeprom() generates a valid 128-byte EEPROM. NaomiSettingsPatcher.put_eeprom() can attach that EEPROM to the in-memory ROM for netboot using a writing stub.

The current WiPi EEPROM editor still saves profiles to /data/naomi_settings_profiles.json only. It does not yet attach the generated EEPROM to the ROM sent to the cabinet. The new protection-bypass patches therefore do not apply a saved profile by themselves.

**Protection-patch usability note:** the Crazy Taxi and Jambo Safari noprotect entries only bypass the game's header-change detection. They do not attach an EEPROM, change a header default, or make a saved profile take effect. Since this app currently stores EEPROM profiles without injecting them into the outgoing ROM, selecting either protection patch alone has no settings benefit. Treat these as prerequisites for a future EEPROM/header-application path, not as standalone gameplay patches.

Ikaruga stores game settings in 32 KiB SRAM rather than EEPROM. NaomiSettingsPatcher.put_sram() is documented, but attaching SRAM can overwrite existing high scores. No SRAM integration is added here.

## Safety and validation

- Every new upstream patch file retains its upstream file-size comment and expected-byte hunks.
- BinaryDiff.can_patch() is mandatory before BinaryDiff.patch(); wrong size or any mismatching preimage causes a safe failure before the transfer buffer is modified.
- Catalogue BinaryDiff hunks must specify every expected byte explicitly; wildcard (*) preconditions are rejected. Tests inspect every bundled upstream patch file for complete before/after byte sequences.
- MVC2 unlock also requires ROM serial BBG0. The two CvS2 unlock files have no serial guard upstream; the app restricts them by distinct title/filename aliases and all 16 byte preimages.
- New patch selections are never enabled automatically.
- The SFZ3 Upper region-unlock patch is removed from the selectable catalogue and ROM-load path. A stale saved selection is filtered out so the game can still load without the patch. The separate SFZ3 Upper Free Play/Silent Attract definitions remain distinct.
- The existing Illvelo Force Free Play patch is unchanged.
- Automated tests cover BinaryDiff application/failure, file-size/preimage guards, serial checks, game-specific option matching, Illvelo regression and filtering of legacy SFZ3 region-unlock selections.
- No actual ROM set or physical cabinet has been tested by this change.

## Sources

Primary project and patch implementation:
- DragonMinded netboot repository: https://github.com/DragonMinded/netboot
- Upstream patch directory: https://github.com/DragonMinded/netboot/tree/trunk/patches
- Crazy Taxi patches: https://github.com/DragonMinded/netboot/tree/trunk/patches (CrazyTaxi_freeplay.binpatch, CrazyTaxi_no_attract.binpatch, CrazyTaxi_noprotect.binpatch)
- Jambo Safari patches: https://github.com/DragonMinded/netboot/tree/trunk/patches (Jambo_Safari_freeplay.binpatch, Jambo_Safari_no_attract.binpatch, Jambo_Safari_noprotect.binpatch)
- MVC2 character unlock: https://github.com/DragonMinded/netboot/blob/trunk/patches/MarvelVsCapcom2_unlocked.binpatch
- CvS2 MOTM character unlock: https://github.com/DragonMinded/netboot/blob/trunk/patches/Capcom_vs_SNK_2_Mark_Of_The_Millennium_2001_unlocked.binpatch
- CvS2 MF character unlock: https://github.com/DragonMinded/netboot/blob/trunk/patches/Capcom_vs_SNK_2_Millionaire_Fighting_2001_unlocked.binpatch
- CvS 2000 character unlock (deferred): https://github.com/DragonMinded/netboot/blob/trunk/patches/Capcom_vs_SNK_Millenium_Fight_2000_unlocked.binpatch
- GGX EEPROM auto-init (deferred): https://github.com/DragonMinded/netboot/blob/trunk/patches/GuiltyGearX_auto_init_eeprom.binpatch

Community and API documentation:
- DragonMinded's Universal Naomi Free-Play and No-Attract-Sound patch discussion: https://www.arcade-projects.com/threads/universal-naomi-free-play-and-no-attract-sound-patches.11202/
- DragonMinded's Naomi EEPROM presets / header protection discussion: https://www.arcade-projects.com/threads/netboot-naomi-with-eeprom-presets.18977/
- EEPROM settings library and ROM-header API: https://pypi.org/project/naomiutils/0.5.3/
- BinaryDiff patch format and expected-byte / file-size validation: https://pypi.org/project/arcadeutils/
