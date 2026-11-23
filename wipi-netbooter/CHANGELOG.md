# Changelog

Notable changes to WiPi Netbooter are documented here. Newest releases appear first.

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

