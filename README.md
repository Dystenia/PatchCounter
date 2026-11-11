# PatchCounter v0.1 — lokaler Windows-MVP

Eigenständige Log-Analyse für DYSTOPIC und andere Python-Projekte. Keine Änderung an DYSTOPIC erforderlich.

## Start unter Windows

1. Repository klonen oder als ZIP herunterladen.
2. `start_windows.bat` ausführen (Python 3.10+ mit `py`-Launcher erforderlich).
3. Im Browser `http://127.0.0.1:8765` öffnen.
4. Vollständigen Pfad zu einer vorhandenen `.log`-/`.txt`-/JSONL-Datei eingeben und importieren.

Alternativ: `pip install -r requirements.txt`, dann `python -m uvicorn patchcounter.app:app --host 127.0.0.1 --port 8765`.

Tests: `python -m unittest discover -s tests -v`

## Grenzen des MVP

- Einfache Textlogs und JSON Lines (`timestamp`/`ts`, `level`, `module`/`logger`, `message`/`msg`). DYSTOPIC-spezifische Multiline-Logs benötigen einen eigenen Parser.
- Gruppiert Warnungen und Fehler anhand normalisierter Nachrichten; das ist eine Heuristik, keine Root-Cause-Analyse.
- Ein erneuter Import derselben Datei überspringt bekannte Zeilennummern; Logrotation/Überschreiben wird noch nicht erkannt.
- Patch-Einträge über `POST /api/patches`; eine UI dafür folgt.
- Kein Login: **nur an 127.0.0.1 binden**, nicht ins Internet stellen. Der Import-Endpunkt kann lokale Dateien lesen.
- Keine automatische Git-Verknüpfung, echte Regressionserkennung oder Hintergrundüberwachung.
- Datenbank: `%USERPROFILE%\.patchcounter\events.db`.

## API

`GET /api/events`, `GET /api/groups`, `POST /api/import` mit `{"path":"C:\\logs\\app.log"}`, `GET /api/patches`, `POST /api/patches` mit `{"fingerprint":"...","note":"...","commit_sha":"..."}`.

API-Dokumentation: `http://127.0.0.1:8765/docs`.
