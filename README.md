# PatchCounter

**Local multi-project log monitoring and error triage**

PatchCounter is a lightweight Python/FastAPI tool that monitors local application logs, groups recurring failures and lets developers inspect the original log files. It is a development prototype, not a public-facing observability service.

**Version:** 0.4.0 | **Stack:** Python, FastAPI, SQLite, HTML/JavaScript, optional PySide6

## Features

- Manage multiple projects and log sources, including glob patterns and recursive scanning.
- Enable or pause projects and sources; automatic polling every five seconds plus manual scans.
- Import plain-text and JSONL logs; recognize ISO-style timestamps in text logs.
- Combine complete standalone Python tracebacks into a single error event.
- Group errors by normalized fingerprints and record patch notes with optional commit references.
- Browse indexed files, paginate raw log lines and open files in an editor where supported.
- Persist projects, events and scan state in SQLite; use log generations for common rotation and truncation cases.

## Native desktop GUI (v0.4)

The optional PySide6 application runs directly against the same SQLite database and core functions as the browser UI. It does not require Uvicorn.

~~~powershell
.\\.venv\\Scripts\\python.exe -m pip install -r requirements-desktop.txt
.\\.venv\\Scripts\\python.exe -m patchcounter.desktop
~~~

Desktop features: dark theme, project selector, project/source enable controls, indexed log preview, summary metrics and a 24-hour error/warning timeline. Scanning runs in a background Qt thread.

The desktop interface and the browser interface share the database; avoid running multiple independent scanners against the same active log sources simultaneously. The 24-hour chart reads event timestamps and currently treats timezone-naive timestamps as UTC.

## Architecture

~~~text
Browser UI (HTML/JavaScript)
          |
     FastAPI app.py ---- background poller
          |                    |
          +------ core.py -----+
                 |
        parser / scanner / grouping
                 |
           SQLite database
                 |
       local log files (read only)
~~~

- **patchcounter/app.py** — API endpoints, embedded UI, background polling.
- **patchcounter/desktop.py** — optional native PySide6 interface.
- **patchcounter/core.py** — log parsing, grouping, scanner, SQLite schema and migration.
- **tests/** — unit and regression tests for import, projects, raw viewer, and rotation.
- **start_windows.bat** — Windows convenience launcher.

## Installation (Windows)

Requires Python 3.10+, Git and PowerShell.

~~~powershell
git clone https://github.com/Dystenia/PatchCounter.git
cd PatchCounter
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn patchcounter.app:app --host 127.0.0.1 --port 8765
~~~

Open **http://127.0.0.1:8765**. Stop with Ctrl+C. Alternatively use **start_windows.bat**; the explicit virtual environment above is recommended.

## Usage

1. Add a project using its name and an existing local directory.
2. Add a log source with a directory and filename pattern, such as *.log or *.jsonl.
3. Enable the project and source, then choose **Jetzt scannen** or wait for automatic polling.
4. Review error groups and open the raw log viewer to inspect source lines.
5. Add patch notes to document investigated or fixed failures.

API documentation: **http://127.0.0.1:8765/docs**.

## Screenshots

Screenshots are not yet included. For the portfolio, capture the **real running UI** showing project configuration, grouped errors and raw log inspection. Use synthetic logs and redact private paths or secrets. Do not substitute mockups for actual application screenshots.

## Tests

~~~powershell
.\.venv\Scripts\python.exe -m compileall -q patchcounter
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
~~~

GitHub Actions runs syntax checks and the unit suite on pushes and pull requests across Linux and Windows. During development, the Windows test suite and a migration check against a copy of an existing database passed.

## Persistence and security

- Default database: %USERPROFILE%\.patchcounter\events.db; configurable with PATCHCOUNTER_DB.
- Back up existing SQLite data before upgrading. v0.3 adds generation-aware event uniqueness and preserves historical IDs.
- Log files are read, not modified; deleting a project does not delete monitored files.
- Bind only to **127.0.0.1**. No authentication, TLS or multi-user access controls are implemented.
- Run a single Uvicorn worker because every app process starts its own poller.

## Known limitations

- Polling can miss transient logs or multiple rotations between scans; scans are limited to 2,000 files by default.
- Rotation detection relies on size and a sampled file prefix, not a durable operating-system file identity. Some same-size rewrites and edits outside the sample may not be detected.
- Older cursors lack a prefix signature until the first scan after upgrade.
- Traceback grouping supports common standalone Python tracebacks, not every logging format.
- Historical event line numbers may no longer match the **current** file after rotation; raw viewing opens the current file.
- Fingerprints normalize UUIDs and numbers; they do not establish root causes.
- No remote agents or automated code fixes. The native GUI supports folder selection but not full feature parity with the web interface.
- The desktop timeline currently scans stored event timestamps and may become slow with very large databases.

## Status

**v0.4.0 — functional development prototype with optional native desktop interface.** The focus is transparent behavior, reproducible tests and explicit limitations.
