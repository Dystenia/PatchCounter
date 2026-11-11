"""Native PatchCounter desktop interface (optional PySide6 dependency)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QColor, QPalette, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
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


DARK_STYLE = """
QWidget { background: #111827; color: #e5eaf3; font-size: 13px; }
QMainWindow { background: #0b1220; }
QPushButton { background: #24364d; border: 1px solid #3b5069; border-radius: 6px;
              padding: 8px 12px; color: #eef4ff; }
QPushButton:hover { background: #315276; border-color: #5c83b0; }
QPushButton:pressed { background: #1b2c41; }
QPushButton:disabled { color: #758398; background: #1b2534; }
QTableWidget { background: #151f2e; alternate-background-color: #1b2839;
               gridline-color: #2d3a4d; border: 1px solid #324158;
               border-radius: 6px; selection-background-color: #22577c;
               selection-color: #ffffff; }
QHeaderView::section { background: #243246; color: #dce8f8;
                       padding: 7px; border: 0; border-right: 1px solid #35465c;
                       border-bottom: 1px solid #35465c; }
QTableCornerButton::section { background: #243246; border: 0; }
QTabWidget::pane { border: 1px solid #34445b; background: #151f2e; }
QTabBar::tab { background: #1b293b; color: #aebdd1; padding: 10px 15px;
               border: 1px solid #34445b; border-bottom: 0; }
QTabBar::tab:selected { background: #263e58; color: #ffffff; }
QTabBar::tab:hover { background: #304761; }
QTextEdit, QLineEdit { background: #101a28; color: #e5eaf3;
                      border: 1px solid #3a4b61; border-radius: 5px;
                      padding: 5px; selection-background-color: #22577c; }
QLabel { color: #cbd6e5; }
QSplitter::handle { background: #34445b; }
QScrollBar:vertical { background: #142031; width: 11px; }
QScrollBar::handle:vertical { background: #405671; border-radius: 5px; min-height: 25px; }
QScrollBar:horizontal { background: #142031; height: 11px; }
QScrollBar::handle:horizontal { background: #405671; border-radius: 5px; min-width: 25px; }
QDialog, QMessageBox, QInputDialog, QFileDialog { background: #111827; }
QComboBox { background: #1b293b; color: #e5eaf3; border: 1px solid #40536b; border-radius: 6px; padding: 7px; min-width: 200px; }
QComboBox QAbstractItemView { background: #1b293b; color: #e5eaf3; selection-background-color: #22577c; }
QFrame#metric { background: #1c2b3e; border: 1px solid #344a63; border-radius: 8px; }
QLabel#metricValue { font-size: 24px; font-weight: bold; color: #f1f6ff; }
QLabel#metricTitle { color: #a7b8cd; }
"""


class EventTimeline(QWidget):
    """Compact 24-hour bar chart: red errors, amber warnings."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(155)
        self.setMaximumHeight(190)
        self.errors = [0] * 24
        self.warnings = [0] * 24
        self.hours = [""] * 24

    def set_series(self, hours, errors, warnings):
        self.hours = hours
        self.errors = errors
        self.warnings = warnings
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(12, 8, -12, -12)
        painter.fillRect(rect, QColor("#1c2b3e"))
        painter.setPen(QColor("#a7b8cd"))
        painter.drawText(rect.adjusted(12, 3, -12, -3),
                         Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                         "Ereignisverlauf · letzte 24 Stunden")
        painter.setPen(QColor("#ef7474"))
        painter.drawText(rect.right() - 185, rect.top() + 17, "■ Fehler")
        painter.setPen(QColor("#e7b65b"))
        painter.drawText(rect.right() - 95, rect.top() + 17, "■ Warnungen")
        left, right = rect.left() + 30, rect.right() - 12
        top, bottom = rect.top() + 33, rect.bottom() - 24
        if right <= left or bottom <= top:
            return
        maximum = max(1, *(a + b for a, b in zip(self.errors, self.warnings)))
        painter.setPen(QPen(QColor("#344a63"), 1))
        for fraction in (0, 0.5, 1):
            y = bottom - int((bottom - top) * fraction)
            painter.drawLine(left, y, right, y)
        step = (right - left) / 24
        for i, (errors, warnings) in enumerate(zip(self.errors, self.warnings)):
            x = left + i * step + step * 0.16
            width = max(2, step * 0.68)
            h_error = (bottom - top) * errors / maximum
            h_warn = (bottom - top) * warnings / maximum
            painter.fillRect(int(x), int(bottom - h_error), int(width),
                             int(h_error), QColor("#ef7474"))
            painter.fillRect(int(x), int(bottom - h_error - h_warn),
                             int(width), int(h_warn), QColor("#e7b65b"))
        painter.setPen(QColor("#a7b8cd"))
        for i in (0, 6, 12, 18, 23):
            painter.drawText(int(left + i * step), bottom + 17, self.hours[i])


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
        self.setMinimumSize(900, 550)
        self.projects = []
        self.selected_project = None
        self.selected_file = None
        self._thread = None
        self._worker = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
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
        selector = QHBoxLayout()
        selector.addWidget(QLabel("Projekt:"))
        self.project_combo = QComboBox()
        self.project_combo.currentIndexChanged.connect(self.change_project)
        selector.addWidget(self.project_combo)
        self.project_info = QLabel("Alle Projekte")
        selector.addWidget(self.project_info, 1)
        layout.addLayout(selector)
        metrics = QGridLayout()
        self.metric_values = {}
        for i, (key, title) in enumerate((
            ("files", "Logdateien"), ("events", "Ereignisse"),
            ("errors", "Fehler / Kritisch"), ("warnings", "Warnungen"),
            ("groups", "Fehlergruppen"), ("rate", "Fehlerquote"),
        )):
            card = QFrame()
            card.setObjectName("metric")
            column = QVBoxLayout(card)
            label = QLabel(title)
            label.setObjectName("metricTitle")
            value = QLabel("–")
            value.setObjectName("metricValue")
            column.addWidget(label)
            column.addWidget(value)
            metrics.addWidget(card, i // 3, i % 3)
            self.metric_values[key] = value
        layout.addLayout(metrics)
        self.timeline = EventTimeline()
        layout.addWidget(self.timeline)
        layout.addWidget(self.status)

        splitter = QSplitter()
        layout.addWidget(splitter, 1)
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
                if self.selected_project is not None and not any(
                    p["id"] == self.selected_project for p in self.projects
                ):
                    self.selected_project = None
                self.project_combo.blockSignals(True)
                self.project_combo.clear()
                self.project_combo.addItem("Alle Projekte", None)
                for p in self.projects:
                    self.project_combo.addItem(p["name"], p["id"])
                index = self.project_combo.findData(self.selected_project)
                self.project_combo.setCurrentIndex(max(index, 0))
                self.project_combo.blockSignals(False)
                self.project_table.blockSignals(True)
                self.fill(self.project_table, [
                    (p["id"], p["name"], p["root"],
                     "Aktiv" if p["enabled"] else "Pausiert", len(p["sources"]))
                    for p in self.projects
                ])
                for i, p in enumerate(self.projects):
                    if p["id"] == self.selected_project:
                        self.project_table.selectRow(i)
                        break
                self.project_table.blockSignals(False)
                self.load_data(db)
        except Exception as exc:
            self.error(exc)

    def change_project(self):
        self.selected_project = self.project_combo.currentData()
        self.selected_file = None
        self.raw_view.clear()
        self.refresh()

    def select_project(self):
        row = self.project_table.currentRow()
        if row < 0 or row >= len(self.projects):
            return
        project_id = self.projects[row]["id"]
        if project_id != self.selected_project:
            self.selected_project = project_id
            self.selected_file = None
            self.raw_view.clear()
            self.refresh()

    def update_metrics(self, db, groups):
        project = next((p for p in self.projects if p["id"] == self.selected_project), None)
        if project:
            state = "Aktiv" if project["enabled"] else "Pausiert"
            self.project_info.setText(f'{project["name"]} · {state} · {project["root"]}')
        else:
            self.project_info.setText(f'Gesamtübersicht · {len(self.projects)} Projekte')
        where = " WHERE project_id=?" if self.selected_project is not None else ""
        args = (self.selected_project,) if self.selected_project is not None else ()
        counts = db.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(CASE WHEN level IN ('ERROR','CRITICAL') THEN 1 ELSE 0 END),0) AS errors, "
            "COALESCE(SUM(CASE WHEN level='WARNING' THEN 1 ELSE 0 END),0) AS warnings "
            "FROM events" + where, args
        ).fetchone()
        total = counts["total"]
        errors = counts["errors"]
        values = {
            "files": len(self.files), "events": total, "errors": errors,
            "warnings": counts["warnings"], "groups": len(groups),
            "rate": f"{errors / total * 100:.1f} %" if total else "0.0 %",
        }
        for key, value in values.items():
            self.metric_values[key].setText(str(value))
        self.update_timeline(db)

    def update_timeline(self, db):
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        hours = [now - timedelta(hours=23 - i) for i in range(24)]
        errors, warnings = [0] * 24, [0] * 24
        where = " WHERE project_id=?" if self.selected_project is not None else ""
        args = (self.selected_project,) if self.selected_project is not None else ()
        for row in db.execute("SELECT ts, level FROM events" + where, args):
            try:
                stamp = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                stamp = stamp.astimezone(timezone.utc).replace(
                    minute=0, second=0, microsecond=0
                )
            except (ValueError, TypeError, OverflowError):
                continue
            index = int((stamp - hours[0]).total_seconds() // 3600)
            if not 0 <= index < 24:
                continue
            if row["level"] in ("ERROR", "CRITICAL"):
                errors[index] += 1
            elif row["level"] == "WARNING":
                warnings[index] += 1
        self.timeline.set_series([hour.strftime("%H:%M") for hour in hours],
                                 errors, warnings)

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
        self.update_metrics(db, groups)

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
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e5eaf3"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#151f2e"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1b2839"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e5eaf3"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#24364d"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#eef4ff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#22577c"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8292a8"))
    app.setPalette(palette)
    app.setStyleSheet(DARK_STYLE)
    window = Desktop()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
