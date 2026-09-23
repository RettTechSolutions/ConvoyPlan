"""Betriebsstofflage eines Fahrzeugs im Marschverband.

Drei Angaben, die die Besatzung unterwegs meldet: Durchschnittsverbrauch
(l/100 km), nutzbares Tankvolumen (l) und Füllstand (%). Daraus rechnet jede
Ansicht selbst, was im Tank ist und wie weit es reicht — gespeichert wird nur,
was gemeldet wurde, wie bei der Stärke (``staerke.py``).

Hier liegen die Grenzen einmal für alle Wege, auf denen eine Meldung
hereinkommt. Die Companion-App prüft dieselben (``app/src/vehicle/fuel.ts``
dort); weicht eine Seite ab, nimmt die App an, was der Server still verwirft.
"""

# Ein Wechsellader liegt um 40 l/100 km, ein Kran darüber. 150 fängt die
# vertippte Null ab, ohne einen realen Fall auszuschließen.
MAX_VERBRAUCH = 150.0
# Der Fahrzeugtank, nicht die Ladung: ein Tankwagen trägt seinen Vorrat nicht
# im eigenen Tank.
MAX_TANK = 1500
MAX_FUELLSTAND = 100


def _zahl(name: str, wert, *, ganz: bool) -> float | int | None:
    if wert is None:
        return None
    # bool ist in Python ein int — als Messwert ist es ein Programmfehler.
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        raise ValueError(f"{name}: Zahl erwartet")
    if ganz:
        if isinstance(wert, float):
            if not wert.is_integer():
                raise ValueError(f"{name}: ganze Zahl erwartet")
            wert = int(wert)
    elif wert != wert:  # NaN
        raise ValueError(f"{name}: Zahl erwartet")
    return wert


def normalisieren(
    verbrauch,
    tank,
    fuellstand,
) -> tuple[float | None, int | None, int | None] | None:
    """Die drei Angaben prüfen.

    Gibt ``None`` zurück, wenn keine einzige angegeben ist — das wäre keine
    Meldung. Anders als bei der Stärke wird eine fehlende Angabe **nicht**
    aufgefüllt: Ein fehlender Tank ist unbekannt, nicht leer. Unplausible
    Werte lösen ``ValueError`` aus, und zwar für die ganze Meldung — eine halb
    übernommene wäre eine, die so niemand abgegeben hat.

    Ein Verbrauch oder Tank von 0 ist kein Messwert, sondern ein Tippfehler
    (die Reichweite würde unendlich bzw. null). Ein Füllstand von 0 dagegen
    ist eine Aussage, und eine dringende.
    """
    v = _zahl("verbrauch", verbrauch, ganz=False)
    t = _zahl("tank", tank, ganz=True)
    f = _zahl("fuellstand", fuellstand, ganz=True)

    if v is None and t is None and f is None:
        return None
    if v is not None and not 0 < v <= MAX_VERBRAUCH:
        raise ValueError(f"verbrauch: muss über 0 und höchstens {MAX_VERBRAUCH:g} liegen")
    if t is not None and not 0 < t <= MAX_TANK:
        raise ValueError(f"tank: muss über 0 und höchstens {MAX_TANK} liegen")
    if f is not None and not 0 <= f <= MAX_FUELLSTAND:
        raise ValueError(f"fuellstand: muss zwischen 0 und {MAX_FUELLSTAND} liegen")

    # Eine Nachkommastelle reicht für einen Durchschnittsverbrauch; mehr wäre
    # eine Genauigkeit, die es im Fahrzeug nicht gibt.
    return (None if v is None else round(float(v), 1), t, f)


def reichweite_km(
    verbrauch: float | None, tank: int | None, fuellstand: int | None
) -> float | None:
    """Reichweite in Kilometern — ``None``, solange eine Angabe fehlt."""
    if verbrauch is None or tank is None or fuellstand is None or verbrauch <= 0:
        return None
    return tank * fuellstand / 100 / verbrauch * 100
