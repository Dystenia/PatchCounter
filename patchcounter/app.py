import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .core import (
    db_connect, import_file, get_events, get_groups, add_patch,
    list_projects, create_project, update_project, delete_project,
    add_source, update_source, delete_source, scan_sources,
)

DB_PATH = Path(os.environ.get("PATCHCOUNTER_DB", str(Path.home() / ".patchcounter" / "events.db")))
POLL_SECONDS = 5

async def poll_loop():
    while True:
        try:
            await asyncio.to_thread(poll_once)
        except Exception as exc:
            print(f"[PatchCounter] scan failed: {exc}", flush=True)
        await asyncio.sleep(POLL_SECONDS)

def poll_once():
    with db_connect(DB_PATH) as db:
        return scan_sources(db)

@asynccontextmanager
async def lifespan(app):
    with db_connect(DB_PATH):
        pass
    task = asyncio.create_task(poll_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

app = FastAPI(title="PatchCounter", version="0.2.0", lifespan=lifespan)

class ImportRequest(BaseModel):
    path: str

class PatchRequest(BaseModel):
    fingerprint: str
    note: str
    commit_sha: str | None = None

class ProjectRequest(BaseModel):
    name: str
    root: str
    enabled: bool = False

class SourceRequest(BaseModel):
    directory: str
    pattern: str = "*.log"
    recursive: bool = True
    enabled: bool = True

def safe_write(action):
    try:
        return action()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc

@app.get("/", response_class=HTMLResponse)
def home():
    return """<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PatchCounter</title>
<style>
body{font:15px system-ui;background:#101723;color:#e7eef8;max-width:1250px;margin:24px auto;padding:0 16px}
h1{margin-bottom:4px}small,.muted{color:#9aa9bd}.panel{background:#1b2534;border:1px solid #364457;border-radius:10px;padding:16px;margin:16px 0}
input,button,select{padding:9px;border-radius:6px;border:1px solid #526179;background:#101723;color:#e7eef8}
button{cursor:pointer;background:#29486c}button:hover{background:#365d87}button.danger{background:#653038}
label{display:inline-block;margin:4px 8px 4px 0}input[type=checkbox]{width:auto}
table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #354052;text-align:left;word-break:break-word}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.row input{flex:1;min-width:160px}
.card{border:1px solid #354052;border-radius:8px;padding:12px;margin:10px 0}
pre{white-space:pre-wrap} .status{min-height:20px}
</style>
<h1>🛠 PatchCounter <small>v0.2 · Lokal</small></h1>
<p class="muted">Universelle Projektverwaltung und automatische Log-Überwachung · Nur auf 127.0.0.1 betreiben</p>
<section class="panel"><h2>Projekte</h2>
<div class="row"><input id="pname" placeholder="Projektname"><input id="proot" placeholder="Projektverzeichnis, z.B. C:\\Projekte\\App">
<button onclick="createProject()">Projekt hinzufügen</button></div>
<p id="status" class="status"></p><div id="projects"></div></section>
<section class="panel"><h2>Log-Ereignisse</h2>
<div class="row"><select id="filter" onchange="refreshLogs()"><option value="">Alle Projekte</option></select>
<button onclick="scanNow()">Jetzt scannen</button></div>
<h3>Fehlergruppen</h3><table><thead><tr><th>Modul</th><th>Level</th><th>Anzahl</th><th>Beispiel</th></tr></thead><tbody id="groups"></tbody></table>
<h3>Letzte Ereignisse</h3><table><thead><tr><th>Zeit</th><th>Level</th><th>Quelle</th><th>Meldung</th></tr></thead><tbody id="events"></tbody></table></section>
<section class="panel"><h2>Einzeldatei importieren</h2><div class="row"><input id="manual" placeholder="Vollständiger Pfad zur Logdatei">
<button onclick="manualImport()">Importieren</button></div></section>
<script>
const $=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const req=async(url,method='GET',body)=>{const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw Error(j.detail||r.statusText);return j};
const msg=x=>$('status').textContent=x;
async function act(fn){try{await fn();msg('Gespeichert.');await loadProjects();await refreshLogs()}catch(e){msg('Fehler: '+e.message)}}
async function createProject(){await act(()=>req('/api/projects','POST',{name:$('pname').value,root:$('proot').value}));$('pname').value=''}
async function editProject(p){const name=prompt('Projektname',p.name);if(name===null)return;const root=prompt('Projektverzeichnis',p.root);if(root===null)return;await act(()=>req('/api/projects/'+p.id,'PUT',{name,root,enabled:p.enabled}))}
async function toggleProject(p){await act(()=>req('/api/projects/'+p.id,'PUT',{name:p.name,root:p.root,enabled:!p.enabled}))}
async function removeProject(p){if(confirm('Projekt '+p.name+' entfernen? Bereits importierte Logs bleiben erhalten.'))await act(()=>req('/api/projects/'+p.id,'DELETE'))}
async function addSourceUI(p){const directory=prompt('Logverzeichnis',p.root);if(directory===null)return;const pattern=prompt('Dateimuster, z.B. *.log oder *.jsonl','*.log');if(pattern===null)return;await act(()=>req('/api/projects/'+p.id+'/sources','POST',{directory,pattern,recursive:true}))}
async function editSource(s){const directory=prompt('Logverzeichnis',s.directory);if(directory===null)return;const pattern=prompt('Dateimuster',s.pattern);if(pattern===null)return;const recursive=confirm('Unterordner einbeziehen? OK = Ja, Abbrechen = Nein');await act(()=>req('/api/sources/'+s.id,'PUT',{directory,pattern,recursive,enabled:!!s.enabled}))}
async function toggleSource(s){await act(()=>req('/api/sources/'+s.id,'PUT',{directory:s.directory,pattern:s.pattern,recursive:!!s.recursive,enabled:!s.enabled}))}
async function removeSource(s){if(confirm('Logquelle entfernen?'))await act(()=>req('/api/sources/'+s.id,'DELETE'))}
let projects=[];
async function loadProjects(){
projects=await req('/api/projects');const selected=$('filter').value;
$('filter').innerHTML='<option value="">Alle Projekte</option>'+projects.map(p=>'<option value="'+p.id+'">'+esc(p.name)+'</option>').join('');
$('filter').value=selected;
const target=$('projects');target.replaceChildren();
for(const p of projects){
const box=document.createElement('div');box.className='card';
box.innerHTML='<b>'+esc(p.name)+'</b> <small>'+(p.enabled?'🟢 Überwachung aktiv':'⏸ Pausiert')+'</small><p class="muted">'+esc(p.root)+'</p>';
const buttons=document.createElement('div');buttons.className='row';
function button(label,handler,danger=false){const b=document.createElement('button');b.textContent=label;if(danger)b.className='danger';b.onclick=handler;buttons.append(b)}
button('Bearbeiten',()=>editProject(p));button(p.enabled?'Pausieren':'Aktivieren',()=>toggleProject(p));button('Logquelle hinzufügen',()=>addSourceUI(p));button('Entfernen',()=>removeProject(p),true);
box.append(buttons);
for(const s of p.sources){
const line=document.createElement('div');line.className='row';line.style.marginTop='10px';
const info=document.createElement('span');info.textContent=(s.enabled?'● ':'○ ')+s.directory+' / '+s.pattern+(s.recursive?' (rekursiv)':'');line.append(info);
for(const [label,handler] of [['Bearbeiten',()=>editSource(s)],[s.enabled?'Quelle pausieren':'Quelle aktivieren',()=>toggleSource(s)],['Löschen',()=>removeSource(s)]]){
const b=document.createElement('button');b.textContent=label;b.onclick=handler;line.append(b)}
box.append(line)}
target.append(box)}
}
async function refreshLogs(){try{
const q=$('filter').value?'?project_id='+encodeURIComponent($('filter').value):'';
const [g,e]=await Promise.all([req('/api/groups'+q),req('/api/events'+q)]);
$('groups').innerHTML=g.map(x=>'<tr><td>'+esc(x.source)+'</td><td>'+esc(x.level)+'</td><td>'+x.occurrences+'</td><td>'+esc(x.example)+'</td></tr>').join('');
$('events').innerHTML=e.map(x=>'<tr><td>'+esc(x.ts)+'</td><td>'+esc(x.level)+'</td><td>'+esc(x.source)+'</td><td>'+esc(x.message)+'</td></tr>').join('');
}catch(e){msg(e.message)}}
async function scanNow(){await act(async()=>{const r=await req('/api/scan','POST');msg(r.imported+' Ereignisse importiert')})}
async function manualImport(){await act(()=>req('/api/import','POST',{path:$('manual').value}))}
loadProjects().then(refreshLogs).catch(e=>msg(e.message));
setInterval(refreshLogs,5000);
</script>"""

@app.get("/api/events")
def events(level: str | None = None, limit: int = 100, project_id: int | None = None):
    with db_connect(DB_PATH) as db:
        return get_events(db, level, limit, project_id)

@app.get("/api/groups")
def groups(project_id: int | None = None):
    with db_connect(DB_PATH) as db:
        return get_groups(db, project_id)

@app.post("/api/import")
def import_logs(req: ImportRequest):
    try:
        with db_connect(DB_PATH) as db:
            return {"imported": import_file(db, req.path)}
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/patches")
def create_patch(req: PatchRequest):
    return safe_write(lambda: _create_patch(req))

def _create_patch(req):
    with db_connect(DB_PATH) as db:
        return {"id": add_patch(db, req.fingerprint, req.note, req.commit_sha)}

@app.get("/api/patches")
def patches():
    with db_connect(DB_PATH) as db:
        return [dict(r) for r in db.execute("SELECT * FROM patches ORDER BY id DESC LIMIT 200")]

@app.get("/api/projects")
def projects():
    with db_connect(DB_PATH) as db:
        return list_projects(db)

@app.post("/api/projects", status_code=201)
def project_create(req: ProjectRequest):
    def operation():
        with db_connect(DB_PATH) as db:
            return {"id": create_project(db, req.name, req.root)}
    return safe_write(operation)

@app.put("/api/projects/{project_id}")
def project_update(project_id: int, req: ProjectRequest):
    def operation():
        with db_connect(DB_PATH) as db:
            return update_project(db, project_id, req.name, req.root, req.enabled)
    if not safe_write(operation):
        raise HTTPException(404, "Project not found")
    return {"ok": True}

@app.delete("/api/projects/{project_id}")
def project_delete(project_id: int):
    with db_connect(DB_PATH) as db:
        if not delete_project(db, project_id):
            raise HTTPException(404, "Project not found")
    return {"ok": True}

@app.post("/api/projects/{project_id}/sources", status_code=201)
def source_create(project_id: int, req: SourceRequest):
    def operation():
        with db_connect(DB_PATH) as db:
            return {"id": add_source(db, project_id, req.directory, req.pattern, req.recursive)}
    return safe_write(operation)

@app.put("/api/sources/{source_id}")
def source_update(source_id: int, req: SourceRequest):
    def operation():
        with db_connect(DB_PATH) as db:
            return update_source(db, source_id, req.directory, req.pattern, req.recursive, req.enabled)
    if not safe_write(operation):
        raise HTTPException(404, "Log source not found")
    return {"ok": True}

@app.delete("/api/sources/{source_id}")
def source_delete(source_id: int):
    with db_connect(DB_PATH) as db:
        if not delete_source(db, source_id):
            raise HTTPException(404, "Log source not found")
    return {"ok": True}

@app.post("/api/scan")
def scan():
    return poll_once()
