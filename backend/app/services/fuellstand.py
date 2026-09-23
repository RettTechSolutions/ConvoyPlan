"""Gemeldeter Füllstand eines Fahrzeugs im Marschverband — Tank oder Akku.

Gemeldet wird in **Prozent**, nicht in Litern: Die Besatzung liest eine
Tanknadel ab („halb", „Reserve"), keine Literzahl, und ein E-Fahrzeug zeigt
ohnehin Prozent. Liter und Reichweite rechnet die Anzeige aus den Stammdaten
(Tankvolumen, Verbrauch) — die Meldung selbst bleibt eine Aussage darüber, was
die Besatzung gesehen hat.

Hier liegt die Prüfung einmal für alle Wege, auf denen ein Füllstand
hereinkommt: der angemeldete Endpunkt und der öffentliche Fahrer-Link. Beide
prüfen dieselben Grenzen, sonst nimmt der eine an, was der andere abweist.
"""

MIN_PROZENT = 0
MAX_PROZENT = 100


def normalisieren(prozent: object) -> int:
    """Den gemeldeten Füllstand prüfen.

    Eine ganze Zahl zwischen 0 und 100. Alles andere löst ``ValueError`` aus —
    auch ``None``: anders als bei der Stärke gibt es keine Teilmeldung, und ein
    leerer Frame ist keine Meldung.
    """
    # bool ist in Python ein int — als Füllstand ist es ein Programmfehler.
    if isinstance(prozent, bool) or not isinstance(prozent, int):
        raise ValueError("prozent: ganze Zahl erwartet")
    if not MIN_PROZENT <= prozent <= MAX_PROZENT:
        raise ValueError(f"prozent: muss zwischen {MIN_PROZENT} und {MAX_PROZENT} liegen")
    return prozent
