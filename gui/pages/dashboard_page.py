"""
gui/pages/dashboard_page.py
-----------------------------
Dashboard: zentrale Übersichtsseite mit den wichtigsten Live-Kennzahlen.

WARUM EIN DASHBOARD ALS STARTSEITE?
In praktisch jedem professionellen Admin-Tool (Windows Admin Center,
Proxmox, Portainer, Zabbix) ist die erste Seite ein Dashboard mit den
wichtigsten Kennzahlen auf einen Blick. Der Gedanke dahinter: 90% der
Zeit will ein Admin nur einen schnellen Gesundheitscheck ("Ist alles
okay?"), nicht sofort tief in einzelne Bereiche eintauchen.

TECHNISCHER ANSATZ:
Ein QTimer aktualisiert die Werte alle 2 Sekunden (konfigurierbar über
config.json -> monitoring.refresh_interval_ms). Die Aktualisierung läuft
über einen FunctionWorker (siehe gui/workers.py), damit das Sammeln der
Systemdaten (insbesondere CPU-Messung mit psutil) die GUI nicht blockiert.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.config_manager import config
from core.process_manager import ProcessManager
from core.system_info import SystemInfoCollector, SystemSnapshot
from gui.widgets.start_card import StatCard
from gui.workers import FunctionWorker
from utils.logger import get_logger

logger = get_logger(__name__)


def _status_for_percent(value: float, warn: float, crit: float = 95) -> str:
    """Bestimmt die Statusfarbe (ok/warn/critical) anhand von Schwellenwerten.

    Schwellenwerte kommen aus der Konfiguration (config.json), nicht
    hartcodiert -- so kann z. B. ein Unternehmen mit knapperen Ressourcen
    die Warnschwelle senken, ohne den Code zu ändern.
    """
    if value >= crit:
        return "critical"
    if value >= warn:
        return "warn"
    return "ok"


class DashboardPage(QWidget):
    """Übersichtsseite mit CPU-, RAM-, Festplatten- und Prozess-Kennzahlen."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._collector = SystemInfoCollector()
        self._worker: FunctionWorker | None = None
        self._build_ui()
        self._start_auto_refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("Dashboard")
        title.setProperty("role", "pageTitle")
        layout.addWidget(title)

        subtitle = QLabel("Live-Übersicht über Systemzustand und Auslastung")
        subtitle.setStyleSheet("color: #9aa0ad;")
        layout.addWidget(subtitle)

        # --- Kachel-Raster (Grid) ---
        grid = QGridLayout()
        grid.setSpacing(14)

        self.card_cpu = StatCard("CPU-Auslastung")
        self.card_ram = StatCard("Arbeitsspeicher")
        self.card_disk = StatCard("Festplatte (System)")
        self.card_uptime = StatCard("Systemlaufzeit")
        self.card_processes = StatCard("Laufende Prozesse")
        self.card_network = StatCard("Netzwerkschnittstellen")

        grid.addWidget(self.card_cpu, 0, 0)
        grid.addWidget(self.card_ram, 0, 1)
        grid.addWidget(self.card_disk, 0, 2)
        grid.addWidget(self.card_uptime, 1, 0)
        grid.addWidget(self.card_processes, 1, 1)
        grid.addWidget(self.card_network, 1, 2)

        layout.addLayout(grid)

        # --- Top-Prozesse Liste ---
        section_label = QLabel("Top 5 Prozesse nach CPU-Auslastung")
        section_label.setProperty("role", "sectionTitle")
        layout.addWidget(section_label)

        self.process_list = QListWidget()
        self.process_list.setMaximumHeight(160)
        layout.addWidget(self.process_list)

        layout.addStretch()

    def _start_auto_refresh(self) -> None:
        interval = config.get("monitoring", "refresh_interval_ms", default=2000)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(interval)
        self.refresh()  # sofortige erste Aktualisierung, nicht erst nach 2s warten

    def refresh(self) -> None:
        """Stößt eine asynchrone Aktualisierung der Dashboard-Daten an.

        Läuft im Hintergrundthread, da `collect_snapshot()` u. a. eine
        CPU-Messung mit kurzer Wartezeit durchführt (siehe system_info.py)
        -- das würde die GUI sonst alle 2 Sekunden kurz einfrieren lassen.
        """
        if self._worker is not None and self._worker.isRunning():
            return  # vorherige Aktualisierung läuft noch -> überspringen
        self._worker = FunctionWorker(self._collector.collect_snapshot)
        self._worker.signals.finished.connect(self._on_snapshot_ready)
        self._worker.signals.error.connect(lambda msg: logger.error("Dashboard-Refresh-Fehler: %s", msg))
        self._worker.start()

    def _on_snapshot_ready(self, snapshot: SystemSnapshot) -> None:
        cpu_warn = config.get("monitoring", "cpu_warning_percent", default=80)
        ram_warn = config.get("monitoring", "ram_warning_percent", default=85)
        disk_warn = config.get("monitoring", "disk_warning_percent", default=90)

        self.card_cpu.set_value(f"{snapshot.cpu_percent:.1f} %", _status_for_percent(snapshot.cpu_percent, cpu_warn))
        self.card_ram.set_value(
            f"{snapshot.ram_percent:.1f} %  ({snapshot.ram_used_gb:.1f}/{snapshot.ram_total_gb:.1f} GB)",
            _status_for_percent(snapshot.ram_percent, ram_warn),
        )

        if snapshot.disks:
            main_disk = max(snapshot.disks, key=lambda d: d.total_gb)
            self.card_disk.set_value(
                f"{main_disk.percent_used:.1f} %  ({main_disk.free_gb:.1f} GB frei)",
                _status_for_percent(main_disk.percent_used, disk_warn),
            )
        else:
            self.card_disk.set_value("keine Daten")

        self.card_uptime.set_value(snapshot.uptime_human)

        active_nics = sum(1 for n in snapshot.network_interfaces if n.is_up)
        self.card_network.set_value(f"{active_nics} aktiv / {len(snapshot.network_interfaces)} gesamt")

        self._refresh_top_processes()

    def _refresh_top_processes(self) -> None:
        try:
            top_cpu, _ = ProcessManager.get_top_consumers(5)
        except Exception as exc:
            logger.warning("Top-Prozesse konnten nicht ermittelt werden: %s", exc)
            return

        self.card_processes.set_value(str(len(ProcessManager.list_processes())))
        self.process_list.clear()
        for proc in top_cpu:
            item = QListWidgetItem(f"PID {proc.pid:>6}   {proc.name:<25}   CPU {proc.cpu_percent:>5.1f} %   RAM {proc.memory_mb:>7.1f} MB")
            self.process_list.addItem(item)