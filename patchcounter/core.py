import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
PATTERN = re.compile(r'(?i)\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL)\b')

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def db_connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=15000')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY, ts TEXT NOT NULL, level TEXT NOT NULL,
      source TEXT NOT NULL, message TEXT NOT NULL, fingerprint TEXT NOT NULL,
      source_file TEXT, source_line INTEGER,
      UNIQUE(source_file, source_line)
    );
    CREATE INDEX IF NOT EXISTS idx_events_fingerprint ON events(fingerprint);
    CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
    CREATE TABLE IF NOT EXISTS patches (
      id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL, commit_sha TEXT,
      note TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'applied',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS projects (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
      root TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS log_sources (
      id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
      directory TEXT NOT NULL, pattern TEXT NOT NULL DEFAULT '*.log',
      recursive INTEGER NOT NULL DEFAULT 1,
      enabled INTEGER NOT NULL DEFAULT 1,
      UNIQUE(project_id, directory, pattern)
    );
    CREATE TABLE IF NOT EXISTS source_cursors (
      source_id INTEGER NOT NULL, file_path TEXT NOT NULL,
      file_size INTEGER NOT NULL, file_mtime_ns INTEGER NOT NULL,
      line_count INTEGER NOT NULL, PRIMARY KEY(source_id,file_path)
    );
    ''')
    columns = {r['name'] for r in db.execute('PRAGMA table_info(events)')}
    if 'project_id' not in columns:
        db.execute('ALTER TABLE events ADD COLUMN project_id INTEGER')
    db.commit()
    return db

def parse_line(line):
    raw = line.strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            msg = str(obj.get('message') or obj.get('msg') or raw)
            level = str(obj.get('level') or 'INFO').upper()
            return {'ts': str(obj.get('timestamp') or obj.get('ts') or utcnow()),
                    'level': level if level in LEVELS else 'INFO',
                    'source': str(obj.get('module') or obj.get('logger') or 'unknown'),
                    'message': msg}
    except (ValueError, TypeError):
        pass
    match = PATTERN.search(raw)
    level = match.group(1).upper() if match else 'INFO'
    if level == 'WARN':
        level = 'WARNING'
    return {'ts': utcnow(), 'level': level, 'source': 'text-log', 'message': raw}

def fingerprint(source, message):
    normalized = re.sub(r'\b[0-9a-f]{8}-[0-9a-f-]{27,}\b', '<uuid>', message, flags=re.I)
    normalized = re.sub(r'\b\d+\b', '<n>', normalized)
    return hashlib.sha256((source + '|' + normalized).encode()).hexdigest()[:16]

def import_file(db, filename, project_id=None):
    filename = Path(filename).resolve()
    if not filename.is_file():
        raise FileNotFoundError(filename)
    count = 0
    with filename.open('r', encoding='utf-8', errors='replace') as handle, db:
        for line_number, line in enumerate(handle, 1):
            event = parse_line(line)
            if not event:
                continue
            event['fingerprint'] = fingerprint(event['source'], event['message'])
            cur = db.execute('''INSERT OR IGNORE INTO events
                (ts,level,source,message,fingerprint,source_file,source_line,project_id)
                VALUES (:ts,:level,:source,:message,:fingerprint,:source_file,:source_line,:project_id)''',
                {**event, 'source_file': str(filename), 'source_line': line_number, 'project_id': project_id})
            count += cur.rowcount
            if project_id is not None and not cur.rowcount:
                db.execute('UPDATE events SET project_id=COALESCE(project_id,?) WHERE source_file=? AND source_line=?',
                           (project_id, str(filename), line_number))
    return count

def get_events(db, level=None, limit=100, project_id=None):
    limit = min(max(int(limit), 1), 500)
    where, args = [], []
    if level:
        where.append('level=?'); args.append(level.upper())
    if project_id is not None:
        where.append('project_id=?'); args.append(project_id)
    sql = 'SELECT * FROM events'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    return [dict(r) for r in db.execute(sql + ' ORDER BY id DESC LIMIT ?', (*args, limit))]

def get_groups(db, project_id=None):
    clause = ' AND project_id=?' if project_id is not None else ''
    args = (project_id,) if project_id is not None else ()
    return [dict(r) for r in db.execute('''SELECT fingerprint, source, level, COUNT(*) AS occurrences,
        MAX(ts) AS last_seen, MAX(message) AS example FROM events
        WHERE level IN ('ERROR','CRITICAL','WARNING')''' + clause +
        ' GROUP BY fingerprint,source,level ORDER BY occurrences DESC LIMIT 200', args)]

def add_patch(db, fingerprint_value, note, commit_sha=None):
    if not fingerprint_value.strip() or not note.strip():
        raise ValueError('fingerprint and note are required')
    with db:
        cur = db.execute('INSERT INTO patches (fingerprint,commit_sha,note,created_at) VALUES (?,?,?,?)',
                         (fingerprint_value, commit_sha, note, utcnow()))
    return cur.lastrowid

def list_projects(db):
    projects = [dict(r) for r in db.execute('SELECT * FROM projects ORDER BY name')]
    for p in projects:
        p['enabled'] = bool(p['enabled'])
        p['sources'] = [dict(r) for r in db.execute(
            'SELECT * FROM log_sources WHERE project_id=? ORDER BY id', (p['id'],))]
    return projects

def create_project(db, name, root):
    name = name.strip()
    directory = Path(root).expanduser().resolve()
    if not name or not directory.is_dir():
        raise ValueError('Name required and project directory must exist')
    with db:
        return db.execute('INSERT INTO projects(name,root,created_at) VALUES(?,?,?)',
                          (name, str(directory), utcnow())).lastrowid

def update_project(db, project_id, name, root, enabled):
    directory = Path(root).expanduser().resolve()
    if not name.strip() or not directory.is_dir():
        raise ValueError('Name required and project directory must exist')
    with db:
        cur = db.execute('UPDATE projects SET name=?,root=?,enabled=? WHERE id=?',
                         (name.strip(), str(directory), int(enabled), project_id))
    return bool(cur.rowcount)

def delete_project(db, project_id):
    with db:
        db.execute('DELETE FROM source_cursors WHERE source_id IN (SELECT id FROM log_sources WHERE project_id=?)', (project_id,))
        db.execute('DELETE FROM log_sources WHERE project_id=?', (project_id,))
        cur = db.execute('DELETE FROM projects WHERE id=?', (project_id,))
    return bool(cur.rowcount)

def add_source(db, project_id, directory, pattern='*.log', recursive=True):
    path = Path(directory).expanduser().resolve()
    if not path.is_dir():
        raise ValueError('Log directory must exist')
    if not pattern or '/' in pattern or '\\' in pattern or pattern in ('.','..'):
        raise ValueError('Invalid filename pattern')
    if not db.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
        raise ValueError('Unknown project')
    with db:
        return db.execute('INSERT INTO log_sources(project_id,directory,pattern,recursive) VALUES(?,?,?,?)',
                          (project_id,str(path),pattern,int(recursive))).lastrowid

def update_source(db, source_id, directory, pattern, recursive, enabled):
    path = Path(directory).expanduser().resolve()
    if not path.is_dir() or not pattern or '/' in pattern or '\\' in pattern:
        raise ValueError('Invalid source configuration')
    with db:
        cur = db.execute('UPDATE log_sources SET directory=?,pattern=?,recursive=?,enabled=? WHERE id=?',
                         (str(path),pattern,int(recursive),int(enabled),source_id))
        db.execute('DELETE FROM source_cursors WHERE source_id=?', (source_id,))
    return bool(cur.rowcount)

def delete_source(db, source_id):
    with db:
        db.execute('DELETE FROM source_cursors WHERE source_id=?', (source_id,))
        cur = db.execute('DELETE FROM log_sources WHERE id=?', (source_id,))
    return bool(cur.rowcount)

def scan_sources(db, max_files=2000):
    """Poll enabled sources. Re-import changed files; duplicate lines are ignored."""
    added, errors, seen = 0, [], 0
    sources = db.execute('''SELECT s.*,p.enabled AS project_enabled FROM log_sources s
                            JOIN projects p ON p.id=s.project_id WHERE s.enabled=1 AND p.enabled=1''').fetchall()
    for source in sources:
        folder = Path(source['directory'])
        try:
            paths = folder.rglob(source['pattern']) if source['recursive'] else folder.glob(source['pattern'])
            for path in paths:
                if seen >= max_files:
                    return {'imported':added,'scanned':seen,'errors':errors,'limited':True}
                if not path.is_file() or path.is_symlink():
                    continue
                seen += 1
                stat = path.stat()
                resolved = str(path.resolve())
                previous = db.execute('SELECT file_size,file_mtime_ns FROM source_cursors WHERE source_id=? AND file_path=?',
                                      (source['id'],resolved)).fetchone()
                if previous and previous['file_size']==stat.st_size and previous['file_mtime_ns']==stat.st_mtime_ns:
                    continue
                added += import_file(db,path,source['project_id'])
                with db:
                    db.execute('''INSERT INTO source_cursors(source_id,file_path,file_size,file_mtime_ns,line_count)
                        VALUES(?,?,?,?,0) ON CONFLICT(source_id,file_path) DO UPDATE SET
                        file_size=excluded.file_size,file_mtime_ns=excluded.file_mtime_ns''',
                        (source['id'],resolved,stat.st_size,stat.st_mtime_ns))
        except (OSError, UnicodeError) as exc:
            errors.append({'source_id':source['id'],'error':str(exc)})
    return {'imported':added,'scanned':seen,'errors':errors,'limited':False}

def list_log_files(db, project_id=None):
    conditions = ['e.source_file IS NOT NULL']
    args = []
    if project_id is not None:
        conditions.append('e.project_id=?')
        args.append(project_id)
    sql = """
        SELECT e.source_file AS path, e.project_id, p.name AS project_name,
               COUNT(*) AS events, SUM(CASE WHEN e.level IN ('ERROR','CRITICAL') THEN 1 ELSE 0 END) AS errors,
               MAX(e.id) AS latest_event_id
        FROM events e LEFT JOIN projects p ON p.id=e.project_id
        WHERE """ + ' AND '.join(conditions) + """
        GROUP BY e.source_file,e.project_id ORDER BY latest_event_id DESC LIMIT 500
    """
    return [dict(r) for r in db.execute(sql, args)]

def file_events(db, path, project_id=None, level=None, search=None, limit=300):
    limit = min(max(int(limit), 1), 500)
    conditions = ['source_file=?']
    args = [path]
    if project_id is not None:
        conditions.append('project_id=?')
        args.append(project_id)
    if level:
        conditions.append('level=?')
        args.append(level.upper())
    if search:
        conditions.append('instr(lower(message),lower(?))>0')
        args.append(search)
    return [dict(r) for r in db.execute(
        'SELECT * FROM events WHERE ' + ' AND '.join(conditions) + ' ORDER BY source_line DESC,id DESC LIMIT ?',
        (*args,limit))]

def verified_log_path(db, path):
    """Only allow files already indexed by PatchCounter, never arbitrary API paths."""
    candidate = Path(path).resolve()
    if not db.execute('SELECT 1 FROM events WHERE source_file=? LIMIT 1', (str(candidate),)).fetchone():
        raise ValueError('File is not indexed by PatchCounter')
    if not candidate.is_file() or candidate.is_symlink():
        raise FileNotFoundError(str(candidate))
    return candidate

def read_raw_lines(db, path, start=1, limit=200):
    from itertools import islice
    if not 1 <= start <= 10_000_000 or not 1 <= limit <= 500:
        raise ValueError('Invalid line range')
    candidate = verified_log_path(db, path)
    with candidate.open('r', encoding='utf-8-sig', errors='replace') as handle:
        lines = [{'number':i, 'text':line.rstrip(chr(13)+chr(10))[:10000]}
                 for i,line in enumerate(islice(handle, start-1, start-1+limit),start)]
    return {'path':str(candidate),'start':start,'lines':lines,'has_more':len(lines)==limit}
