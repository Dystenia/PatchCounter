import asyncio
import os
import sqlite3
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .core import (
    db_connect, import_file, get_events, get_groups, add_patch,
    list_projects, create_project, update_project, delete_project,
    add_source, update_source, delete_source, scan_sources, list_log_files, file_events, read_raw_lines, verified_log_path,
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
<h3>Logdateien</h3><p class="muted">Klicke eine Datei an, um ihre importierten Meldungen zu lesen.</p>
<div id="files"></div>
<div id="filepanel" class="card" style="display:none">
<h3 id="filename">Datei</h3><p class="muted" id="filepath"></p>
<div class="row"><select id="filelevel" onchange="loadFileEvents()"><option value="">Alle Level</option><option>ERROR</option><option>WARNING</option><option>CRITICAL</option><option>INFO</option><option>DEBUG</option></select>
<input id="filesearch" placeholder="Meldungen durchsuchen" oninput="loadFileEvents()">
<button onclick="showRaw()">Rohlog anzeigen</button><button onclick="openEditor()">Im Editor öffnen</button><button onclick="closeFile()">Schließen</button></div>
<table><thead><tr><th>Zeile</th><th>Zeit</th><th>Level</th><th>Meldung (anklicken)</th></tr></thead><tbody id="fileevents"></tbody></table>
<div id="rawpanel" class="card" style="display:none"><h4>Originaldatei (schreibgeschützt)</h4>
<div class="row"><button onclick="rawPage(-1)">Vorherige 200</button><span id="rawrange"></span><button onclick="rawPage(1)">Nächste 200</button>
<input id="rawsearch" placeholder="Auf dieser Seite suchen" oninput="renderRaw()"></div>
<pre id="rawcontent" style="max-height:500px;overflow:auto;white-space:pre-wrap"></pre></div>
<div id="detail" class="card" style="display:none"><h4>Meldungsdetails</h4><pre id="detailtext"></pre></div>
</div>
<h3>Fehlergruppen</h3><table><thead><tr><th>Modul</th><th>Level</th><th>Anzahl</th><th>Beispiel</th></tr></thead><tbody id="groups"></tbody></table>
<h3>Letzte Ereignisse</h3><table><thead><tr><th>Zeit</th><th>Level</th><th>Quelle</th><th>Meldung</th></tr></thead><tbody id="events"></tbody></table></section>
<section class="panel"><h2>Einzeldatei importieren</h2><div class="row"><input id="manual" placeholder="Vollständiger Pfad zur Logdatei">
<button onclick="manualImport()">Importieren</button></div></section>
<script>
const $=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const req=async(url,method='GET',body)=>{const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw Error(j.detail||r.statusText);return j};
const msg=x=>$('status').textContent=x;
async function act(fn){try{await fn();msg('Gespeichert.');await loadProjects();await refreshLogs();await refreshFiles()}catch(e){msg('Fehler: '+e.message)}}
async function createProject(){await act(()=>req('/api/projects','POST',{name:$('pname').value,root:$('proot').value}));$('pname').value=''}
async function editProject(p){const name=prompt('Projektname',p.name);if(name===null)return;const root=prompt('Projektverzeichnis',p.root);if(root===null)return;await act(()=>req('/api/projects/'+p.id,'PUT',{name,root,enabled:p.enabled}))}
async function toggleProject(p){await act(()=>req('/api/projects/'+p.id,'PUT',{name:p.name,root:p.root,enabled:!p.enabled}))}
async function removeProject(p){if(confirm('Projekt '+p.name+' entfernen? Bereits importierte Logs bleiben erhalten.'))await act(()=>req('/api/projects/'+p.id,'DELETE'))}
async function addSourceUI(p){const directory=prompt('Logverzeichnis',p.root);if(directory===null)return;const pattern=prompt('Dateimuster, z.B. *.log oder *.jsonl','*.log');if(pattern===null)return;await act(()=>req('/api/projects/'+p.id+'/sources','POST',{directory,pattern,recursive:true}))}
async function editSource(s){const directory=prompt('Logverzeichnis',s.directory);if(directory===null)return;const pattern=prompt('Dateimuster',s.pattern);if(pattern===null)return;const recursive=confirm('Unterordner einbeziehen? OK = Ja, Abbrechen = Nein');await act(()=>req('/api/sources/'+s.id,'PUT',{directory,pattern,recursive,enabled:!!s.enabled}))}
async function toggleSource(s){await act(()=>req('/api/sources/'+s.id,'PUT',{directory:s.directory,pattern:s.pattern,recursive:!!s.recursive,enabled:!s.enabled}))}
async function removeSource(s){if(confirm('Logquelle entfernen?'))await act(()=>req('/api/sources/'+s.id,'DELETE'))}
let projects=[];let selectedFile=null;let fileRows=[];
function closeFile(){selectedFile=null;$('filepanel').style.display='none';$('rawpanel').style.display='none'}
let rawStart=1,rawLines=[],rawMore=false;
async function showRaw(){rawStart=1;$('rawpanel').style.display='block';await loadRaw()}
async function rawPage(direction){rawStart=Math.max(1,rawStart+direction*200);await loadRaw()}
function renderRaw(){const term=$('rawsearch').value.toLowerCase();$('rawcontent').textContent=rawLines.filter(x=>!term||x.text.toLowerCase().includes(term)).map(x=>String(x.number).padStart(6,' ')+' | '+x.text).join(String.fromCharCode(10))}
async function loadRaw(){if(!selectedFile)return;try{const q=new URLSearchParams({path:selectedFile.path,start:rawStart,limit:200});const data=await req('/api/raw-log?'+q);rawLines=data.lines;rawMore=data.has_more;$('rawrange').textContent='Ab Zeile '+rawStart+(rawMore?' · weitere Zeilen möglich':' · Dateiende');renderRaw()}catch(e){msg('Rohlog: '+e.message)}}
async function openEditor(){if(!selectedFile)return;if(!confirm('Originaldatei im Windows-Standardeditor öffnen?'))return;try{await req('/api/open-editor','POST',{path:selectedFile.path});msg('Editor-Start angefordert.')}catch(e){msg(e.message)}}

function showDetail(id){const e=fileRows.find(x=>x.id===id);if(!e)return;$('detail').style.display='block';$('detailtext').textContent=['Datei: '+e.source_file,'Zeile: '+e.source_line,'Zeit: '+e.ts,'Level: '+e.level,'Quelle: '+e.source,'Fingerprint: '+e.fingerprint,'',e.message].join(String.fromCharCode(10))}
async function openFile(path,projectId){selectedFile={path,projectId};$('filename').textContent=path.replaceAll(String.fromCharCode(92),'/').split('/').pop();$('filepath').textContent=path;$('filepanel').style.display='block';$('detail').style.display='none';await loadFileEvents();if($('rawpanel').style.display!=='none')await loadRaw()}
async function loadFileEvents(){if(!selectedFile)return;try{
const q=new URLSearchParams({path:selectedFile.path,limit:'300'});
if(selectedFile.projectId!==null)q.set('project_id',selectedFile.projectId);
if($('filelevel').value)q.set('level',$('filelevel').value);
if($('filesearch').value)q.set('search',$('filesearch').value);
fileRows=await req('/api/file-events?'+q);
const target=$('fileevents');target.replaceChildren();
for(const e of fileRows){const tr=document.createElement('tr');
for(const value of [e.source_line,e.ts,e.level,e.message]){const td=document.createElement('td');td.textContent=value;tr.append(td)}
tr.style.cursor='pointer';tr.onclick=()=>showDetail(e.id);target.append(tr)}
}catch(e){msg(e.message)}}
async function refreshFiles(){try{const q=$('filter').value?'?project_id='+encodeURIComponent($('filter').value):'';
const files=await req('/api/files'+q);const target=$('files');target.replaceChildren();
for(const f of files){const b=document.createElement('button');b.style.margin='4px';b.textContent=f.path.replaceAll(String.fromCharCode(92),'/').split('/').pop()+' · '+f.events+' Meldungen · '+f.errors+' Fehler';b.title=f.path;b.onclick=()=>openFile(f.path,f.project_id);target.append(b)}
if(!files.length)target.textContent='Noch keine importierten Logdateien.';
}catch(e){msg(e.message)}}

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
loadProjects().then(async()=>{await refreshLogs();await refreshFiles()}).catch(e=>msg(e.message));
setInterval(async()=>{await refreshLogs();await refreshFiles();if(selectedFile)await loadFileEvents()},5000);
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

@app.get("/api/files")
def files(project_id: int | None = None):
    with db_connect(DB_PATH) as db:
        return list_log_files(db, project_id)

@app.get("/api/file-events")
def file_messages(path: str, project_id: int | None = None,
                  level: str | None = None, search: str | None = None, limit: int = 300):
    with db_connect(DB_PATH) as db:
        return file_events(db, path, project_id, level, search, limit)

class FileAction(BaseModel):
    path: str

@app.get("/api/raw-log")
def raw_log(path: str, start: int = 1, limit: int = 200):
    try:
        with db_connect(DB_PATH) as db:
            return read_raw_lines(db, path, start, limit)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc

@app.post("/api/open-editor")
def open_editor(req: FileAction):
    if sys.platform != "win32":
        raise HTTPException(501, "External editor is currently supported on Windows only")
    try:
        with db_connect(DB_PATH) as db:
            path = verified_log_path(db, req.path)
        os.startfile(str(path), "open")
        return {"ok": True}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc
