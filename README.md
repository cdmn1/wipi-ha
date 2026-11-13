# WiPi Home Assistant

An x86-64 Home Assistant app for a WiPi-style Sega Naomi/NetDIMM game browser and loader.

## Project repository

Home Assistant app repository URL:

https://github.com/cdmn1/wipi-ha

The app is developed on the separate wipi-x86-port branch. The default main branch is intentionally not changed while the replacement is being built and tested.

## Configuration tab

- **ROM folder path** (rom_path): defaults to /media/NAOMI. It must be under /media or /share, which Home Assistant maps into the app read-only.
- **NetDIMM cabinets** (cabinets): add a cabinet entry and fill in its name, IP address, platform, and firmware using the separate fields. Supported platforms: naomi, chihiro, triforce. Supported firmware choices are provided in the Configuration tab.
- **Disable CRC check** (disable_crc): optional faster boot behavior; disabled by default.

## ROM fileset layout

The ROM path can point directly to the folder containing ROM files, or to a WiPi fileset root with a roms/ subfolder.

The browser discovers .bin, .bin.gz, and .dat files. A WiPi-compatible romsinfo.csv can be placed in the selected folder, its csv/ subfolder, or the parent fileset's csv/ folder. Artwork is read from images/, artwork/, or img/ in the selected folder or its parent. Metadata and artwork are optional; files still appear by filename if no catalogue is present.

The catalogue and artwork are not bundled. Users provide their own compatible fileset.

## NetDIMM transfer

The app uses DragonMinded's public-domain netdimmutils Python package. Compressed .gz ROMs are decompressed before sending. Cabinet IP addresses and ROM filenames are validated before a transfer begins.

## Current development status

Implemented:
- Home Assistant app repository structure and amd64 container.
- Editable ROM folder path in the Configuration tab.
- Multiple cabinet entries in Configuration.
- WiPi-compatible CSV catalogue matching and optional artwork discovery.
- Search and system, genre, orientation and controls filters in the browser.
- WiPi-compatible enabled/disabled and favourite catalogue handling.
- Classic WiPi-style browser at `/classic`, sharing the same game and NetDIMM APIs as Modern.
- Classic catalogue editor can register ROMs already in the shared ROM folder, edit metadata, enable/disable games and mark favourites. It updates the existing `romsinfo.csv` without changing its header or column order.
- Optional favourite-only and show-disabled views.
- Cabinet selection, NetDIMM connection test, and send/reboot workflow.
- CI build, Python syntax, package API, web UI and catalogue smoke tests.

The Classic route is an initial browser port, not yet a complete replacement for every original WiPi PHP setup page. Raspberry Pi-only actions remain intentionally unavailable. The app now needs write access to its configured `/media` or `/share` folder to save catalogue changes; ROM and asset files remain in their existing shared folders.

Not yet validated against a physical cabinet:
- A complete real NetDIMM upload and boot.
- Performance and compatibility across different NetDIMM firmware versions.

WiPi-specific advanced settings, per-game patches, card emulation, OpenJVS, OpenFFB, and Raspberry Pi hardware integrations are not included in this first x86 port.

The existing naomi-netboot-ha repository and app remain untouched.
