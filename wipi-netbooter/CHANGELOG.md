# Changelog

Notable changes to WiPi Netbooter are documented here. Newest releases appear first.

## 0.4.4

- Expanded the Naomi patch catalogue with guarded Free Play, Silent Attract, and character-unlock patches for supported titles, including Crazy Taxi, Jambo Safari, Capcom vs. SNK, Capcom vs. SNK 2, and Marvel vs. Capcom 2.
- Added header-protection bypasses for supported Crazy Taxi and Jambo Safari workflows.
- Hardened binary patching: patches now validate ROM size, game identity, and expected original bytes before writing. A mismatch is rejected rather than patched blindly.
- Removed the legacy Street Fighter Zero 3 Upper region-unlock options.
- Improved compatibility with the current arcade utility dependencies and EEPROM editor handling.
- Clarified Naomi header settings and compatibility fields.

**Testing note:** CI checks pass for this release. Not every newly catalogued game patch has been verified on a physical cabinet; use new patches cautiously and retain an unmodified ROM backup.

