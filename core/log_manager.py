"""
core/log_manager.py
---------------------
Log-Verwaltung: Windows-Ereignisprotokolle auslesen, eigene Anwendungs-Logs
erstellen, Fehler übersichtlich darstellen.

WARUM IST DAS FÜR EINEN FACHINFORMATIKER SYSTEMINTEGRATION RELEVANT?
Die Ereignisanzeige (eventvwr.msc) ist nach Taskmanager und Ping das
dritthäufigste Werkzeug bei der Fehlerdiagnose unter Windows: "Warum ist
der Server gestern Nacht neu gestartet?", "Welcher Dienst hat einen Fehler
gemeldet, bevor die Anwendung abgestürzt ist?" -- die Antworten stehen
fast immer im Ereignisprotokoll (System, Anwendung, Sicherheit).

VERWENDETE BIBLIOTHEKEN / TECHNIKEN:
  - `win32evtlog` aus dem Paket `pywin32`: Der Standardweg, um unter
    Python auf die Windows-Ereignisprotokolle zuzugreifen. Da `pywin32`
    in dieser Linux-Sandbox nicht sinnvoll nutzbar ist, ist der Code so
    geschrieben, dass er den Import zur Laufzeit (nicht beim Programmstart)
    durchführt und bei Nichtverfügbarkeit eine klare Fehlermeldung liefert
    -- exakt das gleiche Muster wie im service_manager.py.
  - `logging` (Standardbibliothek) für die EIGENEN Anwendungs-Logs --
    siehe utils/logger.py, das zentral im ganzen Projekt verwendet wird.

ALTERNATIVE: Auf neueren Windows-Versionen kann man Ereignisprotokolle
auch über PowerShell (`Get-WinEvent`) auslesen und das Ergebnis als JSON
zurückgeben (`ConvertTo-Json`). Das haben wir bewusst NICHT als Hauptweg
gewählt, weil das Starten eines PowerShell-Subprozesses pro Abfrage
langsamer ist als die native win32evtlog-API. Es ist aber als alternative
Implementierung im README als Erweiterungsmöglichkeit dokumentiert.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger(__name__)

IS_WINDOWS = platform.system().lower() == "windows"


@dataclass
class EventLogEntry:
    time_generated: str
    source: str
    event_id: int
    event_type: str  # "Error", "Warning", "Information"
    message: str


class LogManager:
    """Liest Windows-Ereignisprotokolle und verwaltet eigene Log-Dateien."""

    # Mapping der numerischen Windows-Event-Typen auf lesbare Strings.
    _EVENT_TYPE_MAP = {
        1: "Error",
        2: "Warning",
        4: "Information",
        8: "Success Audit",
        16: "Failure Audit",
    }

    @staticmethod
    def read_event_log(log_type: str = "System", max_entries: int = 50) -> list[EventLogEntry]:
        """Liest die letzten Einträge eines Windows-Ereignisprotokolls.

        Args:
            log_type: "System", "Application" oder "Security".
            max_entries: Maximale Anzahl der zurückgegebenen, neuesten Einträge.
        """
        if not IS_WINDOWS:
            raise RuntimeError(
                "Das Auslesen von Windows-Ereignisprotokollen ist nur unter "
                "Windows verfügbar (benötigt pywin32 / win32evtlog)."
            )

        try:
            import win32evtlog  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Paket 'pywin32' nicht installiert. Installation: pip install pywin32"
            ) from exc

        entries: list[EventLogEntry] = []
        handle = win32evtlog.OpenEventLog(None, log_type)
        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ

        try:
            while len(entries) < max_entries:
                records = win32evtlog.ReadEventLog(handle, flags, 0)
                if not records:
                    break
                for record in records:
                    if len(entries) >= max_entries:
                        break
                    entries.append(
                        EventLogEntry(
                            time_generated=str(record.TimeGenerated),
                            source=record.SourceName,
                            event_id=record.EventID & 0xFFFF,  # untere 16 Bit = eigentliche ID
                            event_type=LogManager._EVENT_TYPE_MAP.get(record.EventType, "Unbekannt"),
                            message=", ".join(record.StringInserts or []),
                        )
                    )
        finally:
            win32evtlog.CloseEventLog(handle)

        logger.info("%d Ereignisprotokoll-Einträge aus '%s' gelesen.", len(entries), log_type)
        return entries

    @staticmethod
    def filter_errors_and_warnings(entries: list[EventLogEntry]) -> list[EventLogEntry]:
        """Filtert eine Liste von Log-Einträgen auf Fehler und Warnungen.

        Das ist die typische erste Triage bei der Fehlersuche: Hunderte
        Informationsmeldungen sind meist irrelevant, Fehler/Warnungen
        verdienen Aufmerksamkeit.
        """
        return [e for e in entries if e.event_type in ("Error", "Warning", "Failure Audit")]