"""Hardware-Kennzahlen des Hosts — ohne zusätzliche Abhängigkeiten.

Alle Werte stammen aus dem procfs bzw. ``statvfs``; es wird bewusst kein
``psutil`` eingeführt (eine Abhängigkeit weniger im Image, und wir brauchen
ohnehin nur eine Handvoll Werte).

Was der Container tatsächlich sieht
-----------------------------------
``/proc/stat``, ``/proc/meminfo``, ``/proc/loadavg`` und ``/proc/diskstats``
sind **nicht** namespaced: ein Container liest dort die Werte des Hosts. Das ist
hier genau das Gewünschte — die Systemübersicht soll die Maschine unter der
Anwendung zeigen, nicht nur den Backend-Container. Läuft auf dem Host lxcfs,
liefern ``meminfo``/``stat`` stattdessen die Container-Sicht; die Zahlen bleiben
dann korrekt, beziehen sich aber auf das Cgroup-Limit.

Belegung/Freiplatz werden per ``statvfs`` über die gemounteten Pfade ermittelt
(``/`` liegt auf dem Docker-Dateisystem des Hosts, ``/uploads`` und
``/update_status`` sind Volumes). Damit ist der Plattenplatz, der der Instanz
tatsächlich zur Verfügung steht, exakt erfasst.

Sämtliche Leser sind fehlertolerant: fehlt eine Quelle (anderes OS, gehärteter
Kernel ohne PSI), liefert die jeweilige Funktion ``None`` statt zu werfen.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

_PROC = Path("/proc")

# Nur echte Blockgeräte zählen. Partitionen (sda1) und virtuelle Geräte
# (loop, ram, dm-, zram) würden die Summen sonst doppelt zählen bzw. verfälschen.
_IGNORED_DISK_PREFIXES = ("loop", "ram", "dm-", "zram", "md", "sr", "fd")

# Sektorgröße, die /proc/diskstats implizit verwendet (immer 512 B, unabhängig
# von der physischen Sektorgröße des Geräts).
_SECTOR_BYTES = 512


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return None


# ── CPU ──────────────────────────────────────────────────────────────────────

@dataclass
class CpuTimes:
    total: float
    idle: float


def read_cpu_times() -> CpuTimes | None:
    """Kumulative CPU-Ticks aus /proc/stat (Zeile ``cpu``)."""
    raw = _read(_PROC / "stat")
    if not raw:
        return None
    for line in raw.splitlines():
        if not line.startswith("cpu "):
            continue
        parts = [float(v) for v in line.split()[1:] if v.replace(".", "").isdigit()]
        if len(parts) < 5:
            return None
        # user nice system idle iowait irq softirq steal …
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
        return CpuTimes(total=sum(parts), idle=idle)
    return None


def cpu_percent_between(previous: CpuTimes | None, current: CpuTimes | None) -> float | None:
    """Auslastung in Prozent zwischen zwei Messpunkten (None bei Lücken)."""
    if previous is None or current is None:
        return None
    total_delta = current.total - previous.total
    idle_delta = current.idle - previous.idle
    if total_delta <= 0:
        return None
    return round(max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0)), 2)


def cpu_count() -> int | None:
    try:
        return os.cpu_count()
    except Exception:
        return None


def load_average() -> tuple[float, float, float] | None:
    try:
        one, five, fifteen = os.getloadavg()
        return round(one, 2), round(five, 2), round(fifteen, 2)
    except (OSError, AttributeError):
        return None


# ── Arbeitsspeicher ──────────────────────────────────────────────────────────

@dataclass
class MemoryInfo:
    total_bytes: int
    available_bytes: int
    used_bytes: int
    percent: float
    swap_total_bytes: int
    swap_used_bytes: int


def read_memory() -> MemoryInfo | None:
    raw = _read(_PROC / "meminfo")
    if not raw:
        return None
    values: dict[str, int] = {}
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0]) * 1024  # kB → Bytes

    total = values.get("MemTotal")
    if not total:
        return None
    # MemAvailable ist die einzig ehrliche Kennzahl für „was ist wirklich frei" —
    # MemFree ignoriert wiederverwendbaren Page-Cache. Auf sehr alten Kerneln
    # ohne MemAvailable fallen wir auf free+buffers+cached zurück.
    available = values.get("MemAvailable")
    if available is None:
        available = values.get("MemFree", 0) + values.get("Buffers", 0) + values.get("Cached", 0)
    used = max(0, total - available)
    swap_total = values.get("SwapTotal", 0)
    swap_used = max(0, swap_total - values.get("SwapFree", 0))
    return MemoryInfo(
        total_bytes=total,
        available_bytes=available,
        used_bytes=used,
        percent=round(used / total * 100.0, 2),
        swap_total_bytes=swap_total,
        swap_used_bytes=swap_used,
    )


# ── Plattenbelegung ──────────────────────────────────────────────────────────

@dataclass
class DiskUsage:
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "total_bytes": self.total_bytes,
            "used_bytes": self.used_bytes,
            "free_bytes": self.free_bytes,
            "percent": self.percent,
        }


def disk_usage(paths: list[str]) -> list[DiskUsage]:
    """Belegung je Pfad. Nicht existierende Pfade werden übersprungen; Pfade auf
    demselben Dateisystem werden zusammengefasst (sonst stünde dieselbe Platte
    mehrfach in der Übersicht)."""
    out: list[DiskUsage] = []
    seen_devices: set[int] = set()
    for path in paths:
        try:
            stat = os.stat(path)
            if stat.st_dev in seen_devices:
                continue
            vfs = os.statvfs(path)
        except OSError:
            continue
        seen_devices.add(stat.st_dev)
        total = vfs.f_blocks * vfs.f_frsize
        free = vfs.f_bavail * vfs.f_frsize          # für Nicht-root verfügbar
        # „used" gegen die für Nicht-root nutzbare Kapazität, damit die Prozent-
        # angabe mit `df` übereinstimmt (df rechnet die root-Reserve heraus).
        used = (vfs.f_blocks - vfs.f_bfree) * vfs.f_frsize
        usable = used + free
        if total <= 0:
            continue
        out.append(
            DiskUsage(
                path=path,
                total_bytes=total,
                used_bytes=used,
                free_bytes=free,
                percent=round(used / usable * 100.0, 2) if usable else 0.0,
            )
        )
    return out


# ── Platten-I/O ──────────────────────────────────────────────────────────────

@dataclass
class DiskIoCounters:
    read_bytes: int
    write_bytes: int
    io_ms: int
    at: float = field(default_factory=time.monotonic)


def read_disk_io() -> DiskIoCounters | None:
    """Summierte Lese-/Schreibbytes und Busy-Zeit aller echten Blockgeräte."""
    raw = _read(_PROC / "diskstats")
    if not raw:
        return None
    read_sectors = write_sectors = io_ms = 0
    found = False
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 14:
            continue
        name = fields[2]
        if name.startswith(_IGNORED_DISK_PREFIXES):
            continue
        # Partitionen ausschließen: "sda1" endet auf eine Ziffer, während das
        # Gerät selbst ("sda") das nicht tut. NVMe heißt "nvme0n1" (Gerät) vs.
        # "nvme0n1p1" (Partition).
        if name[-1].isdigit() and not name.startswith("nvme"):
            continue
        if name.startswith("nvme") and "p" in name.split("n")[-1]:
            continue
        try:
            read_sectors += int(fields[5])
            write_sectors += int(fields[9])
            io_ms += int(fields[12])
        except ValueError:
            continue
        found = True
    if not found:
        return None
    return DiskIoCounters(
        read_bytes=read_sectors * _SECTOR_BYTES,
        write_bytes=write_sectors * _SECTOR_BYTES,
        io_ms=io_ms,
    )


def disk_io_rates(
    previous: DiskIoCounters | None, current: DiskIoCounters | None
) -> tuple[float | None, float | None, float | None]:
    """(Lese-B/s, Schreib-B/s, Busy-%) zwischen zwei Messpunkten."""
    if previous is None or current is None:
        return None, None, None
    elapsed = current.at - previous.at
    if elapsed <= 0:
        return None, None, None
    read_rate = max(0.0, (current.read_bytes - previous.read_bytes) / elapsed)
    write_rate = max(0.0, (current.write_bytes - previous.write_bytes) / elapsed)
    # Busy-Zeit über alle Geräte summiert, deshalb kann der Wert bei mehreren
    # Platten über 100 % liegen — auf 100 begrenzen wäre irreführend, wir
    # normieren stattdessen nicht und dokumentieren es als „Summe".
    util = max(0.0, (current.io_ms - previous.io_ms) / (elapsed * 1000.0) * 100.0)
    return round(read_rate, 1), round(write_rate, 1), round(util, 2)


# ── Druck (PSI) ──────────────────────────────────────────────────────────────

def read_pressure(resource: str) -> dict[str, float] | None:
    """PSI-Werte (``some``-Zeile) für ``cpu``/``memory``/``io``.

    Rückgabe z. B. ``{"avg10": 1.2, "avg60": 0.8, "avg300": 0.4}``. ``None``,
    wenn der Kernel PSI nicht bereitstellt (<4.20 oder ohne CONFIG_PSI).
    """
    raw = _read(_PROC / "pressure" / resource)
    if not raw:
        return None
    for line in raw.splitlines():
        if not line.startswith("some"):
            continue
        out: dict[str, float] = {}
        for token in line.split()[1:]:
            key, _, value = token.partition("=")
            if key.startswith("avg"):
                try:
                    out[key] = float(value)
                except ValueError:
                    continue
        return out or None
    return None


def uptime_seconds() -> float | None:
    raw = _read(_PROC / "uptime")
    if not raw:
        return None
    try:
        return round(float(raw.split()[0]), 1)
    except (ValueError, IndexError):
        return None
