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
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
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
    ''')
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

def import_file(db, filename):
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
                (ts,level,source,message,fingerprint,source_file,source_line)
                VALUES (:ts,:level,:source,:message,:fingerprint,:source_file,:source_line)''',
                {**event, 'source_file': str(filename), 'source_line': line_number})
            count += cur.rowcount
    return count

def get_events(db, level=None, limit=100):
    limit = min(max(int(limit), 1), 500)
    if level:
        rows = db.execute('SELECT * FROM events WHERE level=? ORDER BY id DESC LIMIT ?', (level.upper(), limit))
    else:
        rows = db.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,))
    return [dict(row) for row in rows]

def get_groups(db):
    rows = db.execute('''SELECT fingerprint, source, level, COUNT(*) AS occurrences,
        MAX(ts) AS last_seen, MAX(message) AS example FROM events
        WHERE level IN ('ERROR','CRITICAL','WARNING')
        GROUP BY fingerprint,source,level ORDER BY occurrences DESC LIMIT 200''')
    return [dict(row) for row in rows]

def add_patch(db, fingerprint_value, note, commit_sha=None):
    if not fingerprint_value.strip() or not note.strip():
        raise ValueError('fingerprint and note are required')
    with db:
        cur = db.execute('INSERT INTO patches (fingerprint,commit_sha,note,created_at) VALUES (?,?,?,?)',
                         (fingerprint_value, commit_sha, note, utcnow()))
    return cur.lastrowid
