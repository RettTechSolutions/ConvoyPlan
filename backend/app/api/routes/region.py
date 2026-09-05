"""Regionswechsel im Admin-Panel: Vorab-Rechnung, Auslösen, Status, Abbruch.

Zwei Router in diesem Modul: `router` (Prefix `/admin/region`, Singular) fuer
`preview`, das Ausloesen selbst, `status`, `log`, `cancel` und die aktuell
aktive Region; `admin_router` (Prefix `/admin`) fuer die Plural-Route
`GET /admin/regions` (Liste verfuegbarer Regionen). Ein einzelner Router mit
Prefix `/admin/region` koennte `/admin/regions` nicht bedienen — der Plural
liegt ausserhalb dieses Prefix.

`preview` hat keine Nebenwirkung: es schreibt nichts (kein Aufruf von
`region_switch.write_request`) und loest keinen Import aus. Es beantwortet
nur die Frage, ob eine Region auf diese Maschine passt, bevor der Operator
einen stundenlangen Graph-Bau anstoesst. `switch_region` loest den echten
Wechsel aus (schreibt eine Anforderung ins geteilte Volume, die der Updater
abholt) und ist deshalb strikt gegen einen bereits laufenden Regionswechsel
oder ein bereits laufendes normales Update verriegelt (siehe dort).
"""

import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import decode_stream_token, get_db, require_superadmin
from app.config import settings
from app.models.user import User
from app.services import (
    audit, geofabrik, host_metrics, region_compose, region_estimate, region_switch,
)

router = APIRouter(prefix="/admin/region", tags=["admin"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])

# Von der GraphHopper-Region geschrieben (Task 6/7), hier nur lesend
# gemountet (OSM_PATH, read-only siehe docker-compose.yml). Fehlt die Datei
# (noch kein Wechsel seit der Installation durchgefuehrt), gilt die in
# docker-compose.yml hinterlegte Werkseinstellung (DACH) als aktiv.
_REGION_FILE_NAME = ".region"
_DEFAULT_REGION_URL = "https://download.geofabrik.de/europe/dach-latest.osm.pbf"
_DEFAULT_REGION_FILENAME = "dach-latest.osm.pbf"

# Read-only in docker-compose.yml gemountet (siehe dort) — das Backend
# schreibt hier nichts, `df` auf dem Mount meldet das darunterliegende
# Dateisystem, also genau die Kapazitaet, die Extract und Graph tatsaechlich
# zur Verfuegung steht.
OSM_PATH = "/data/osm"
GRAPH_PATH = "/data/graph"


class RegionUrls(BaseModel):
    """Eine oder mehrere Geofabrik-URLs.

    Mehrere Eintraege werden vom Updater zu EINER Karte zusammengefuehrt
    (siehe 2026-09-04-mehrere-regionen-design.md). Genau ein Eintrag ist der
    bisherige Pfad und verhaelt sich unveraendert.
    """
    urls: list[str]


def _reclaimable_heap_bytes() -> int:
    """Heap-Anteil des laufenden GraphHopper, der waehrend eines Imports
    zurueckgewonnen werden kann.

    Herkunft: `JAVA_OPTS`/`-Xmx` der *aktiven* Region (app/config.py,
    `settings.java_opts`, aus derselben Env-Variable wie der
    GraphHopper-Container in docker-compose.yml). Der Updater startet den
    Import-Prozess mit einem eigenen, kleineren Heap und faehrt den
    laufenden GraphHopper-Container erst danach — mit dem neuen Graph — mit
    voller Groesse wieder hoch. Fuer die Dauer des Imports steht der Anteil,
    den GraphHopper normalerweise als `-Xmx` beansprucht, dem Import-Prozess
    zur Verfuegung, auch wenn `MemAvailable` ihn (weil vom laufenden
    Container gehalten) nicht als frei ausweist.
    Alternativen wie eine Live-Abfrage des Container-Cgroups wurden bewusst
    verworfen: `preview` darf keine Docker-Abfrage ausloesen (kein
    Docker-Socket im Backend, siehe docker-compose.yml-Kommentar beim
    dockerproxy-Sidecar) und der konfigurierte `-Xmx`-Wert ist ohnehin die
    verbindliche Obergrenze, die GraphHopper sich reservieren *darf* —
    unabhaengig davon, wie viel es im Moment der Anfrage tatsaechlich
    benutzt. Kann der Wert nicht geparst werden (z. B. leeres `JAVA_OPTS`),
    wird konservativ 0 zurueckgegeben statt zu raten.
    """
    for token in settings.java_opts.split():
        if not token.startswith("-Xmx"):
            continue
        value = token[len("-Xmx"):].strip().lower()
        unit = value[-1] if value and value[-1].isalpha() else ""
        number = value[:-1] if unit else value
        try:
            amount = float(number)
        except ValueError:
            return 0
        multiplier = {"g": 1024**3, "m": 1024**2, "k": 1024, "": 1}.get(unit)
        if multiplier is None:
            return 0
        return int(amount * multiplier)
    return 0


@router.post("/preview")
async def preview(body: RegionUrls, _: User = Depends(require_superadmin)):
    """Schaetzt Ressourcenbedarf und -verfuegbarkeit fuer einen Regionswechsel.

    Reine Lesefunktion: validiert nur die URL, fragt per HTTP-HEAD die
    Extract-Groesse ab und liest lokale Hardware-Kennzahlen — es wird nichts
    heruntergeladen, geschrieben oder an den Updater gemeldet.
    """
    try:
        # Genau eine validierte URL im Umlauf (Altlast behoben, Task 5): vorher
        # wurde validate_region_url() aufgerufen und ihr Rueckgabewert verworfen,
        # bevor head_size_bytes() intern erneut (und mit dem rohen body.url)
        # validierte — zwei parallele URL-Werte, von denen nur der zweite
        # tatsaechlich verwendet wurde. Jetzt wird ausschliesslich das rekon-
        # struierte Ergebnis von validate_region_url() weiterverwendet.
        if not body.urls:
            raise ValueError("Keine Region ausgewählt.")
        # Jeder Bestandteil einzeln durch die Allowlist — die Sicherheitsgrenze
        # gilt pro URL, nicht fuer die Liste als Ganzes.
        # Entdoppelt: Dieselbe Region zweimal ausgewaehlt ergaebe sonst eine
        # "zusammengesetzte" Region aus einem einzigen Extract, das der Updater
        # zweimal unter demselben Namen laedt und mit sich selbst verschmilzt.
        # Nach der Validierung entdoppeln, damit zwei Schreibweisen derselben
        # URL zusammenfallen — validate_region_url() rekonstruiert sie kanonisch.
        urls = list(dict.fromkeys(geofabrik.validate_region_url(u) for u in body.urls))
        sizes = [await geofabrik.head_size_bytes(u) for u in urls]
        extract = region_estimate.sum_extract_bytes(sizes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ConnectionError as exc:
        # Netzwerkfehler (Timeout, Verbindungsabbruch) sind kein Problem der
        # Eingabe des Nutzers, sondern der Erreichbarkeit von Geofabrik —
        # 503 statt 400, mit einer Meldung, die zum erneuten Versuch anleitet
        # (Fix-Runde 1, Important 2).
        raise HTTPException(503, str(exc)) from exc

    graph = region_estimate.estimate_graph_bytes(extract)
    ram_needed = region_estimate.estimate_ram_bytes(extract)

    mem = host_metrics.read_memory()
    ram_available = mem.available_bytes if mem else 0
    # Zusaetzlich zum ohnehin freien Speicher zurueckgewinnbar, weil der
    # Updater den laufenden GraphHopper waehrend des Imports verkleinert
    # (Details siehe _reclaimable_heap_bytes). Getrennt ausgewiesen statt in
    # `ram_available_bytes` eingerechnet, damit das Panel zeigen kann, dass
    # die Routenplanung waehrend des Imports mit weniger Speicher auskommen
    # muss.
    ram_reclaimable = _reclaimable_heap_bytes()
    ram_effective_available = ram_available + ram_reclaimable

    disks = host_metrics.disk_usage([OSM_PATH, GRAPH_PATH])
    disk_free = sum(d.free_bytes for d in disks) if disks else 0
    # Waehrend des Wechsels liegen altes und neues Extract plus beide Graphen
    # gleichzeitig auf der Platte — deshalb die doppelte Rechnung.
    #
    # Bei einer ZUSAMMENGESETZTEN Region kommen die N Quelldateien und die
    # daraus verschmolzene Datei hinzu; dafuer gibt es eine eigene, groessere
    # Formel. Fuer genau eine Region bleibt es bei der bisherigen Rechnung —
    # die neue Formel faellt dort hoeher aus und wuerde bestehende Urteile
    # verschieben, ohne dass sich am Ablauf etwas geaendert haette.
    if len(sizes) > 1:
        disk_needed = region_estimate.estimate_disk_during_switch(sizes)
    else:
        disk_needed = extract + graph

    ram_verdict = region_estimate.verdict(ram_needed, ram_effective_available)
    disk_verdict = region_estimate.verdict(disk_needed, disk_free)
    worst = "reicht nicht" if "reicht nicht" in (ram_verdict, disk_verdict) else (
        "knapp" if "knapp" in (ram_verdict, disk_verdict) else "ok"
    )

    def gb(n: int) -> str:
        return f"{n / (1024 ** 3):.1f} GB"

    reason = (
        f"Import braucht ~{gb(ram_needed)} Heap. Verfuegbar sind {gb(ram_available)}, "
        f"zusaetzlich {gb(ram_reclaimable)} durch Verkleinern des laufenden "
        f"GraphHopper waehrend des Imports (effektiv {gb(ram_effective_available)}). "
        f"Auf der Platte werden ~{gb(disk_needed)} benoetigt, frei sind {gb(disk_free)}."
    )
    paths = [region_compose.path_from_url(u) for u in urls]
    return {
        "sources": paths,
        "composed": len(paths) > 1,
        "overlapping": region_compose.overlapping(paths),
        "extract_bytes": extract,
        "graph_bytes": graph,
        "ram_needed_bytes": ram_needed,
        "ram_available_bytes": ram_available,
        "ram_reclaimable_bytes": ram_reclaimable,
        "ram_effective_available_bytes": ram_effective_available,
        "disk_needed_bytes": disk_needed,
        "disk_free_bytes": disk_free,
        "duration_minutes": list(region_estimate.estimate_duration_minutes(extract)),
        "verdict": worst,
        "reason": reason,
    }


def _read_active_region() -> dict:
    """Liest die aktuell aktive Region aus `.region` (siehe Modul-Docstring).

    Existiert die Datei nicht oder ist sie nicht lesbar, gilt die
    Werkseinstellung aus docker-compose.yml als aktiv — kein Fehler, sondern
    der Normalzustand direkt nach der Installation, bevor je ein Wechsel
    stattgefunden hat.
    """
    values: dict[str, str] = {}
    try:
        with open(os.path.join(OSM_PATH, _REGION_FILE_NAME)) as f:
            for line in f:
                if "=" in line:
                    key, _, value = line.strip().partition("=")
                    values[key] = value
    except OSError:
        # Siehe Docstring: Datei fehlt oder ist unlesbar = Normalzustand vor
        # dem ersten Regionswechsel. `values` bleibt leer, der Aufrufer
        # bemerkt nichts weiter ausser den unten greifenden Factory-Defaults
        # — kein Fehlerfall, den man weiterreichen muesste.
        pass
    return {
        "url": values.get("OSM_DOWNLOAD_URL", _DEFAULT_REGION_URL),
        "filename": values.get("OSM_FILENAME", _DEFAULT_REGION_FILENAME),
        "java_opts": values.get("JAVA_OPTS", settings.java_opts),
    }


async def _audit_switch_rejected(
    db: AsyncSession, request: Request, user: User, url: str, reason: str
) -> None:
    """Protokolliert einen abgelehnten Auslöseversuch (400/409/503).

    Fix-Runde 1 (Kleinigkeit): vorher wurde nur der Erfolgsfall auditiert —
    wer wiederholt ungültige URLs einwirft oder gegen eine laufende Sperre
    rennt, blieb unsichtbar. Sicherheitsrelevante Admin-Aktionen gehören
    unabhängig vom Ausgang in die Spur.
    """
    await audit.record(
        db,
        "region.switch_rejected",
        request=request,
        actor_id=user.id,
        actor_email=user.email,
        target_type="region",
        detail={"url": url, "reason": reason},
    )


@router.post("", status_code=202)
async def switch_region(
    body: RegionUrls,
    request: Request,
    user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Loest einen Regionswechsel aus.

    Schreibt (anders als `preview`) tatsaechlich eine Anforderung ins
    geteilte Volume, die der Updater abholt — der eigentliche Import- und
    Umschalt-Vorgang laeuft danach ausserhalb dieses Requests weiter.

    Nebenlaeufigkeit (Fix-Runde 1 zu Task 5 — vorherige Fassung hatte hier
    eine echte TOCTOU-Lücke): die Konfliktprüfung (`TRIGGER_FILE` aus
    admin.py existiert, oder `region_switch.is_busy()`) lief vorher VOR dem
    bis zu 15 s dauernden HTTP-HEAD-Request in `geofabrik.head_size_bytes()`.
    In diesem mehrsekündigen Fenster hätte eine zweite, praktisch
    gleichzeitige Anfrage denselben "nicht beschäftigt"-Zustand gesehen und
    wäre ebenfalls durchgekommen — bei mehreren Uvicorn-Workern keine
    theoretische Sorge. Die Prüfung steht deshalb jetzt unmittelbar vor dem
    Schreiben, nicht davor; der teure, nebenwirkungsfreie HEAD-Request darf
    weiterhin zuerst laufen. Die eigentliche Garantie liefert aber nicht
    dieser Vorab-Check (der bleibt nur ein schneller Fail-Fast-Pfad), sondern
    dass `region_switch.write_request()` die Anforderungsdatei EXKLUSIV
    anlegt (`FileExistsError`, wenn eine zweite Anfrage im verbleibenden,
    winzigen Fenster zwischen Prüfung und Schreiben gewinnt) — siehe dort.
    Der bestehende `trigger-update`-Endpunkt (admin.py) legt `TRIGGER_FILE`
    aus demselben Grund jetzt ebenfalls exklusiv an und prüft spiegelbildlich
    `region_switch.is_busy()`, damit sich beide Operationen gegenseitig
    ausschliessen. Der Import von `TRIGGER_FILE` erfolgt bewusst erst hier
    (Funktionsrumpf), nicht auf Modulebene — admin.py importiert seinerseits
    nichts aus region.py, ein Import auf Modulebene wuerde also zwar nicht
    zirkulaer sein, aber unnoetig eine Abhaengigkeit zwischen zwei sonst
    unabhaengigen Routern erzeugen.
    """
    roh = ", ".join(body.urls) if body.urls else "(leer)"
    try:
        if not body.urls:
            raise ValueError("Keine Region ausgewählt.")
        # Siehe Kommentar in preview(): jeder Bestandteil einzeln durch die
        # Allowlist, nur die rekonstruierten URLs werden weiterverwendet.
        # Entdoppelt: Dieselbe Region zweimal ausgewaehlt ergaebe sonst eine
        # "zusammengesetzte" Region aus einem einzigen Extract, das der Updater
        # zweimal unter demselben Namen laedt und mit sich selbst verschmilzt.
        # Nach der Validierung entdoppeln, damit zwei Schreibweisen derselben
        # URL zusammenfallen — validate_region_url() rekonstruiert sie kanonisch.
        urls = list(dict.fromkeys(geofabrik.validate_region_url(u) for u in body.urls))
        sizes = [await geofabrik.head_size_bytes(u) for u in urls]
        extract = region_estimate.sum_extract_bytes(sizes)
    except ValueError as exc:
        await _audit_switch_rejected(db, request, user, roh, str(exc))
        raise HTTPException(400, str(exc)) from exc
    except ConnectionError as exc:
        await _audit_switch_rejected(db, request, user, roh, str(exc))
        raise HTTPException(503, str(exc)) from exc

    ram = region_estimate.estimate_ram_bytes(extract)
    # Mindestens 2 GB Heap, aufgerundet auf ganze GB — analog zur
    # Groessenordnung der bestehenden JAVA_OPTS-Defaults (siehe config.py).
    heap_gb = max(2, round(ram / (1024 ** 3)))
    java_opts = f"-Xmx{heap_gb}g -Xms1g -XX:+UseG1GC"

    # Bei genau einer Region bleibt alles wie bisher: der Dateiname kommt aus
    # der URL, OSM_SOURCES bleibt leer. Erst mehrere Bestandteile erzeugen eine
    # zusammengefuehrte Datei, deren Name den Hash der sortierten Liste traegt —
    # daran erkennt entrypoint.sh spaeter einen Wechsel der Zusammensetzung.
    paths = [region_compose.path_from_url(u) for u in urls]
    if len(urls) > 1:
        filename = region_compose.merged_filename(paths)
        sources = region_compose.sources_value(paths)
    else:
        filename = urls[0].rsplit("/", 1)[-1]
        sources = ""
    url = urls[0]

    # Konfliktprüfung unmittelbar vor dem Schreiben (siehe Docstring oben) —
    # nur ein Fail-Fast-Pfad, die verbindliche Sperre ist die exklusive
    # Dateierstellung in write_request().
    from app.api.routes.admin import TRIGGER_FILE

    if os.path.exists(TRIGGER_FILE) or region_switch.is_busy():
        await _audit_switch_rejected(
            db, request, user, url, "Update oder Regionswechsel läuft bereits."
        )
        raise HTTPException(409, "Es läuft bereits ein Update oder Regionswechsel.")

    try:
        region_switch.write_request(url, filename, java_opts, user.email, sources=sources)
    except FileExistsError as exc:
        # Der eigentliche TOCTOU-Schutz: der Vorab-Check oben kann von einer
        # zweiten, fast gleichzeitigen Anfrage im verbleibenden Fenster noch
        # bestanden werden — aber nur eine der beiden kann REQUEST_FILE
        # exklusiv anlegen. Die andere landet hier statt die erste
        # Anforderung stillschweigend zu überschreiben.
        await _audit_switch_rejected(
            db, request, user, url,
            "Wettlauf mit einer gleichzeitigen Anforderung (exklusives Anlegen fehlgeschlagen).",
        )
        raise HTTPException(409, "Es läuft bereits ein Update oder Regionswechsel.") from exc
    except OSError as exc:
        await _audit_switch_rejected(db, request, user, url, f"Volume nicht beschreibbar: {exc}")
        raise HTTPException(
            503,
            "Regionswechsel konnte nicht ausgelöst werden: Das Update-Volume ist "
            "nicht beschreibbar. Der Updater repariert die Rechte automatisch beim "
            "nächsten Lauf — bitte in wenigen Minuten erneut versuchen.",
        ) from exc

    await audit.record(
        db,
        "region.switch_requested",
        request=request,
        actor_id=user.id,
        actor_email=user.email,
        target_type="region",
        detail={"url": url, "filename": filename, "extract_bytes": extract, "java_opts": java_opts},
    )
    return {"status": "requested"}


@router.get("/status")
async def region_status(_: User = Depends(require_superadmin)):
    """Aktueller Fortschritt eines laufenden oder zuletzt beendeten Regionswechsels.

    Liest ausschliesslich `region_switch.read_status()` — die vom Updater
    zuletzt geschriebene Statusdatei. Ruht kein Wechsel, ist das der
    Default-Zustand `{"phase": "idle"}`.
    """
    return region_switch.read_status()


async def _require_superadmin_stream_token(token: str, db: AsyncSession) -> None:
    """Prueft ein per Query-Parameter uebergebenes Stream-Ticket.

    Wortgleich zur Absicherung von `GET /api/admin/update-log` (admin.py):
    EventSource kann keinen Authorization-Header setzen, also wandert ein
    kurzlebiges Ticket in die URL. `decode_stream_token` weist
    mfa_pending-Token ab; die Gegenprobe in der Datenbank stellt sicher, dass
    ein gesperrtes, degradiertes oder abgemeldetes Konto nicht weiterstreamen
    kann, nachdem `token_version` erhoeht oder `is_superadmin` entzogen wurde.
    """
    token_data = decode_stream_token(token)
    if not token_data.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    result = await db.execute(select(User).where(User.id == token_data.user_id))
    db_user = result.scalar_one_or_none()
    if not db_user or not db_user.is_active:
        raise HTTPException(401, "Invalid token")
    if not db_user.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    if token_data.token_version != db_user.token_version:
        raise HTTPException(401, "Session expired — please log in again")


# Wie lange ein einzelner Strom offen bleibt (Sekunden). Deutlich groesser als
# beim Update-Log: ein Graph-Bau laeuft je nach Region Stunden, und genau
# dessen Ausgabe ist der Grund fuer diesen Endpunkt. Der Browser verbindet
# nach dem Ende ueber `retry:` von selbst neu und bekommt das Log ab Byte 0
# erneut — es geht also nichts verloren.
_LOG_STREAM_SECONDS = 3600
_LOG_POLL_SECONDS = 0.5
_LOG_KEEPALIVE_SECONDS = 20


@router.get("/log")
async def stream_region_log(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """SSE-Strom der Live-Ausgabe des Updaters (`region.log`).

    Das Panel zeigte bisher nur die fuenf bis acht Phasenmeldungen aus
    `region_status.json` — bei einem zweistuendigen Import stand dort eine
    einzige Zeile. `region.log` enthaelt dagegen die vollstaendige Ausgabe des
    Import-Containers (switch-region.sh leitet sie live dorthin um).

    Der Strom beginnt immer bei Byte 0: wer das Panel mitten im Import oeffnet
    oder neu laedt, bekommt den bisherigen Verlauf und danach den Zuwachs.
    Beendet wird er, sobald `region_status.json` eine Endphase meldet.
    """
    await _require_superadmin_stream_token(token, db)
    log_file = region_switch.log_path()

    async def log_generator():
        offset = 0
        # Rest einer noch unvollstaendigen Zeile. `f.read()` liefert, was gerade
        # in der Datei steht — schreibt der Updater in diesem Moment, endet der
        # Block mitten in einer Zeile. Ohne Puffer ginge dieses Fragment als
        # vollstaendige `data:`-Zeile hinaus und der Rest kaeme als zweite; im
        # Panel stand dann so etwas wie "[2026-09-05 10" ueber der eigentlichen
        # Zeile. Deshalb wird nur bis zum letzten Zeilenumbruch ausgeliefert.
        pending = b""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + _LOG_STREAM_SECONDS
        last_activity = loop.time()

        yield "retry: 2000\n\n"  # Hinweis an den Browser fuer den Neuaufbau

        while loop.time() < deadline:
            # Bewusst binaer gelesen und selbst dekodiert: `offset` ist eine
            # Byte-Position, und `seek()` auf einem Textstrom erwartet einen
            # undurchsichtigen Cookie aus `tell()`, keine beliebige Zahl.
            try:
                with open(log_file, "rb") as f:
                    f.seek(offset)
                    raw = f.read()
            except OSError:
                raw = b""
            if raw:
                offset += len(raw)
                last_activity = loop.time()
                pending += raw
                complete, sep, pending = pending.rpartition(b"\n")
                if sep:
                    for line in complete.decode("utf-8", errors="replace").split("\n"):
                        if line.strip():
                            yield f"data: {line}\n\n"

            # Endphase erst NACH dem Ausliefern des Zuwachses pruefen, sonst
            # fehlen die letzten Zeilen des Laufs.
            if region_switch.read_status().get("phase") in ("done", "failed"):
                # Eine letzte Zeile ohne abschliessenden Umbruch gehoert noch
                # dazu — der Updater ist fertig, es kommt nichts mehr nach.
                if pending.strip():
                    yield f"data: {pending.decode('utf-8', errors='replace')}\n\n"
                yield "event: done\ndata: \n\n"
                return

            if loop.time() - last_activity > _LOG_KEEPALIVE_SECONDS:
                yield ": keepalive\n\n"
                last_activity = loop.time()

            await asyncio.sleep(_LOG_POLL_SECONDS)

        yield "event: done\ndata: timeout\n\n"

    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Puffern in Nginx/Caddy abschalten
        },
    )


@router.post("/cancel", status_code=202)
async def cancel_region_switch(_: User = Depends(require_superadmin)):
    """Signalisiert dem Updater, einen laufenden Regionswechsel abzubrechen.

    409, wenn gerade keiner laeuft — es gibt dann nichts abzubrechen.
    """
    if not region_switch.is_busy():
        raise HTTPException(409, "Es läuft kein Regionswechsel.")
    region_switch.request_cancel()
    return {"status": "cancelling"}


@router.get("")
async def current_region(_: User = Depends(require_superadmin)):
    """Aktuell aktive Region (siehe `_read_active_region`)."""
    return _read_active_region()


@admin_router.get("/regions")
async def list_regions(_: User = Depends(require_superadmin)):
    """Liste aller bei Geofabrik verfuegbaren Regionen (Kontinente, Laender,
    Teilregionen), fuer die Auswahl im Panel.

    Der Index wird beim ersten Aufruf geholt und danach prozessweit im
    Speicher gecacht (siehe `geofabrik.list_regions`) — 555 Eintraege, ~3,8 MB
    JSON, die sich bei jedem Panel-Aufruf neu zu holen waere unnoetiger
    Traffic fuer eine Liste, die sich praktisch nie aendert.
    """
    try:
        entries = await geofabrik.list_regions()
    except ConnectionError as exc:
        raise HTTPException(503, str(exc)) from exc
    return [
        {"id": e.id, "name": e.name, "path": e.path, "url": e.url}
        for e in entries
    ]
