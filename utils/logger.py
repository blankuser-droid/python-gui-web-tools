"""
utils/logger.py
----------------
Zentrales Logging-Setup für das gesamte Projekt.

WARUM EIN EIGENES LOGGING-MODUL?
In professioneller Software druckt man Fehler NICHT einfach mit `print()`
aus. Gründe:

1. `print()` verschwindet, sobald das Terminal/die App geschlossen wird.
   Ein Admin-Tool MUSS aber nachvollziehbar protokollieren, was passiert ist
   (z. B. "Wer hat wann welchen Dienst gestoppt?").
2. Logging kennt Stufen (DEBUG, INFO, WARNING, ERROR, CRITICAL) – so kann
   man im Betrieb nur Fehler anzeigen lassen, in der Entwicklung aber alles.
3. Logging kann gleichzeitig in eine Datei UND auf die Konsole schreiben.

Dieses Modul stellt eine zentrale Funktion `get_logger()` bereit, die jedes
andere Modul importiert. So hat jedes Modul (system_info, network_tools, ...)
seinen eigenen, klar erkennbaren Logger-Namen, aber alle schreiben in
dieselbe Logdatei unter data/logs/sysadmin_toolkit.log.

Verwendete Bibliothek: `logging` (Python-Standardbibliothek, keine
Zusatzinstallation nötig – das ist bewusst so gewählt, damit das Tool
ohne viele Abhängigkeiten läuft).
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# Basisverzeichnis des Projekts (zwei Ebenen über dieser Datei)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "data", "logs")
LOG_FILE = os.path.join(LOG_DIR, "sysadmin_toolkit.log")

os.makedirs(LOG_DIR, exist_ok=True)

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Wird einmal pro Prozess initialisiert, damit nicht mehrfach Handler
# angehängt werden (sonst tauchen Log-Zeilen doppelt/dreifach auf).
_initialized = False


def _setup_root_logger(level: int = logging.INFO) -> None:
    """Initialisiert den Root-Logger einmalig mit Datei- und Konsolen-Handler.

    RotatingFileHandler statt einfachem FileHandler:
    -> Begrenzung der Dateigröße (hier 2 MB, 5 Backups). In der Praxis
       laufen Logdateien ohne Rotation nach Monaten auf mehrere GB an und
       verstopfen die Festplatte. Das ist ein klassischer Admin-Fehler,
       den wir hier von Anfang an vermeiden.
    """
    global _initialized
    if _initialized:
        return

    root_logger = logging.getLogger("sysadmin_toolkit")
    root_logger.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    _initialized = True


def get_logger(module_name: str) -> logging.Logger:
    """Liefert einen Logger für ein bestimmtes Modul zurück.

    Beispiel-Verwendung in einem anderen Modul:

        from utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Dienst erfolgreich gestartet")
        logger.error("Zugriff verweigert", exc_info=True)

    Args:
        module_name: Üblicherweise __name__ des aufrufenden Moduls.

    Returns:
        Ein konfigurierter logging.Logger, der Ausgaben in die
        zentrale Logdatei und auf die Konsole schreibt.
    """
    _setup_root_logger()
    return logging.getLogger(f"sysadmin_toolkit.{module_name}")