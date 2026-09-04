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


def log_path() -> str:
    """Pfad der Live-Ausgabe des Updaters (`region.log`).

    Oeffentlich, weil der SSE-Endpunkt `GET /api/admin/region/log` die Datei
    selbst inkrementell liest — anders als bei `read_status()` waere ein
    Rueckgabewert als String hier nutzlos: der Strom laeuft ueber Stunden und
    liest jeweils nur den Zuwachs ab einem Byte-Offset.
    """
    return _path(LOG_FILE)


def _spool_to_tempfile(directory: str, data: str) -> str:
    """Schreibt `data` vollstaendig in eine neue Temporaerdatei im selben
    Verzeichnis (also garantiert selbes Dateisystem) und gibt deren Pfad
    zurueck. Gemeinsame Grundlage fuer `_write_atomic()` (ueberschreibt ein
    bestehendes Ziel) und `_write_atomic_exclusive()` (lehnt ein bestehendes
    Ziel ab) — beide brauchen exakt denselben ersten Schritt und
    unterscheiden sich nur im letzten (`os.replace()` vs. `os.link()`).
    """
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        return tmp_path
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            # Aufraeumen ist best effort: Der eigentliche Fehler wird gleich
            # per `raise` unveraendert weitergereicht, das bemerkt der
            # Aufrufer. Scheitert zusaetzlich das Entfernen (z. B. Datei
            # schon weg), bleibt hoechstens eine harmlose `.tmp-`-Leiche im
            # Verzeichnis zurueck — kein Grund, den urspruenglichen Fehler zu
            # verdecken.
            pass
        raise


def _write_atomic(path: str, data: str) -> None:
    """Schreibt `data` atomar nach `path`, ueberschreibt ein bestehendes Ziel.

    Es wird in eine temporaere Datei im selben Verzeichnis geschrieben und
    anschliessend per os.replace() umbenannt. Ein Rename innerhalb desselben
    Dateisystems ist atomar — ein Leser sieht die Zieldatei entweder gar
    nicht oder vollstaendig, nie mit halbem Inhalt.
    """
    directory = os.path.dirname(path)
    tmp_path = _spool_to_tempfile(directory, data)
    try:
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            # Wie in _spool_to_tempfile(): best effort, der eigentliche
            # Fehler von os.replace() wird gleich per `raise` durchgereicht
            # und ist das, was der Aufrufer sieht. Ein Fehlschlag hier
            # hinterlaesst hoechstens eine harmlose `.tmp-`-Leiche.
            pass
        raise


def _write_atomic_exclusive(path: str, data: str) -> None:
    """Wie `_write_atomic()`, aber lehnt ein bereits bestehendes Ziel ab,
    statt es zu ueberschreiben (`FileExistsError`).

    Hintergrund (Fix-Runde 1 zu Task 5, echte TOCTOU-Luecke): `write_request()`
    wird von der Route erst NACH einem bis zu 15 s dauernden HTTP-HEAD-Request
    aufgerufen. Ein reiner Vorab-Check von `is_busy()` vor diesem Request laesst
    ein mehrsekuendiges Fenster offen, in dem eine zweite, praktisch
    gleichzeitige Anforderung denselben "nicht beschaeftigt"-Zustand sieht und
    ebenfalls durchkommt — bei mehreren Uvicorn-Workern keine rein theoretische
    Sorge. `_write_atomic()` (via `os.replace()`) wuerde die erste Anforderung
    dann stillschweigend durch die zweite ersetzen: zwei Regionswechsel wuerden
    denselben Compose-Stack anfassen, einer baut einen Graphen, der andere
    startet Container neu.

    `os.replace()` ersetzt ein bestehendes Ziel bedingungslos — dafuer ist es
    da. `os.link()` (Hardlink) dagegen lehnt ein bestehendes Ziel mit
    `FileExistsError` ab; das ist exakt die Semantik, die hier gebraucht wird.
    Der Inhalt bleibt trotzdem atomar sichtbar: die Temporaerdatei ist zum
    Zeitpunkt des Verlinkens bereits vollstaendig geschrieben, ein Leser sieht
    das Ziel entweder gar nicht oder vollstaendig — dieselbe Garantie wie bei
    `_write_atomic()`, nur mit "ablehnen" statt "ersetzen" als letztem Schritt.
    Die Temporaerdatei wird in jedem Fall entfernt (auch wenn `os.link()`
    fehlschlaegt), damit keine `.tmp-`-Leiche im Volume zurueckbleibt.
    """
    directory = os.path.dirname(path)
    tmp_path = _spool_to_tempfile(directory, data)
    try:
        os.link(tmp_path, path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            # Best effort: os.link() ist zu diesem Zeitpunkt bereits
            # entschieden (verlinkt oder mit FileExistsError/OSError
            # fehlgeschlagen, beides unveraendert sichtbar fuer den
            # Aufrufer). Scheitert nur das Entfernen der Temporaerdatei,
            # bleibt hoechstens eine harmlose `.tmp-`-Leiche im Volume
            # zurueck — kein Datenverlust, keine Doppel-Anforderung.
            pass


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
    Antwort uebersetzen kann: `FileExistsError` (eine Anforderung liegt
    bereits vor — exklusives Anlegen, siehe `_write_atomic_exclusive()`) in
    ein 409, jeder andere `OSError` (Volume nicht beschreibbar) in ein 503.
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
        # Siehe Kommentar oben: nur die Terminal-Anzeige betroffen, nicht die
        # Anforderung selbst. Der Aufrufer bemerkt hoechstens ein zunaechst
        # leeres Log-Terminal im Admin-Panel, nichts weiter — die kritische
        # Request-Datei unten wird unabhaengig davon geschrieben.
        pass
    # Kritisch: Diese Datei ist die eigentliche Anforderung an den Updater.
    # Exklusiv (nicht ueberschreibend) angelegt — siehe _write_atomic_exclusive().
    # FileExistsError (zweite Anforderung waehrend eine erste noch aussteht
    # oder gerade verarbeitet wird) und jeder andere OSError (Volume nicht
    # beschreibbar) werden unveraendert durchgereicht, damit der Aufrufer
    # (die Route) sie wie bei trigger_update in 409 bzw. 503 uebersetzen kann.
    _write_atomic_exclusive(_path(REQUEST_FILE), json.dumps(payload))


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
