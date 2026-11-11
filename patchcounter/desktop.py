"""Native PatchCounter desktop interface (optional PySide6 dependency)."""
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from .app import DB_PATH
from .core import (
    add_source, create_project, db_connect, file_events, get_events, get_groups,
    list_log_files, list_projects, read_raw_lines, scan_sources, update_project,
    update_source,
)


class ScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    @Slot()
    def run(self):
        try:
            with db_connect(DB_PATH) as db:
                result = scan_sources(db)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class Desktop(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PatchCounter · Desktop v0.4")
        self.resize(1200, 780)
        self.projects = []
        self.selected_project = None
        self.selected_file = None
        self._thread = None
        self._worker = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        bar = QHBoxLayout()
        self.status = QLabel("Bereit")
        for label, callback in (
            ("Projekt hinzufügen", self.add_project),
            ("Projekt aktivieren/pausieren", self.toggle_project),
            ("Logquelle hinzufügen", self.add_log_source),
            ("Quelle aktivieren/pausieren", self.toggle_source),
            ("Jetzt scannen", self.start_scan),
            ("Aktualisieren", self.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            bar.addWidget(button)
        layout.addLayout(bar)
        layout.addWidget(self.status)

        splitter = QSplitter()
        layout.addWidget(splitter)
        self.project_table = self.make_table(["ID", "Projekt", "Verzeichnis", "Status", "Quellen"])
        self.project_table.itemSelectionChanged.connect(self.select_project)
        splitter.addWidget(self.project_table)

        right = QTabWidget()
        splitter.addWidget(right)
        splitter.setSizes([430, 770])

        self.source_table = self.make_table(["ID", "Verzeichnis", "Muster", "Aktiv"])
        right.addTab(self.source_table, "Logquellen")
        self.group_table = self.make_table(["Quelle", "Level", "Anzahl", "Beispiel"])
        right.addTab(self.group_table, "Fehlergruppen")
        self.event_table = self.make_table(["Zeit", "Level", "Quelle", "Meldung"])
        right.addTab(self.event_table, "Ereignisse")

        files_page = QWidget()
        files_layout = QVBoxLayout(files_page)
        self.file_table = self.make_table(["Datei", "Ereignisse", "Fehler"])
        self.file_table.itemSelectionChanged.connect(self.select_file)
        files_layout.addWidget(self.file_table)
        self.raw_view = QTextEdit()
        self.raw_view.setReadOnly(True)
        files_layout.addWidget(self.raw_view)
        raw_button = QPushButton("Rohlog lesen (erste 200 Zeilen)")
        raw_button.clicked.connect(self.load_raw)
        files_layout.addWidget(raw_button)
        right.addTab(files_page, "Logdateien")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.start_scan)
        self.timer.start(5000)
        self.refresh()

    @staticmethod
    def make_table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @staticmethod
    def fill(table, rows):
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                table.setItem(i, j, QTableWidgetItem(str(value if value is not None else "")))

    def error(self, exc):
        QMessageBox.warning(self, "PatchCounter", str(exc))

    def refresh(self):
        try:
            with db_connect(DB_PATH) as db:
                self.projects = list_projects(db)
                self.fill(self.project_table, [
                    (p["id"], p["name"], p["root"],
                     "Aktiv" if p["enabled"] else "Pausiert", len(p["sources"]))
                    for p in self.projects
                ])
                if self.selected_project is not None:
                    for i, p in enumerate(self.projects):
                        if p["id"] == self.selected_project:
                            self.project_table.selectRow(i)
                            break
                    else:
                        self.selected_project = None
                self.load_data(db)
        except Exception as exc:
            self.error(exc)

    def select_project(self):
        row = self.project_table.currentRow()
        if row < 0 or row >= len(self.projects):
            return
        self.selected_project = self.projects[row]["id"]
        try:
            with db_connect(DB_PATH) as db:
                self.load_data(db)
        except Exception as exc:
            self.error(exc)

    def load_data(self, db):
        project = next((p for p in self.projects if p["id"] == self.selected_project), None)
        self.sources = project["sources"] if project else []
        self.fill(self.source_table, [
            (s["id"], s["directory"], s["pattern"], "Ja" if s["enabled"] else "Nein")
            for s in self.sources
        ])
        groups = get_groups(db, self.selected_project)
        self.fill(self.group_table, [
            (g["source"], g["level"], g["occurrences"], g["example"][:300])
            for g in groups
        ])
        events = get_events(db, project_id=self.selected_project)
        self.fill(self.event_table, [
            (e["ts"], e["level"], e["source"], e["message"][:500])
            for e in events
        ])
        self.files = list_log_files(db, self.selected_project)
        self.fill(self.file_table, [
            (f["path"], f["events"], f["errors"]) for f in self.files
        ])

    def add_project(self):
        name, ok = QInputDialog.getText(self, "Projekt", "Projektname:")
        if not ok or not name.strip():
            return
        directory = QFileDialog.getExistingDirectory(self, "Projektverzeichnis")
        if not directory:
            return
        try:
            with db_connect(DB_PATH) as db:
                self.selected_project = create_project(db, name, directory)
            self.refresh()
        except Exception as exc:
            self.error(exc)

    def toggle_project(self):
        project = next((p for p in self.projects if p["id"] == self.selected_project), None)
        if not project:
            return
        try:
            with db_connect(DB_PATH) as db:
                update_project(db, project["id"], project["name"], project["root"], not project["enabled"])
            self.refresh()
        except Exception as exc:
            self.error(exc)

    def add_log_source(self):
        project = next((p for p in self.projects if p["id"] == self.selected_project), None)
        if not project:
            self.error("Bitte zuerst ein Projekt auswählen.")
            return
        directory = QFileDialog.getExistingDirectory(self, "Logverzeichnis", project["root"])
        if not directory:
            return
        pattern, ok = QInputDialog.getText(self, "Logquelle", "Dateimuster:", text="*.log")
        if not ok:
            return
        try:
            with db_connect(DB_PATH) as db:
                add_source(db, project["id"], directory, pattern)
            self.refresh()
        except Exception as exc:
            self.error(exc)

    def toggle_source(self):
        row = self.source_table.currentRow()
        if row < 0 or row >= len(self.sources):
            return
        s = self.sources[row]
        try:
            with db_connect(DB_PATH) as db:
                update_source(db, s["id"], s["directory"], s["pattern"],
                              bool(s["recursive"]), not bool(s["enabled"]))
            self.refresh()
        except Exception as exc:
            self.error(exc)

    def select_file(self):
        row = self.file_table.currentRow()
        if 0 <= row < len(self.files):
            self.selected_file = self.files[row]["path"]

    def load_raw(self):
        if not self.selected_file:
            self.error("Bitte zuerst eine Logdatei auswählen.")
            return
        try:
            with db_connect(DB_PATH) as db:
                data = read_raw_lines(db, self.selected_file, 1, 200)
            self.raw_view.setPlainText("\n".join(
                f'{line["number"]:6} | {line["text"]}' for line in data["lines"]
            ))
        except Exception as exc:
            self.error(exc)

    def start_scan(self):
        if self._thread is not None:
            return
        self._thread = QThread(self)
        self._worker = ScanWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self.scan_finished)
        self._worker.failed.connect(self.scan_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self.thread_finished)
        self._thread.start()

    def scan_finished(self, result):
        self.status.setText(f'Scan: {result["scanned"]} Dateien, {result["imported"]} neue Ereignisse')
        self.refresh()

    def scan_failed(self, message):
        self.status.setText("Scan fehlgeschlagen: " + message)

    def thread_finished(self):
        self._thread.deleteLater()
        self._thread = None
        self._worker = None


def main():
    app = QApplication(sys.argv)
    window = Desktop()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
