"""
config/config_manager.py
-------------------------
Verwaltung der Anwendungskonfiguration.

WARUM EINE KONFIGURATIONSDATEI STATT FEST IM CODE VERDRAHTETER WERTE?
Ein zentrales Prinzip professioneller Software ist die Trennung von Code
und Konfiguration ("Separation of Concerns"). Beispiele, warum das wichtig
ist:

  - Der Pfad für Backups soll vom Anwender geändert werden können, ohne
    den Quellcode anzufassen oder die Anwendung neu zu kompilieren/bauen.
  - Schwellenwerte für Monitoring-Warnungen (z. B. "CPU > 80 % = Warnung")
    sind je nach Unternehmen unterschiedlich und müssen anpassbar sein.
  - In einer echten Firmenumgebung würde man Konfigurationsdateien sogar
    zentral über Gruppenrichtlinien oder ein Configuration-Management-Tool
    (Ansible, Puppet) verteilen – das funktioniert nur, wenn Konfiguration
    von Code getrennt ist.

Wir verwenden JSON statt z. B. INI oder YAML, weil:
  - JSON ist in der Python-Standardbibliothek (`json`-Modul) ohne
    Zusatzinstallation nutzbar.
  - JSON unterstützt verschachtelte Strukturen (wichtig für Gruppen wie
    "network", "backup", "monitoring").
  - JSON ist in nahezu jeder Programmiersprache lesbar, falls später z. B.
    ein Web-Dashboard dieselbe Konfiguration mitlesen soll.

ALTERNATIVE: Für sehr komplexe, von Menschen häufig editierte Configs wäre
YAML oft angenehmer zu lesen (Kommentare möglich!). Für dieses Tool ist
JSON jedoch völlig ausreichend und reduziert Abhängigkeiten.
"""

import json
import os
import shutil
from typing import Any

from utils.exceptions import ConfigError
from utils.logger import get_logger

logger = get_logger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "config", "default_config.json")
USER_CONFIG_PATH = os.path.join(BASE_DIR, "config", "user_config.json")


class ConfigManager:
    """Lädt, validiert, liefert und speichert die Anwendungskonfiguration.

    Funktionsweise:
        1. Beim ersten Start existiert nur `default_config.json`.
        2. Diese wird beim ersten Start nach `user_config.json` kopiert.
        3. Ab dann liest/schreibt die Anwendung ausschließlich
           `user_config.json`, sodass Benutzeränderungen erhalten bleiben,
           selbst wenn das Tool aktualisiert wird (default_config.json
           würde bei einem Update überschrieben, user_config.json nicht).

    Dieses Muster ("Default + User-Override") ist Standard in vielen
    professionellen Anwendungen (z. B. VS Code: settings.default.json vs.
    settings.json).
    """

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(USER_CONFIG_PATH):
            logger.info("Keine user_config.json gefunden – erstelle aus Default.")
            try:
                shutil.copyfile(DEFAULT_CONFIG_PATH, USER_CONFIG_PATH)
            except OSError as exc:
                raise ConfigError(
                    f"Konnte Standardkonfiguration nicht kopieren: {exc}"
                ) from exc

        try:
            with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            logger.info("Konfiguration erfolgreich geladen aus %s", USER_CONFIG_PATH)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Fehler beim Laden der Konfiguration: %s", exc)
            raise ConfigError(f"Konfiguration konnte nicht gelesen werden: {exc}") from exc

    def get(self, *keys: str, default: Any = None) -> Any:
        """Liest einen verschachtelten Konfigurationswert.

        Beispiel:
            config.get("network", "default_ping_count")
            -> entspricht config_dict["network"]["default_ping_count"]

        Args:
            *keys: Pfad durch die verschachtelte Konfiguration.
            default: Rückgabewert, falls der Schlüssel nicht existiert.
        """
        node: Any = self._config
        for key in keys:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return default
        return node

    def set(self, *keys: str, value: Any) -> None:
        """Setzt einen verschachtelten Konfigurationswert (im Speicher).

        Ruft NICHT automatisch save() auf – das muss bewusst geschehen,
        damit nicht bei jeder kleinen Änderung sofort auf die Festplatte
        geschrieben wird (Performance, und man kann mehrere Änderungen
        sammeln und dann gemeinsam speichern).
        """
        if not keys:
            raise ConfigError("Mindestens ein Schlüssel erforderlich.")
        node = self._config
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    def save(self) -> None:
        """Schreibt die aktuelle Konfiguration zurück auf die Festplatte."""
        try:
            with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.info("Konfiguration gespeichert.")
        except OSError as exc:
            logger.error("Fehler beim Speichern der Konfiguration: %s", exc)
            raise ConfigError(f"Konfiguration konnte nicht gespeichert werden: {exc}") from exc

    def reset_to_defaults(self) -> None:
        """Setzt die Konfiguration auf die Werkseinstellungen zurück."""
        shutil.copyfile(DEFAULT_CONFIG_PATH, USER_CONFIG_PATH)
        self._load()
        logger.warning("Konfiguration wurde auf Standardwerte zurückgesetzt.")


# Singleton-Instanz: Im gesamten Projekt wird dieselbe Konfiguration genutzt,
# anstatt dass jedes Modul seine eigene Kopie lädt. Das verhindert
# inkonsistente Zustände (Modul A liest alte Werte, Modul B neue Werte).
config = ConfigManager()