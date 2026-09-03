"""Regionswechsel im Admin-Panel: Vorab-Rechnung (Preview) vor dem Graph-Bau.

Dieser Router traegt bewusst nur `POST /admin/region/preview` unter dem
Prefix `/admin/region` (Singular). Task 5 braucht zusaetzlich
`GET /api/admin/regions` (Plural, Liste verfuegbarer Regionen) — das liegt
ausserhalb dieses Prefix und gehoert NICHT hierher. Dafuer legt Task 5 einen
eigenen `APIRouter` an (z. B. `app/api/routes/regions.py`), sonst kollidiert
der Prefix mit `/admin/region/{irgendwas}` und FastAPI muesste zwischen
`/admin/region/preview` und `/admin/regions` anhand der Routing-Reihenfolge
disambiguieren.

`preview` hat keine Nebenwirkung: es schreibt nichts (kein Aufruf von
`region_switch.write_request`) und loest keinen Import aus. Es beantwortet
nur die Frage, ob eine Region auf diese Maschine passt, bevor der Operator
einen stundenlangen Graph-Bau anstoesst.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_superadmin
from app.config import settings
from app.models.user import User
from app.services import geofabrik, host_metrics, region_estimate

router = APIRouter(prefix="/admin/region", tags=["admin"])

# Read-only in docker-compose.yml gemountet (siehe dort) — das Backend
# schreibt hier nichts, `df` auf dem Mount meldet das darunterliegende
# Dateisystem, also genau die Kapazitaet, die Extract und Graph tatsaechlich
# zur Verfuegung steht.
OSM_PATH = "/data/osm"
GRAPH_PATH = "/data/graph"


class RegionUrl(BaseModel):
    url: str


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
async def preview(body: RegionUrl, _: User = Depends(require_superadmin)):
    """Schaetzt Ressourcenbedarf und -verfuegbarkeit fuer einen Regionswechsel.

    Reine Lesefunktion: validiert nur die URL, fragt per HTTP-HEAD die
    Extract-Groesse ab und liest lokale Hardware-Kennzahlen — es wird nichts
    heruntergeladen, geschrieben oder an den Updater gemeldet.
    """
    try:
        geofabrik.validate_region_url(body.url)
        extract = await geofabrik.head_size_bytes(body.url)
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
    return {
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
