# WiPi Home Assistant

A Home Assistant app port of the WiPi Netbooter experience for x86-64 systems.

## Goal

Provide a browser-based Naomi netboot interface in Home Assistant, with:

- ROM discovery from the configured Home Assistant media folder
- Cabinet management for multiple NetDIMMs
- Game selection and loading through the established DragonMinded netboot tools
- Persistent configuration across app updates

The target is x86-64 Home Assistant. Raspberry Pi-specific hardware integrations are out of scope for the initial version unless later shown to be required.

## Development principles

1. Keep the existing `naomi-netboot-ha` app untouched.
2. Use WiPi as the functional reference; do not assume the Raspberry Pi image itself is portable.
3. Separate the web frontend, netboot/loader logic, and optional hardware services.
4. Discover ROMs from files actually present in the configured ROM directory. Treat catalogue metadata as optional enrichment, not as a requirement for a file to appear.
5. Preserve the upstream licensing and attribution of every reused component.
6. Build and validate an x86-64 container before asking the user to install anything.

## Initial investigation

Before implementing the runtime, document:

- Which WiPi frontend files and PHP extensions are required.
- How the frontend invokes the Python loader.
- Which DragonMinded tools and Python dependencies are required.
- Which services are Raspberry Pi-specific and can be omitted.
- How cabinet and ROM configuration are stored.

## Planned app layout

The intended Home Assistant app will live in its own app directory and include:

- `config.yaml` — Home Assistant app metadata and options
- `Dockerfile` — x86-64 runtime image
- `run.sh` — startup and persistent configuration setup
- `rootfs/` — app-owned frontend, loader integration and service configuration

This repository starts clean; no files or runtime code are copied from the previous `naomi-netboot-ha` project by default.
