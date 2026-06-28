"""
gui/pages/network_page.py
----------------------------
Netzwerk-Werkzeuge: Ping, Traceroute, DNS-Lookup, Portscanner, aktive
Verbindungen -- jeweils als eigener Tab.

DIDAKTISCHER HINWEIS:
Diese Seite zeigt exemplarisch das wichtigste GUI-Muster dieser ganzen
Anwendung: Eingabefeld -> Button -> Hintergrund-Worker -> Ergebnisanzeige.
Einmal verstanden, lässt sich dieses Muster auf jede weitere Funktion
übertragen (siehe gui/workers.py für die Erklärung, WARUM Hintergrund-
Threads hier zwingend notwendig sind).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config.config_manager import config
from core.network_tools import NetworkTools, PingResult, PortScanResult
from gui.workers import FunctionWorker
from utils.logger import get_logger

logger = get_logger(__name__)


class NetworkPage(QWidget):
    """Container-Seite mit einem Tab pro Netzwerk-Werkzeug."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._active_workers: list[FunctionWorker] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("Netzwerk")
        title.setProperty("role", "pageTitle")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_ping_tab(), "Ping")
        tabs.addTab(self._build_traceroute_tab(), "Traceroute")
        tabs.addTab(self._build_dns_tab(), "DNS-Lookup")
        tabs.addTab(self._build_portscan_tab(), "Portscanner")
        tabs.addTab(self._build_connections_tab(), "Aktive Verbindungen")
        layout.addWidget(tabs)

    # ---------------------------------------------------------------- PING
    def _build_ping_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        self.ping_host_input = QLineEdit("8.8.8.8")
        self.ping_count_input = QSpinBox()
        self.ping_count_input.setRange(1, 50)
        self.ping_count_input.setValue(config.get("network", "default_ping_count", default=4))
        form.addRow("Host / IP-Adresse:", self.ping_host_input)
        form.addRow("Anzahl Pakete:", self.ping_count_input)
        layout.addLayout(form)

        self.btn_ping = QPushButton("Ping starten")
        self.btn_ping.clicked.connect(self._run_ping)
        layout.addWidget(self.btn_ping)

        self.ping_output = QPlainTextEdit()
        self.ping_output.setReadOnly(True)
        layout.addWidget(self.ping_output)
        return widget

    def _run_ping(self) -> None:
        host = self.ping_host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "Eingabe fehlt", "Bitte einen Host oder eine IP-Adresse eingeben.")
            return
        count = self.ping_count_input.value()
        self.btn_ping.setEnabled(False)
        self.ping_output.setPlainText(f"Ping zu {host} wird ausgeführt...")

        worker = FunctionWorker(NetworkTools.ping, host, count=count)
        worker.signals.finished.connect(self._on_ping_done)
        worker.signals.error.connect(lambda msg: self._on_tool_error(self.ping_output, self.btn_ping, msg))
        self._track_worker(worker)

    def _on_ping_done(self, result: PingResult) -> None:
        self.btn_ping.setEnabled(True)
        summary = (
            f"Ziel: {result.host}\n"
            f"Gesendet: {result.packets_sent}  |  Empfangen: {result.packets_received}  |  "
            f"Verlust: {result.packet_loss_percent} %\n"
            f"Durchschnittliche Latenz: {result.avg_latency_ms} ms\n"
            f"Status: {'ERREICHBAR' if result.success else 'NICHT ERREICHBAR'}\n\n"
            f"--- Rohausgabe ---\n{result.raw_output}"
        )
        self.ping_output.setPlainText(summary)

    # ----------------------------------------------------------- TRACEROUTE
    def _build_traceroute_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        self.tracert_host_input = QLineEdit("8.8.8.8")
        form.addRow("Host / IP-Adresse:", self.tracert_host_input)
        layout.addLayout(form)

        self.btn_tracert = QPushButton("Traceroute starten")
        self.btn_tracert.clicked.connect(self._run_traceroute)
        layout.addWidget(self.btn_tracert)

        self.tracert_output = QPlainTextEdit()
        self.tracert_output.setReadOnly(True)
        layout.addWidget(self.tracert_output)
        return widget

    def _run_traceroute(self) -> None:
        host = self.tracert_host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "Eingabe fehlt", "Bitte einen Host oder eine IP-Adresse eingeben.")
            return
        self.btn_tracert.setEnabled(False)
        self.tracert_output.setPlainText(f"Traceroute zu {host} läuft (kann bis zu einer Minute dauern)...")

        worker = FunctionWorker(NetworkTools.traceroute, host)
        worker.signals.finished.connect(lambda out: self._on_traceroute_done(out))
        worker.signals.error.connect(lambda msg: self._on_tool_error(self.tracert_output, self.btn_tracert, msg))
        self._track_worker(worker)

    def _on_traceroute_done(self, output: str) -> None:
        self.btn_tracert.setEnabled(True)
        self.tracert_output.setPlainText(output)

    # ----------------------------------------------------------------- DNS
    def _build_dns_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        self.dns_input = QLineEdit("www.example.com")
        form.addRow("Hostname oder IP-Adresse:", self.dns_input)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        self.btn_dns_forward = QPushButton("Forward-Lookup (Name -> IP)")
        self.btn_dns_forward.clicked.connect(self._run_dns_forward)
        self.btn_dns_reverse = QPushButton("Reverse-Lookup (IP -> Name)")
        self.btn_dns_reverse.setProperty("variant", "secondary")
        self.btn_dns_reverse.clicked.connect(self._run_dns_reverse)
        button_row.addWidget(self.btn_dns_forward)
        button_row.addWidget(self.btn_dns_reverse)
        layout.addLayout(button_row)

        self.dns_output = QPlainTextEdit()
        self.dns_output.setReadOnly(True)
        layout.addWidget(self.dns_output)
        return widget

    def _run_dns_forward(self) -> None:
        host = self.dns_input.text().strip()
        try:
            ips = NetworkTools.dns_lookup(host)
            self.dns_output.setPlainText(f"{host} löst auf zu:\n" + "\n".join(ips))
        except Exception as exc:
            self.dns_output.setPlainText(f"Fehler: {exc}")

    def _run_dns_reverse(self) -> None:
        ip = self.dns_input.text().strip()
        try:
            hostname = NetworkTools.reverse_dns_lookup(ip)
            self.dns_output.setPlainText(f"{ip} löst auf zu Hostname:\n{hostname}")
        except Exception as exc:
            self.dns_output.setPlainText(f"Fehler: {exc}")

    # ------------------------------------------------------------ PORTSCAN
    def _build_portscan_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        warning = QLabel(
            "⚠ Nur gegen eigene, autorisierte Systeme verwenden. Portscans gegen\n"
            "fremde Systeme ohne Erlaubnis können rechtliche Konsequenzen haben."
        )
        warning.setStyleSheet("color: #d29922; font-weight: bold;")
        layout.addWidget(warning)

        form = QFormLayout()
        self.scan_host_input = QLineEdit("127.0.0.1")
        self.scan_ports_input = QLineEdit("21,22,23,25,53,80,110,143,443,445,3389")
        form.addRow("Ziel-Host:", self.scan_host_input)
        form.addRow("Ports (kommagetrennt):", self.scan_ports_input)
        layout.addLayout(form)

        self.btn_scan = QPushButton("Portscan starten")
        self.btn_scan.clicked.connect(self._run_portscan)
        layout.addWidget(self.btn_scan)

        self.scan_output = QPlainTextEdit()
        self.scan_output.setReadOnly(True)
        layout.addWidget(self.scan_output)
        return widget

    def _run_portscan(self) -> None:
        host = self.scan_host_input.text().strip()
        ports_text = self.scan_ports_input.text().strip()
        try:
            ports = [int(p.strip()) for p in ports_text.split(",") if p.strip()]
        except ValueError:
            QMessageBox.warning(self, "Ungültige Eingabe", "Ports müssen kommagetrennte Zahlen sein, z. B. 22,80,443")
            return
        if not host or not ports:
            QMessageBox.warning(self, "Eingabe fehlt", "Bitte Host und mindestens einen Port angeben.")
            return

        self.btn_scan.setEnabled(False)
        self.scan_output.setPlainText(f"Scanne {len(ports)} Port(s) auf {host}...")
        timeout = config.get("network", "port_scan_timeout_s", default=0.5)

        worker = FunctionWorker(NetworkTools.scan_ports, host, ports, timeout_s=timeout)
        worker.signals.finished.connect(self._on_portscan_done)
        worker.signals.error.connect(lambda msg: self._on_tool_error(self.scan_output, self.btn_scan, msg))
        self._track_worker(worker)

    def _on_portscan_done(self, result: PortScanResult) -> None:
        self.btn_scan.setEnabled(True)
        lines = [f"Ergebnis für {result.host}:", ""]
        lines.append(f"OFFEN ({len(result.open_ports)}): " + (", ".join(map(str, result.open_ports)) or "keine"))
        lines.append(f"GESCHLOSSEN ({len(result.closed_ports)}): " + (", ".join(map(str, result.closed_ports)) or "keine"))
        self.scan_output.setPlainText("\n".join(lines))

    # ------------------------------------------------------------ CONNECTIONS
    def _build_connections_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.btn_connections = QPushButton("Aktive Verbindungen anzeigen")
        self.btn_connections.clicked.connect(self._run_connections)
        layout.addWidget(self.btn_connections)

        self.connections_table = QTableWidget(0, 5)
        self.connections_table.setHorizontalHeaderLabels(
            ["Lokale Adresse", "Remote-Adresse", "Status", "PID", "Prozess"]
        )
        self.connections_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.connections_table.verticalHeader().setVisible(False)
        self.connections_table.setAlternatingRowColors(True)
        layout.addWidget(self.connections_table)
        return widget

    def _run_connections(self) -> None:
        self.btn_connections.setEnabled(False)
        worker = FunctionWorker(NetworkTools.get_active_connections)
        worker.signals.finished.connect(self._on_connections_done)
        worker.signals.error.connect(
            lambda msg: (self.btn_connections.setEnabled(True), QMessageBox.warning(self, "Fehler", msg))
        )
        self._track_worker(worker)

    def _on_connections_done(self, connections: list) -> None:
        self.btn_connections.setEnabled(True)
        self.connections_table.setRowCount(len(connections))
        for i, c in enumerate(connections):
            values = [c.local_address, c.remote_address, c.status,
                      str(c.pid) if c.pid else "-", c.process_name or "-"]
            for col, val in enumerate(values):
                self.connections_table.setItem(i, col, QTableWidgetItem(val))

    # ------------------------------------------------------------- HELPERS
    def _on_tool_error(self, output_widget: QPlainTextEdit, button: QPushButton, message: str) -> None:
        button.setEnabled(True)
        output_widget.setPlainText(f"Fehler: {message}")

    def _track_worker(self, worker: FunctionWorker) -> None:
        """Hält eine Referenz auf laufende Worker, damit sie nicht vorzeitig
        von Python eingesammelt werden, und startet sie."""
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._active_workers.remove(worker) if worker in self._active_workers else None)
        worker.start()