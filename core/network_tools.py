"""
core/network_tools.py
----------------------
Netzwerk-Diagnose-Werkzeuge: Ping, Traceroute, DNS-Lookup, Portscanner,
aktive Netzwerkverbindungen.

WARUM IST DAS FÜR EINEN FACHINFORMATIKER SYSTEMINTEGRATION RELEVANT?
Netzwerkdiagnose ist DAS Tagesgeschäft im 1st/2nd-Level-Support und in der
Systemintegration: "Server X ist nicht erreichbar" -> Ping, Traceroute,
Portscan sind die ersten drei Werkzeuge, die man in dieser Reihenfolge
einsetzt (siehe systematische Fehlerdiagnose im README).

VERWENDETE BIBLIOTHEKEN:
  - `subprocess` (Standardbibliothek): Ruft die nativen Systembefehle
    `ping` und `tracert`/`traceroute` auf. WARUM nicht eine reine
    Python-Lösung (z. B. das Paket `ping3`)? Weil `ping3` auf Windows
    Admin-Rechte für ICMP-Rohpakete benötigt und sich je nach Windows-
    Version unterschiedlich verhält. Die Nutzung der nativen Bordmittel
    ist robuster und genau das, was ein Admin auch von Hand täte –
    wir automatisieren also einen echten Admin-Workflow, statt ihn
    durch eine Bibliothek zu ersetzen, die anders funktioniert.
  - `socket` (Standardbibliothek): DNS-Lookup (Name -> IP) und
    Portscanner (TCP-Connect-Scan).
  - `psutil` (Drittanbieter): Aktive Netzwerkverbindungen
    (`psutil.net_connections()`), da die Standardbibliothek das nicht
    plattformübergreifend anbietet.

WICHTIGER SICHERHEITSHINWEIS:
Der Portscanner darf ausschließlich gegen Systeme eingesetzt werden, für
die eine ausdrückliche Erlaubnis vorliegt (eigene Systeme, eigenes Labor-
netz). Portscans gegen fremde Systeme ohne Erlaubnis können je nach
Rechtsordnung eine Straftat darstellen (in Deutschland z. B. relevant im
Kontext von § 202c StGB / "Hackerparagraph", abhängig vom Einzelfall).
Diese Anwendung ist ausschließlich für den Einsatz in der eigenen,
autorisierten Infrastruktur gedacht (genau wie unser TechSolutions-Labor).
"""

from __future__ import annotations

import platform
import re
import socket
import subprocess
from dataclasses import dataclass, field

import psutil

from utils.exceptions import NetworkToolError
from utils.logger import get_logger

logger = get_logger(__name__)

IS_WINDOWS = platform.system().lower() == "windows"


@dataclass
class PingResult:
    host: str
    success: bool
    packets_sent: int
    packets_received: int
    packet_loss_percent: float
    avg_latency_ms: float | None
    raw_output: str


@dataclass
class PortScanResult:
    host: str
    open_ports: list[int] = field(default_factory=list)
    closed_ports: list[int] = field(default_factory=list)


@dataclass
class ConnectionInfo:
    local_address: str
    remote_address: str
    status: str
    pid: int | None
    process_name: str | None


class NetworkTools:
    """Sammlung von Netzwerk-Diagnosefunktionen.

    Alle Methoden sind als `staticmethod` implementiert, da sie keinen
    inneren Zustand benötigen (zustandslose, reine Werkzeugfunktionen).
    Das hält die Klasse einfach erweiterbar: Ein neues Tool (z. B.
    "ARP-Scan") bedeutet einfach eine weitere statische Methode.
    """

    @staticmethod
    def ping(host: str, count: int = 4, timeout_ms: int = 1000) -> PingResult:
        """Führt einen Ping-Befehl gegen einen Host aus.

        Nutzt den systemeigenen ping-Befehl, da dessen Parameter sich
        zwischen Windows (-n, -w in Millisekunden) und Linux (-c, -W in
        Sekunden) unterscheiden – ein klassisches Cross-Plattform-Detail,
        das man als Systemintegrator kennen muss.
        """
        if IS_WINDOWS:
            cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
        else:
            timeout_s = max(1, timeout_ms // 1000)
            cmd = ["ping", "-c", str(count), "-W", str(timeout_s), host]

        logger.info("Ping wird ausgeführt: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=count * 2 + 5
            )
            output = proc.stdout + proc.stderr
        except subprocess.TimeoutExpired as exc:
            raise NetworkToolError(f"Ping nach {host} hat das Zeitlimit überschritten.") from exc
        except OSError as exc:
            raise NetworkToolError(f"Ping konnte nicht ausgeführt werden: {exc}") from exc

        return NetworkTools._parse_ping_output(host, count, output)

    @staticmethod
    def _parse_ping_output(host: str, count: int, output: str) -> PingResult:
        """Parst die Textausgabe von ping in ein strukturiertes Ergebnis.

        Hinweis für Lernende: Das Parsen von Kommandozeilen-Textausgaben
        ist fehleranfällig (unterschiedliche Sprachversionen von Windows
        liefern z. B. "Gesendet" statt "Sent"!). In einer produktiven
        Lösung würde man ggf. zusätzlich auf eine sprachunabhängige
        Bibliothek umsteigen. Hier zeigen wir den Klassiker-Ansatz mit
        regulären Ausdrücken, der in vielen realen Skripten genauso zu
        finden ist.
        """
        received = len(re.findall(r"(TTL=|ttl=)", output))
        if received == 0:
            received = output.lower().count("bytes from")

        loss_percent = round(100 * (count - received) / count, 1) if count else 0.0

        avg_match = re.search(r"Average = (\d+)ms", output) or re.search(
            r"= ([\d.]+)/([\d.]+)/([\d.]+)", output  # Linux: min/avg/max
        )
        avg_latency = None
        if avg_match:
            try:
                # Windows-Format hat genau 1 Gruppe, Linux-Format 3 (avg ist Gruppe 2)
                avg_latency = float(avg_match.group(2)) if len(avg_match.groups()) >= 2 else float(avg_match.group(1))
            except (ValueError, IndexError):
                avg_latency = None

        return PingResult(
            host=host,
            success=received > 0,
            packets_sent=count,
            packets_received=received,
            packet_loss_percent=loss_percent,
            avg_latency_ms=avg_latency,
            raw_output=output,
        )

    @staticmethod
    def traceroute(host: str, max_hops: int = 30) -> str:
        """Führt eine Traceroute zu einem Host aus und gibt die Rohausgabe zurück.

        Wir geben hier bewusst die rohe Textausgabe zurück (statt sie zu
        parsen), da Traceroute-Ausgaben stark variieren und für die GUI
        primär als lesbarer Verlauf dargestellt werden ("Hop 1: ..., Hop 2: ...").
        """
        cmd = (
            ["tracert", "-h", str(max_hops), host]
            if IS_WINDOWS
            else ["traceroute", "-m", str(max_hops), host]
        )
        logger.info("Traceroute wird ausgeführt: %s", " ".join(cmd))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return proc.stdout + proc.stderr
        except subprocess.TimeoutExpired as exc:
            raise NetworkToolError(f"Traceroute zu {host} hat das Zeitlimit überschritten.") from exc
        except FileNotFoundError as exc:
            raise NetworkToolError(
                "traceroute/tracert wurde nicht gefunden. Unter Linux ggf. "
                "'apt install traceroute' ausführen."
            ) from exc

    @staticmethod
    def dns_lookup(hostname: str) -> list[str]:
        """Löst einen Hostnamen in seine IP-Adresse(n) auf (Forward-Lookup).

        Nutzt `socket.gethostbyname_ex`, da diese Funktion -- anders als
        `gethostbyname` -- ALLE bekannten IP-Adressen liefert (relevant bei
        DNS-Round-Robin / Load Balancing, z. B. bei großen Webseiten, die
        mehrere A-Records besitzen).
        """
        try:
            _, _, ip_addresses = socket.gethostbyname_ex(hostname)
            logger.info("DNS-Lookup für %s erfolgreich: %s", hostname, ip_addresses)
            return ip_addresses
        except socket.gaierror as exc:
            raise NetworkToolError(f"DNS-Auflösung für '{hostname}' fehlgeschlagen: {exc}") from exc

    @staticmethod
    def reverse_dns_lookup(ip_address: str) -> str:
        """Löst eine IP-Adresse zu einem Hostnamen auf (Reverse-Lookup, PTR-Record)."""
        try:
            hostname, _, _ = socket.gethostbyaddr(ip_address)
            return hostname
        except socket.herror as exc:
            raise NetworkToolError(f"Reverse-DNS für '{ip_address}' fehlgeschlagen: {exc}") from exc

    @staticmethod
    def scan_ports(host: str, ports: list[int], timeout_s: float = 0.5) -> PortScanResult:
        """Führt einen TCP-Connect-Portscan gegen einen Host aus.

        FUNKTIONSWEISE (TCP-Connect-Scan):
        Für jeden zu prüfenden Port wird versucht, einen vollständigen
        TCP-Handshake (SYN -> SYN/ACK -> ACK) aufzubauen. Gelingt das
        (connect_ex liefert 0 zurück), ist der Port offen/erreichbar.

        WARUM TCP-CONNECT-SCAN STATT SYN-SCAN?
        Ein reiner SYN-Scan (wie ihn z. B. nmap mit Rohsockets macht)
        benötigt erhöhte Rechte (Raw Sockets) und ist auf Windows ohne
        zusätzliche Treiber (Npcap) kaum nativ umsetzbar. Der TCP-Connect-
        Scan funktioniert mit Standard-Python-Sockets ohne Sonderrechte –
        ein guter Kompromiss zwischen Portabilität und Funktionsumfang
        für ein Admin-Tool, das auf jedem Windows-Client laufen soll.

        SICHERHEITSHINWEIS: Siehe Modul-Docstring oben – nur gegen
        autorisierte Zielsysteme einsetzen.
        """
        result = PortScanResult(host=host)
        try:
            resolved_ip = socket.gethostbyname(host)
        except socket.gaierror as exc:
            raise NetworkToolError(f"Host '{host}' konnte nicht aufgelöst werden: {exc}") from exc

        logger.info("Portscan gestartet gegen %s (%s), %d Ports", host, resolved_ip, len(ports))
        for port in ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_s)
            try:
                code = sock.connect_ex((resolved_ip, port))
                if code == 0:
                    result.open_ports.append(port)
                else:
                    result.closed_ports.append(port)
            finally:
                sock.close()
        logger.info(
            "Portscan beendet: %d offen, %d geschlossen", len(result.open_ports), len(result.closed_ports)
        )
        return result

    @staticmethod
    def get_active_connections(limit: int = 200) -> list[ConnectionInfo]:
        """Liefert aktuell aktive Netzwerkverbindungen (vergleichbar mit `netstat -ano`).

        Hinweis: Unter Windows benötigt das Auslesen von Prozessnamen für
        ALLE Verbindungen ggf. Administratorrechte. Ohne diese liefert
        psutil für manche PIDs `None` zurück -- wir behandeln das defensiv,
        statt abzustürzen.
        """
        connections: list[ConnectionInfo] = []
        try:
            conns = psutil.net_connections(kind="inet")
        except psutil.AccessDenied as exc:
            raise NetworkToolError(
                "Zugriff verweigert. Bitte als Administrator ausführen, um "
                f"alle Verbindungen zu sehen ({exc})."
            ) from exc

        for c in conns[:limit]:
            local = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "-"
            remote = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "-"
            process_name = None
            if c.pid:
                try:
                    process_name = psutil.Process(c.pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    process_name = None
            connections.append(
                ConnectionInfo(
                    local_address=local,
                    remote_address=remote,
                    status=c.status,
                    pid=c.pid,
                    process_name=process_name,
                )
            )
        return connections