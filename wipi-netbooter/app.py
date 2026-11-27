"""WiPi-style Home Assistant NetDIMM application."""
from __future__ import annotations

import csv
import gzip
import ipaddress
import json
import logging
import socket
import struct
import os
import threading
import uuid
import urllib.error
import urllib.request

try:
    from naomi import NaomiRom, NaomiRomRegionEnum
except ImportError:
    NaomiRom = NaomiRomRegionEnum = None

try:
    from naomi.settings import NaomiSettingsManager, get_default_settings_directory
except ImportError:
    NaomiSettingsManager = get_default_settings_directory = None
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template_string, request, send_from_directory

try:
    from netdimm import NetDimm, NetDimmTargetEnum, NetDimmVersionEnum
except ImportError:
    NetDimm = NetDimmTargetEnum = NetDimmVersionEnum = None

try:
    from arcadeutils.binary import BinaryDiff
except ImportError:
    BinaryDiff = None

OPTIONS_FILE = Path("/data/options.json")
DEFAULT_ROM_PATH = "/media/NAOMI"
ALLOWED_ROOTS = (Path("/media"), Path("/share"))
ROM_SUFFIXES = (".bin", ".bin.gz", ".dat")
LOG = logging.getLogger("wipi-ha")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__)
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
TIME_HACK_LOCK = threading.Lock()
TIME_HACK_EVENTS: dict[str, threading.Event] = {}
TIME_HACK_THREADS: dict[str, threading.Thread] = {}
CABINET_LOAD_LOCKS: dict[str, threading.Lock] = {}
CABINET_LOAD_LOCKS_LOCK = threading.Lock()
TIME_HACK_INTERVAL = 5
TIME_HACK_LIMIT_MS = 10 * 60 * 1000
CATALOGUE_LOCK = threading.Lock()
PATCH_SETTINGS_FILE = Path("/data/patch_settings.json")
PATCHES_DIR = Path(__file__).with_name("patches")
PATCH_SETTINGS_LOCK = threading.Lock()
PATCH_DEFINITIONS: dict[str, dict[str, Any]] = {}

# Documented byte patches from DragonMinded's Naomi netboot patch research.
# Every patch verifies the original bytes before modifying the upload buffer.
_DOCUMENTED_GAME_PATCHES = [
    # key, display name, catalogue aliases, filename aliases, free-play offset, silent-attract offset
    ("guilty_gear_x", "Guilty Gear X", ("guilty gear x",), ("ggx",), 0x72A28, 0x72ABC),
    ("ikaruga", "Ikaruga", ("ikaruga",), ("ikaruga",), 0x52626, None),
    ("illvelo", "Illvelo", ("illvelo", "illmatic envelope"), ("illmatic_envelope",), 0x620C6, 0x6214E),
    ("karous", "Karous", ("karous",), ("karous",), 0x6135A, 0x613E0),
    ("marvel_vs_capcom_2", "Marvel vs. Capcom 2", ("marvel vs. capcom 2", "marvel vs capcom 2"), ("mvsc2", "mvsc-2"), 0x1D8138, 0x1D81CC),
    ("monkey_ball", "Monkey Ball", ("monkey ball",), ("monkeyba", "monkey_ball"), 0x6BE30, 0x6BEC4),
    ("power_stone_2", "Power Stone 2", ("power stone 2", "powerstone 2"), ("pstone2", "powerstone2"), 0x158F88, 0x15901C),
    ("puyo_puyo_da", "Puyo Puyo Da!", ("puyo puyo da", "puyopuyo da"), ("puyopuyoda",), 0x44F86, 0x4500C),
    ("puyo_puyo_fever", "Puyo Puyo Fever", ("puyo puyo fever", "puyopuyo fever"), ("puyofever",), 0x37EAE, 0x37F36),
    ("quiz_k_qmode", "Quiz K QMode", ("quiz k qmode", "quiz k q-mode"), ("quizkqmode",), 0x29A58, 0x29AEC),
    ("radirgy", "Radirgy", ("radirgy",), ("radirgy",), 0x6136E, 0x613F4),
    ("street_fighter_zero_3_upper", "Street Fighter Zero 3 Upper", ("street fighter zero 3 upper",), ("sfz3upper", "zero3upper"), 0xE8832, 0xE88B8),
    ("tetris_kiwamemichi", "Tetris Kiwamemichi", ("tetris kiwamemichi", "tetris kiwamemiti"), ("tetris_kiwamemichi", "tetris_kiwamemiti"), 0x7FAB2, 0x7FB38),
    ("trigger_heart_exelica", "Trigger Heart Exelica", ("trigger heart exelica",), ("triggere", "exelica"), 0x13E522, 0x13E5AA),
    ("trizeal", "Trizeal", ("trizeal",), ("trizeal",), 0xBE782, 0xBE808),
    ("under_defeat", "Under Defeat", ("under defeat",), ("underdefeat", "under_defeat"), 0x43FD6, 0x4405C),
    ("capcom_vs_snk", "Capcom vs. SNK: Millennium Fight 2000", ("capcom vs snk: millennium fight 2000", "capcom vs snk millennium fight 2000"), ("capcom_vs_snk_millenium_fight_2000",), 0xFF358, 0xFF3EC),
    ("capcom_vs_snk_2_motm", "Capcom vs. SNK 2: Mark of the Millennium 2001", ("capcom vs snk 2: mark of the millennium 2001", "capcom vs. snk 2: mark of the millennium 2001"), ("cvs2motm", "capcom_vs_snk_2_mark_of_the_millennium_2001"), 0x116E58, 0x116EEC),
    ("capcom_vs_snk_2_mf", "Capcom vs. SNK 2: Millionaire Fighting 2001", ("capcom vs snk 2: millionaire fighting 2001", "capcom vs. snk 2: millionaire fighting 2001"), ("cvs2mf", "capcom_vs_snk_2_millionaire_fighting_2001"), 0x1161F8, 0x11628C),
]

_DOCUMENTED_GAME_PATCH_SIZES = {
    "capcom_vs_snk": 125829120,
    "capcom_vs_snk_2_motm": 159383552,
    "capcom_vs_snk_2_mf": 159383552,
}

for _key, _title, _names, _files, _freeplay, _silent in _DOCUMENTED_GAME_PATCHES:
    for _suffix, _label, _offset, _expected, _replacement in (
        ("force_freeplay", "Force Free Play", _freeplay, "42 84", "1A E0"),
        ("silent_attract", "Silent Attract", _silent, "40 63", "00 E3"),
    ):
        if _offset is None:
            continue
        _definition = {
            "title": f"{_label} — {_title} (community patch)",
            "description": f"Applies the documented {_label.lower()} byte patch for {_title}. The original ROM file is never modified.",
            "filename_contains": set(_files),
            "catalogue_name_contains": set(_names),
            "offset": _offset,
            "expected": _expected,
            "replacement": _replacement,
            "target": "naomi",
        }
        if _key in _DOCUMENTED_GAME_PATCH_SIZES:
            _definition["file_size"] = _DOCUMENTED_GAME_PATCH_SIZES[_key]
        PATCH_DEFINITIONS[f"{_key}_{_suffix}"] = _definition

for _suffix in ("force_freeplay", "silent_attract"):
    PATCH_DEFINITIONS[f"capcom_vs_snk_{_suffix}"]["filename_stems"] = {"capsnk"}

PATCH_DEFINITIONS.update({
    "crazy_taxi_force_freeplay": {
        "title": "Force Free Play — Crazy Taxi (upstream patch)",
        "description": "Direct game-code patch. Requires the exact 128 MiB image, header ID BAC0 at 0x134, and all expected bytes.",
        "patch_file": "CrazyTaxi_freeplay.binpatch",
        "filename_contains": {"crazytaxi", "crazy_taxi"},
        "catalogue_name_contains": {"crazy taxi"},
        "target": "naomi",
    },
    "crazy_taxi_silent_attract": {
        "title": "Silent Attract — Crazy Taxi (upstream patch)",
        "description": "Direct game-code patch. Requires the exact 128 MiB image, header ID BAC0 at 0x134, and all expected bytes.",
        "patch_file": "CrazyTaxi_no_attract.binpatch",
        "filename_contains": {"crazytaxi", "crazy_taxi"},
        "catalogue_name_contains": {"crazy taxi"},
        "target": "naomi",
    },
    "crazy_taxi_noprotect": {
        "title": "Header protection bypass — Crazy Taxi (upstream patch)",
        "description": "Prerequisite for modifying header/EEPROM settings. Requires the exact 128 MiB image, header ID BAC0 at 0x134, and all expected bytes. Does not attach an EEPROM profile by itself.",
        "patch_file": "CrazyTaxi_noprotect.binpatch",
        "filename_contains": {"crazytaxi", "crazy_taxi"},
        "catalogue_name_contains": {"crazy taxi"},
        "target": "naomi",
    },
    "jambo_safari_force_freeplay": {
        "title": "Force Free Play — Jambo Safari (upstream patch)",
        "description": "Direct game-code patch. Requires the exact 72 MiB image, header ID BAU0 at 0x134, and all expected bytes.",
        "patch_file": "Jambo_Safari_freeplay.binpatch",
        "filename_contains": {"jambosafari", "jambo_safari"},
        "catalogue_name_contains": {"jambo safari"},
        "target": "naomi",
    },
    "jambo_safari_silent_attract": {
        "title": "Silent Attract — Jambo Safari (upstream patch)",
        "description": "Direct game-code patch. Requires the exact 72 MiB image, header ID BAU0 at 0x134, and all expected bytes.",
        "patch_file": "Jambo_Safari_no_attract.binpatch",
        "filename_contains": {"jambosafari", "jambo_safari"},
        "catalogue_name_contains": {"jambo safari"},
        "target": "naomi",
    },
    "jambo_safari_noprotect": {
        "title": "Header protection bypass — Jambo Safari (upstream patch)",
        "description": "Prerequisite for modifying header/EEPROM settings. Requires the exact 72 MiB image, header ID BAU0 at 0x134, and all expected bytes. Does not attach an EEPROM profile by itself.",
        "patch_file": "Jambo_Safari_noprotect.binpatch",
        "filename_contains": {"jambosafari", "jambo_safari"},
        "catalogue_name_contains": {"jambo safari"},
        "target": "naomi",
    },
    "marvel_vs_capcom_2_unlocked": {
        "title": "All characters unlocked — Marvel vs. Capcom 2 (upstream patch)",
        "description": "Applies the upstream character-unlock patch. Requires ROM serial BBG0, the exact 143242752-byte image, and all expected bytes.",
        "patch_file": "MarvelVsCapcom2_unlocked.binpatch",
        "required_serial": "BBG0",
        "filename_contains": {"mvsc2", "mvsc-2", "marvelvscapcom2"},
        "catalogue_name_contains": {"marvel vs. capcom 2", "marvel vs capcom 2"},
        "target": "naomi",
    },
    "capcom_vs_snk_2_motm_unlocked": {
        "title": "All characters unlocked — CvS2 Mark of the Millennium 2001 (upstream patch)",
        "description": "Applies the upstream character-unlock patch. Requires the exact 159383552-byte image and all 16 expected-byte checks; the upstream patch has no ROM-serial guard, so use only on this exact game variant.",
        "patch_file": "Capcom_vs_SNK_2_Mark_Of_The_Millennium_2001_unlocked.binpatch",
        "filename_contains": {"cvs2motm", "capcom_vs_snk_2_mark_of_the_millennium_2001"},
        "catalogue_name_contains": {"capcom vs snk 2: mark of the millennium 2001", "capcom vs. snk 2: mark of the millennium 2001"},
        "target": "naomi",
    },
    "capcom_vs_snk_2_mf_unlocked": {
        "title": "All characters unlocked — CvS2 Millionaire Fighting 2001 (upstream patch)",
        "description": "Applies the upstream character-unlock patch. Requires the exact 159383552-byte image and all 16 expected-byte checks; the upstream patch has no ROM-serial guard, so use only on this exact game variant.",
        "patch_file": "Capcom_vs_SNK_2_Millionaire_Fighting_2001_unlocked.binpatch",
        "filename_contains": {"cvs2mf", "capcom_vs_snk_2_millionaire_fighting_2001"},
        "catalogue_name_contains": {"capcom vs snk 2: millionaire fighting 2001", "capcom vs. snk 2: millionaire fighting 2001"},
        "target": "naomi",
    },
})

CATALOGUE_COLUMNS = [
    "system", "romname", "image", "video", "description", "lcd_description",
    "manufacturer", "year", "genre", "rating", "orientation", "controls",
    "enabled", "favourite", "openjvs", "openffb", "game_id", "audit_name", "region",
]


def options() -> dict[str, Any]:
    try:
        return json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def rom_folder() -> Path:
    raw = str(options().get("rom_path", DEFAULT_ROM_PATH)).strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise ValueError("ROM folder path must be absolute.")
    resolved = candidate.resolve()
    if not any(resolved == root or root in resolved.parents for root in ALLOWED_ROOTS):
        raise ValueError("ROM folder must be inside Home Assistant's /media or /share mount.")
    return resolved


def cabinets() -> list[dict[str, str]]:
    result = []
    for index, entry in enumerate(options().get("cabinets", [])):
        # Current config uses structured fields; accept the early pipe-delimited
        # development format as a harmless migration fallback.
        if isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            address = str(entry.get("ip", "")).strip()
            target = str(entry.get("target", "naomi")).strip().lower()
            firmware = str(entry.get("firmware", "4.01")).strip()
            power_entity = str(entry.get("power_entity", "")).strip()
        else:
            fields = [part.strip() for part in str(entry).split("|")]
            if len(fields) < 2:
                continue
            name, address = fields[0], fields[1]
            target = fields[2].lower() if len(fields) > 2 and fields[2] else "naomi"
            firmware = fields[3] if len(fields) > 3 and fields[3] else "4.01"
            power_entity = ""
        if not name or not address:
            continue
        try:
            ipaddress.ip_address(address)
        except ValueError:
            continue
        if target not in {"naomi", "chihiro", "triforce"}:
            continue
        result.append({"id": str(index), "name": name, "ip": address,
                       "target": target, "firmware": firmware,
                       "power_entity": power_entity if power_entity.startswith("switch.") else ""})
    return result


def rom_directories(folder: Path) -> list[Path]:
    """Support either a ROM folder itself or a WiPi fileset root containing roms/."""
    candidates = [folder, folder / "roms"]
    return [candidate for candidate in candidates if candidate.is_dir()]


def catalogue_path(folder: Path) -> Path | None:
    candidates = (
        folder / "romsinfo.csv",
        folder / "csv" / "romsinfo.csv",
        folder.parent / "romsinfo.csv",
        folder.parent / "csv" / "romsinfo.csv",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def discover_systems(folder: Path) -> list[str]:
    """Return every distinct non-empty system label present in the ROM CSV."""
    csv_path = catalogue_path(folder)
    if not csv_path:
        return []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            systems = {
                (row.get("system") or "").strip()
                for row in csv.DictReader(stream)
            }
        return sorted((value for value in systems if value), key=str.casefold)
    except (OSError, csv.Error, UnicodeError) as exc:
        LOG.warning("Could not read systems from ROM catalogue %s: %s", csv_path, exc)
        return []


def discover_games() -> tuple[list[dict[str, Any]], str | None]:
    folder = rom_folder()
    if not folder.is_dir() or not os.access(folder, os.R_OK):
        return [], f"ROM folder is missing or unreadable: {folder}"

    metadata: dict[str, dict[str, str]] = {}
    csv_path = catalogue_path(folder)
    if csv_path:
        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    filename = (row.get("romname") or "").strip()
                    if filename:
                        metadata[filename] = row
        except (OSError, csv.Error, UnicodeError) as exc:
            LOG.warning("Could not read ROM catalogue %s: %s", csv_path, exc)

    games = []
    try:
        for directory in rom_directories(folder):
            for path in directory.iterdir():
                if not path.is_file() or not any(path.name.lower().endswith(s) for s in ROM_SUFFIXES):
                    continue
                row = metadata.get(path.name, {})
                games.append({
                    "filename": path.name,
                    "file_mtime": path.stat().st_mtime,
                    "name": row.get("description") or row.get("romname") or path.name,
                    "description": row.get("description", ""),
                    "lcd_description": row.get("lcd_description", ""),
                    "system": row.get("system", "Unknown system"),
                    "manufacturer": row.get("manufacturer", ""),
                    "year": row.get("year", ""),
                    "genre": row.get("genre", ""),
                    "orientation": row.get("orientation", ""),
                    "controls": row.get("controls", ""),
                    "rating": row.get("rating", ""),
                    "lcd_description": row.get("lcd_description", ""),
                    "enabled": (row.get("enabled", "Yes") or "Yes").strip().lower() == "yes",
                    "favourite": (row.get("favourite", "") or "").strip().lower() == "yes",
                    "image": row.get("image", ""),
                    "video": row.get("video", ""),
                    "catalogued": bool(row),
                    "game_id": (row.get("game_id") or "").strip(),
                    "region": (row.get("region") or "").strip().upper(),
                })
    except OSError as exc:
        return [], f"Cannot read ROM folder: {exc}"
    games.sort(key=lambda game: game["name"].casefold())
    return games, None


def safe_rom(filename: str) -> Path:
    folder = rom_folder()
    if Path(filename).name != filename:
        raise ValueError("Invalid ROM filename.")
    for directory in rom_directories(folder):
        path = directory / filename
        if path.is_file() and any(path.name.lower().endswith(s) for s in ROM_SUFFIXES):
            return path
    raise FileNotFoundError("ROM file is not available.")


def load_patch_settings() -> dict[str, list[str]]:
    try:
        raw = json.loads(PATCH_SETTINGS_FILE.read_text(encoding="utf-8"))
        settings: dict[str, list[str]] = {}
        for key, value in raw.items():
            if not isinstance(value, list):
                continue
            # Retire the known-bad SFZ3 Upper region unlock from legacy profiles.
            selected = [str(item) for item in value
                        if isinstance(item, str) and item != "naomi_region_unlock"]
            if selected:
                settings[str(key)] = selected
        return settings
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def save_patch_settings(settings: dict[str, list[str]]) -> None:
    PATCH_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = PATCH_SETTINGS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(PATCH_SETTINGS_FILE)


def game_patch_options(game: dict[str, Any]) -> list[dict[str, Any]]:
    selected = set(load_patch_settings().get(game["filename"], []))
    result = []
    for patch_id, definition in PATCH_DEFINITIONS.items():
        game_id_match = game.get("game_id") in definition.get("game_ids", set())
        filename = Path(game.get("filename", "")).name.casefold()
        name = " ".join(str(game.get(field, "")) for field in
                        ("name", "description", "audit_name")).casefold()
        filename_match = any(token in filename for token in
                             definition.get("filename_contains", set()))
        catalogue_match = any(token in name for token in
                              definition.get("catalogue_name_contains", set()))
        stem_match = any(filename == stem or filename.startswith(stem + ".")
                         for stem in definition.get("filename_stems", set()))
        if game_id_match or stem_match or filename_match or catalogue_match:
            result.append({"id": patch_id, "title": definition["title"],
                           "description": definition["description"], "enabled": patch_id in selected})
    return result

def apply_documented_byte_patch(data: bytes, patch_id: str) -> bytes:
    """Apply a documented game patch only when its original bytes match."""
    definition = PATCH_DEFINITIONS.get(patch_id)
    if not definition or "offset" not in definition:
        raise ValueError(f"Unknown documented game patch: {patch_id}")
    offset = int(definition["offset"])
    original = bytes.fromhex(str(definition["expected"]))
    replacement = bytes.fromhex(str(definition["replacement"]))
    title = str(definition["title"])
    required_size = definition.get("file_size")
    if required_size is not None and len(data) != int(required_size):
        raise ValueError(
            f"{title}: ROM size is {len(data)} bytes; expected exactly "
            f"{int(required_size)} bytes for this documented image."
        )
    if len(data) < offset + len(original):
        raise ValueError(f"{title}: ROM is too small for the documented patch.")
    actual = data[offset:offset + len(original)]
    if actual != original:
        raise ValueError(
            f"{title} was not applied: ROM bytes at 0x{offset:X} "
            f"are {actual.hex(' ').upper()}, expected {original.hex(' ').upper()}. "
            "This ROM revision may not match the documented patch."
        )
    return data[:offset] + replacement + data[offset + len(replacement):]


def apply_illvelo_force_freeplay(data: bytes) -> bytes:
    """Backward-compatible wrapper for the original Illvelo patch test."""
    return apply_documented_byte_patch(data, "illvelo_force_freeplay")

def binary_patch_preconditions_match(data: bytes, patch_lines: list[str]) -> bool:
    """Check the declared image size and every upstream BinaryDiff preimage byte."""
    required_size = BinaryDiff.size(patch_lines)
    if required_size is not None and len(data) != required_size:
        return False
    for line_number, line in enumerate(patch_lines, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            offset_text, changes = line.split(":", 1)
            before_text, after_text = changes.split("->", 1)
            before = before_text.strip().split()
            after = after_text.strip().split()
            offset = int(offset_text.strip(), 16)
        except ValueError as exc:
            raise ValueError(f"Malformed BinaryDiff line {line_number}: {line}") from exc
        if len(before) != len(after):
            raise ValueError(f"BinaryDiff line {line_number} has different before/after lengths.")
        if offset < 0 or offset + len(before) > len(data):
            return False
        for index, token in enumerate(before):
            if token == "*":
                raise ValueError(
                    f"Wildcard precondition on BinaryDiff line {line_number} is not allowed; "
                    "every catalogue patch byte must be explicitly verified."
                )
            try:
                expected = int(token, 16)
            except ValueError as exc:
                raise ValueError(f"Invalid expected byte on BinaryDiff line {line_number}: {token}") from exc
            if not 0 <= expected <= 0xFF:
                raise ValueError(f"Invalid expected byte on BinaryDiff line {line_number}: {token}")
            if data[offset + index] != expected:
                return False
    return True


def apply_binary_patch(data: bytes, patch_id: str) -> bytes:
    """Apply an upstream BinaryDiff patch only after validating every preimage byte."""
    definition = PATCH_DEFINITIONS.get(patch_id)
    if not definition or not definition.get("patch_file"):
        raise ValueError(f"Unknown upstream binary patch: {patch_id}")
    if BinaryDiff is None:
        raise RuntimeError("arcadeutils BinaryDiff is unavailable; refusing to apply the patch.")
    patch_file = str(definition["patch_file"])
    if Path(patch_file).name != patch_file:
        raise ValueError("Invalid patch file path.")
    patch_path = PATCHES_DIR / patch_file
    try:
        patch_lines = patch_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"Could not read upstream patch file {patch_file}: {exc}") from exc

    required_serial = definition.get("required_serial")
    if required_serial:
        if NaomiRom is None:
            raise RuntimeError("Naomi ROM tools are unavailable; refusing a serial-specific patch.")
        rom = NaomiRom(data)
        if not rom.valid:
            raise ValueError(f"{definition['title']}: input is not a valid Naomi ROM.")
        if rom.serial != str(required_serial).encode("ascii"):
            actual = rom.serial.decode("ascii", errors="replace")
            raise ValueError(
                f"{definition['title']} requires Naomi ROM serial {required_serial}; "
                f"this image reports {actual!r}."
            )

    try:
        applicable = BinaryDiff.can_patch(data, patch_lines)
    except Exception as exc:
        raise ValueError(f"{definition['title']}: could not validate patch size/format: {exc}") from exc
    if not applicable or not binary_patch_preconditions_match(data, patch_lines):
        raise ValueError(
            f"{definition['title']} was not applied: ROM size or one or more expected "
            "byte sequences do not match the upstream patch preconditions."
        )
    try:
        return BinaryDiff.patch(data, patch_lines)
    except Exception as exc:
        raise ValueError(f"{definition['title']} could not be applied safely: {exc}") from exc


def apply_game_patches(data: bytes, filename: str, cabinet: dict[str, str]) -> tuple[bytes, list[str]]:
    selected = set(load_patch_settings().get(filename, []))
    if not selected:
        return data, []
    game = next((item for item in discover_games()[0] if item["filename"] == filename), None)
    if not game:
        raise ValueError("Game is no longer present in the ROM catalogue.")
    allowed = {patch["id"] for patch in game_patch_options(game)}
    unknown = selected - allowed
    if unknown:
        raise ValueError("Unsupported patch selection: " + ", ".join(sorted(unknown)))
    for patch_id in sorted(selected):
        definition = PATCH_DEFINITIONS[patch_id]
        if cabinet["target"] != definition.get("target", "naomi"):
            raise ValueError(f"The {definition['title']} patch is only supported on NAOMI cabinets.")
        if definition.get("patch_file"):
            data = apply_binary_patch(data, patch_id)
        elif definition.get("offset") is not None:
            data = apply_documented_byte_patch(data, patch_id)
        else:
            raise ValueError(f"Patch {patch_id} has no supported patch mechanism.")
    return data, sorted(selected)


def enum_value(enum_type: Any, value: str) -> Any:
    if enum_type is None:
        raise RuntimeError("NetDIMM transfer library is unavailable in this build.")
    for member in enum_type:
        if str(member.value).lower() == value.lower():
            return member
    raise ValueError(f"Unsupported NetDIMM setting: {value}")


def cabinet_load_lock(cabinet_id: str) -> threading.Lock:
    with CABINET_LOAD_LOCKS_LOCK:
        return CABINET_LOAD_LOCKS.setdefault(cabinet_id, threading.Lock())


def stop_time_hack(cabinet: dict[str, str]) -> None:
    """Stop the keepalive and wait until its NetDIMM TCP socket is closed."""
    cabinet_id = cabinet["id"]
    with TIME_HACK_LOCK:
        stop_event = TIME_HACK_EVENTS.get(cabinet_id)
        thread = TIME_HACK_THREADS.get(cabinet_id)
        if stop_event:
            stop_event.set()
    if thread and thread.is_alive():
        thread.join(timeout=7)
        if thread.is_alive():
            raise RuntimeError(f"Time Hack connection for {cabinet['name']} did not close; refusing to start another NetDIMM session.")
    with TIME_HACK_LOCK:
        if TIME_HACK_EVENTS.get(cabinet_id) is stop_event:
            TIME_HACK_EVENTS.pop(cabinet_id, None)
            TIME_HACK_THREADS.pop(cabinet_id, None)
    if thread:
        LOG.info("Time Hack stopped and connection closed for %s", cabinet["name"])


def start_time_hack(cabinet: dict[str, str]) -> None:
    """Keep the original WiPi NetDIMM time limit alive without Pi dependencies."""
    cabinet_id = cabinet["id"]
    stop_time_hack(cabinet)
    stop_event = threading.Event()

    def keepalive() -> None:
        packet = struct.pack("<II", 0x17000004, TIME_HACK_LIMIT_MS)
        while not stop_event.is_set():
            try:
                # WiPi keeps one NetDIMM TCP session open and refreshes every 5s.
                with socket.create_connection((cabinet["ip"], 10703), timeout=5) as connection:
                    connection.settimeout(5)
                    while not stop_event.is_set():
                        connection.sendall(packet)
                        if stop_event.wait(TIME_HACK_INTERVAL):
                            break
            except OSError as exc:
                if not stop_event.is_set():
                    LOG.warning("Time Hack connection to %s failed; retrying: %s", cabinet["ip"], exc)
                    stop_event.wait(2)

    thread = threading.Thread(target=keepalive, name="time-hack-" + cabinet_id, daemon=True)
    with TIME_HACK_LOCK:
        TIME_HACK_EVENTS[cabinet_id] = stop_event
        TIME_HACK_THREADS[cabinet_id] = thread
    thread.start()
    LOG.info("Time Hack enabled for %s (10-minute limit refreshed every 5 seconds)", cabinet["name"])

def perform_load(job_id: str, cabinet: dict[str, str], filename: str) -> None:
    def update(**values: Any) -> None:
        with JOBS_LOCK:
            JOBS[job_id].update(values)

    load_lock = cabinet_load_lock(cabinet["id"])
    if not load_lock.acquire(blocking=False):
        update(status="error", message=f"Another NetDIMM operation is already running for {cabinet['name']}.")
        return

    time_hack_paused = False
    try:
        rom = safe_rom(filename)
        update(status="preparing", message="Preparing ROM image", progress=0)
        if rom.name.lower().endswith(".gz"):
            with gzip.open(rom, "rb") as stream:
                data = stream.read()
        else:
            data = rom.read_bytes()

        data, applied_patches = apply_game_patches(data, filename, cabinet)
        if applied_patches:
            LOG.info("Applied game patches for %s: %s", filename, ", ".join(applied_patches))

        # The Time Hack owns a persistent connection to TCP/10703. Close it
        # completely before NetDimm opens its upload/control session.
        stop_time_hack(cabinet)
        time_hack_paused = True
        LOG.info("Starting NetDIMM upload to %s for %s", cabinet["name"], filename)

        target = enum_value(NetDimmTargetEnum, cabinet["target"])
        version = enum_value(NetDimmVersionEnum, cabinet["firmware"])
        dimm = NetDimm(cabinet["ip"], version=version, target=target,
                       log=lambda message, **kwargs: (
                           LOG.info("NetDIMM %s: %s", cabinet["name"], message),
                           update(message=str(message))
                       ))

        def progress(sent: int, total: int) -> None:
            percent = int((sent / total) * 100) if total else 0
            update(status="uploading", progress=max(0, min(100, percent)),
                   message=f"Uploading to {cabinet['name']}: {percent}%")

        update(status="uploading", message=f"Connecting to {cabinet['name']}", progress=0)
        LOG.info("Calling NetDimm.send for %s", cabinet["name"])
        dimm.send(data, disable_crc_check=bool(options().get("disable_crc", False)),
                  progress_callback=progress)
        update(status="rebooting", message="Upload complete; rebooting cabinet", progress=100)
        LOG.info("Upload complete; rebooting %s", cabinet["name"])
        dimm.reboot()
        update(status="complete", message=f"{cabinet['name']} is being booted", progress=100)
    except Exception as exc:
        LOG.exception("NetDIMM load failed for %s", cabinet.get("name", "cabinet"))
        update(status="error", message=str(exc))
    finally:
        if time_hack_paused and bool(options().get("time_hack", True)):
            try:
                start_time_hack(cabinet)
            except Exception:
                LOG.exception("Could not restart Time Hack for %s", cabinet["name"])
        load_lock.release()



PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WiPi Netbooter</title>
<style>
:root{color-scheme:dark;font-family:Arial,sans-serif;background:#101820;color:#eef4f7}
*{box-sizing:border-box}body{margin:0}.top{background:#142b3a;border-bottom:4px solid #168ac4;padding:22px max(20px,calc((100% - 1180px)/2))}
h1{margin:0;font-size:26px;letter-spacing:.07em}.tag{color:#91cce9;font-size:12px;letter-spacing:.2em;margin-top:5px}
main{max-width:1180px;margin:24px auto;padding:0 18px}.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:18px}
input,select,button{font:inherit;border:1px solid #476273;border-radius:7px;background:#1b2e3b;color:#eef4f7;padding:11px}
input{flex:1;min-width:220px}button{cursor:pointer;background:#087eb7;border-color:#168ac4;font-weight:bold}button:disabled{opacity:.45;cursor:not-allowed}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:16px}
.card{background:#1b2a35;border:1px solid #344b5a;border-radius:10px;overflow:hidden}
.art{height:132px;background:#243d4d;display:flex;align-items:center;justify-content:center;color:#9ab5c5}
.art img{width:100%;height:100%;object-fit:contain}.preview{display:block;width:100%;max-height:180px;background:#000}.info{padding:13px}.name{font-weight:bold;font-size:16px}.meta{color:#a9bdc9;font-size:12px;margin:6px 0 12px}
.card button{width:100%;padding:9px}.panel{background:#1b2a35;border:1px solid #344b5a;border-radius:10px;padding:16px;margin:0 0 18px}
.muted{color:#a9bdc9}.good{color:#8bd5a5}.bad{color:#ffaaa2}.job{margin-top:12px;line-height:1.5}
.launch-overlay{position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.78);display:flex;align-items:center;justify-content:center;padding:20px}
.launch-overlay[hidden]{display:none}.launch-dialog{width:min(100%,440px);background:#1b2a35;border:1px solid #168ac4;border-radius:12px;padding:24px;text-align:center;box-shadow:0 18px 60px #0009}
.launch-dialog h2{margin:0 0 12px}.launch-dialog p{line-height:1.5;color:#c2d5df}.launch-dialog button{width:100%;margin-top:12px;padding:14px}
@media(max-width:520px){.top{padding:18px}h1{font-size:21px}}
</style></head><body>
<header class="top"><h1>WiPi NETBOOTER</h1><div class="tag">SEGA NAOMI · NETDIMM MANAGER</div><div style="margin-top:10px"><a href="/classic" style="color:#91cce9">Open Classic interface</a></div></header>
<main>
<section class="panel">
<div class="toolbar">
<input id="search" placeholder="Search games..." oninput="filterGames()">
<select id="system" onchange="filterGames()"><option value="">All systems</option></select>
<select id="genre" onchange="filterGames()"><option value="">All genres</option></select>
<select id="orientation" onchange="filterGames()"><option value="">All orientations</option></select>
<select id="controls" onchange="filterGames()"><option value="">All controls</option></select>
<select id="sort" onchange="filterGames()" aria-label="Sort games"><option value="name">Sort: A–Z</option><option value="date">Date added: newest first</option></select>
<label class="muted"><input id="favourites" type="checkbox" onchange="filterGames()" style="min-width:auto;flex:0"> Favourites</label>
<label class="muted"><input id="show-disabled" type="checkbox" onchange="filterGames()" style="min-width:auto;flex:0"> Show disabled</label>
<select id="cabinet"><option value="">Choose cabinet…</option></select>
<button id="test-cabinet" type="button">TEST CONNECTION</button>
<span id="power-status" class="muted"></span>
<button id="power-on" type="button">POWER ON</button><button id="power-off" type="button">POWER OFF</button>
</div>
<div class="muted" id="summary">Loading game list…</div>
<div id="job" class="job"></div>
<div class="panel" id="patch-profile" hidden><strong id="patch-profile-title">Game patches</strong><div id="patch-profile-options"></div><button id="save-patch-profile" type="button">SAVE PATCH SETTINGS</button> <button id="close-patch-profile" type="button">CLOSE</button><span id="patch-profile-status" class="muted"></span></div>
<div class="panel" id="game-settings" hidden><strong id="game-settings-title">NAOMI EEPROM SETTINGS</strong><p class="muted">Edit the default EEPROM profile for this game. Saving stores the profile only; it does not modify your ROM or apply settings to the cabinet yet.</p><div id="game-settings-region-wrap" hidden>Region: <select id="game-settings-region"></select></div><div id="game-settings-fields"></div><button id="save-game-settings" type="button">SAVE SETTINGS PROFILE</button> <button id="close-game-settings" type="button">CLOSE</button><span id="game-settings-status" class="muted"></span></div>
</section>
<div class="grid" id="games"></div>
</main>
<div id="launch-countdown" class="launch-overlay" hidden role="dialog" aria-modal="true" aria-labelledby="launch-countdown-title">
 <div class="launch-dialog"><h2 id="launch-countdown-title">Cabinet powered on</h2><p id="launch-countdown-message"></p><button id="launch-now-button" type="button">LAUNCH GAME NOW</button></div>
</div>
<script>
let games=[], cabinets=[];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function init(){
 const r=await fetch('/api/games'); const d=await r.json(); games=d.games||[];
 document.getElementById('summary').textContent=d.error||String(games.length)+' game files found · ROM folder: '+(d.rom_path||'unavailable');
 const systems=[...new Set(games.map(g=>g.system).filter(Boolean))].sort();
 const genres=[...new Set(games.map(g=>g.genre).filter(Boolean))].sort();
 const orientations=[...new Set(games.map(g=>g.orientation).filter(Boolean))].sort();
 const controls=[...new Set(games.map(g=>g.controls).filter(Boolean))].sort();
 for(const pair of [['system',systems],['genre',genres],['orientation',orientations],['controls',controls]]) for(const v of pair[1]){const o=document.createElement('option');o.value=v;o.textContent=v;document.getElementById(pair[0]).appendChild(o)}
 const c=await fetch('/api/cabinets'); cabinets=(await c.json()).cabinets||[];
 const cabinetSelect=document.getElementById('cabinet');
 cabinets.forEach(cabinet=>{const o=document.createElement('option');o.value=cabinet.id;o.textContent=cabinet.name+' ('+cabinet.ip+')';cabinetSelect.appendChild(o)});
 document.getElementById('test-cabinet').addEventListener('click',testCabinet);
 document.getElementById('cabinet').addEventListener('change',refreshCabinetPower);
 document.getElementById('power-on').addEventListener('click',()=>setCabinetPower('on'));
 document.getElementById('power-off').addEventListener('click',()=>setCabinetPower('off'));
 refreshCabinetPower();
 filterGames();
}
function filterGames(){
 const q=document.getElementById('search').value.toLowerCase(),s=document.getElementById('system').value,g=document.getElementById('genre').value;
 const o=document.getElementById('orientation').value,c=document.getElementById('controls').value;
 const favourites=document.getElementById('favourites').checked,showDisabled=document.getElementById('show-disabled').checked;
 const sort=document.getElementById('sort').value;
 const shown=games.filter(x=>(showDisabled||x.enabled)&&(!favourites||x.favourite)&&(!q||(x.name+' '+x.filename+' '+x.manufacturer).toLowerCase().includes(q))&&(!s||x.system===s)&&(!g||x.genre===g)&&(!o||x.orientation===o)&&(!c||x.controls===c));
 shown.sort((a,b)=>sort==='date'?(b.file_mtime||0)-(a.file_mtime||0):a.name.localeCompare(b.name,undefined,{sensitivity:'base'}));
 document.getElementById('summary').textContent=String(shown.length)+' of '+String(games.length)+' games';
 document.getElementById('games').innerHTML=shown.map(x=>{
  const art=x.image?'<img loading="lazy" src="/art/'+encodeURIComponent(x.image)+'" onerror="this.remove()">':'NAOMI';
  const video=x.video?'<video class="preview" controls preload="none" playsinline src="/video/'+encodeURIComponent(x.video)+'"></video>':'';
  const fav=x.favourite?' ★':'';
  const regionFlag=({JPN:'🇯🇵',USA:'🇺🇸',EXPORT:'🌍'})[String(x.region||'').toUpperCase()]||'';
  const disabled=x.enabled?'':' · DISABLED';
  const button=x.enabled?'<button data-rom="'+encodeURIComponent(x.filename)+'" '+(cabinets.length?'':'disabled')+'>LOAD GAME</button>':'<button disabled>DISABLED IN CATALOGUE</button>';
  const profile=x.patchable?'<button type="button" data-profile="'+encodeURIComponent(x.filename)+'">PATCH PROFILE</button>':'';
  const settings=String(x.system||'').toLowerCase().includes('naomi')?'<button type="button" data-settings="'+encodeURIComponent(x.filename)+'">EEPROM SETTINGS</button>':'';
  return '<article class="card"><div class="art">'+art+'</div>'+video+'<div class="info"><div class="name">'+esc(x.name)+(regionFlag?' '+regionFlag:'')+fav+'</div><div class="meta">'+esc(x.system)+' · '+esc(x.year)+' · '+esc(x.genre)+'<br>'+esc(x.orientation)+' · '+esc(x.controls)+disabled+'</div>'+button+profile+settings+'</div></article>';
 }).join('');
 document.querySelectorAll('[data-rom]').forEach(button=>button.addEventListener('click',()=>launchGame(button.dataset.rom)));
 document.querySelectorAll('[data-profile]').forEach(button=>button.addEventListener('click',()=>openPatchProfile(button.dataset.profile)));
 document.querySelectorAll('[data-settings]').forEach(button=>button.addEventListener('click',()=>openGameSettings(button.dataset.settings)));
}
async function refreshCabinetPower(){
 const cabinet=cabinets.find(c=>c.id===document.getElementById('cabinet').value);
 const status=document.getElementById('power-status'),on=document.getElementById('power-on'),off=document.getElementById('power-off');
 const enabled=!!(cabinet&&cabinet.power_entity);
 status.textContent=enabled?'Power: '+(cabinet.power_state||'unknown'):(cabinet?'No power entity configured':'');
 on.disabled=!enabled;off.disabled=!enabled;
}
async function setCabinetPower(action){
 const id=document.getElementById('cabinet').value,cabinet=cabinets.find(c=>c.id===id);
 if(!cabinet||!cabinet.power_entity)return;
 if(action==='off'&&!confirm('Turn off '+cabinet.name+'? This cuts power to the cabinet.'))return;
 const status=document.getElementById('power-status');status.textContent='Sending power '+action+'…';
 try{
  const response=await fetch('/api/cabinets/'+encodeURIComponent(id)+'/power',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
  const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'Power command failed');
  cabinet.power_state=result.state||action;status.textContent='Power: '+cabinet.power_state;
 }catch(error){status.textContent='Power error: '+error.message}
}
async function testCabinet(){
 const cabinetId=document.getElementById('cabinet').value;
 const panel=document.getElementById('job');
 if(!cabinetId){panel.textContent='Choose a cabinet first.';return}
 panel.textContent='Testing NetDIMM connection…';
 const response=await fetch('/api/cabinets/'+encodeURIComponent(cabinetId)+'/test',{method:'POST'});
 const result=await response.json();
 panel.textContent=result.message||'Connection test finished.';
 panel.className='job '+(result.ok?'good':'bad');
}
let activePatchFilename='';
async function openPatchProfile(encoded){
 const filename=decodeURIComponent(encoded),panel=document.getElementById('patch-profile');
 activePatchFilename=filename;panel.hidden=false;
 document.getElementById('patch-profile-title').textContent='Patch profile: '+filename;
 const options=document.getElementById('patch-profile-options'),status=document.getElementById('patch-profile-status');
 options.textContent='Checking available patches…';status.textContent='';
 try{
  const response=await fetch('/api/games/'+encodeURIComponent(filename)+'/patches');
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Could not load patch profile');
  options.innerHTML=result.patches.length?result.patches.map(p=>'<label style="display:block;margin:12px 0"><input type="checkbox" data-patch-id="'+esc(p.id)+'" '+(p.enabled?'checked':'')+'> <strong>'+esc(p.title)+'</strong><br><span class="muted">'+esc(p.description)+'</span></label>').join(''):'<p class="muted">No patches are currently available for this game.</p>';
  document.getElementById('save-patch-profile').disabled=!result.patches.length;
  panel.scrollIntoView({behavior:'smooth',block:'center'});
 }catch(error){options.textContent=error.message;document.getElementById('save-patch-profile').disabled=true}
}
async function savePatchProfile(){
 const selected=[...document.querySelectorAll('#patch-profile-options [data-patch-id]:checked')].map(x=>x.dataset.patchId);
 const status=document.getElementById('patch-profile-status');status.textContent='Saving…';
 try{
  const response=await fetch('/api/games/'+encodeURIComponent(activePatchFilename)+'/patches',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({patches:selected})});
  const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'Could not save patch settings');
  status.textContent=result.message;
 }catch(error){status.textContent='Error: '+error.message}
}
document.getElementById('save-patch-profile').addEventListener('click',savePatchProfile);
document.getElementById('close-patch-profile').addEventListener('click',()=>{document.getElementById('patch-profile').hidden=true});
let activeSettingsFilename='', activeSettings=null;
async function openGameSettings(encoded){
 const filename=decodeURIComponent(encoded),panel=document.getElementById('game-settings');
 activeSettingsFilename=filename;panel.hidden=false;
 document.getElementById('game-settings-title').textContent='EEPROM settings: '+filename;
 document.getElementById('game-settings-fields').textContent='Reading Naomi ROM settings…';
 document.getElementById('game-settings-status').textContent='';
 try{
  const response=await fetch('/api/games/'+encodeURIComponent(filename)+'/settings');
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Could not read EEPROM settings');
  activeSettings=result.settings;
  const region=document.getElementById('game-settings-region'),wrap=document.getElementById('game-settings-region-wrap');
  region.innerHTML=result.regions.map(r=>'<option value="'+esc(r)+'" '+(r===result.region?'selected':'')+'>'+esc(r)+'</option>').join('');
  wrap.hidden=result.regions.length<2;
  renderGameSettings(activeSettings);
  panel.scrollIntoView({behavior:'smooth',block:'center'});
 }catch(error){activeSettings=null;document.getElementById('game-settings-fields').textContent=error.message}
}
function renderGameSettings(wrapper){
 const root=document.getElementById('game-settings-fields');
 const groups=[['System settings',wrapper.system],['Game settings',wrapper.game]];
 root.innerHTML=groups.map(([title,group])=>{
  if(!group||!Array.isArray(group.settings)||!group.settings.length)return '';
  const visibleSettings=group.settings.map((setting,index)=>({setting,index})).filter(({setting})=>{
   const name=String(setting.name||'');
   // Keep only the simple Coin/Credit Assignment choice (restricted below
   // to 1:1 and Free Play). Hide low-level coin/credit fields such as coins
   // per credit, multipliers, bonus coins and sequence options.
   return !(/coin|credit|sequence/i.test(name)&&!/coin\\s*\\/\\s*credit\\s*assignment/i.test(name));
  });
  if(!visibleSettings.length)return '';
  return '<h3>'+title+'</h3>'+visibleSettings.map(({setting,index})=>{
   const values=setting.values;
   if(!values||typeof values!=='object'||setting.read_only===true)return '';
   let entries=Object.entries(values);
   // Coin/Credit Assignment is a 27-choice scale. Keep the normal editor
   // focused on standard 1:1 (#1) and Free Play (#27), without changing
   // the underlying settings object or discarding any EEPROM bytes.
   if(/coin/i.test(String(setting.name||''))){
    const numberedOne=entries.filter(([value,label])=>/#\\s*0*1\\b/i.test(String(label)));
    const freePlay=entries.filter(([value,label])=>/free\\s*play/i.test(String(label))||/#\\s*0*27\\b/i.test(String(label)));
    const first=numberedOne.length?numberedOne:[entries[0]].filter(Boolean);
    const last=freePlay.length?freePlay:(entries.length>=27?[entries[entries.length-1]]:[]);
    entries=[...new Map([...first,...last].map(entry=>[entry[0],entry])).values()];
   }
   const options=entries.map(([value,label])=>'<option value="'+esc(value)+'" '+(Number(value)===Number(setting.current)?'selected':'')+'>'+esc(label)+'</option>').join('');
   return '<label style="display:block;margin:12px 0"><strong>'+esc(setting.name||('Setting '+(index+1)))+'</strong><select style="display:block;width:100%;margin-top:5px" data-setting-group="'+title.split(' ')[0].toLowerCase()+'" data-setting-index="'+index+'">'+options+'</select></label>';
  }).join('');
 }).join('')||'<p class="muted">No editable EEPROM settings were found for this game.</p>';
}
document.getElementById('game-settings-region').addEventListener('change',async()=>{
 const region=document.getElementById('game-settings-region').value;
 try{
  const response=await fetch('/api/games/'+encodeURIComponent(activeSettingsFilename)+'/settings?region='+encodeURIComponent(region));
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Could not read region settings');
  activeSettings=result.settings;renderGameSettings(activeSettings);
 }catch(error){document.getElementById('game-settings-status').textContent='Error: '+error.message}
});
document.getElementById('save-game-settings').addEventListener('click',async()=>{
 if(!activeSettings)return;
 for(const select of document.querySelectorAll('#game-settings-fields select[data-setting-index]')){
  const group=select.dataset.settingGroup==='system'?'system':'game';
  const index=Number(select.dataset.settingIndex);
  activeSettings[group].settings[index].current=Number(select.value);
 }
 const status=document.getElementById('game-settings-status');status.textContent='Saving profile…';
 try{
  const response=await fetch('/api/games/'+encodeURIComponent(activeSettingsFilename)+'/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({region:document.getElementById('game-settings-region').value,settings:activeSettings})});
  const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'Could not save settings');
  status.textContent=result.message;
 }catch(error){status.textContent='Error: '+error.message}
});
document.getElementById('close-game-settings').addEventListener('click',()=>{document.getElementById('game-settings').hidden=true});
async function submitGameLoad(filename,cabinetId){
 const response=await fetch('/api/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:filename,cabinet_id:cabinetId})});
 const result=await response.json();
 if(response.status===409&&result.power_required)return {powerRequired:true,result};
 if(!response.ok)throw new Error(result.error||'Could not start game load');
 return {result};
}
async function powerOnAndWait(cabinetId,cabinetName,status){
 status.textContent=cabinetName+' is off. Sending power-on command…';
 const power=await fetch('/api/cabinets/'+encodeURIComponent(cabinetId)+'/power',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'on'})});
 const powered=await power.json();
 if(!power.ok||!powered.ok)throw new Error(powered.error||'Could not power on cabinet');
 for(let attempt=0;attempt<60;attempt++){
  await new Promise(resolve=>setTimeout(resolve,1000));
  const response=await fetch('/api/cabinets');
  const data=await response.json();
  const cabinet=(data.cabinets||[]).find(item=>item.id===cabinetId);
  if(cabinet&&cabinet.power_state==='on')return;
  if(cabinet&&cabinet.power_state==='unavailable')throw new Error('Could not read the cabinet outlet state from Home Assistant');
  status.textContent='Waiting for '+cabinetName+' to power on… ('+(attempt+1)+'s)';
 }
 throw new Error('Cabinet did not report power ON within 60 seconds. Game was not loaded.');
}
function waitForNetdimmReady(cabinetName){
 const overlay=document.getElementById('launch-countdown'),message=document.getElementById('launch-countdown-message'),button=document.getElementById('launch-now-button');
 return new Promise(resolve=>{
  let remaining=35,interval;
  const update=()=>{message.textContent=cabinetName+' is powered on. NetDIMM will launch automatically in '+remaining+' seconds. Press below to launch immediately.'};
  const finish=()=>{clearInterval(interval);button.removeEventListener('click',finish);overlay.hidden=true;resolve()};
  button.addEventListener('click',finish,{once:true});overlay.hidden=false;update();
  interval=setInterval(()=>{remaining-=1;if(remaining<=0)finish();else update()},1000);
 });
}
async function launchGame(encoded){
 const filename=decodeURIComponent(encoded);
 const cabinetId=document.getElementById('cabinet').value;
 const status=document.getElementById('job');
 if(!cabinetId){status.textContent='Choose a cabinet first.';return}
 status.className='job';status.textContent='Checking cabinet power…';
 try{
  let attempt=await submitGameLoad(filename,cabinetId);
  if(attempt.powerRequired){
   const name=attempt.result.cabinet_name||'The selected cabinet';
   if(!confirm(name+' is powered off. Turn it on and launch this game?')){status.textContent='Launch cancelled. Cabinet remains off.';return}
   await powerOnAndWait(cabinetId,name,status);
   await waitForNetdimmReady(name);
   attempt=await submitGameLoad(filename,cabinetId);
   if(attempt.powerRequired)throw new Error('Cabinet still reports power OFF. Game was not loaded.');
  }
  const result=attempt.result;
  status.textContent=result.message||'Request submitted';
  if(result.job_id)watchJob(result.job_id);
 }catch(error){status.className='job bad';status.textContent='Launch failed: '+error.message}
}
async function watchJob(id){
 const panel=document.getElementById('job');
 for(let i=0;i<360;i++){await new Promise(r=>setTimeout(r,1000));const d=await (await fetch('/api/jobs/'+id)).json();panel.textContent=d.status+': '+(d.message||'')+' '+(d.progress??0)+'%';if(['complete','error'].includes(d.status)){panel.className='job '+(d.status==='complete'?'good':'bad');return}}
}
init().catch(e=>document.getElementById('summary').textContent='Could not load game list: '+e);
</script></body></html>"""


@app.get("/")
def index():
    if str(options().get("frontend", "modern")).strip().lower() == "classic":
        classic_page = Path(__file__).with_name("classic.html").read_text(encoding="utf-8")
        return render_template_string(classic_page)
    return render_template_string(PAGE)


@app.get("/modern")
def modern_index():
    return render_template_string(PAGE)


@app.get("/classic")
def classic_index():
    classic_page = Path(__file__).with_name("classic.html").read_text(encoding="utf-8")
    return render_template_string(classic_page)


@app.get("/api/games")
def api_games():
    try:
        games, error = discover_games()
        for game in games:
            game["patchable"] = bool(game_patch_options(game))
        return jsonify(games=games, systems=discover_systems(rom_folder()), error=error, rom_path=str(rom_folder()))
    except (OSError, ValueError) as exc:
        return jsonify(games=[], error=str(exc), rom_path=None)


def supervisor_api(method: str, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError("Home Assistant API access is not enabled for this app.")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        "http://supervisor/core/api/" + endpoint.lstrip("/"),
        data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Home Assistant returned HTTP {exc.code}: {detail[:200]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not contact Home Assistant: {exc}") from exc


def cabinet_power_state(cabinet: dict[str, str]) -> str:
    entity = cabinet.get("power_entity", "")
    if not entity:
        return ""
    try:
        state = supervisor_api("GET", f"states/{entity}")
        return str(state.get("state", "unavailable"))
    except Exception as exc:
        LOG.warning("Could not read power state for %s: %s", cabinet["name"], exc)
        return "unavailable"


@app.get("/api/cabinets")
def api_cabinets():
    configured = cabinets()
    for cabinet in configured:
        cabinet["power_state"] = cabinet_power_state(cabinet) if cabinet["power_entity"] else ""
    return jsonify(cabinets=configured)


@app.post("/api/cabinets/<cabinet_id>/power")
def api_cabinet_power(cabinet_id: str):
    selected = next((cabinet for cabinet in cabinets() if cabinet["id"] == cabinet_id), None)
    if selected is None:
        return jsonify(ok=False, error="Select a configured cabinet."), 400
    entity = selected.get("power_entity", "")
    if not entity:
        return jsonify(ok=False, error="No Power entity is configured for this cabinet."), 400
    body = request.get_json(silent=True) or {}
    action = str(body.get("action", "")).lower()
    if action not in {"on", "off"}:
        return jsonify(ok=False, error="Power action must be on or off."), 400
    # Power operations must never leave a persistent Time Hack socket attached
    # to a cabinet that is being switched on or off.
    load_lock = cabinet_load_lock(selected["id"])
    if not load_lock.acquire(blocking=False):
        return jsonify(ok=False, error=f"A NetDIMM operation is already running for {selected['name']}. Please wait and try again."), 409
    try:
        stop_time_hack(selected)
        LOG.info("Time Hack halted before powering %s %s", selected["name"], action)
        supervisor_api("POST", f"services/switch/turn_{action}", {"entity_id": entity})
        return jsonify(ok=True, message=f"{selected['name']} power {action} command sent.",
                       state=cabinet_power_state(selected))
    except Exception as exc:
        LOG.warning("Power %s failed for %s: %s", action, selected["name"], exc)
        return jsonify(ok=False, error=str(exc)), 502
    finally:
        load_lock.release()


@app.post("/api/catalogue")
def api_update_catalogue():
    body = request.get_json(silent=True) or {}
    filename = str(body.get("romname", "")).strip()
    try:
        rom = safe_rom(filename)
    except (OSError, ValueError) as exc:
        return jsonify(ok=False, error=str(exc)), 400

    # A catalogue entry is metadata for a ROM already present in the shared ROM folder.
    values = {
        "system": str(body.get("system", "Sega Naomi")).strip(),
        "romname": filename,
        "image": Path(str(body.get("image", "")).strip()).name if body.get("image") else "",
        "video": Path(str(body.get("video", "")).strip()).name if body.get("video") else "",
        "description": str(body.get("description", "")).strip() or rom.stem,
        "lcd_description": str(body.get("lcd_description", "")).strip(),
        "manufacturer": str(body.get("manufacturer", "")).strip(),
        "year": str(body.get("year", "")).strip(),
        "genre": str(body.get("genre", "")).strip(),
        "rating": str(body.get("rating", "")).strip(),
        "orientation": str(body.get("orientation", "")).strip(),
        "controls": str(body.get("controls", "")).strip(),
        "enabled": "Yes" if body.get("enabled", True) else "No",
        "favourite": "Yes" if body.get("favourite", False) else "No",
        "region": str(body.get("region", "")).strip().upper(),
    }
    if values["region"] not in {"", "JPN", "USA", "EXPORT"}:
        return jsonify(ok=False, error="Region must be blank, JPN, USA, or EXPORT."), 400

    for field in ("image", "video"):
        if values[field] and values[field] != str(body.get(field, "")).strip():
            return jsonify(ok=False, error=f"Invalid {field} filename."), 400

    try:
        folder = rom_folder()
        csv_path = catalogue_path(folder) or (folder / "romsinfo.csv")
        with CATALOGUE_LOCK:
            rows: list[dict[str, str]] = []
            fieldnames = CATALOGUE_COLUMNS.copy()
            if csv_path.is_file():
                with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream)
                    if reader.fieldnames:
                        fieldnames = list(reader.fieldnames)
                    if "region" not in fieldnames:
                        fieldnames.append("region")
                    rows = [{key: (row.get(key) or "") for key in fieldnames}
                            for row in reader]
            if "region" not in fieldnames:
                fieldnames.append("region")
            existing = next((row for row in rows if row.get("romname", "").strip() == filename), None)
            if existing is None:
                existing = {key: "" for key in fieldnames}
                rows.append(existing)
            for key, value in values.items():
                if key in fieldnames:
                    existing[key] = value
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = csv_path.with_name(csv_path.name + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            temporary.replace(csv_path)
        return jsonify(ok=True, message=f"Saved catalogue entry for {filename}.")
    except (OSError, csv.Error, UnicodeError) as exc:
        LOG.exception("Could not update ROM catalogue")
        return jsonify(ok=False, error=f"Could not save catalogue: {exc}"), 500


@app.get("/art/<path:filename>")
def artwork(filename: str):
    return serve_asset(filename, ("images", "artwork", "img"))


@app.get("/video/<path:filename>")
def video_preview(filename: str):
    return serve_asset(filename, ("videos", "video"))


def serve_asset(filename: str, subfolders: tuple[str, ...]):
    if Path(filename).name != filename:
        abort(404)
    try:
        folder = rom_folder()
    except ValueError:
        abort(404)
    # Assets are stored inside the configured ROM folder.
    for subfolder in subfolders:
        candidate = folder / subfolder
        if (candidate / filename).is_file():
            return send_from_directory(candidate, filename)
    abort(404)


@app.post("/api/cabinets/<cabinet_id>/test")
def api_test_cabinet(cabinet_id: str):
    selected = next((cabinet for cabinet in cabinets() if cabinet["id"] == cabinet_id), None)
    if selected is None:
        return jsonify(ok=False, message="Select a configured cabinet."), 400
    try:
        dimm = NetDimm(
            selected["ip"],
            version=enum_value(NetDimmVersionEnum, selected["firmware"]),
            target=enum_value(NetDimmTargetEnum, selected["target"]),
        )
        dimm.info()
        return jsonify(ok=True, message=f"NetDIMM at {selected['ip']} responded.")
    except Exception as exc:
        LOG.warning("NetDIMM connection test failed for %s: %s", selected["name"], exc)
        return jsonify(ok=False, message=f"Could not reach {selected['name']}: {exc}"), 502


def read_rom_bytes(filename: str) -> bytes:
    rom_path = safe_rom(filename)
    if rom_path.name.lower().endswith(".gz"):
        with gzip.open(rom_path, "rb") as stream:
            return stream.read()
    return rom_path.read_bytes()


@app.get("/api/games/<path:filename>/settings")
def api_game_settings(filename: str):
    """Return editable EEPROM settings discovered from a game's Naomi ROM serial."""
    if NaomiRom is None or NaomiRomRegionEnum is None or NaomiSettingsManager is None:
        return jsonify(error="Naomi settings tools are unavailable in this build."), 503
    try:
        data = read_rom_bytes(filename)
        rom = NaomiRom(data)
        if not rom.valid:
            return jsonify(error="This file is not a valid Naomi ROM image."), 400
        regions = list(rom.regions)
        if not regions:
            return jsonify(error="The Naomi ROM header does not declare a supported region."), 422
        requested_region = request.args.get("region", "").strip()
        region = next((item for item in regions if item.name == requested_region), None) if requested_region else regions[0]
        if region is None:
            return jsonify(error="Requested region is not declared by this ROM.",
                           regions=[item.name for item in regions]), 400
        manager = NaomiSettingsManager(get_default_settings_directory())
        wrapper = manager.from_rom(rom, region)
        settings = wrapper.to_json()
        # Re-open a previously saved profile for this exact ROM and region.
        profiles_path = Path("/data/naomi_settings_profiles.json")
        try:
            with SETTINGS_PROFILES_LOCK:
                profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
            saved = profiles.get(filename, {})
            if saved.get("region") == region.name and isinstance(saved.get("settings"), dict):
                settings = manager.from_json(saved["settings"]).to_json()
        except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            LOG.warning("Ignoring unreadable saved Naomi settings profile for %s: %s", filename, exc)
        return jsonify(filename=filename, serial=rom.serial.hex().upper(),
                       region=region.name, regions=[item.name for item in regions],
                       settings=settings)
    except FileNotFoundError:
        return jsonify(error="ROM file is not available."), 404
    except Exception as exc:
        LOG.warning("Could not read Naomi settings for %s: %s", filename, exc)
        return jsonify(error=str(exc)), 422


SETTINGS_PROFILES_FILE = Path("/data/naomi_settings_profiles.json")
SETTINGS_PROFILES_LOCK = threading.Lock()


@app.post("/api/games/<path:filename>/settings")
def api_save_game_settings(filename: str):
    if NaomiSettingsManager is None:
        return jsonify(ok=False, error="Naomi settings tools are unavailable in this build."), 503
    try:
        safe_rom(filename)
        body = request.get_json(silent=True) or {}
        settings = body.get("settings")
        if not isinstance(settings, dict):
            return jsonify(ok=False, error="Settings profile must be a JSON object."), 400
        manager = NaomiSettingsManager(get_default_settings_directory())
        wrapper = manager.from_json(settings)
        # Validate that the selected values can be represented as a real Naomi EEPROM.
        manager.to_eeprom(wrapper)
        region = str(body.get("region", "")).strip()
        with SETTINGS_PROFILES_LOCK:
            try:
                profiles = json.loads(SETTINGS_PROFILES_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                profiles = {}
            profiles[filename] = {"region": region, "settings": settings}
            SETTINGS_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
            temporary = SETTINGS_PROFILES_FILE.with_suffix(".tmp")
            temporary.write_text(json.dumps(profiles, indent=2, sort_keys=True), encoding="utf-8")
            temporary.replace(SETTINGS_PROFILES_FILE)
        return jsonify(ok=True, message="EEPROM settings profile saved. It is not applied to the ROM or cabinet yet.")
    except FileNotFoundError:
        return jsonify(ok=False, error="ROM file is not available."), 404
    except Exception as exc:
        LOG.warning("Could not save Naomi settings for %s: %s", filename, exc)
        return jsonify(ok=False, error=str(exc)), 422


@app.get("/api/games/<path:filename>/patches")
def api_game_patches(filename: str):
    try:
        safe_rom(filename)
        game = next((item for item in discover_games()[0] if item["filename"] == filename), None)
        if game is None:
            return jsonify(error="Game is not in the current catalogue."), 404
        return jsonify(filename=filename, patches=game_patch_options(game))
    except (OSError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/games/<path:filename>/patches")
def api_save_game_patches(filename: str):
    try:
        safe_rom(filename)
        game = next((item for item in discover_games()[0] if item["filename"] == filename), None)
        if game is None:
            return jsonify(ok=False, error="Game is not in the current catalogue."), 404
        body = request.get_json(silent=True) or {}
        requested = body.get("patches", [])
        if not isinstance(requested, list) or any(not isinstance(item, str) for item in requested):
            return jsonify(ok=False, error="Patch selections must be a list of patch IDs."), 400
        allowed = {patch["id"] for patch in game_patch_options(game)}
        if len(set(requested)) != len(requested) or not set(requested).issubset(allowed):
            return jsonify(ok=False, error="One or more selected patches are not available for this game."), 400
        with PATCH_SETTINGS_LOCK:
            settings = load_patch_settings()
            if requested:
                settings[filename] = sorted(requested)
            else:
                settings.pop(filename, None)
            save_patch_settings(settings)
        return jsonify(ok=True, message="Game patch settings saved.", patches=game_patch_options(game))
    except (OSError, ValueError) as exc:
        return jsonify(ok=False, error=str(exc)), 400


@app.post("/api/load")
def api_load():
    body = request.get_json(silent=True) or {}
    filename = str(body.get("filename", ""))
    cabinet_id = str(body.get("cabinet_id", ""))
    try:
        safe_rom(filename)
    except (OSError, ValueError) as exc:
        return jsonify(error=str(exc)), 400
    selected = next((c for c in cabinets() if c["id"] == cabinet_id), None)
    if selected is None:
        return jsonify(error="Select a configured cabinet."), 400
    # Do not attempt a NetDIMM upload while the configured cabinet outlet is off.
    # The UI can offer to power it on, then retry this same request.
    power_state = cabinet_power_state(selected) if selected.get("power_entity") else ""
    if power_state == "off":
        return jsonify(error=f"{selected['name']} is powered off.",
                       power_required=True, power_state=power_state,
                       cabinet_name=selected["name"]), 409
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "queued", "message": "Waiting to start", "progress": 0}
    thread = threading.Thread(target=perform_load, args=(job_id, selected, filename), daemon=True)
    thread.start()
    return jsonify(job_id=job_id, message=f"Loading {filename} to {selected['name']}."), 202


@app.get("/api/jobs/<job_id>")
def api_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None:
        return jsonify(error="Unknown loading job."), 404
    return jsonify(job)


@app.get("/api/status")
def api_status():
    try:
        games, error = discover_games()
    except (OSError, ValueError) as exc:
        games, error = [], str(exc)
    return jsonify(ok=error is None, game_count=len(games), error=error,
                   cabinet_count=len(cabinets()), netdimm_library=NetDimm is not None)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8256")), threaded=True)
