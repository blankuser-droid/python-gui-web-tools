"""
core/automation.py
--------------------
Automatisierung: eigene PowerShell/Bash-Skripte speichern und ausführen,
geplante Wartungsaufgaben, kombinierte Systembereinigung.

WARUM IST DAS FÜR EINEN FACHINFORMATIKER SYSTEMINTEGRATION RELEVANT?
"Wenn du etwas zweimal von Hand machst, automatisiere es beim dritten
Mal" ist eine Kerneinstellung professioneller Systemadministration.
PowerShell (Windows) und Bash (Linux) sind die zwei zentralen
Skriptsprachen, die in der Ausbildung zum Fachinformatiker für
Systemintegration explizit gefordert werden (siehe Rahmenlehrplan).

Dieses Modul ist bewusst KEIN vollwertiger Skript-Interpreter, sondern ein
sicherer "Runner": Es verwaltet Skript-Dateien an einem zentralen Ort und
führt sie kontrolliert mit Zeitlimit (Timeout) und Ergebnis-Logging aus --
exakt das, was man von einem Orchestrierungs-Werkzeug erwartet.

VERWENDETE BIBLIOTHEKEN:
  - `subprocess`: Ausführen von .ps1 (über `powershell.exe -File`) bzw.
    .sh (über `bash`) Skripten.
  - `pathlib` / `os`: Verwaltung der Skriptdateien.

SICHERHEITSHINWEIS (SEHR WICHTIG):
Das Ausführen von Skripten ist potenziell gefährlich (ein Skript kann
beliebigen Code ausführen). Diese Klasse implementiert daher bewusst:
  1. Einen festen Skript-Ordner (`data/scripts`) -- es können nur Skripte
     ausgeführt werden, die dort liegen, nicht beliebige Pfade im System
     (verhindert versehentliches/böswilliges Ausführen von Fremdskripten).
  2. Ein Timeout für jede Ausführung (verhindert "hängende" Skripte, die
     die GUI blockieren).
  3. Vollständiges Logging jeder Ausführung (Nachvollziehbarkeit -- wer
     hat wann welches Skript mit welchem Ergebnis ausgeführt).

PowerShell-ExecutionPolicy: Windows blockiert standardmäßig die
Ausführung von .ps1-Skripten ("Restricted"). Für eigene, vertrauenswürdige
Skripte ist `-ExecutionPolicy Bypass` (NUR für den einzelnen Aufruf, nicht
systemweit!) der gängige, sichere Mittelweg -- das ändert NICHT die
globale Richtlinie des Systems, sondern gilt nur für diesen einen Prozess.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from dataclasses import dataclass, field

from utils.exceptions import SysAdminToolkitError
from utils.logger import get_logger

logger = get_logger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCRIPT_DIR = os.path.join(BASE_DIR, "data", "scripts")

IS_WINDOWS = platform.system().lower() == "windows"


@dataclass
class ScriptExecutionResult:
    script_name: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    success: bool
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


class AutomationManager:
    """Verwaltet und führt eigene Wartungs-Skripte (PowerShell/Bash) aus."""

    ALLOWED_EXTENSIONS = {".ps1", ".sh", ".py"}

    def __init__(self, script_dir: str = DEFAULT_SCRIPT_DIR) -> None:
        self.script_dir = script_dir
        os.makedirs(self.script_dir, exist_ok=True)

    def save_script(self, name: str, content: str) -> str:
        """Speichert ein Skript im zentralen, kontrollierten Skript-Ordner.

        Args:
            name: Dateiname inkl. Endung, z. B. 'backup_check.ps1'.
            content: Skriptinhalt als Text.

        Raises:
            SysAdminToolkitError: Wenn die Dateiendung nicht erlaubt ist
                oder der Name versucht, das Skriptverzeichnis zu
                verlassen (z. B. '../../bösartig.ps1' -- Schutz vor
                "Path Traversal").
        """
        safe_name = os.path.basename(name)  # entfernt jeden Pfadanteil
        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise SysAdminToolkitError(
                f"Dateiendung '{ext}' nicht erlaubt. Erlaubt: {', '.join(self.ALLOWED_EXTENSIONS)}"
            )

        path = os.path.join(self.script_dir, safe_name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Skript gespeichert: %s", path)
        return path

    def list_scripts(self) -> list[str]:
        """Listet alle gespeicherten Skripte im zentralen Ordner auf."""
        return sorted(
            f for f in os.listdir(self.script_dir)
            if os.path.splitext(f)[1].lower() in self.ALLOWED_EXTENSIONS
        )

    def run_script(self, name: str, timeout_seconds: int = 60) -> ScriptExecutionResult:
        """Führt ein gespeichertes Skript aus und protokolliert das Ergebnis.

        WICHTIG: Es kann ausschließlich ein Skript ausgeführt werden, das
        sich physisch im `script_dir` befindet -- `os.path.basename()`
        verhindert, dass über den `name`-Parameter ein anderer Pfad
        (z. B. außerhalb des erlaubten Ordners) angegeben werden kann.
        """
        safe_name = os.path.basename(name)
        path = os.path.join(self.script_dir, safe_name)
        if not os.path.isfile(path):
            raise SysAdminToolkitError(f"Skript nicht gefunden: {safe_name}")

        ext = os.path.splitext(safe_name)[1].lower()
        if ext == ".ps1":
            cmd = ["powershell.exe" if IS_WINDOWS else "pwsh", "-NoProfile",
                   "-ExecutionPolicy", "Bypass", "-File", path]
        elif ext == ".sh":
            cmd = ["bash", path]
        elif ext == ".py":
            cmd = ["python", path] if IS_WINDOWS else ["python3", path]
        else:
            raise SysAdminToolkitError(f"Nicht unterstützter Skripttyp: {ext}")

        logger.info("Führe Skript aus: %s", " ".join(cmd))
        start = time.time()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_seconds
            )
            duration = round(time.time() - start, 2)
            result = ScriptExecutionResult(
                script_name=safe_name,
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_seconds=duration,
                success=proc.returncode == 0,
            )
        except subprocess.TimeoutExpired as exc:
            duration = round(time.time() - start, 2)
            result = ScriptExecutionResult(
                script_name=safe_name,
                exit_code=-1,
                stdout=exc.stdout or "",
                stderr=f"Zeitlimit ({timeout_seconds}s) überschritten.",
                duration_seconds=duration,
                success=False,
            )
        except FileNotFoundError as exc:
            raise SysAdminToolkitError(
                f"Interpreter für '{ext}' nicht gefunden: {exc}"
            ) from exc

        log_level = logger.info if result.success else logger.warning
        log_level(
            "Skript '%s' beendet (Exit-Code %d, %.2fs)",
            safe_name, result.exit_code, result.duration_seconds,
        )
        return result

    @staticmethod
    def get_sample_scripts() -> dict[str, str]:
        """Liefert vorgefertigte Beispiel-Skripte (PowerShell + Bash),
        die direkt gespeichert und ausgeführt werden können.

        Das ist gleichzeitig Lernmaterial: Die Skripte zeigen typische
        Wartungsaufgaben, wie sie im Berufsalltag vorkommen.
        """
        powershell_disk_report = (
            "# disk_report.ps1\n"
            "# Zeigt die Festplattenbelegung aller Laufwerke an.\n"
            "Get-Volume | Where-Object DriveLetter | "
            "Select-Object DriveLetter, FileSystemLabel, "
            "@{N='SizeGB';E={[math]::Round($_.Size/1GB,2)}}, "
            "@{N='FreeGB';E={[math]::Round($_.SizeRemaining/1GB,2)}} | "
            "Format-Table -AutoSize\n"
        )
        bash_cleanup = (
            "#!/bin/bash\n"
            "# cleanup.sh - einfache Systembereinigung unter Linux\n"
            "echo 'Bereinige APT-Cache...'\n"
            "apt-get clean 2>/dev/null\n"
            "echo 'Lösche temporäre Dateien älter als 7 Tage...'\n"
            "find /tmp -type f -mtime +7 -delete 2>/dev/null\n"
            "echo 'Fertig.'\n"
        )
        return {
            "disk_report.ps1": powershell_disk_report,
            "cleanup.sh": bash_cleanup,
        }