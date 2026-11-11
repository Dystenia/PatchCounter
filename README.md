# PatchCounter v0.2 — Multi-Project Log Monitoring

Lokales, universelles Python-Log-Dashboard für Windows. DYSTOPIC ist nur ein möglicher Anwendungsfall; **keine DYSTOPIC-spezifischen Pfade oder Änderungen an überwachten Projekten**.

## Windows-Start

Python 3.10+ und den Python-`py`-Launcher installieren, Repository klonen und `start_windows.bat` ausführen. Dashboard: **http://127.0.0.1:8765**. Alternativ: `pip install -r requirements.txt` und `python -m uvicorn patchcounter.app:app --host 127.0.0.1 --port 8765`.

## Projektverwaltung in der Web-GUI

1. Projektname und vorhandenen lokalen Projektordner eingeben; **Projekt hinzufügen**.
2. **Logquelle hinzufügen**: vorhandenes Logverzeichnis und Dateimuster (`*.log`, `*.jsonl`, `*.txt`) eingeben. Je Muster eine Logquelle anlegen. Unterordner können rekursiv gescannt werden.
3. **Aktivieren** startet die automatische Überwachung des Projekts; **Pausieren** hält sie an. Einzelne Logquellen lassen sich ebenfalls pausieren, bearbeiten oder entfernen.
4. **Jetzt scannen** löst eine sofortige Prüfung aus. Das Dashboard aktualisiert Ereignisse alle fünf Sekunden.
5. Projekt entfernen löscht nur seine Konfiguration und Quellen, **keine Dateien im überwachten Projekt**. Bereits importierte Ereignisse bleiben in PatchCounter erhalten.

Projekt- und Quellenkonfiguration werden in SQLite gespeichert. Bereits vorhandene V0.1-Daten werden beim Start durch Ergänzung einer optionalen Projekt-ID erhalten. Ältere Ereignisse sind weiterhin unter „Alle Projekte“ sichtbar.

## Funktionsgrenzen / wichtige Hinweise

- Polling alle 5 Sekunden; maximal 2000 gefundene Dateien pro Scan. Nur aktivierte Projekte und Quellen werden überwacht.
- Einfache TXT-/JSONL-Logs, **noch kein Python-Multiline-Traceback-Parser**.
- Erneuter Import ignoriert bereits bekannte Zeilennummern pro Pfad. **Logrotation, Überschreiben und gekürzte Dateien werden noch nicht zuverlässig erkannt**; dafür ist eine spätere Cursor-/Dateiidentitätsmigration erforderlich.
- Noch kein nativer Windows-Ordnerauswahldialog: Verzeichnisse werden über Pfadeingabefelder beziehungsweise Dialoge im Browser konfiguriert.
- Patch-Historie bleibt über `/api/patches` verfügbar, ohne Git-Automatisierung.
- Kein Login, kein TLS: **nur auf `127.0.0.1` starten**, niemals öffentlich exponieren. Die lokale API kann Dateien lesen, auf die der ausführende Benutzer Zugriff hat.
- Der Poller startet mit dem lokalen FastAPI-Prozess; nur **einen Uvicorn-Worker** verwenden.
- Datenbank: `%USERPROFILE%\.patchcounter\events.db`; optional `PATCHCOUNTER_DB` setzen.

## Tests

`python -m unittest discover -s tests -v`

Die Tests enthalten Projekt-CRUD, Aktivieren/Pausieren, Quellenverwaltung, Polling und einen V0.1-Datenmigrationstest. **Windows-Abnahme und Tests müssen nach dem Checkout lokal ausgeführt werden.**

API-Referenz unter `http://127.0.0.1:8765/docs`.
