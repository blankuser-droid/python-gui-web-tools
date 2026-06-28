"""
core/system_info.py
--------------------
Sammelt Systeminformationen: Computername, Benutzer, OS, CPU, RAM,
Festplatten, Netzwerkkarten, IP/MAC-Adressen, Uptime.

WARUM IST DAS FÜR EINEN FACHINFORMATIKER SYSTEMINTEGRATION RELEVANT?
Die allererste Tätigkeit bei jedem Support-Fall oder jeder Inventarisierung
ist die Erfassung des Systemzustands ("Welche Hardware/Software läuft hier
überhaupt?"). Genau das automatisiert dieses Modul – vergleichbar mit dem,
was kommerzielle Inventarisierungstools (z. B. Lansweeper, PDQ Inventory)
im Kern tun.

VERWENDETE BIBLIOTHEKEN:
  - `platform` (Standardbibliothek): Betriebssystem, Architektur, Hostname.
  - `socket` (Standardbibliothek): Hostname, lokale IP-Adresse.
  - `psutil` (Drittanbieter, sehr verbreitet in Sysadmin-Tools): CPU-Kerne
    und -Auslastung, Arbeitsspeicher, Festplattenpartitionen und deren
    Belegung, Netzwerkschnittstellen samt IP/MAC, Systemstartzeit (Uptime).
    psutil ist plattformübergreifend (Windows/Linux/macOS) und genau
    deswegen DER De-facto-Standard für solche Tools in Python.
  - `getpass` (Standardbibliothek): aktueller Benutzername, funktioniert
    auch dann, wenn Umgebungsvariablen wie USERNAME nicht gesetzt sind.
  - `uuid` (Standardbibliothek): wird hier als Fallback für MAC-Adressen
    genutzt, falls psutil auf einer Schnittstelle keine MAC liefert.

ALTERNATIVE OHNE PSUTIL:
Man könnte auf Windows direkt WMI (`wmic`-Befehle oder das `wmi`-Paket)
nutzen. Das liefert teils detailliertere Informationen (z. B. genaue
Mainboard-Seriennummer), ist aber Windows-exklusiv. Da unser Tool laut
Anforderung für Windows 10/11 gedacht ist, aber sauber, portabel und
wartbar bleiben soll, ist psutil die bessere Wahl – WMI-Aufrufe könnten
aber als Erweiterung ergänzt werden (siehe README, Abschnitt "Erweiterungs-
möglichkeiten").
"""

from __future__ import annotations

import getpass
import platform
import socket
import time
from dataclasses import dataclass, field

import psutil

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DiskInfo:
    """Repräsentiert eine einzelne Festplattenpartition."""
    device: str
    mountpoint: str
    fstype: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent_used: float


@dataclass
class NetworkInterfaceInfo:
    """Repräsentiert eine einzelne Netzwerkschnittstelle."""
    name: str
    ip_address: str | None
    mac_address: str | None
    is_up: bool


@dataclass
class SystemSnapshot:
    """Ein vollständiger 'Schnappschuss' des Systemzustands zu einem
    bestimmten Zeitpunkt. Wird z. B. für das Dashboard und für
    Berichte (PDF/HTML/CSV/JSON) verwendet.
    """
    computer_name: str
    user_name: str
    os_name: str
    os_version: str
    os_architecture: str
    cpu_physical_cores: int
    cpu_logical_cores: int
    cpu_percent: float
    ram_total_gb: float
    ram_used_gb: float
    ram_percent: float
    uptime_human: str
    disks: list[DiskInfo] = field(default_factory=list)
    network_interfaces: list[NetworkInterfaceInfo] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


class SystemInfoCollector:
    """Sammelt alle relevanten Systeminformationen.

    Die Klasse trennt bewusst einzelne "get_..."-Methoden von der
    zusammenfassenden `collect_snapshot()`-Methode. Vorteil: Die GUI kann
    z. B. NUR die CPU-Auslastung alle 2 Sekunden abfragen (performant),
    ohne jedes Mal auch Festplatten und Netzwerkkarten neu auszulesen,
    was teurer (langsamer) ist.
    """

    @staticmethod
    def get_computer_name() -> str:
        return platform.node() or socket.gethostname()

    @staticmethod
    def get_user_name() -> str:
        return getpass.getuser()

    @staticmethod
    def get_os_info() -> tuple[str, str, str]:
        """Liefert (Name, Version, Architektur), z. B. ('Windows', '11', '64bit')."""
        return platform.system(), platform.release(), platform.architecture()[0]

    @staticmethod
    def get_cpu_info() -> tuple[int, int, float]:
        """Liefert (physische Kerne, logische Kerne, aktuelle Auslastung %).

        `interval=0.3` bedeutet: psutil misst die CPU-Auslastung über ein
        kurzes Zeitfenster von 0,3 Sekunden. Ohne Intervall (interval=None)
        würde beim ersten Aufruf fälschlich oft 0.0% zurückgegeben, weil
        kein Vergleichszeitraum existiert – ein klassischer Fehler, den
        Einsteiger bei psutil machen.
        """
        physical = psutil.cpu_count(logical=False) or 0
        logical = psutil.cpu_count(logical=True) or 0
        percent = psutil.cpu_percent(interval=0.3)
        return physical, logical, percent

    @staticmethod
    def get_ram_info() -> tuple[float, float, float]:
        """Liefert (Gesamt-RAM GB, genutzt GB, Prozent genutzt)."""
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024 ** 3)
        used_gb = mem.used / (1024 ** 3)
        return round(total_gb, 2), round(used_gb, 2), mem.percent

    @staticmethod
    def get_disks() -> list[DiskInfo]:
        """Liefert alle eingehängten Festplattenpartitionen mit Belegung.

        Wichtig: Wechseldatenträger (CD-ROM, leere USB-Slots) können unter
        Windows einen PermissionError auslösen, wenn z. B. kein Medium
        eingelegt ist. Deshalb wird jede Partition einzeln in try/except
        behandelt, damit ein einzelnes Problemlaufwerk nicht die gesamte
        Erfassung abbricht (Fail-Safe-Prinzip).
        """
        disks: list[DiskInfo] = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError) as exc:
                logger.warning("Festplatte %s nicht lesbar: %s", part.device, exc)
                continue
            disks.append(
                DiskInfo(
                    device=part.device,
                    mountpoint=part.mountpoint,
                    fstype=part.fstype,
                    total_gb=round(usage.total / (1024 ** 3), 2),
                    used_gb=round(usage.used / (1024 ** 3), 2),
                    free_gb=round(usage.free / (1024 ** 3), 2),
                    percent_used=usage.percent,
                )
            )
        return disks

    @staticmethod
    def get_network_interfaces() -> list[NetworkInterfaceInfo]:
        """Liefert alle Netzwerkschnittstellen mit IPv4- und MAC-Adresse.

        psutil.net_if_addrs() liefert pro Interface eine Liste von
        'snicaddr'-Objekten (eine pro Adressfamilie: IPv4, IPv6, MAC/Link).
        Wir filtern gezielt nach AF_INET (IPv4) und AF_LINK/AF_PACKET (MAC),
        da für ein Admin-Tool primär diese beiden relevant sind.
        """
        import socket as _socket

        stats = psutil.net_if_stats()
        interfaces: list[NetworkInterfaceInfo] = []

        for name, addrs in psutil.net_if_addrs().items():
            ip_addr = None
            mac_addr = None
            for addr in addrs:
                if addr.family == _socket.AF_INET:
                    ip_addr = addr.address
                # AF_LINK (macOS/BSD) bzw. psutil.AF_LINK (Windows/Linux via
                # psutil-Konstante) liefert die MAC-Adresse.
                elif hasattr(psutil, "AF_LINK") and addr.family == psutil.AF_LINK:
                    mac_addr = addr.address

            is_up = stats[name].isup if name in stats else False
            interfaces.append(
                NetworkInterfaceInfo(
                    name=name, ip_address=ip_addr, mac_address=mac_addr, is_up=is_up
                )
            )
        return interfaces

    @staticmethod
    def get_uptime_human() -> str:
        """Liefert die Systemlaufzeit als lesbaren String, z. B. '2 Tage, 5:13:02'."""
        boot_time = psutil.boot_time()
        uptime_seconds = int(time.time() - boot_time)
        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if days > 0:
            return f"{days} Tage, {hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def collect_snapshot(self) -> SystemSnapshot:
        """Erstellt einen vollständigen Systemschnappschuss.

        Dies ist die zentrale Methode, die das Dashboard und der
        Report-Generator aufrufen.
        """
        logger.info("Erstelle Systemschnappschuss...")
        os_name, os_version, os_arch = self.get_os_info()
        physical_cores, logical_cores, cpu_percent = self.get_cpu_info()
        ram_total, ram_used, ram_percent = self.get_ram_info()

        snapshot = SystemSnapshot(
            computer_name=self.get_computer_name(),
            user_name=self.get_user_name(),
            os_name=os_name,
            os_version=os_version,
            os_architecture=os_arch,
            cpu_physical_cores=physical_cores,
            cpu_logical_cores=logical_cores,
            cpu_percent=cpu_percent,
            ram_total_gb=ram_total,
            ram_used_gb=ram_used,
            ram_percent=ram_percent,
            uptime_human=self.get_uptime_human(),
            disks=self.get_disks(),
            network_interfaces=self.get_network_interfaces(),
        )
        logger.info("Systemschnappschuss erfolgreich erstellt.")
        return snapshot