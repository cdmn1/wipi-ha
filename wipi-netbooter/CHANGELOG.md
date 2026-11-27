# Changelog

## 0.4.11

- Fixed a Classic interface startup regression: EEPROM event handlers are now attached only after the game-detail editor elements are created, allowing the game list to initialize normally.

## 0.4.10

- Added EEPROM settings access to the Classic interface for Naomi games, matching the Modern interface. The editor uses ROM-declared regions and the simplified settings filter; saved profiles do not modify ROMs or apply settings to the cabinet.

Notable changes to WiPi Netbooter are documented here. Newest releases appear first.

## 0.4.9

- Simplified the NAOMI EEPROM settings editor by hiding low-level coin/credit configuration fields (coins per credit, multipliers, bonus coins and sequence options). Kept the simple Coin/Credit Assignment selector, limited to 1:1 and Free Play.

## 0.4.8

- Added game sorting to both Modern and Classic interfaces: alphabetical by title (default), or by ROM file modification date with newest files first. The date is read from each actual .bin/.bin.gz file, not the catalogue's game-release year.

## 0.4.7

- Increased the automatic NetDIMM launch countdown after powering on a cabinet from 30 to 35 seconds in both the Modern and Classic interfaces.


## 0.4.5

- Added a pre-launch cabinet power check. If a configured cabinet outlet is OFF, both interfaces offer to power it on before loading a game.
- When accepted, the add-on sends the existing Home Assistant switch power-on command, waits for the outlet to report ON, and only then starts the NetDIMM upload. If power-on fails or the outlet does not come on within 60 seconds, the game is not loaded.
- Cabinets without a configured power entity retain the existing launch workflow.

**Testing note:** CI validates the add-on build and automated checks; verify the power-on prompt and outlet timing with the actual cabinet and smart outlet after updating.

## 0.4.4

- Expanded the Naomi patch catalogue with guarded Free Play, Silent Attract, and character-unlock patches for supported titles, including Crazy Taxi, Jambo Safari, Capcom vs. SNK, Capcom vs. SNK 2, and Marvel vs. Capcom 2.
- Added header-protection bypasses for supported Crazy Taxi and Jambo Safari workflows.
- Hardened binary patching: patches now validate ROM size, game identity, and expected original bytes before writing. A mismatch is rejected rather than patched blindly.
- Removed the legacy Street Fighter Zero 3 Upper region-unlock options.
- Improved compatibility with the current arcade utility dependencies and EEPROM editor handling.
- Clarified Naomi header settings and compatibility fields.

**Testing note:** CI checks pass for this release. Not every newly catalogued game patch has been verified on a physical cabinet; use new patches cautiously and retain an unmodified ROM backup.

