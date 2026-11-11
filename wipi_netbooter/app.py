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
    for index, line in enumerate(options().get("cabinets", [])):
        fields = [part.strip() for part in str(line).split("|")]
        if len(fields) < 2 or not fields[0] or not fields[1]:
            continue
        name, address = fields[0], fields[1]
        try:
            ipaddress.ip_address(address)
        except ValueError:
            continue
        target = fields[2].lower() if len(fields) > 2 and fields[2] else "naomi"
        firmware = fields[3] if len(fields) > 3 and fields[3] else "4.01"
        if target not in {"naomi", "chihiro", "triforce"}:
            continue
        result.append({"id": str(index), "name": name, "ip": address,
                       "target": target, "firmware": firmware})
    return result


def catalogue_path(folder: Path) -> Path | None:
    for candidate in (folder / "romsinfo.csv", folder / "csv" / "romsinfo.csv"):
        if candidate.is_file():
            return candidate
    return None


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
        for path in folder.iterdir():
            if not path.is_file() or not any(path.name.lower().endswith(s) for s in ROM_SUFFIXES):
                continue
            row = metadata.get(path.name, {})
            games.append({
                "filename": path.name,
                "name": row.get("description") or row.get("romname") or path.name,
                "system": row.get("system", "Unknown system"),
                "manufacturer": row.get("manufacturer", ""),
                "year": row.get("year", ""),
                "genre": row.get("genre", ""),
                "orientation": row.get("orientation", ""),
                "controls": row.get("controls", ""),
                "image": row.get("image", ""),
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
    path = folder / filename
    if not path.is_file() or not any(path.name.lower().endswith(s) for s in ROM_SUFFIXES):
        raise FileNotFoundError("ROM file is not available.")
    return path


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
                       log=lambda message: update(message=str(message)))

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
.art img{width:100%;height:100%;object-fit:contain}.info{padding:13px}.name{font-weight:bold;font-size:16px}.meta{color:#a9bdc9;font-size:12px;margin:6px 0 12px}
.card button{width:100%;padding:9px}.panel{background:#1b2a35;border:1px solid #344b5a;border-radius:10px;padding:16px;margin:0 0 18px}
.muted{color:#a9bdc9}.good{color:#8bd5a5}.bad{color:#ffaaa2}.job{margin-top:12px;line-height:1.5}
@media(max-width:520px){.top{padding:18px}h1{font-size:21px}}
</style></head><body>
<header class="top"><h1>WiPi NETBOOTER</h1><div class="tag">SEGA NAOMI · NETDIMM MANAGER</div></header>
<main>
<section class="panel">
<div class="toolbar">
<input id="search" placeholder="Search games..." oninput="filterGames()">
<select id="system" onchange="filterGames()"><option value="">All systems</option></select>
<select id="genre" onchange="filterGames()"><option value="">All genres</option></select>
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
 for(const pair of [['system',systems],['genre',genres]]) for(const v of pair[1]){const o=document.createElement('option');o.value=v;o.textContent=v;document.getElementById(pair[0]).appendChild(o)}
 const c=await fetch('/api/cabinets'); cabinets=(await c.json()).cabinets||[];
 filterGames();
}
function filterGames(){
 const q=document.getElementById('search').value.toLowerCase(),s=document.getElementById('system').value,g=document.getElementById('genre').value;
 const shown=games.filter(x=>(!q||(x.name+' '+x.filename+' '+x.manufacturer).toLowerCase().includes(q))&&(!s||x.system===s)&&(!g||x.genre===g));
 document.getElementById('summary').textContent=String(shown.length)+' of '+String(games.length)+' games';
 document.getElementById('games').innerHTML=shown.map(x=>'<article class="card"><div class="art">'+(x.image?'<img loading="lazy" src="/art/'+encodeURIComponent(x.image)+'" onerror="this.remove()">':'NAOMI')+'</div><div class="info"><div class="name">'+esc(x.name)+'</div><div class="meta">'+esc(x.system)+' · '+esc(x.year)+' · '+esc(x.genre)+'</div><button '+(cabinets.length?'':'disabled')+' onclick="chooseCabinet(\\''+encodeURIComponent(x.filename)+'\\')">LOAD GAME</button></div></article>').join('');
}
async function chooseCabinet(encoded){
 const filename=decodeURIComponent(encoded);
 if(!cabinets.length){document.getElementById('job').textContent='No cabinets configured. Add entries in the app Configuration tab.';return}
 const choice=prompt('Enter cabinet number:\\n'+cabinets.map((c,i)=>String(i+1)+'. '+c.name+' ('+c.ip+')').join('\\n'),'1');
 const index=Number(choice)-1;if(!Number.isInteger(index)||!cabinets[index])return;
 const r=await fetch('/api/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:filename,cabinet_id:cabinets[index].id})});
 const d=await r.json();document.getElementById('job').textContent=d.message||d.error||'Request submitted';
 if(d.job_id) watchJob(d.job_id);
}
async function watchJob(id){
 const panel=document.getElementById('job');
 for(let i=0;i<360;i++){await new Promise(r=>setTimeout(r,1000));const d=await (await fetch('/api/jobs/'+id)).json();panel.textContent=d.status+': '+(d.message||'')+' '+(d.progress??0)+'%';if(['complete','error'].includes(d.status)){panel.className='job '+(d.status==='complete'?'good':'bad');return}}
}
init().catch(e=>document.getElementById('summary').textContent='Could not load game list: '+e);
</script></body></html>"""


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.get("/api/games")
def api_games():
    try:
        games, error = discover_games()
        return jsonify(games=games, error=error, rom_path=str(rom_folder()))
    except (OSError, ValueError) as exc:
        return jsonify(games=[], error=str(exc), rom_path=None)


@app.get("/api/cabinets")
def api_cabinets():
    return jsonify(cabinets=cabinets())


@app.get("/art/<path:filename>")
def artwork(filename: str):
    if Path(filename).name != filename:
        abort(404)
    try:
        folder = rom_folder()
    except ValueError:
        abort(404)
    for subfolder in ("images", "artwork", "img"):
        candidate = folder / subfolder
        if (candidate / filename).is_file():
            return send_from_directory(candidate, filename)
    abort(404)


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
    games, error = discover_games()
    return jsonify(ok=error is None, game_count=len(games), error=error,
                   cabinet_count=len(cabinets()), netdimm_library=NetDimm is not None)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8256")), threaded=True)
