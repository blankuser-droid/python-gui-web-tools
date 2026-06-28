"""
core/process_manager.py
-------------------------
Prozessverwaltung: laufende Prozesse anzeigen, suchen, beenden,
CPU- und RAM-Auslastung überwachen.

WARUM IST DAS FÜR EINEN FACHINFORMATIKER SYSTEMINTEGRATION RELEVANT?
Der Taskmanager ist eines der meistgenutzten Werkzeuge im Admin-Alltag:
"Welcher Prozess blockiert die CPU?", "Ist Anwendung X noch lebendig
(hängt) oder bereits abgestürzt?", "Muss ich einen Prozess zwangsweise
beenden?". Dieses Modul bildet exakt diesen Workflow programmatisch ab.

VERWENDETE BIBLIOTHEK:
  - `psutil`: Plattformübergreifender Zugriff auf Prozessliste, CPU-/RAM-
    Nutzung pro Prozess, sowie zum Beenden von Prozessen (terminate/kill).

WICHTIGER UNTERSCHIED terminate() vs. kill():
  - `terminate()` sendet unter Linux SIGTERM (Prozess kann sich selbst
    sauber beenden, z. B. offene Dateien schließen) und unter Windows
    TerminateProcess (dort gibt es kein Äquivalent zu SIGTERM, daher
    praktisch gleichwertig mit kill()).
  - `kill()` sendet unter Linux SIGKILL (sofortiges, hartes Beenden ohne
    Aufräumen). Unter Windows ist kill() ein Alias für terminate().
  Wir bieten beide Optionen an, da es in der Praxis wichtig ist, ZUERST
  ein "sanftes" Beenden zu versuchen und erst bei Bedarf ein hartes.
"""

from __future__ import annotations

from dataclasses import dataclass

import psutil

from utils.exceptions import InsufficientPrivilegesError, ProcessNotFoundError
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProcessInfo:
    pid: int
    name: str
    username: str | None
    cpu_percent: float
    memory_mb: float
    status: str


class ProcessManager:
    """Werkzeuge zur Prozessüberwachung und -steuerung."""

    @staticmethod
    def list_processes(sort_by: str = "cpu_percent") -> list[ProcessInfo]:
        """Liefert alle laufenden Prozesse, standardmäßig nach CPU-Last sortiert.

        Performance-Hinweis: `proc.cpu_percent()` ohne vorheriges "Aufwärmen"
        liefert beim ersten Aufruf 0.0 für JEDEN Prozess (psutil vergleicht
        intern zwei Zeitpunkte). In der GUI lösen wir das, indem die
        Prozessliste regelmäßig (z. B. alle 2 Sekunden) neu abgefragt wird –
        dann sind die Werte ab dem zweiten Aufruf aussagekräftig.
        """
        processes: list[ProcessInfo] = []
        for proc in psutil.process_iter(
            attrs=["pid", "name", "username", "cpu_percent", "memory_info", "status"]
        ):
            try:
                info = proc.info
                memory_mb = info["memory_info"].rss / (1024 ** 2) if info["memory_info"] else 0.0
                processes.append(
                    ProcessInfo(
                        pid=info["pid"],
                        name=info["name"] or "unbekannt",
                        username=info.get("username"),
                        cpu_percent=info.get("cpu_percent") or 0.0,
                        memory_mb=round(memory_mb, 1),
                        status=info.get("status") or "unbekannt",
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Prozess kann zwischen Auflistung und Auslesen beendet
                # worden sein ("Race Condition") -- das ist normal und
                # wird einfach übersprungen statt das Tool abstürzen zu
                # lassen.
                continue

        valid_sort_keys = {"cpu_percent", "memory_mb", "pid", "name"}
        if sort_by in valid_sort_keys:
            processes.sort(key=lambda p: getattr(p, sort_by), reverse=sort_by != "name")
        return processes

    @staticmethod
    def find_process(query: str) -> list[ProcessInfo]:
        """Sucht Prozesse, deren Name die Suchanfrage (Teilstring) enthält."""
        query_lower = query.lower()
        return [p for p in ProcessManager.list_processes() if query_lower in p.name.lower()]

    @staticmethod
    def kill_process(pid: int, force: bool = False) -> None:
        """Beendet einen Prozess anhand seiner PID.

        Args:
            pid: Prozess-ID.
            force: False = terminate() (sanft), True = kill() (hart).
        """
        try:
            proc = psutil.Process(pid)
            proc_name = proc.name()
            if force:
                proc.kill()
            else:
                proc.terminate()
            # Kurz warten, um zu prüfen, ob der Prozess wirklich beendet wurde
            proc.wait(timeout=3)
            logger.info("Prozess %s (PID %d) beendet (force=%s).", proc_name, pid, force)
        except psutil.NoSuchProcess as exc:
            raise ProcessNotFoundError(f"Prozess mit PID {pid} existiert nicht.") from exc
        except psutil.AccessDenied as exc:
            raise InsufficientPrivilegesError(
                f"Keine Berechtigung, Prozess PID {pid} zu beenden. "
                "Tool ggf. als Administrator ausführen."
            ) from exc
        except psutil.TimeoutExpired:
            logger.warning("Prozess PID %d reagiert nicht auf terminate() – ggf. force=True nötig.", pid)

    @staticmethod
    def get_top_consumers(n: int = 5) -> tuple[list[ProcessInfo], list[ProcessInfo]]:
        """Liefert die Top-N Prozesse nach CPU- und nach RAM-Verbrauch.

        Nützlich für das Dashboard: "Was belastet das System aktuell am
        meisten?" ist meist die erste Frage bei Performance-Problemen.
        """
        all_procs = ProcessManager.list_processes(sort_by="cpu_percent")
        top_cpu = all_procs[:n]
        top_ram = sorted(all_procs, key=lambda p: p.memory_mb, reverse=True)[:n]
        return top_cpu, top_ram