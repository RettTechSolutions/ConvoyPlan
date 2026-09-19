"""Die Bereiche — welcher Ausschnitt der Fachdaten einer Verbindung offensteht.

Scopes beantworten „lesen oder schreiben". Sie beantworten nicht „worauf".
Ein Konvoi-Assistent, der Marschzeiten plant, braucht keine Positionen der
Besatzungen; ein Statusmelder braucht keine Marschbefehle. Bis hierher ging
beides nur zusammen, weil ``convoy:read`` alles Lesbare meinte.

Diese Datei zieht die zweite Achse ein: jedes Werkzeug gehört zu genau einem
Bereich, und eine Organisation gibt frei, welche Bereiche sie überhaupt
hergibt. Beide Achsen wirken als **Und**: ein Werkzeug steht zur Verfügung,
wenn sein Scope erteilt *und* sein Bereich freigegeben ist.

Genau ein Bereich je Werkzeug, auch wenn manche zwei Dinge berühren
(``fahrzeug_zu_konvoi_hinzufuegen`` ändert eine Zuordnung zwischen beiden).
Maßgeblich ist, was der Aufruf **verändert oder preisgibt**, nicht was er
nebenbei erwähnt — eine Regel mit zwei Bereichen je Werkzeug wäre im Portal
nicht mehr erklärbar und im Zweifel zu eng.

``organisation_details`` steht in keinem Bereich: es nennt Name und
Beschreibung der Organisation, für die die Verbindung ohnehin gilt. Etwas zu
verbergen, was im Zustimmungsbildschirm dranstand, wäre Sicherheitstheater —
also steht es in ``GRUNDWERKZEUGE`` und ist immer dabei.
"""
from app.mcp import READ_TOOLS, WRITE_TOOLS

BEREICH_KONVOIS = "konvois"
BEREICH_FAHRZEUGE = "fahrzeuge"
BEREICH_WEGPUNKTE = "wegpunkte"
BEREICH_ROUTEN = "routen"
BEREICH_STATUS = "status"

ALL_BEREICHE: tuple[str, ...] = (
    BEREICH_KONVOIS,
    BEREICH_FAHRZEUGE,
    BEREICH_WEGPUNKTE,
    BEREICH_ROUTEN,
    BEREICH_STATUS,
)

# Was im Portal und auf dem Zustimmungsbildschirm dransteht. Ein Org-Admin
# liest „konvois" nicht als Berechtigung, sondern als Datenbankspalte.
BEREICH_LABELS: dict[str, str] = {
    BEREICH_KONVOIS: "Konvois und Marschbefehle",
    BEREICH_FAHRZEUGE: "Fahrzeuge und ihre Zuordnung zum Konvoi",
    BEREICH_WEGPUNKTE: "Wegpunkte und Marschstrecke",
    BEREICH_ROUTEN: "Routen abrufen und berechnen",
    BEREICH_STATUS: "Live-Positionen, Marschstatus und Mannschaftsstärke",
}

# Werkzeuge ohne Bereich — immer verfügbar, solange die Verbindung überhaupt
# besteht. Absichtlich kurz und absichtlich hier statt als Sonderfall im Code.
GRUNDWERKZEUGE: tuple[str, ...] = ("organisation_details",)

TOOL_BEREICHE: dict[str, str] = {
    # Konvois: die Kolonne selbst, ihre Gliederung und der Marschbefehl.
    "konvois_auflisten": BEREICH_KONVOIS,
    "konvoi_details": BEREICH_KONVOIS,
    "unterkonvois_auflisten": BEREICH_KONVOIS,
    "konvoi_anlegen": BEREICH_KONVOIS,
    "konvoi_aktualisieren": BEREICH_KONVOIS,
    # Die Marschordnung ist eine Eigenschaft des Konvois, nicht der Fahrzeuge.
    "konvoi_fahrzeuge_umsortieren": BEREICH_KONVOIS,
    # Fahrzeuge: der Fuhrpark und wer in welcher Kolonne mitfährt.
    "fahrzeuge_auflisten": BEREICH_FAHRZEUGE,
    "fahrzeug_details": BEREICH_FAHRZEUGE,
    "fahrzeug_anlegen": BEREICH_FAHRZEUGE,
    "fahrzeug_aktualisieren": BEREICH_FAHRZEUGE,
    "fahrzeug_zu_konvoi_hinzufuegen": BEREICH_FAHRZEUGE,
    "fahrzeug_aus_konvoi_entfernen": BEREICH_FAHRZEUGE,
    # Wegpunkte.
    "wegpunkte_auflisten": BEREICH_WEGPUNKTE,
    "wegpunkt_anlegen": BEREICH_WEGPUNKTE,
    "wegpunkt_aktualisieren": BEREICH_WEGPUNKTE,
    "wegpunkte_umsortieren": BEREICH_WEGPUNKTE,
    # Routen.
    "route_abrufen": BEREICH_ROUTEN,
    "route_berechnen": BEREICH_ROUTEN,
    # Status: wo die Fahrzeuge stehen und wie weit die Kolonne ist. Der
    # empfindlichste Bereich — hier hängen Standorte von Menschen dran.
    "fahrzeugpositionen_abrufen": BEREICH_STATUS,
    "konvoi_status": BEREICH_STATUS,
    "fahrzeugstatus_setzen": BEREICH_STATUS,
    # Die Mannschaftsstärke gehört zur Lage, nicht zum Fuhrpark: sie sagt,
    # wer gerade unterwegs ist, und ändert sich mit jeder Meldung.
    "fahrzeugstaerke_melden": BEREICH_STATUS,
}

# Was eine frisch eingeschaltete Organisation bekommt, solange niemand etwas
# anderes einstellt: alle Bereiche, aber nur lesend (siehe
# ``services/org_mcp_policy.py``). Die Einschränkung sitzt bei den Scopes,
# nicht hier — „nichts sehen" ist kein brauchbarer Ausgangszustand für eine
# Verbindung, die jemand gerade bewusst eingeschaltet hat.
STANDARD_BEREICHE: tuple[str, ...] = ALL_BEREICHE


def bereich_fuer(werkzeug: str) -> str | None:
    """Der Bereich eines Werkzeugs; None bei den Grundwerkzeugen.

    Ein **unbekannter** Name landet ebenfalls bei None und damit im Freien.
    Das ist kein Leck: Werkzeuge, die es nicht gibt, ruft niemand auf, und
    ``tests/test_org_mcp_policy.py`` hält die Tabelle gegen die
    Positivliste in ``app/mcp/__init__.py`` — ein neues Werkzeug ohne Bereich
    bricht dort, bevor es in Produktion etwas heraustragen kann."""
    return TOOL_BEREICHE.get(werkzeug)


def erlaubt(werkzeug: str, bereiche: list[str] | set[str] | tuple[str, ...]) -> bool:
    """Ob ein Werkzeug unter den freigegebenen Bereichen benutzbar ist."""
    bereich = bereich_fuer(werkzeug)
    return bereich is None or bereich in set(bereiche)


def werkzeuge_fuer(bereiche: list[str] | set[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Alle Werkzeuge, die unter diesen Bereichen benutzbar sind."""
    return tuple(w for w in (*READ_TOOLS, *WRITE_TOOLS) if erlaubt(w, bereiche))
