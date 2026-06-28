"""
core/disk_manager.py
---------------------
Festplattenverwaltung: freien Speicher anzeigen, Laufwerke analysieren,
große Dateien finden, temporäre Dateien löschen, Papierkorb leeren.

WARUM IST DAS FÜR EINEN FACHINFORMATIKER SYSTEMINTEGRATION RELEVANT?
"Die Festplatte ist voll" ist einer der häufigsten Support-Tickets
überhaupt. Statt von Hand durch Ordner zu klicken, automatisiert dieses
Modul die klassische Analyse: Wo liegt der Speicherfresser? Was kann
gefahrlos gelöscht werden (Temp-Dateien, Papierkorb)?

VERWENDETE BIBLIOTHEKEN:
  - `os` / `pathlib` (Standardbibliothek): Verzeichnisse durchsuchen,
    Dateigrößen ermitteln, Dateien löschen.
  - `psutil` (Drittanbieter): Festplattenbelegung pro Partition
    (siehe auch system_info.py).
  - `shutil` (Standardbibliothek): Papierkorb-Funktionalität wird NICHT
    direkt von shutil unterstützt (shutil.rmtree löscht endgültig!).
    Für den "echten" Windows-Papierkorb (mit Wiederherstellbarkeit)
    bräuchte man unter Windows das Drittanbieter-Paket `send2trash` oder
    die Windows-Shell-API. Das ist hier als Erweiterungspunkt dokumentiert
    (siehe Methode `empty_recycle_bin`).

SICHERHEITSHINWEIS:
Das endgültige Löschen von Dateien (z. B. temporäre Dateien) ist
unwiderruflich. Produktive Tools sollten daher:
  1. Standardmäßig einen "Dry-Run"-Modus anbieten (nur anzeigen, was
     gelöscht WÜRDE, ohne wirklich zu löschen).
  2. Vor dem eigentlichen Löschen eine explizite Bestätigung verlangen.
Beides ist in diesem Modul über den Parameter `dry_run` umgesetzt.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from utils.exceptions import SysAdminToolkitError
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LargeFileInfo:
    path: str
    size_mb: float


@dataclass
class CleanupReport:
    """Ergebnis einer Bereinigungsaktion (Temp-Dateien oder Papierkorb)."""
    files_found: int = 0
    files_deleted: int = 0
    bytes_freed: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = True

    @property
    def mb_freed(self) -> float:
        return round(self.bytes_freed / (1024 ** 2), 2)


class DiskManager:
    """Werkzeuge zur Festplattenverwaltung und -bereinigung."""

    # Typische temporäre Verzeichnisse unter Windows. Unter Linux/macOS
    # (z. B. für Tests in dieser Sandbox) wird zusätzlich /tmp genutzt.
    WINDOWS_TEMP_PATHS = [
        r"C:\Windows\Temp",
        os.path.expandvars(r"%LOCALAPPDATA%\Temp"),
    ]

    @staticmethod
    def get_disk_usage_summary() -> list[dict]:
        """Liefert eine kompakte Übersicht aller Partitionen (für Dashboard/GUI)."""
        summary = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            summary.append(
                {
                    "mountpoint": part.mountpoint,
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "used_gb": round(usage.used / (1024 ** 3), 2),
                    "free_gb": round(usage.free / (1024 ** 3), 2),
                    "percent": usage.percent,
                }
            )
        return summary

    @staticmethod
    def find_large_files(
        root_path: str, min_size_mb: float = 100.0, max_results: int = 50
    ) -> list[LargeFileInfo]:
        """Durchsucht ein Verzeichnis rekursiv nach Dateien über einer Mindestgröße.

        WARUM os.walk STATT pathlib.rglob?
        os.walk erlaubt es, einzelne nicht lesbare Unterverzeichnisse
        (z. B. wegen fehlender Berechtigung) gezielt zu überspringen, ohne
        dass die gesamte Suche abbricht (`onerror`-Parameter bzw. try/except
        pro Verzeichnis). Das ist in echten Firmenumgebungen mit
        Berechtigungsstrukturen wichtig -- ein einzelner geschützter
        Ordner soll die Analyse nicht zum Absturz bringen.
        """
        results: list[LargeFileInfo] = []
        min_size_bytes = min_size_mb * 1024 * 1024

        if not os.path.isdir(root_path):
            raise SysAdminToolkitError(f"Pfad existiert nicht oder ist kein Verzeichnis: {root_path}")

        for dirpath, _dirnames, filenames in os.walk(root_path, onerror=lambda e: logger.warning("Zugriffsfehler: %s", e)):
            for filename in filenames:
                full_path = os.path.join(dirpath, filename)
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    continue
                if size >= min_size_bytes:
                    results.append(LargeFileInfo(path=full_path, size_mb=round(size / (1024 ** 2), 2)))

        results.sort(key=lambda f: f.size_mb, reverse=True)
        return results[:max_results]

    @staticmethod
    def clean_temp_files(dry_run: bool = True, extra_paths: list[str] | None = None) -> CleanupReport:
        """Löscht (oder simuliert das Löschen von) temporären Dateien.

        Args:
            dry_run: Wenn True (Standard!), wird NICHTS gelöscht -- es wird
                nur berechnet, was gelöscht werden würde. Das ist die
                sichere Default-Einstellung; echtes Löschen muss bewusst
                mit dry_run=False angefordert werden ("Opt-in statt Opt-out"
                bei destruktiven Aktionen -- Best Practice in Admin-Tools).
            extra_paths: Zusätzliche, vom Benutzer angegebene Pfade.
        """
        report = CleanupReport(dry_run=dry_run)
        candidate_paths = list(DiskManager.WINDOWS_TEMP_PATHS)
        if os.path.isdir("/tmp"):
            candidate_paths.append("/tmp")
        if extra_paths:
            candidate_paths.extend(extra_paths)

        for base_path in candidate_paths:
            if not base_path or not os.path.isdir(base_path):
                continue
            for dirpath, _dirnames, filenames in os.walk(base_path):
                for filename in filenames:
                    full_path = os.path.join(dirpath, filename)
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        continue
                    report.files_found += 1
                    if dry_run:
                        report.bytes_freed += size
                        continue
                    try:
                        os.remove(full_path)
                        report.files_deleted += 1
                        report.bytes_freed += size
                    except OSError as exc:
                        report.errors.append(f"{full_path}: {exc}")

        logger.info(
            "Temp-Bereinigung (%s): %d Dateien gefunden, %d gelöscht, %.2f MB",
            "Simulation" if dry_run else "AUSGEFÜHRT",
            report.files_found,
            report.files_deleted,
            report.mb_freed,
        )
        return report

    @staticmethod
    def empty_recycle_bin(dry_run: bool = True) -> CleanupReport:
        """Leert den Windows-Papierkorb.

        IMPLEMENTIERUNGSHINWEIS (wichtig für Erweiterung):
        Python bietet keine eingebaute, plattformübergreifende Funktion
        zum Leeren des Windows-Papierkorbs. In einer realen Windows-
        Installation würde man hierfür entweder:

          a) das Drittanbieter-Paket `winshell` nutzen:
             `winshell.recycle_bin().empty(confirm=False, show_progress=False)`
          b) oder direkt die Windows-Shell-API über `ctypes` aufrufen
             (SHEmptyRecycleBinW aus shell32.dll).

        Da diese Sandbox-Umgebung kein Windows ist und `winshell` hier
        nicht sinnvoll testbar ist, ist diese Methode bewusst als
        dokumentierter Erweiterungspunkt umgesetzt: Sie liefert ein
        CleanupReport-Objekt mit einer klaren Fehlermeldung, wenn die
        Funktionalität auf der aktuellen Plattform nicht verfügbar ist,
        und zeigt im Kommentar exakt, wie es auf echtem Windows ergänzt
        werden müsste.
        """
        report = CleanupReport(dry_run=dry_run)
        try:
            import winshell  # type: ignore  # nur unter Windows verfügbar
        except ImportError:
            report.errors.append(
                "Papierkorb-Funktion benötigt das Paket 'winshell' und läuft "
                "nur unter Windows. Installation: pip install winshell pywin32"
            )
            logger.warning("winshell nicht verfügbar – Papierkorb-Funktion übersprungen.")
            return report

        try:
            items = list(winshell.recycle_bin())
            report.files_found = len(items)
            if not dry_run:
                winshell.recycle_bin().empty(confirm=False, show_progress=False, sound=False)
                report.files_deleted = report.files_found
        except Exception as exc:  # winshell kann diverse COM-Fehler werfen
            report.errors.append(str(exc))
            logger.error("Fehler beim Leeren des Papierkorbs: %s", exc)
        return report