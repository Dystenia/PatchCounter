import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .core import db_connect, import_file, get_events, get_groups, add_patch

app = FastAPI(title="PatchCounter", version="0.1.0")
DB_PATH = Path(os.environ.get("PATCHCOUNTER_DB", str(Path.home() / ".patchcounter" / "events.db")))

class ImportRequest(BaseModel):
    path: str

class PatchRequest(BaseModel):
    fingerprint: str
    note: str
    commit_sha: str | None = None

@app.get("/", response_class=HTMLResponse)
def home():
    return """<!doctype html><html lang="de"><meta charset="utf-8"><title>PatchCounter</title>
<style>body{font:16px system-ui;background:#101723;color:#e7eef8;max-width:1100px;margin:40px auto;padding:0 18px}
input,button{padding:10px;border-radius:6px}input{width:65%}button{cursor:pointer}table{width:100%;border-collapse:collapse}
td,th{padding:9px;border-bottom:1px solid #354052;text-align:left;word-break:break-word}small{color:#aeb8c8}</style>
<h1>🛠 PatchCounter <small>v0.1 · lokal</small></h1>
<p>Importiere eine vorhandene Logdatei (TXT oder JSON Lines). Keine automatische Änderung an DYSTOPIC.</p>
<input id="path" placeholder="C:\\Pfad\\zu\\engine.log"><button onclick="loadLog()">Importieren</button>
<p id="status"></p><h2>Fehlergruppen</h2><table><thead><tr><th>Modul</th><th>Level</th><th>Anzahl</th><th>Beispiel</th><th>Fingerprint</th></tr></thead><tbody id="groups"></tbody></table>
<h2>Letzte Ereignisse</h2><table><thead><tr><th>Zeit</th><th>Level</th><th>Quelle</th><th>Meldung</th></tr></thead><tbody id="events"></tbody></table>
<script>
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function refresh(){
const [g,e]=await Promise.all([fetch('/api/groups').then(r=>r.json()),fetch('/api/events').then(r=>r.json())]);
document.getElementById('groups').innerHTML=g.map(x=>'<tr><td>'+esc(x.source)+'</td><td>'+esc(x.level)+'</td><td>'+x.occurrences+'</td><td>'+esc(x.example)+'</td><td>'+esc(x.fingerprint)+'</td></tr>').join('');
document.getElementById('events').innerHTML=e.map(x=>'<tr><td>'+esc(x.ts)+'</td><td>'+esc(x.level)+'</td><td>'+esc(x.source)+'</td><td>'+esc(x.message)+'</td></tr>').join('');
}
async function loadLog(){
const r=await fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:document.getElementById('path').value})});
const j=await r.json();document.getElementById('status').textContent=r.ok?j.imported+' neue Ereignisse importiert':JSON.stringify(j);if(r.ok)refresh();
}
refresh();</script></html>"""

@app.get("/api/events")
def events(level: str | None = None, limit: int = 100):
    with db_connect(DB_PATH) as db:
        return get_events(db, level, limit)

@app.get("/api/groups")
def groups():
    with db_connect(DB_PATH) as db:
        return get_groups(db)

@app.post("/api/import")
def import_logs(req: ImportRequest):
    try:
        with db_connect(DB_PATH) as db:
            return {"imported": import_file(db, req.path)}
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/patches")
def create_patch(req: PatchRequest):
    try:
        with db_connect(DB_PATH) as db:
            return {"id": add_patch(db, req.fingerprint, req.note, req.commit_sha)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/patches")
def patches():
    with db_connect(DB_PATH) as db:
        return [dict(r) for r in db.execute("SELECT * FROM patches ORDER BY id DESC LIMIT 200")]
