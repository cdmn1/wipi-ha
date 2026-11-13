"""WiPi-style Home Assistant NetDIMM application."""
from __future__ import annotations

import csv
import gzip
import ipaddress
import json
import logging
import os
import threading
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template_string, request, send_from_directory

try:
    from netdimm import NetDimm, NetDimmTargetEnum, NetDimmVersionEnum
except ImportError:
    NetDimm = NetDimmTargetEnum = NetDimmVersionEnum = None

OPTIONS_FILE = Path("/data/options.json")
DEFAULT_ROM_PATH = "/media/NAOMI"
ALLOWED_ROOTS = (Path("/media"), Path("/share"))
ROM_SUFFIXES = (".bin", ".bin.gz", ".dat")
LOG = logging.getLogger("wipi-ha")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__)
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
CATALOGUE_LOCK = threading.Lock()
CATALOGUE_COLUMNS = [
    "system", "romname", "image", "video", "description", "lcd_description",
    "manufacturer", "year", "genre", "rating", "orientation", "controls",
    "enabled", "favourite", "openjvs", "openffb", "game_id", "audit_name",
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


def enum_value(enum_type: Any, value: str) -> Any:
    if enum_type is None:
        raise RuntimeError("NetDIMM transfer library is unavailable in this build.")
    for member in enum_type:
        if str(member.value).lower() == value.lower():
            return member
    raise ValueError(f"Unsupported NetDIMM setting: {value}")


def perform_load(job_id: str, cabinet: dict[str, str], filename: str) -> None:
    def update(**values: Any) -> None:
        with JOBS_LOCK:
            JOBS[job_id].update(values)

    try:
        rom = safe_rom(filename)
        update(status="preparing", message="Preparing ROM image", progress=0)
        if rom.name.lower().endswith(".gz"):
            with gzip.open(rom, "rb") as stream:
                data = stream.read()
        else:
            data = rom.read_bytes()

        target = enum_value(NetDimmTargetEnum, cabinet["target"])
        version = enum_value(NetDimmVersionEnum, cabinet["firmware"])
        dimm = NetDimm(cabinet["ip"], version=version, target=target,
                       log=lambda message, **kwargs: update(message=str(message)))

        def progress(sent: int, total: int) -> None:
            percent = int((sent / total) * 100) if total else 0
            update(status="uploading", progress=max(0, min(100, percent)),
                   message=f"Uploading to {cabinet['name']}: {percent}%")

        update(status="uploading", message=f"Connecting to {cabinet['name']}", progress=0)
        dimm.send(data, disable_crc_check=bool(options().get("disable_crc", False)),
                  progress_callback=progress)
        update(status="rebooting", message="Upload complete; rebooting cabinet", progress=100)
        dimm.reboot()
        update(status="complete", message=f"{cabinet['name']} is being booted", progress=100)
    except Exception as exc:
        LOG.exception("NetDIMM load failed for %s", cabinet.get("name", "cabinet"))
        update(status="error", message=str(exc))


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
<label class="muted"><input id="favourites" type="checkbox" onchange="filterGames()" style="min-width:auto;flex:0"> Favourites</label>
<label class="muted"><input id="show-disabled" type="checkbox" onchange="filterGames()" style="min-width:auto;flex:0"> Show disabled</label>
<select id="cabinet"><option value="">Choose cabinet…</option></select>
<button id="test-cabinet" type="button">TEST CONNECTION</button>
</div>
<div class="muted" id="summary">Loading game list…</div>
<div id="job" class="job"></div>
</section>
<div class="grid" id="games"></div>
</main>
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
 filterGames();
}
function filterGames(){
 const q=document.getElementById('search').value.toLowerCase(),s=document.getElementById('system').value,g=document.getElementById('genre').value;
 const o=document.getElementById('orientation').value,c=document.getElementById('controls').value;
 const favourites=document.getElementById('favourites').checked,showDisabled=document.getElementById('show-disabled').checked;
 const shown=games.filter(x=>(showDisabled||x.enabled)&&(!favourites||x.favourite)&&(!q||(x.name+' '+x.filename+' '+x.manufacturer).toLowerCase().includes(q))&&(!s||x.system===s)&&(!g||x.genre===g)&&(!o||x.orientation===o)&&(!c||x.controls===c));
 document.getElementById('summary').textContent=String(shown.length)+' of '+String(games.length)+' games';
 document.getElementById('games').innerHTML=shown.map(x=>{
  const art=x.image?'<img loading="lazy" src="/art/'+encodeURIComponent(x.image)+'" onerror="this.remove()">':'NAOMI';
  const video=x.video?'<video class="preview" controls preload="none" playsinline src="/video/'+encodeURIComponent(x.video)+'"></video>':'';
  const fav=x.favourite?' ★':'';
  const disabled=x.enabled?'':' · DISABLED';
  const button=x.enabled?'<button data-rom="'+encodeURIComponent(x.filename)+'" '+(cabinets.length?'':'disabled')+'>LOAD GAME</button>':'<button disabled>DISABLED IN CATALOGUE</button>';
  return '<article class="card"><div class="art">'+art+'</div>'+video+'<div class="info"><div class="name">'+esc(x.name)+fav+'</div><div class="meta">'+esc(x.system)+' · '+esc(x.year)+' · '+esc(x.genre)+'<br>'+esc(x.orientation)+' · '+esc(x.controls)+disabled+'</div>'+button+'</div></article>';
 }).join('');
 document.querySelectorAll('[data-rom]').forEach(button=>button.addEventListener('click',()=>launchGame(button.dataset.rom)));
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
async function launchGame(encoded){
 const filename=decodeURIComponent(encoded);
 const cabinetId=document.getElementById('cabinet').value;
 if(!cabinetId){document.getElementById('job').textContent='Choose a cabinet first.';return}
 const r=await fetch('/api/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:filename,cabinet_id:cabinetId})});
 const result=await r.json();document.getElementById('job').textContent=result.message||result.error||'Request submitted';
 if(result.job_id) watchJob(result.job_id);
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
    try:
        supervisor_api("POST", f"services/switch/turn_{action}", {"entity_id": entity})
        return jsonify(ok=True, message=f"{selected['name']} power {action} command sent.",
                       state=cabinet_power_state(selected))
    except Exception as exc:
        LOG.warning("Power %s failed for %s: %s", action, selected["name"], exc)
        return jsonify(ok=False, error=str(exc)), 502


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
    }
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
                        fieldnames = reader.fieldnames
                    rows = [{key: (row.get(key) or "") for key in fieldnames}
                            for row in reader]
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
