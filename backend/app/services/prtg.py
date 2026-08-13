"""Aufbereitung der Systemkennzahlen als PRTG-Sensordaten.

Warum ein eigenes Format
------------------------
``/api/admin/system/overview`` liefert fachlich verschachteltes JSON — gut für
das Admin-Portal, unbrauchbar für PRTG. Der Sensortyp **HTTP Data Advanced**
erwartet eine flache Kanalliste in genau dieser Form::

    {"prtg": {"result": [{"channel": "…", "value": "…", "unit": "…"}], "text": "…"}}

Dieses Modul gießt die Momentaufnahme aus ``system_metrics.live_snapshot`` in
jene Form. Damit genügt in PRTG ein einziger Sensor ohne Skript und ohne
Mapping-Template: URL eintragen, unter *Custom HTTP Headers* die Zeile
``X-API-Key: cvp_…`` hinterlegen, fertig.

Stabile Kanäle
--------------
PRTG ordnet Kanäle beim ersten Durchlauf einer festen ID zu und erkennt sie
danach am Namen. Kanäle dürfen deshalb weder ihren Namen ändern noch von
Abfrage zu Abfrage verschwinden — sonst reißt der Verlauf ab. Ein Kennwert, der
sich auf dem Host nicht messen lässt (PSI-Druck ohne passenden Kernel,
Datenbankgröße außerhalb von PostgreSQL), wird deshalb weggelassen: er fehlt
dann dauerhaft, nicht sprunghaft. Werte, die es gibt, werden nie unterschlagen —
auch die Null nicht.

Grenzwerte
----------
Die Warn- und Fehlergrenzen unten sind Startwerte, die PRTG beim Anlegen der
Kanäle übernimmt. Wer sie in den Kanaleinstellungen des Sensors anpasst,
behält seine Werte — PRTG überschreibt sie bei folgenden Abfragen nicht.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Von PRTG anerkannte Einheiten. Andere Bezeichner führen dazu, dass der Kanal
# ohne Einheit dargestellt wird, deshalb hier als Konstanten statt als Literale.
PERCENT = "Percent"
COUNT = "Count"
BYTES = "BytesDisk"             # reine Byte-Skalierung (B/KB/MB/GB) — auch für RAM
SPEED_DISK = "SpeedDisk"        # Bytes pro Sekunde
TIME_SECONDS = "TimeSeconds"
TIME_RESPONSE = "TimeResponse"  # Millisekunden
CUSTOM = "Custom"

# Auslastungsgrenzen, ab denen ein Blick lohnt bzw. gehandelt werden muss.
_WARN_PERCENT = 85.0
_ERROR_PERCENT = 95.0


def _channel(
    name: str,
    value: float | int | None,
    *,
    unit: str = COUNT,
    customunit: str | None = None,
    decimals: int | None = None,
    warn_above: float | None = None,
    error_above: float | None = None,
    warn_message: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any] | None:
    """Einen Kanal bauen — oder ``None``, wenn der Kennwert nicht vorliegt.

    ``decimals`` entscheidet über die Darstellung: ohne Angabe wird gerundet und
    als Ganzzahl geliefert (PRTG-Vorgabe für Zählkanäle), mit Angabe als
    Fließkommawert mit ``float: 1``. Der Wert geht als Zeichenkette raus, damit
    das Dezimaltrennzeichen garantiert ein Punkt ist.
    """
    if value is None:
        return None

    channel: dict[str, Any] = {"channel": name, "unit": unit}
    if decimals is None:
        channel["value"] = str(int(round(float(value))))
    else:
        channel["value"] = f"{float(value):.{decimals}f}"
        channel["float"] = 1
    if customunit is not None:
        channel["customunit"] = customunit

    if warn_above is not None or error_above is not None:
        channel["limitmode"] = 1
        if warn_above is not None:
            channel["limitmaxwarning"] = warn_above
        if error_above is not None:
            channel["limitmaxerror"] = error_above
        if warn_message is not None:
            channel["limitwarningmsg"] = warn_message
        if error_message is not None:
            channel["limiterrormsg"] = error_message
    return channel


def _sample_age_seconds(collector: dict[str, Any], now: datetime) -> float | None:
    """Alter der letzten gespeicherten Stichprobe in Sekunden.

    ``None``, solange der Collector abgeschaltet ist oder noch nie gemessen hat —
    beides ist kein Störungsfall, sondern schlicht kein Messwert.
    """
    if not collector.get("enabled"):
        return None
    raw = collector.get("last_sample_at")
    if not raw:
        return None
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return max(0.0, (now - last).total_seconds())


def _summary(host: dict[str, Any], docker: dict[str, Any]) -> str:
    """Statuszeile des Sensors — das, was in PRTG neben dem Sensornamen steht."""
    parts: list[str] = []
    for label, value in (
        ("CPU", host.get("cpu_percent")),
        ("RAM", host.get("mem_percent")),
        ("Platte", host.get("disk_percent")),
    ):
        if value is not None:
            parts.append(f"{label} {value:.0f} %")

    if not docker.get("available"):
        parts.append("Docker-API nicht erreichbar")
    else:
        parts.append(f"{docker.get('running', 0)}/{docker.get('total', 0)} Container laufen")
        unhealthy = docker.get("unhealthy") or 0
        if unhealthy:
            parts.append(f"{unhealthy} gestört")

    return " · ".join(parts) if parts else "Keine Kennzahlen messbar"


def error_payload(message: str) -> dict[str, Any]:
    """Sensorantwort für den Fehlerfall — PRTG zeigt den Text am Sensor an."""
    return {"prtg": {"error": 1, "text": message}}


def sensor_payload(snapshot: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Momentaufnahme in PRTG-Sensordaten übersetzen."""
    now = now or datetime.now(timezone.utc)
    host = snapshot.get("host") or {}
    docker = snapshot.get("docker") or {}
    database = snapshot.get("database") or {}
    usage = snapshot.get("usage") or {}
    collector = snapshot.get("collector") or {}

    disk_total, disk_used = host.get("disk_total_bytes"), host.get("disk_used_bytes")
    disk_free = None if disk_total is None or disk_used is None else disk_total - disk_used

    candidates = [
        # ── Host ──
        _channel(
            "CPU-Auslastung", host.get("cpu_percent"),
            unit=PERCENT, decimals=1,
            warn_above=_WARN_PERCENT, error_above=_ERROR_PERCENT,
            warn_message="CPU dauerhaft hoch ausgelastet",
            error_message="CPU am Anschlag",
        ),
        _channel("Load 1 min", host.get("load1"), unit=CUSTOM, customunit="Load", decimals=2),
        _channel("Load 5 min", host.get("load5"), unit=CUSTOM, customunit="Load", decimals=2),
        _channel(
            "Arbeitsspeicher belegt", host.get("mem_percent"),
            unit=PERCENT, decimals=1,
            warn_above=_WARN_PERCENT, error_above=_ERROR_PERCENT,
            warn_message="Arbeitsspeicher wird knapp",
            error_message="Arbeitsspeicher nahezu erschöpft",
        ),
        _channel("Arbeitsspeicher verfügbar", host.get("mem_available_bytes"), unit=BYTES),
        _channel("Swap belegt", host.get("swap_used_bytes"), unit=BYTES),
        _channel(
            "Plattenbelegung", host.get("disk_percent"),
            unit=PERCENT, decimals=1,
            warn_above=_WARN_PERCENT, error_above=_ERROR_PERCENT,
            warn_message="Platte läuft voll",
            error_message="Platte fast voll",
        ),
        _channel("Platte frei", disk_free, unit=BYTES),
        _channel("Schreibrate", host.get("disk_write_bytes_s"), unit=SPEED_DISK),
        _channel("Leserate", host.get("disk_read_bytes_s"), unit=SPEED_DISK),
        # PSI misst, wie lange Prozesse auf eine Ressource *warten mussten* —
        # der frühere Indikator als reine Auslastung, entsprechend enge Grenzen.
        _channel("CPU-Druck", host.get("psi_cpu_avg10"), unit=PERCENT, decimals=2,
                 warn_above=20.0, error_above=50.0),
        _channel("Speicher-Druck", host.get("psi_mem_avg10"), unit=PERCENT, decimals=2,
                 warn_above=10.0, error_above=30.0),
        _channel("I/O-Druck", host.get("psi_io_avg10"), unit=PERCENT, decimals=2,
                 warn_above=20.0, error_above=50.0),
        _channel("Laufzeit", host.get("uptime_seconds"), unit=TIME_SECONDS),
        # ── Datenbank ──
        _channel("Datenbankgröße", database.get("size_bytes"), unit=BYTES),
        _channel("Datenbankverbindungen", database.get("connections"), unit=COUNT),
        # ── Nutzung ──
        _channel("Aktive Benutzer", usage.get("active_users"), unit=COUNT),
        _channel("Aktive Demo-Besucher", usage.get("active_demo_users"), unit=COUNT),
        _channel("Eindeutige Benutzer heute", usage.get("unique_users_today"), unit=COUNT),
        _channel("Anmeldungen 24 h", usage.get("logins_24h"), unit=COUNT),
        _channel("Antwortzeit Ø", usage.get("avg_response_ms"), unit=TIME_RESPONSE, decimals=1),
    ]

    # ── Container ──
    # Nur wenn die Docker-API antwortet: sonst stünden dort drei Nullen, die wie
    # „kein Container läuft" aussehen, obwohl nur die Auskunft fehlt.
    if docker.get("available"):
        candidates += [
            _channel("Container gesamt", docker.get("total"), unit=COUNT),
            _channel("Container laufend", docker.get("running"), unit=COUNT),
            _channel(
                "Container gestört", docker.get("unhealthy"), unit=COUNT,
                error_above=0,
                error_message="Container mit rotem Healthcheck oder gestoppt",
            ),
        ]

    # ── Collector ──
    # Ein stehengebliebener Sampler fällt sonst nicht auf: die Live-Werte kommen
    # weiter, nur der Verlauf friert ein.
    age = _sample_age_seconds(collector, now)
    if age is not None:
        interval = collector.get("interval_s") or 300
        candidates.append(
            _channel(
                "Alter der letzten Stichprobe", age, unit=TIME_SECONDS,
                warn_above=interval * 3, error_above=interval * 6,
                warn_message="Sampler hinkt hinterher",
                error_message="Sampler erfasst keine Stichproben mehr",
            )
        )

    channels = [c for c in candidates if c is not None]
    if not channels:
        return error_payload("Keine Systemkennzahlen messbar")

    return {"prtg": {"result": channels, "text": _summary(host, docker)}}
