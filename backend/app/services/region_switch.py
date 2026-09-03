"""Dateiprotokoll zwischen Backend und Updater.

Dieselbe Bruecke wie der bestehende Update-Trigger (admin.py:1141): Das
Backend schreibt eine Absicht in das geteilte Volume, der Updater pollt sie.
Das Backend fasst Docker nie an.
"""
import json
import os
import tempfile
from datetime import datetime, timezone

VOLUME = "/update_status"

REQUEST_FILE = "region_request.json"
STATUS_FILE = "region_status.json"
LOG_FILE = "region.log"
CANCEL_FILE = "region.cancel"
LOCK_FILE = "region.lock"


def _path(name: str) -> str:
    return os.path.join(VOLUME, name)


def _write_atomic(path: str, data: str) -> None:
    """Schreibt `data` atomar nach `path`.

    Es wird in eine temporaere Datei im selben Verzeichnis (also auf
    demselben Dateisystem) geschrieben und anschliessend per os.replace()
    umbenannt. Ein Rename innerhalb desselben Dateisystems ist atomar —
    der Updater sieht die Zieldatei entweder gar nicht oder vollstaendig,
    nie mit halbem Inhalt.
    """
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except BaseException:
        # Aufraeumen, falls das Schreiben oder der Rename fehlschlaegt —
        # sonst bleibt eine verwaiste Temporaerdatei im Volume zurueck.
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def write_request(url: str, filename: str, java_opts: str, actor_email: str) -> None:
    """Schreibt eine Regionswechsel-Anforderung ins geteilte Volume.

    Reihenfolge bewusst wie in trigger_update(): Erst die Log-Zeile, dann die
    Request-Datei. Pollt der Updater genau dazwischen, sieht er nur die
    Log-Zeile und noch keine Request-Datei — er wartet einfach auf den
    naechsten Zyklus, es passiert nichts Falsches. Waere die Reihenfolge
    umgekehrt, koennte der Updater die Request-Datei sofort aufgreifen und
    zu arbeiten beginnen, bevor die erste Log-Zeile sichtbar ist — das
    Terminal im Admin-Panel bliebe dann kurz leer, obwohl der Wechsel schon
    laeuft. Die hier gewaehlte Reihenfolge vermeidet das.

    Die Fehlerbehandlung ist bewusst asymmetrisch, analog zu trigger_update():
    Ein Fehlschlag beim Schreiben der Log-Zeile ist unkritisch (sie dient nur
    dazu, das Terminal nicht leer aussehen zu lassen) und wird verschluckt.
    Ein Fehlschlag beim Schreiben der Request-Datei ist dagegen das
    eigentliche Ergebnis dieser Funktion — er wird durchgereicht, damit der
    Aufrufer (die Route) ihn wie bei trigger_update in eine verstaendliche
    503-Antwort uebersetzen kann.
    """
    os.makedirs(VOLUME, exist_ok=True)
    payload = {
        "url": url,
        "filename": filename,
        "java_opts": java_opts,
        "requested_by": actor_email,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    # Erste Log-Zeile sofort, damit das Terminal nicht leer bleibt, waehrend
    # der Updater bis zu 10 s schlaeft — analog trigger_update(). Unkritisch:
    # schlaegt das fehl, faehrt die eigentliche Anforderung trotzdem fort.
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(_path(LOG_FILE), "w") as f:
            f.write(f"[{ts}] Regionswechsel angefordert — warte auf Updater…\n")
    except OSError:
        pass
    # Kritisch: Diese Datei ist die eigentliche Anforderung an den Updater.
    # Schlaegt das Schreiben fehl, reicht die Funktion den OSError durch.
    _write_atomic(_path(REQUEST_FILE), json.dumps(payload))


def read_status() -> dict:
    """Liest den zuletzt vom Updater geschriebenen Status.

    Existiert die Datei nicht oder ist sie (z. B. waehrend eines laufenden
    Schreibvorgangs) nicht valides JSON, gilt der Ruhezustand als Default.
    """
    try:
        with open(_path(STATUS_FILE)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"phase": "idle"}


def is_busy() -> bool:
    """True, wenn eine Anforderung wartet oder der Updater ein Lock haelt.

    Beide Faelle bedeuten „beschaeftigt": eine noch nicht abgeholte
    Request-Datei genauso wie ein vom Updater waehrend der Verarbeitung
    gehaltenes Lock.
    """
    return os.path.exists(_path(REQUEST_FILE)) or os.path.exists(_path(LOCK_FILE))


def request_cancel() -> None:
    """Signalisiert dem Updater, einen laufenden Regionswechsel abzubrechen."""
    os.makedirs(VOLUME, exist_ok=True)
    with open(_path(CANCEL_FILE), "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())
