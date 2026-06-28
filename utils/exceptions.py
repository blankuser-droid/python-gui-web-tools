"""
utils/exceptions.py
--------------------
Zentrale, projektspezifische Exception-Klassen.

WARUM EIGENE EXCEPTIONS?
Ein häufiger Anfängerfehler ist es, überall mit generischem `except Exception`
zu arbeiten. Das verschleiert, WAS genau schiefgegangen ist (Netzwerkfehler?
Berechtigungsfehler? Datei nicht gefunden?).

Eigene Exception-Klassen erlauben es, in der GUI gezielt zu reagieren, z. B.:

    try:
        service_manager.stop_service("Spooler")
    except InsufficientPrivilegesError:
        show_message("Bitte als Administrator ausführen.")
    except ServiceNotFoundError:
        show_message("Dienst existiert nicht.")

Das ist Best Practice in professioneller Systemintegration-Software und
zeigt im Quellcode sauberes Fehlerkonzept (wichtig für Code-Reviews und
Bewerbungsgespräche).
"""


class SysAdminToolkitError(Exception):
    """Basisklasse für alle Fehler dieses Projekts.

    Jede andere Exception-Klasse im Projekt erbt hiervon. So kann man im
    Notfall mit `except SysAdminToolkitError` ALLE eigenen Fehlerarten
    gemeinsam abfangen, ohne versehentlich auch fremde Bibliotheksfehler
    zu verschlucken.
    """
    pass


class InsufficientPrivilegesError(SysAdminToolkitError):
    """Wird ausgelöst, wenn eine Aktion Administratorrechte benötigt
    (z. B. Dienst starten/stoppen, bestimmte Systeminformationen)."""
    pass


class ServiceNotFoundError(SysAdminToolkitError):
    """Wird ausgelöst, wenn ein angegebener Windows-Dienst nicht existiert."""
    pass


class ProcessNotFoundError(SysAdminToolkitError):
    """Wird ausgelöst, wenn ein Prozess (PID oder Name) nicht gefunden wurde."""
    pass


class NetworkToolError(SysAdminToolkitError):
    """Wird ausgelöst bei Fehlern in Netzwerk-Tools (Ping, Traceroute, etc.)."""
    pass


class BackupError(SysAdminToolkitError):
    """Wird ausgelöst, wenn ein Backup-Vorgang fehlschlägt
    (z. B. Quellordner nicht erreichbar, Zielpfad voll)."""
    pass


class ConfigError(SysAdminToolkitError):
    """Wird ausgelöst bei fehlerhafter oder fehlender Konfiguration."""
    pass


class ReportGenerationError(SysAdminToolkitError):
    """Wird ausgelöst, wenn die Erstellung eines Berichts (PDF/HTML/CSV/JSON)
    fehlschlägt."""
    pass