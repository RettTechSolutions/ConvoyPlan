"""Mannschaftsstärke (Personalstärke) eines Fahrzeugs im Marschverband.

Geschrieben wird sie ``Führer/Unterführer/Mannschaften//Gesamt``, also etwa
``0/1/8//9``. Gespeichert werden nur die ersten drei Zahlen — die Gesamtzahl
wird gerechnet, nie eingegeben, sonst driftet sie von den Summanden weg.

Hier liegt das Vokabular einmal für alle Wege, auf denen eine Stärke
hereinkommt: der angemeldete Endpunkt und der öffentliche Fahrer-Link. Beide
prüfen dieselben Grenzen, sonst nimmt der eine an, was der andere abweist.
"""

# Mehr als 99 Personen in *einer* Rolle auf *einem* Fahrzeug gibt es nicht; die
# Grenze fängt vertippte Zahlen ab, ohne einen realen Fall auszuschließen.
MAX_JE_ROLLE = 99

_ROLLEN = ("fuehrer", "unterfuehrer", "mannschaften")


def normalisieren(
    fuehrer: int | None,
    unterfuehrer: int | None,
    mannschaften: int | None,
) -> tuple[int, int, int] | None:
    """Die drei Zahlen prüfen und auffüllen.

    Gibt ``None`` zurück, wenn keine einzige Zahl angegeben ist — „nicht
    gemeldet". Ist mindestens eine angegeben, zählen die fehlenden als 0:
    ``0/0/0`` ist dann eine Aussage (niemand an Bord) und kein Fehlen.
    Unplausible Zahlen lösen ``ValueError`` aus.
    """
    werte = (fuehrer, unterfuehrer, mannschaften)
    if all(w is None for w in werte):
        return None

    geprueft: list[int] = []
    for rolle, wert in zip(_ROLLEN, werte):
        if wert is None:
            geprueft.append(0)
            continue
        # bool ist in Python ein int — als Stärke ist es ein Programmfehler.
        if isinstance(wert, bool) or not isinstance(wert, int):
            raise ValueError(f"{rolle}: ganze Zahl erwartet")
        if not 0 <= wert <= MAX_JE_ROLLE:
            raise ValueError(f"{rolle}: muss zwischen 0 und {MAX_JE_ROLLE} liegen")
        geprueft.append(wert)
    return (geprueft[0], geprueft[1], geprueft[2])


def gesamt(
    fuehrer: int | None,
    unterfuehrer: int | None,
    mannschaften: int | None,
) -> int | None:
    """Gesamtstärke, oder ``None`` wenn nichts gemeldet ist.

    Nicht 0 im Fehlen-Fall: die Führung muss „keine Meldung" von „keine
    Besatzung" unterscheiden können.
    """
    werte = normalisieren(fuehrer, unterfuehrer, mannschaften)
    return None if werte is None else sum(werte)
