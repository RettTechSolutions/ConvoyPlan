"""Die Scopes des MCP-Servers und ihr Verhältnis zu den Rollen.

Scopes sind hier **keine zweite Berechtigungslogik**, sondern eine Projektion
der bestehenden Rollenhierarchie aus ``app/api/guards.py``. Ein Token kann nie
mehr dürfen als die Mitgliedschaft des Benutzers in der gewählten
Organisation: was der Benutzer als *beobachter* nicht darf, darf auch ein
Token nicht, das ``convoy:write`` verlangt.

Es gibt bewusst **keinen** Scope für Löschen, für Administration oder für
irgendetwas auf Instanz-Ebene.
"""
from app.api.guards import ROLE_ORDER

# Lesen: Konvois, Fahrzeuge, Wegpunkte, Routen, Positionen, Status.
SCOPE_READ = "convoy:read"
# Fahrzeugstatus und Positionen setzen — das, was eine Besatzung unterwegs tut.
SCOPE_FLEET_STATUS = "fleet:status"
# Anlegen, Ändern, Route berechnen. Löschen ist auch hiermit nicht möglich.
SCOPE_WRITE = "convoy:write"

ALL_SCOPES: tuple[str, ...] = (SCOPE_READ, SCOPE_FLEET_STATUS, SCOPE_WRITE)

# Welche Mindestrolle ein Scope voraussetzt. Die Namen sind exakt die der
# Mitgliedschaftsrollen; ROLE_ORDER bleibt die einzige Rangfolge im System.
SCOPE_MIN_ROLE: dict[str, str] = {
    SCOPE_READ: "beobachter",
    SCOPE_FLEET_STATUS: "fahrer",
    SCOPE_WRITE: "planer",
}

# Scope-Hierarchie: Die Spec verlangt ausdrücklich, dass der Server
# berücksichtigt, wenn ein breiterer Scope einen engeren einschließt. Wer
# schreiben darf, darf auch Status setzen und lesen.
SCOPE_IMPLIES: dict[str, frozenset[str]] = {
    SCOPE_WRITE: frozenset({SCOPE_WRITE, SCOPE_FLEET_STATUS, SCOPE_READ}),
    SCOPE_FLEET_STATUS: frozenset({SCOPE_FLEET_STATUS, SCOPE_READ}),
    SCOPE_READ: frozenset({SCOPE_READ}),
}

# Was die Protected Resource Metadata als scopes_supported ausweist. Die Spec
# will hier den *minimalen* Satz für die Grundfunktion sehen, nicht die
# Gesamtmenge — breitere Scopes fordert der Client per Step-up nach.
SCOPES_SUPPORTED: list[str] = [SCOPE_READ]

# Menschenlesbare Beschreibungen für den Consent-Screen. Ein Benutzer, der
# "convoy:write" liest, hat nichts verstanden.
SCOPE_LABELS: dict[str, str] = {
    SCOPE_READ: "Konvois, Fahrzeuge, Wegpunkte, Routen und Positionen lesen",
    SCOPE_FLEET_STATUS: "Fahrzeugstatus und Positionen melden",
    SCOPE_WRITE: "Konvois und Fahrzeuge anlegen und ändern, Routen berechnen",
}


def expand(scopes: list[str] | set[str] | tuple[str, ...]) -> frozenset[str]:
    """Eine Scope-Menge um alles erweitern, was sie einschließt."""
    result: set[str] = set()
    for scope in scopes:
        result |= SCOPE_IMPLIES.get(scope, frozenset({scope}))
    return frozenset(result)


def satisfies(granted: list[str] | set[str] | tuple[str, ...], required: str) -> bool:
    """Ob eine erteilte Scope-Menge den geforderten Scope abdeckt."""
    return required in expand(granted)


def scopes_for_role(role: str) -> list[str]:
    """Die Scopes, die eine Rolle überhaupt erhalten kann.

    Ein unbekannter Rollenname ergibt die leere Liste — fail-closed, nicht
    fail-open: eine Rolle, die wir nicht kennen, bekommt nichts."""
    rank = ROLE_ORDER.get(role, -1)
    return [s for s in ALL_SCOPES if rank >= ROLE_ORDER[SCOPE_MIN_ROLE[s]]]


def grantable(requested: list[str] | set[str] | tuple[str, ...], role: str) -> list[str]:
    """Aus den angefragten Scopes die herausfiltern, die die Rolle hergibt.

    Der Schnitt, nicht die Vereinigung: ein Client, der zu viel verlangt,
    bekommt weniger statt eines Fehlers — und ein Client, der zu wenig
    verlangt, bekommt nicht mehr, als er wollte."""
    allowed = set(scopes_for_role(role))
    return [s for s in ALL_SCOPES if s in allowed and s in set(requested)]


# ── Welcher Scope für welches Werkzeug ───────────────────────────────────
#
# Dieselbe Zuordnung, die die Werkzeuge selbst über ``ctx.require()``
# erzwingen — hier noch einmal als Tabelle, damit die Transportschicht sie
# *vor* dem Aufruf kennt und eine protokollgerechte Scope-Challenge senden
# kann (RFC 6750 §3.1). Ein Werkzeugfehler kann das nicht: er entsteht
# innerhalb einer bereits beantworteten HTTP-Anfrage.
#
# Die Tabelle ist damit eine zweite Quelle derselben Wahrheit. Ein Test
# (``tests/test_mcp_stepup.py``) vergleicht sie gegen die registrierten
# Werkzeuge, damit sie nicht auseinanderläuft: jedes Werkzeug muss hier
# stehen, und kein Eintrag darf auf ein Werkzeug zeigen, das es nicht gibt.
TOOL_SCOPES: dict[str, str] = {
    # Lesend
    "konvois_auflisten": SCOPE_READ,
    "konvoi_details": SCOPE_READ,
    "unterkonvois_auflisten": SCOPE_READ,
    "fahrzeuge_auflisten": SCOPE_READ,
    "fahrzeug_details": SCOPE_READ,
    "wegpunkte_auflisten": SCOPE_READ,
    "route_abrufen": SCOPE_READ,
    "fahrzeugpositionen_abrufen": SCOPE_READ,
    "konvoi_status": SCOPE_READ,
    # Schreibend
    "konvoi_anlegen": SCOPE_WRITE,
    "konvoi_aktualisieren": SCOPE_WRITE,
    "fahrzeug_anlegen": SCOPE_WRITE,
    "fahrzeug_aktualisieren": SCOPE_WRITE,
    "fahrzeug_zu_konvoi_hinzufuegen": SCOPE_WRITE,
    "fahrzeug_aus_konvoi_entfernen": SCOPE_WRITE,
    "konvoi_fahrzeuge_umsortieren": SCOPE_WRITE,
    "wegpunkt_anlegen": SCOPE_WRITE,
    "wegpunkt_aktualisieren": SCOPE_WRITE,
    "wegpunkte_umsortieren": SCOPE_WRITE,
    "route_berechnen": SCOPE_WRITE,
    # Marschstatus melden ist das, was eine Besatzung unterwegs tut.
    "fahrzeugstatus_setzen": SCOPE_FLEET_STATUS,
}


def required_for_tool(name: str) -> str | None:
    """Der Scope, den ein Werkzeug voraussetzt; None bei unbekanntem Namen.

    Unbekannt heißt hier ausdrücklich **nicht** „darf alles": die
    Transportschicht lässt einen unbekannten Namen durch und überlässt die
    Ablehnung dem SDK, das ihn ohnehin nicht kennt."""
    return TOOL_SCOPES.get(name)
