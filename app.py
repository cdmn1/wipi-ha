"""Initial WiPi Home Assistant app shell.

The ROM directory is supplied by the Home Assistant app Configuration tab
through /data/options.json. Only HA-mapped /media and /share paths are allowed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from flask import Flask, jsonify, render_template_string

OPTIONS_FILE = Path("/data/options.json")
DEFAULT_ROM_PATH = "/media/NAOMI"
ALLOWED_ROOTS = (Path("/media"), Path("/share"))

app = Flask(__name__)


def configured_rom_path() -> Path:
    """Read and validate the ROM directory selected in HA app options."""
    try:
        options = json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
        raw_path = str(options.get("rom_path", DEFAULT_ROM_PATH)).strip()
    except FileNotFoundError:
        raw_path = os.environ.get("ROM_PATH", DEFAULT_ROM_PATH)
    except (OSError, json.JSONDecodeError, AttributeError):
        raw_path = DEFAULT_ROM_PATH

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        raise ValueError("ROM folder path must be an absolute path.")

    # Resolve existing parent paths while preventing traversal outside mapped mounts.
    resolved = candidate.resolve()
    if not any(resolved == root or root in resolved.parents for root in ALLOWED_ROOTS):
        raise ValueError("Choose a folder inside Home Assistant's /media or /share mount.")
    return resolved


def rom_status() -> dict:
    try:
        folder = configured_rom_path()
    except (OSError, ValueError) as exc:
        return {"ok": False, "path": None, "message": str(exc), "games": []}

    if not folder.exists():
        return {
            "ok": False,
            "path": str(folder),
            "message": "The configured folder does not exist or is not mounted in Home Assistant.",
            "games": [],
        }
    if not folder.is_dir():
        return {
            "ok": False,
            "path": str(folder),
            "message": "The configured path exists, but it is not a folder.",
            "games": [],
        }
    if not os.access(folder, os.R_OK):
        return {
            "ok": False,
            "path": str(folder),
            "message": "The app cannot read this folder. Check its Home Assistant mount and permissions.",
            "games": [],
        }

    # Initial discovery only. Actual NetDIMM loading and catalogue integration
    # will be added after the portable loader and its licensing are verified.
    games = sorted(
        entry.name for entry in folder.iterdir()
        if entry.is_file() and entry.suffix.lower() in {".bin", ".dat"}
    )
    return {
        "ok": True,
        "path": str(folder),
        "message": f"Folder is accessible. Found {len(games)} candidate game file(s).",
        "games": games,
    }


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WiPi Netbooter</title>
<style>
:root{color-scheme:dark;font-family:Arial,sans-serif;background:#101820;color:#f3f6f8}
body{max-width:900px;margin:0 auto;padding:28px 20px}
header{border-bottom:3px solid #168ac4;padding-bottom:18px;margin-bottom:24px}
h1{margin:0;color:#fff;letter-spacing:.04em} .sub{color:#8fc9e8;margin-top:6px}
.panel{background:#1b2a35;border:1px solid #344b5a;border-radius:10px;padding:20px;margin:16px 0}
.status{font-weight:bold;color:#8bd5a5}.bad{color:#ffb0a8}
code{overflow-wrap:anywhere;color:#b7dff4}
ul{padding-left:22px}li{padding:5px 0}
.small{color:#a9bac5;font-size:.9rem}
</style>
</head>
<body>
<header><h1>WiPi NETBOOTER</h1><div class="sub">SEGA NAOMI · HOME ASSISTANT EDITION</div></header>
<section class="panel">
<h2>ROM storage</h2>
<p class="{{ 'status' if status.ok else 'bad' }}">{{ status.message }}</p>
{% if status.path %}<p>Selected folder: <code>{{ status.path }}</code></p>{% endif %}
<p class="small">Change this folder in Home Assistant: Settings → Apps → WiPi Netbooter → Configuration.</p>
</section>
<section class="panel">
<h2>Game files</h2>
{% if status.games %}
<ul>{% for game in status.games %}<li>{{ game }}</li>{% endfor %}</ul>
{% elif status.ok %}
<p>No .bin or .dat files found in this folder yet.</p>
{% else %}
<p>Game discovery will start when the ROM folder is available.</p>
{% endif %}
</section>
<p class="small">Initial development build — NetDIMM cabinet setup and game loading are not enabled yet.</p>
</body></html>"""


@app.get("/")
def index():
    return render_template_string(PAGE, status=rom_status())


@app.get("/api/status")
def api_status():
    return jsonify(rom_status())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8256")))
