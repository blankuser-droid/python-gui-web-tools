"""
gui/workers.py
----------------
Generischer Hintergrund-Worker, um zeitintensive Operationen (Ping,
Portscan, Backup, Skriptausführung) NICHT im GUI-Thread auszuführen.

WARUM IST DAS WICHTIG? (Eines der häufigsten Anfängerprobleme bei GUI-Apps!)
Qt (wie praktisch jedes GUI-Framework) hat EINEN zentralen "Event-Loop"-
Thread, der für Zeichnen, Mausklicks, Tastatureingaben usw. zuständig ist.
Führt man eine lang dauernde Operation (z. B. einen Portscan über 1000
Ports, der mehrere Sekunden dauert) DIREKT in einem Button-Klick-Handler
aus, friert die GESAMTE Anwendung für die Dauer der Operation ein
("Application not responding" / weißes Fenster). Das ist für ein
professionelles Admin-Tool nicht akzeptabel.

LÖSUNG: Die eigentliche Arbeit läuft in einem separaten `QThread`. Der
Worker sendet über Qt-Signale (`finished`, `error`, `progress`) Ergebnisse
zurück an den GUI-Thread, wo sie sicher angezeigt werden dürfen (Qt-
Widgets dürfen NUR aus dem GUI-Thread heraus verändert werden -- das ist
eine harte Regel von Qt, deren Missachtung zu Abstürzen führen kann).

Dieses Muster (QThread + Signals) ist der Standardweg in PySide6/PyQt für
"Fire-and-forget"-Hintergrundaufgaben mit Ergebnis-Rückmeldung.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal


class WorkerSignals(QObject):
    """Sammlung der Signale, die ein Worker während/nach seiner Arbeit sendet."""
    finished = Signal(object)   # Ergebnis der Funktion (beliebiger Typ)
    error = Signal(str)         # Fehlermeldung als Text
    started = Signal()


class FunctionWorker(QThread):
    """Führt eine beliebige Python-Funktion in einem eigenen Thread aus.

    Verwendung in einer Page:

        self.worker = FunctionWorker(NetworkTools.ping, "8.8.8.8", count=4)
        self.worker.signals.finished.connect(self._on_ping_done)
        self.worker.signals.error.connect(self._on_ping_error)
        self.worker.start()

    Wichtig: Eine Referenz auf den Worker (`self.worker = ...`) MUSS
    gehalten werden, solange er läuft -- sonst räumt Python das Objekt
    ggf. vorzeitig per Garbage Collection ab, was zu Abstürzen führt.
    """

    def __init__(self, func: Callable, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        """Wird von Qt automatisch im neuen Thread aufgerufen (durch .start())."""
        self.signals.started.emit()
        try:
            result = self._func(*self._args, **self._kwargs)
            self.signals.finished.emit(result)
        except Exception as exc:  # bewusst breit, da hier JEDER Fehler aus
            # der Geschäftslogik (NetworkToolError, BackupError, ...)
            # sicher an die GUI weitergereicht werden muss, statt den
            # Hintergrundthread (und damit unbemerkt die Funktion) crashen
            # zu lassen.
            self.signals.error.emit(str(exc))