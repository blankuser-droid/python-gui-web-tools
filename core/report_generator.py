"""
core/report_generator.py
--------------------------
Erstellt Berichte über den Systemzustand in vier Formaten: PDF, HTML,
CSV, JSON.
"""

from __future__ import annotations

import csv
import importlib
import json
import os
import time
from typing import Any

Template = None
colors = None
A4 = None
getSampleStyleSheet = None
cm = None
Paragraph = None
SimpleDocTemplate = None
Spacer = None
Table = None
TableStyle = None
_JINJA2_IMPORT_ERROR = None
_REPORTLAB_IMPORT_ERROR = None


def _load_optional_dependencies() -> None:
    """Lädt Jinja2 und reportlab nur, wenn sie verfügbar sind."""
    global Template, colors, A4, getSampleStyleSheet, cm, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    global _JINJA2_IMPORT_ERROR, _REPORTLAB_IMPORT_ERROR

    try:
        Template = importlib.import_module("jinja2").Template
    except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
        Template = None
        _JINJA2_IMPORT_ERROR = exc
    else:
        _JINJA2_IMPORT_ERROR = None

    try:
        colors_module = importlib.import_module("reportlab.lib.colors")
        colors = colors_module

        pagesizes = importlib.import_module("reportlab.lib.pagesizes")
        A4 = pagesizes.A4

        styles = importlib.import_module("reportlab.lib.styles")
        getSampleStyleSheet = styles.getSampleStyleSheet

        units = importlib.import_module("reportlab.lib.units")
        cm = units.cm

        platypus = importlib.import_module("reportlab.platypus")
        Paragraph = platypus.Paragraph
        SimpleDocTemplate = platypus.SimpleDocTemplate
        Spacer = platypus.Spacer
        Table = platypus.Table
        TableStyle = platypus.TableStyle
    except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
        colors = None
        A4 = None
        getSampleStyleSheet = None
        cm = None
        Paragraph = None
        SimpleDocTemplate = None
        Spacer = None
        Table = None
        TableStyle = None
        _REPORTLAB_IMPORT_ERROR = exc
    else:
        _REPORTLAB_IMPORT_ERROR = None


# Hinweis: _load_optional_dependencies() wird jetzt LAZY aufgerufen,
# damit Importieren dieses Moduls beim Start nicht unnötig verlangsamt.

from core.system_info import SystemSnapshot
from utils.exceptions import ReportGenerationError
from utils.logger import get_logger

logger = get_logger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REPORT_DIR = os.path.join(BASE_DIR, "data", "reports")

_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Systembericht - {{ snapshot.computer_name }}</title>
<style>
  body { font-family: Segoe UI, Arial, sans-serif; margin: 2em; color: #222; }
  h1 { color: #1f4e79; border-bottom: 2px solid #1f4e79; padding-bottom: 0.3em; }
  h2 { color: #2e75b6; margin-top: 1.5em; }
  table { border-collapse: collapse; width: 100%; margin-top: 0.5em; }
  th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; font-size: 0.92em; }
  th { background-color: #2e75b6; color: white; }
  tr:nth-child(even) { background-color: #f4f8fb; }
  .meta { color: #666; font-size: 0.85em; }
  .warn { color: #b30000; font-weight: bold; }
</style>
</head>
<body>
  <h1>Systembericht: {{ snapshot.computer_name }}</h1>
  <p class="meta">Erstellt am {{ snapshot.timestamp }} | Benutzer: {{ snapshot.user_name }}</p>

  <h2>Systemübersicht</h2>
  <table>
    <tr><th>Eigenschaft</th><th>Wert</th></tr>
    <tr><td>Betriebssystem</td><td>{{ snapshot.os_name }} {{ snapshot.os_version }} ({{ snapshot.os_architecture }})</td></tr>
    <tr><td>CPU-Kerne (physisch / logisch)</td><td>{{ snapshot.cpu_physical_cores }} / {{ snapshot.cpu_logical_cores }}</td></tr>
    <tr><td>CPU-Auslastung</td><td>{{ snapshot.cpu_percent }} %</td></tr>
    <tr><td>Arbeitsspeicher gesamt</td><td>{{ snapshot.ram_total_gb }} GB</td></tr>
    <tr><td>Arbeitsspeicher genutzt</td><td>{{ snapshot.ram_used_gb }} GB ({{ snapshot.ram_percent }} %)</td></tr>
    <tr><td>Systemlaufzeit (Uptime)</td><td>{{ snapshot.uptime_human }}</td></tr>
  </table>

  <h2>Festplatten</h2>
  <table>
    <tr><th>Laufwerk</th><th>Dateisystem</th><th>Gesamt (GB)</th><th>Genutzt (GB)</th><th>Frei (GB)</th><th>Belegung (%)</th></tr>
    {% for disk in snapshot.disks %}
    <tr>
      <td>{{ disk.mountpoint }}</td>
      <td>{{ disk.fstype }}</td>
      <td>{{ disk.total_gb }}</td>
      <td>{{ disk.used_gb }}</td>
      <td>{{ disk.free_gb }}</td>
      <td class="{{ 'warn' if disk.percent_used > 90 else '' }}">{{ disk.percent_used }}</td>
    </tr>
    {% endfor %}
  </table>

  <h2>Netzwerkschnittstellen</h2>
  <table>
    <tr><th>Name</th><th>IP-Adresse</th><th>MAC-Adresse</th><th>Status</th></tr>
    {% for nic in snapshot.network_interfaces %}
    <tr>
      <td>{{ nic.name }}</td>
      <td>{{ nic.ip_address or '-' }}</td>
      <td>{{ nic.mac_address or '-' }}</td>
      <td>{{ 'Aktiv' if nic.is_up else 'Inaktiv' }}</td>
    </tr>
    {% endfor %}
  </table>

  <p class="meta">Erstellt mit SysAdmin Toolkit</p>
</body>
</html>
"""


class ReportGenerator:
    """Erstellt Systemberichte in verschiedenen Formaten aus einem SystemSnapshot."""

    def __init__(self, output_dir: str = DEFAULT_REPORT_DIR) -> None:
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _build_filename(self, snapshot: SystemSnapshot, extension: str) -> str:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_name = snapshot.computer_name.replace(" ", "_")
        return os.path.join(self.output_dir, f"report_{safe_name}_{timestamp}.{extension}")

    def generate_json(self, snapshot: SystemSnapshot) -> str:
        """Exportiert den Snapshot als JSON-Datei. Liefert den Dateipfad zurück."""
        path = self._build_filename(snapshot, "json")
        try:
            data = self._snapshot_to_dict(snapshot)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            raise ReportGenerationError(f"JSON-Bericht konnte nicht erstellt werden: {exc}") from exc
        logger.info("JSON-Bericht erstellt: %s", path)
        return path

    @staticmethod
    def _snapshot_to_dict(snapshot: SystemSnapshot) -> dict:
        d = snapshot.__dict__.copy()
        d["disks"] = [disk.__dict__ for disk in snapshot.disks]
        d["network_interfaces"] = [nic.__dict__ for nic in snapshot.network_interfaces]
        return d

    def generate_csv(self, snapshot: SystemSnapshot) -> str:
        path = self._build_filename(snapshot, "csv")
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["# Systembericht", snapshot.computer_name, snapshot.timestamp])
                writer.writerow(["# OS", f"{snapshot.os_name} {snapshot.os_version}"])
                writer.writerow(["# CPU-Auslastung (%)", snapshot.cpu_percent])
                writer.writerow(["# RAM genutzt (%)", snapshot.ram_percent])
                writer.writerow([])
                writer.writerow(["Laufwerk", "Dateisystem", "Gesamt_GB", "Genutzt_GB", "Frei_GB", "Belegung_Prozent"])
                for disk in snapshot.disks:
                    writer.writerow(
                        [disk.mountpoint, disk.fstype, disk.total_gb, disk.used_gb, disk.free_gb, disk.percent_used]
                    )
                writer.writerow([])
                writer.writerow(["Netzwerkschnittstelle", "IP_Adresse", "MAC_Adresse", "Status"])
                for nic in snapshot.network_interfaces:
                    writer.writerow(
                        [nic.name, nic.ip_address or "-", nic.mac_address or "-", "Aktiv" if nic.is_up else "Inaktiv"]
                    )
        except OSError as exc:
            raise ReportGenerationError(f"CSV-Bericht konnte nicht erstellt werden: {exc}") from exc
        logger.info("CSV-Bericht erstellt: %s", path)
        return path

    def generate_html(self, snapshot: SystemSnapshot) -> str:
        """Rendert den Snapshot über ein Jinja2-Template als HTML-Datei."""
        # Lazy load optional deps only when actually rendering HTML
        _load_optional_dependencies()
        path = self._build_filename(snapshot, "html")
        if Template is None:
            raise ReportGenerationError(
                "HTML-Berichte erfordern die Bibliothek 'jinja2'. Installiere sie mit 'pip install jinja2'."
            ) from _JINJA2_IMPORT_ERROR
        try:
            template = Template(_HTML_TEMPLATE)
            html_content = template.render(snapshot=snapshot)
            with open(path, "w", encoding="utf-8") as f:
                f.write(html_content)
        except OSError as exc:
            raise ReportGenerationError(f"HTML-Bericht konnte nicht erstellt werden: {exc}") from exc
        logger.info("HTML-Bericht erstellt: %s", path)
        return path

    def generate_pdf(self, snapshot: SystemSnapshot) -> str:
        """Erstellt einen PDF-Bericht mit reportlab (Platypus-Layout-Engine)."""
        # Lazy load reportlab only when creating a PDF
        _load_optional_dependencies()
        path = self._build_filename(snapshot, "pdf")
        if _REPORTLAB_IMPORT_ERROR is not None:
            raise ReportGenerationError(
                "PDF-Berichte erfordern die Bibliothek 'reportlab'. Installiere sie mit 'pip install reportlab'."
            ) from _REPORTLAB_IMPORT_ERROR
        try:
            doc = SimpleDocTemplate(path, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
            styles = getSampleStyleSheet()
            elements = []

            elements.append(Paragraph(f"Systembericht: {snapshot.computer_name}", styles["Title"]))
            elements.append(
                Paragraph(
                    f"Erstellt am {snapshot.timestamp} | Benutzer: {snapshot.user_name}", styles["Normal"]
                )
            )
            elements.append(Spacer(1, 0.5 * cm))

            elements.append(Paragraph("Systemübersicht", styles["Heading2"]))
            overview_data = [
                ["Eigenschaft", "Wert"],
                ["Betriebssystem", f"{snapshot.os_name} {snapshot.os_version} ({snapshot.os_architecture})"],
                ["CPU-Kerne (phys./log.)", f"{snapshot.cpu_physical_cores} / {snapshot.cpu_logical_cores}"],
                ["CPU-Auslastung", f"{snapshot.cpu_percent} %"],
                ["RAM gesamt", f"{snapshot.ram_total_gb} GB"],
                ["RAM genutzt", f"{snapshot.ram_used_gb} GB ({snapshot.ram_percent} %)"],
                ["Uptime", snapshot.uptime_human],
            ]
            elements.append(self._build_table(overview_data))
            elements.append(Spacer(1, 0.5 * cm))

            elements.append(Paragraph("Festplatten", styles["Heading2"]))
            disk_data = [["Laufwerk", "Dateisystem", "Gesamt GB", "Genutzt GB", "Frei GB", "Belegung %"]]
            for disk in snapshot.disks:
                disk_data.append(
                    [disk.mountpoint, disk.fstype, disk.total_gb, disk.used_gb, disk.free_gb, disk.percent_used]
                )
            elements.append(self._build_table(disk_data))
            elements.append(Spacer(1, 0.5 * cm))

            elements.append(Paragraph("Netzwerkschnittstellen", styles["Heading2"]))
            nic_data = [["Name", "IP-Adresse", "MAC-Adresse", "Status"]]
            for nic in snapshot.network_interfaces:
                nic_data.append(
                    [nic.name, nic.ip_address or "-", nic.mac_address or "-", "Aktiv" if nic.is_up else "Inaktiv"]
                )
            elements.append(self._build_table(nic_data))

            doc.build(elements)
        except Exception as exc:  # reportlab kann diverse interne Fehler werfen
            raise ReportGenerationError(f"PDF-Bericht konnte nicht erstellt werden: {exc}") from exc

        logger.info("PDF-Bericht erstellt: %s", path)
        return path

    @staticmethod
    def _build_table(data: list[list]) -> Any:
        str_data = [[str(cell) for cell in row] for row in data]
        table = Table(str_data, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f8fb")]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        return table