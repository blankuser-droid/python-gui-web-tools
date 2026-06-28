"""
gui/pages/system_page.py
---------------------------
Detailansicht aller Systeminformationen, inkl. Export als Bericht
(PDF/HTML/CSV/JSON).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.system_info import SystemInfoCollector, SystemSnapshot
from gui.workers import FunctionWorker
from utils.exceptions import ReportGenerationError
from utils.logger import get_logger

logger = get_logger(__name__)


class SystemPage(QWidget):
    """Zeigt detaillierte Systeminformationen und ermöglicht den Berichtsexport."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._collector = SystemInfoCollector()
        self._report_generator = None  # lazy init
        self._current_snapshot: SystemSnapshot | None = None
        self._export_buttons: list[QPushButton] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("System")
        title.setProperty("role", "pageTitle")
        layout.addWidget(title)

        # --- Aktionsleiste ---
        action_bar = QHBoxLayout()
        self.btn_refresh = QPushButton("Aktualisieren")
        self.btn_refresh.clicked.connect(self.refresh)
        action_bar.addWidget(self.btn_refresh)

        action_bar.addStretch()

        for label, fmt in [("PDF exportieren", "pdf"), ("HTML exportieren", "html"),
                            ("CSV exportieren", "csv"), ("JSON exportieren", "json")]:
            btn = QPushButton(label)
            btn.setProperty("variant", "secondary")
            btn.clicked.connect(lambda _checked, f=fmt: self._export_report(f))
            action_bar.addWidget(btn)
            self._export_buttons.append(btn)

        layout.addLayout(action_bar)

        # --- Übersichtstabelle ---
        overview_label = QLabel("Systemübersicht")
        overview_label.setProperty("role", "sectionTitle")
        layout.addWidget(overview_label)

        self.overview_table = self._make_table(["Eigenschaft", "Wert"])
        self.overview_table.setMaximumHeight(220)
        layout.addWidget(self.overview_table)

        # --- Festplatten ---
        disk_label = QLabel("Festplatten")
        disk_label.setProperty("role", "sectionTitle")
        layout.addWidget(disk_label)

        self.disk_table = self._make_table(
            ["Laufwerk", "Dateisystem", "Gesamt (GB)", "Genutzt (GB)", "Frei (GB)", "Belegung (%)"]
        )
        layout.addWidget(self.disk_table)

        # --- Netzwerkkarten ---
        nic_label = QLabel("Netzwerkschnittstellen")
        nic_label.setProperty("role", "sectionTitle")
        layout.addWidget(nic_label)

        self.nic_table = self._make_table(["Name", "IP-Adresse", "MAC-Adresse", "Status"])
        layout.addWidget(self.nic_table)

    @staticmethod
    def _make_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        return table

    def refresh(self) -> None:
        """Sammelt die Systemdaten im Hintergrund (siehe gui/workers.py)."""
        self.btn_refresh.setEnabled(False)
        worker = FunctionWorker(self._collector.collect_snapshot)
        worker.signals.finished.connect(self._on_data_ready)
        worker.signals.error.connect(self._on_error)
        worker.start()
        self._worker = worker  # Referenz halten (siehe workers.py Docstring)

    def _on_data_ready(self, snapshot: SystemSnapshot) -> None:
        self._current_snapshot = snapshot
        self.btn_refresh.setEnabled(True)

        rows = [
            ("Computername", snapshot.computer_name),
            ("Benutzername", snapshot.user_name),
            ("Betriebssystem", f"{snapshot.os_name} {snapshot.os_version} ({snapshot.os_architecture})"),
            ("CPU-Kerne (physisch / logisch)", f"{snapshot.cpu_physical_cores} / {snapshot.cpu_logical_cores}"),
            ("CPU-Auslastung", f"{snapshot.cpu_percent:.1f} %"),
            ("Arbeitsspeicher gesamt", f"{snapshot.ram_total_gb:.2f} GB"),
            ("Arbeitsspeicher genutzt", f"{snapshot.ram_used_gb:.2f} GB ({snapshot.ram_percent:.1f} %)"),
            ("Systemlaufzeit", snapshot.uptime_human),
        ]
        self.overview_table.setRowCount(len(rows))
        for i, (key, value) in enumerate(rows):
            self.overview_table.setItem(i, 0, QTableWidgetItem(key))
            self.overview_table.setItem(i, 1, QTableWidgetItem(value))

        self.disk_table.setRowCount(len(snapshot.disks))
        for i, disk in enumerate(snapshot.disks):
            values = [disk.mountpoint, disk.fstype, f"{disk.total_gb:.2f}",
                      f"{disk.used_gb:.2f}", f"{disk.free_gb:.2f}", f"{disk.percent_used:.1f}"]
            for col, val in enumerate(values):
                self.disk_table.setItem(i, col, QTableWidgetItem(val))

        self.nic_table.setRowCount(len(snapshot.network_interfaces))
        for i, nic in enumerate(snapshot.network_interfaces):
            values = [nic.name, nic.ip_address or "-", nic.mac_address or "-",
                      "Aktiv" if nic.is_up else "Inaktiv"]
            for col, val in enumerate(values):
                self.nic_table.setItem(i, col, QTableWidgetItem(val))

    def _on_error(self, message: str) -> None:
        self.btn_refresh.setEnabled(True)
        QMessageBox.warning(self, "Fehler", f"Systemdaten konnten nicht abgerufen werden:\n{message}")

    def _ensure_report_generator(self) -> None:
        if self._report_generator is None:
            # Lazy import/instanzieren erst beim ersten Export, vermeidet Startzeit-Imports
            from core.report_generator import ReportGenerator
            self._report_generator = ReportGenerator()

    def _set_export_buttons_enabled(self, enabled: bool) -> None:
        for b in self._export_buttons:
            b.setEnabled(enabled)

    def _export_report(self, fmt: str) -> None:
        if self._current_snapshot is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst die Systemdaten aktualisieren.")
            return

        self._ensure_report_generator()

        generator_map = {
            "pdf": self._report_generator.generate_pdf,
            "html": self._report_generator.generate_html,
            "csv": self._report_generator.generate_csv,
            "json": self._report_generator.generate_json,
        }

        generator = generator_map.get(fmt)
        if generator is None:
            QMessageBox.warning(self, "Fehler", "Unbekanntes Exportformat.")
            return

        # Disable export buttons while running
        self._set_export_buttons_enabled(False)

        worker = FunctionWorker(generator, self._current_snapshot)
        worker.signals.finished.connect(self._on_export_finished)
        worker.signals.error.connect(self._on_export_error)
        worker.start()
        self._export_worker = worker  # Referenz halten

    def _on_export_finished(self, path: str) -> None:
        self._set_export_buttons_enabled(True)
        suggested_name = path.split("/")[-1].split("\\")[-1]
        target, _ = QFileDialog.getSaveFileName(self, "Bericht speichern als...", suggested_name)
        if target:
            import shutil
            try:
                shutil.copyfile(path, target)
            except Exception as exc:
                QMessageBox.critical(self, "Fehler beim Kopieren", str(exc))
                return
            QMessageBox.information(self, "Erfolg", f"Bericht gespeichert unter:\n{target}")
        else:
            QMessageBox.information(self, "Erfolg", f"Bericht erstellt unter:\n{path}")

    def _on_export_error(self, message: str) -> None:
        self._set_export_buttons_enabled(True)
        QMessageBox.critical(self, "Fehler beim Export", message)