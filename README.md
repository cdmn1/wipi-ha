# WiPi Home Assistant

A Home Assistant app port of the WiPi Netbooter experience for x86-64 systems.

## Current development status

The `wipi-x86-port` branch now contains the first Home Assistant app scaffold:

- x86-64 (`amd64`) container definition.
- Home Assistant Configuration-tab option named `rom_path`, defaulting to `/media/NAOMI`.
- Read-only access to Home Assistant's `/media` and `/share` mounts.
- Runtime validation that the selected path is inside one of those mounted locations and is readable.
- A small initial web page and status endpoint that report the selected folder and discover candidate `.bin` / `.dat` files.

This is an early development build, not yet a usable netboot application. Cabinet configuration, catalogue/artwork integration, NetDIMM communication, game loading, and automated image builds still need to be implemented and tested.

## ROM folder configuration

The ROM directory is configured in Home Assistant, not hard-coded into the app:

1. Open **Settings → Apps → WiPi Netbooter → Configuration**.
2. Set **ROM folder path** (for example, `/media/NAOMI`).
3. Save the configuration and restart the app if Home Assistant requests it.

The folder must be under `/media` or `/share`, because those are the locations explicitly made available to the app. The app mounts them read-only so it cannot modify the user's ROM collection.

## Project goals

- Browser-based game browser, cabinet selection and loading workflow.
- Multiple configurable NetDIMMs, without invented or hard-coded network addresses.
- ROM discovery from the configured Home Assistant mount.
- WiPi catalogue and artwork compatibility where licensing and file formats permit.
- Persistent settings across app updates.
- x86-64 support without Raspberry Pi GPIO or other Pi-only hardware dependencies.

## Upstream compatibility and licensing

WiPi is the functional reference, but the public GitHub metadata for both the WiPiNetbooter64 fork and the original WiPiNetbooter repository currently reports no declared repository licence. For that reason, this project does not copy their frontend or loader source wholesale. The portable NetDIMM components and their individual dependencies will be checked before any reuse; otherwise, equivalent behavior will be implemented independently with appropriate attribution.

The app will not bundle game ROMs. Users provide their own ROM files and any compatible catalogue/artwork fileset.

## Safety of the existing installation

Development takes place on the separate `wipi-x86-port` branch and in the separate `wipi-ha` repository. The existing `naomi-netboot-ha` app is not modified.
