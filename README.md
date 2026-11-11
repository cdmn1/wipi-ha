# WiPi Home Assistant

An x86-64 Home Assistant app for a WiPi-style Sega Naomi/NetDIMM game browser and loader.

## Install structure

This repository is a Home Assistant app repository. Add this repository URL in Home Assistant's app-store repository manager:

https://github.com/cdmn1/wipi-ha

Development is currently on the wipi-x86-port branch; it is not ready for installation from the default branch yet.

## Configuration

The app exposes its settings in the Home Assistant Configuration tab:

- ROM folder path (rom_path): defaults to /media/NAOMI. Must be under /media or /share.
- Cabinets (cabinets): add one entry per NetDIMM using Name|IP address|platform|firmware, for example Main cabinet|192.168.1.50|naomi|4.01. Replace the example address with the actual NetDIMM address. Supported platforms: naomi, chihiro, triforce.
- Disable CRC check (disable_crc): optional faster boot behavior; disabled by default.

The app mounts /media and /share read-only and validates the selected ROM folder.

## ROM catalogue and artwork

The game browser discovers files in the selected ROM folder. It can enrich entries from a WiPi-compatible romsinfo.csv placed either directly in the folder or in its csv/ subfolder. Artwork is read from images/, artwork/, or img/ beneath the selected folder. The catalogue and artwork are not bundled; users provide their own fileset. Games remain visible by filename even if the catalogue is absent.

Supported ROM file extensions are .bin, .bin.gz, and .dat.

## NetDIMM transfer

The app uses DragonMinded's public-domain netdimmutils Python package for transfer. Compressed .gz files are decompressed in the app before sending. The app validates cabinet IP addresses and ROM filenames before starting a transfer.

## Current status

This is an early development build. The game browser, optional catalogue matching, cabinet selection, and NetDIMM send/reboot path are implemented, but must be validated against a real NetDIMM before being considered ready for everyday use. WiPi-specific advanced settings, per-game patches, card emulation, OpenJVS, OpenFFB, and other Raspberry Pi hardware integrations are not included yet.

The existing naomi-netboot-ha repository and app are not modified by this project.
