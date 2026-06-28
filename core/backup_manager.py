"""
core/backup_manager.py
------------------------
Backup-Funktionen: Ordner sichern, ZIP-Backup erstellen, Backup-Protokoll,
Grundlage für automatische/geplante Backups.

WARUM IST DAS FÜR EINEN FACHINFORMATIKER SYSTEMINTEGRATION RELEVANT?
Backups sind die "Lebensversicherung" jeder IT-Infrastruktur. In der
Abschlussprüfung Teil 2 und im Berufsalltag wird die 3-2-1-Regel quasi
immer vorausgesetzt:
  - 3 Kopien der Daten (1 Original + 2 Backups)
  - 2 unterschiedliche Speichermedien (z. B. lokale HDD + NAS/Cloud)
  - 1 Kopie extern / offsite (Schutz vor Diebstahl, Brand, Ransomware)

Dieses Modul implementiert den TECHNISCHEN Teil (Daten sichern, komprimieren,
protokollieren). Das STRATEGISCHE Backup-Konzept (3-2-1-Regel, Rotation,
Aufbewahrungsfristen) gehört zur Dokumentation und wird in README.md /
im TechSolutions-Projekt separat ausgearbeitet.

VERWENDETE BIBLIOTHEKEN:
  - `shutil` (Standardbibliothek): `shutil.make_archive()` für ZIP-Erstellung,
    `shutil.copytree()` für unkomprimierte 1:1-Kopien.
  - `zipfile` (Standardbibliothek): für detaillierte Kontrolle beim
    Hinzufügen einzelner Dateien (z. B. um Fortschritt zu protokollieren).
  - `json` (Standardbibliothek): Backup-Protokoll als maschinenlesbare
    JSON-Datei (zusätzlich zu menschenlesbarem Logging).
  - `hashlib`: SHA-256-Prüfsumme der erzeugten ZIP-Datei, um die
    Integrität des Backups nachträglich verifizieren zu können
    ("Ist das Backup wirklich vollständig und unbeschädigt?" -- ein
    Punkt, den professionelle Backup-Lösungen wie Veeam ebenfalls bieten).

WARUM ZIP UND NICHT TAR/7Z?
ZIP ist sowohl unter Windows als auch Linux nativ ohne Zusatzsoftware
lesbar (Windows Explorer kann ZIP direkt öffnen). Für ein Cross-Plattform-
Tool, das primär auf Windows läuft, ist das die pragmatischste Wahl.
TAR.GZ hätte ggf. eine etwas bessere Kompression bei Textdateien, ist
aber unter Windows ohne Zusatzsoftware unhandlicher.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field

from utils.exceptions import BackupError
from utils.logger import get_logger

logger = get_logger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")
BACKUP_LOG_PATH = os.path.join(BASE_DIR, "data", "backups", "backup_log.json")


@dataclass
class BackupResult:
    source_path: str
    archive_path: str
    size_mb: float
    sha256: str
    duration_seconds: float
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    success: bool = True
    error_message: str | None = None


class BackupManager:
    """Erstellt und protokolliert Backups."""

    def __init__(self, backup_dir: str = DEFAULT_BACKUP_DIR) -> None:
        self.backup_dir = backup_dir
        os.makedirs(self.backup_dir, exist_ok=True)

    @staticmethod
    def _calculate_sha256(file_path: str) -> str:
        """Berechnet die SHA-256-Prüfsumme einer Datei.

        Die Datei wird in 8-KB-Blöcken gelesen statt vollständig in den
        Speicher geladen ("Chunked Reading") -- bei großen Backup-Dateien
        (mehrere GB) würde das Laden der gesamten Datei in den RAM sonst
        zu Speicherproblemen führen.
        """
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def create_zip_backup(self, source_path: str, backup_name: str | None = None) -> BackupResult:
        """Erstellt ein komprimiertes ZIP-Backup eines Ordners.

        Args:
            source_path: Zu sicherndes Verzeichnis.
            backup_name: Optionaler Name; falls None wird automatisch ein
                Name mit Zeitstempel generiert (verhindert versehentliches
                Überschreiben älterer Backups).
        """
        if not os.path.isdir(source_path):
            raise BackupError(f"Quellordner existiert nicht: {source_path}")

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        folder_name = os.path.basename(os.path.normpath(source_path))
        name = backup_name or f"{folder_name}_{timestamp}"
        archive_base = os.path.join(self.backup_dir, name)

        start = time.time()
        try:
            # shutil.make_archive fügt automatisch die Endung ".zip" an
            archive_path = shutil.make_archive(archive_base, "zip", root_dir=source_path)
        except (OSError, shutil.Error) as exc:
            logger.error("Backup fehlgeschlagen für %s: %s", source_path, exc)
            result = BackupResult(
                source_path=source_path,
                archive_path="",
                size_mb=0.0,
                sha256="",
                duration_seconds=round(time.time() - start, 2),
                success=False,
                error_message=str(exc),
            )
            self._append_to_log(result)
            raise BackupError(f"Backup fehlgeschlagen: {exc}") from exc

        duration = round(time.time() - start, 2)
        size_mb = round(os.path.getsize(archive_path) / (1024 ** 2), 2)
        checksum = self._calculate_sha256(archive_path)

        result = BackupResult(
            source_path=source_path,
            archive_path=archive_path,
            size_mb=size_mb,
            sha256=checksum,
            duration_seconds=duration,
        )
        logger.info(
            "Backup erfolgreich: %s -> %s (%.2f MB, %.2f s, SHA256=%s...)",
            source_path, archive_path, size_mb, duration, checksum[:12],
        )
        self._append_to_log(result)
        return result

    def _append_to_log(self, result: BackupResult) -> None:
        """Hängt das Backup-Ergebnis an das persistente JSON-Backup-Protokoll an.

        WARUM EIN SEPARATES BACKUP-PROTOKOLL (zusätzlich zum allgemeinen
        Logging)? Ein Backup-Protokoll muss langfristig auswertbar und
        strukturiert (maschinenlesbar) sein, z. B. um später automatisch
        zu prüfen: "Wurden in den letzten 7 Tagen täglich Backups
        erstellt?" Das allgemeine Text-Log ist dafür nicht geeignet.
        """
        entries = []
        if os.path.exists(BACKUP_LOG_PATH):
            try:
                with open(BACKUP_LOG_PATH, "r", encoding="utf-8") as f:
                    entries = json.load(f)
            except (json.JSONDecodeError, OSError):
                entries = []

        entries.append(result.__dict__)

        with open(BACKUP_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)

    @staticmethod
    def get_backup_log() -> list[dict]:
        """Liest das vollständige Backup-Protokoll (für die GUI/Reports)."""
        if not os.path.exists(BACKUP_LOG_PATH):
            return []
        try:
            with open(BACKUP_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Backup-Protokoll konnte nicht gelesen werden: %s", exc)
            return []

    def cleanup_old_backups(self, keep_versions: int = 5) -> int:
        """Löscht alte Backup-Archive, sodass nur die N neuesten erhalten bleiben.

        WARUM ROTATION WICHTIG IST: Ohne Rotation füllt sich die
        Backup-Festplatte irgendwann komplett -- ein klassischer
        Anfängerfehler, der dazu führt, dass irgendwann GAR KEIN Backup
        mehr erstellt werden kann (kein Speicherplatz mehr frei), genau
        dann, wenn man es am dringendsten bräuchte.

        Returns:
            Anzahl der gelöschten Archive.
        """
        zip_files = [
            os.path.join(self.backup_dir, f)
            for f in os.listdir(self.backup_dir)
            if f.endswith(".zip")
        ]
        zip_files.sort(key=os.path.getmtime, reverse=True)  # neueste zuerst

        to_delete = zip_files[keep_versions:]
        for path in to_delete:
            try:
                os.remove(path)
                logger.info("Altes Backup gelöscht (Rotation): %s", path)
            except OSError as exc:
                logger.warning("Konnte altes Backup nicht löschen: %s", exc)
        return len(to_delete)