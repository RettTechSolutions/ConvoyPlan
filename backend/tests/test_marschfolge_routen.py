"""Umsortieren muss beim Umsortieren landen.

`/convoys/{convoy_id}/vehicles/reorder` und
`/convoys/{convoy_id}/vehicles/{vehicle_id}` sehen für den Router gleich aus:
Starlette nimmt die erste Route, die passt, und ein Platzhalter passt auch auf
`reorder`. Steht die Platzhalterroute vorn, läuft jedes Umsortieren in den PATCH
für ein einzelnes Fahrzeug und scheitert dort mit 422, weil „reorder" keine UUID
ist — die Marschfolge ließe sich nicht mehr ändern, ohne dass an der Route etwas
falsch aussähe.

Geprüft wird deshalb nicht der eine Fall, sondern die Regel: jeder feste Pfad
unter `/convoys` erreicht seinen eigenen Endpunkt.
"""

import re
import uuid

from app.api.routes.convoys import router

PLATZHALTER = re.compile(r"\{[^}]+\}")


def _fester_pfad(pfad: str) -> str:
    """Platzhalter durch Kennungen ersetzen, feste Segmente stehen lassen."""
    return PLATZHALTER.sub(lambda _: str(uuid.uuid4()), pfad)


def _erste_treffende(pfad: str, methode: str):
    for route in router.routes:
        treffer, _ = route.matches(
            {"type": "http", "path": pfad, "method": methode, "headers": []}
        )
        if treffer.name == "FULL":
            return route
    return None


def _routen_mit_festem_endsegment():
    for route in router.routes:
        letztes = route.path.rsplit("/", 1)[-1]
        if letztes and not PLATZHALTER.fullmatch(letztes):
            yield route


def test_umsortieren_erreicht_den_umsortier_endpunkt():
    pfad = f"/convoys/{uuid.uuid4()}/vehicles/reorder"

    assert _erste_treffende(pfad, "PATCH").name == "reorder_convoy_vehicles"


def test_kein_fester_pfad_wird_von_einem_platzhalter_geschluckt():
    verdeckt = []
    for route in _routen_mit_festem_endsegment():
        for methode in sorted(route.methods - {"HEAD"}):
            getroffen = _erste_treffende(_fester_pfad(route.path), methode)
            if getroffen is not route:
                verdeckt.append(
                    f"{methode} {route.path} landet bei "
                    f"{getattr(getroffen, 'path', 'nirgends')}"
                )

    assert verdeckt == []
