"""
core/service_manager.py
-------------------------
Verwaltung von Windows-Diensten: anzeigen, starten, stoppen, Status abfragen.

WARUM IST DAS FÜR EINEN FACHINFORMATIKER SYSTEMINTEGRATION RELEVANT?
Windows-Dienste (z. B. der Druckerwarteschlangen-Dienst "Spooler", der
DNS-Client, der Windows Update-Dienst) sind das Rückgrat des Betriebs-
systems und vieler Serveranwendungen (SQL Server, IIS, AD DS laufen alle
als Dienste). Ein Admin muss Dienste täglich prüfen, neu starten oder bei
Fehlkonfiguration deaktivieren können -- klassisches Troubleshooting
("Dienst X reagiert nicht mehr -> einfach neu starten" ist oft der erste
Lösungsversuch).

VERWENDETE BIBLIOTHEKEN / TECHNIKEN:
  - `psutil.win_service_iter()`: Listet alle Windows-Dienste plattform-
    spezifisch auf (nur unter Windows verfügbar). Liefert Name,
    Anzeigename, Status, Startverhalten.
  - `subprocess` + `sc.exe`: Zum Starten/Stoppen wird bewusst der native
    Windows-Befehl `sc start <Dienst>` / `sc stop <Dienst>` verwendet
    statt der direkten Windows-Service-API (pywin32). Begründung:
      a) `sc.exe` ist auf jedem Windows-System vorhanden (keine
         zusätzliche Abhängigkeit wie `pywin32` nötig).
      b) Die Fehlermeldungen von `sc.exe` (z. B. Zugriff verweigert)
         sind genau das, was ein Admin auch aus der Kommandozeile kennt
         -- das erleichtert das Debuggen.
    ALTERNATIVE für produktiven Einsatz: Das Paket `pywin32`
    (`win32serviceutil.StartService(...)`) bietet eine sauberere,
    programmatische API ohne Textparsing. Das ist als Erweiterungspunkt
    im README dokumentiert.

WICHTIGER SICHERHEITSHINWEIS:
Das Starten/Stoppen von Diensten erfordert unter Windows in der Regel
Administratorrechte. Diese Anwendung sollte daher bei Bedarf "Als
Administrator ausführen" gestartet werden (siehe README, Abschnitt
Installation). Ein versehentliches Stoppen kritischer Systemdienste
(z. B. "RPC Endpoint Mapper") kann das System instabil machen -- die GUI
zeigt deshalb vor kritischen Aktionen eine Sicherheitsabfrage an.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass

from utils.exceptions import InsufficientPrivilegesError, ServiceNotFoundError
from utils.logger import get_logger

logger = get_logger(__name__)

IS_WINDOWS = platform.system().lower() == "windows"


@dataclass
class ServiceInfo:
    name: str
    display_name: str
    status: str  # z. B. "running", "stopped", "start_pending"
    start_type: str | None = None


class ServiceManager:
    """Verwaltung von Windows-Diensten.

    Auf Nicht-Windows-Systemen (wie unserer Linux-Testsandbox) werfen
    die Methoden bewusst eine klare, verständliche Fehlermeldung statt
    eines kryptischen AttributeError -- auch das ist professionelles
    Fehlerverhalten ("Fail gracefully with a clear message").
    """

    @staticmethod
    def _ensure_windows() -> None:
        if not IS_WINDOWS:
            raise RuntimeError(
                "Die Dienstverwaltung ist eine Windows-spezifische Funktion "
                "(psutil.win_service_iter / sc.exe) und auf diesem Betriebssystem "
                "nicht verfügbar."
            )

    @staticmethod
    def list_services() -> list[ServiceInfo]:
        """Listet alle installierten Windows-Dienste auf."""
        ServiceManager._ensure_windows()
        import psutil  # lokal importiert, da win_service_iter nur unter Windows existiert

        services = []
        for svc in psutil.win_service_iter():
            try:
                d = svc.as_dict()
                services.append(
                    ServiceInfo(
                        name=d["name"],
                        display_name=d["display_name"],
                        status=d["status"],
                        start_type=d.get("start_type"),
                    )
                )
            except Exception as exc:  # psutil kann hier diverse WinErrors werfen
                logger.warning("Dienst %s konnte nicht gelesen werden: %s", svc.name(), exc)
        return services

    @staticmethod
    def get_service_status(service_name: str) -> str:
        """Liefert den aktuellen Status eines einzelnen Dienstes."""
        ServiceManager._ensure_windows()
        import psutil

        try:
            svc = psutil.win_service_get(service_name)
            return svc.status()
        except Exception as exc:
            raise ServiceNotFoundError(f"Dienst '{service_name}' nicht gefunden: {exc}") from exc

    @staticmethod
    def _run_sc_command(action: str, service_name: str) -> str:
        """Führt `sc <action> <service_name>` aus und liefert die Ausgabe.

        `action` ist z. B. "start" oder "stop".
        """
        cmd = ["sc", action, service_name]
        logger.info("Führe aus: %s", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        output = proc.stdout + proc.stderr

        if "access is denied" in output.lower() or "zugriff verweigert" in output.lower():
            raise InsufficientPrivilegesError(
                f"Zugriff verweigert beim Versuch, Dienst '{service_name}' zu {action}en. "
                "Anwendung als Administrator ausführen."
            )
        if "does not exist" in output.lower() or "nicht vorhanden" in output.lower():
            raise ServiceNotFoundError(f"Dienst '{service_name}' existiert nicht.")
        return output

    @staticmethod
    def start_service(service_name: str) -> str:
        """Startet einen Windows-Dienst über sc.exe."""
        ServiceManager._ensure_windows()
        result = ServiceManager._run_sc_command("start", service_name)
        logger.info("Dienst '%s' Startbefehl ausgeführt.", service_name)
        return result

    @staticmethod
    def stop_service(service_name: str) -> str:
        """Stoppt einen Windows-Dienst über sc.exe."""
        ServiceManager._ensure_windows()
        result = ServiceManager._run_sc_command("stop", service_name)
        logger.info("Dienst '%s' Stoppbefehl ausgeführt.", service_name)
        return result

    @staticmethod
    def restart_service(service_name: str) -> None:
        """Startet einen Dienst neu (stop, dann start).

        Praxisrelevanz: Der klassische "Have you tried turning it off
        and on again?"-Workflow, hier automatisiert. Zwischen Stop und
        Start wird kurz gewartet, da `sc stop` asynchron zurückkehrt --
        der Dienst befindet sich oft noch im Zustand "STOP_PENDING",
        wenn der Befehl schon zurückkommt.
        """
        import time

        ServiceManager.stop_service(service_name)
        time.sleep(2)
        ServiceManager.start_service(service_name)