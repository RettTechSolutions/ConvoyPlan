"""Die Verhaltenszusagen an den Werkzeugen.

Die MCP-Spezifikation kennt vier Hinweise, mit denen ein Werkzeug sagt, wie es
sich verhält. Sie sind **unverbindlich** — ein Client darf ihnen nicht
vertrauen, wo es um Rechte geht, dafür gibt es Scopes und die Rollenprüfung.
Nützlich sind sie trotzdem: ohne sie muss ein Client aus dem Namen raten, ob
ein Aufruf etwas anrichtet, und die Entwicklerrichtlinien für ChatGPT-Apps
fragen ausdrücklich danach.

Die wichtigste Zusage, die ConvoyPlan hier machen kann, ist ``destructive =
False`` an **jedem** Werkzeug. Das ist keine Schönfärberei, sondern die
Positivliste in ``app/mcp/__init__.py`` in anderer Form: Es gibt kein Werkzeug,
das einen Konvoi, ein Fahrzeug, einen Wegpunkt oder eine Route löscht.
``fahrzeug_aus_konvoi_entfernen`` löst eine Zuordnung — der Datensatz bleibt,
und der Aufruf lässt sich mit ``fahrzeug_zu_konvoi_hinzufuegen`` zurücknehmen.

``open_world`` ist überall ``False``: Die Werkzeuge arbeiten auf dem Bestand
**einer** Organisation in dieser Instanz, nicht auf einer offenen Menge. Die
einzige Ausnahme wäre ``route_berechnen``, das GraphHopper befragt — auch das
ist ein Dienst dieser Installation, kein offenes Netz.
"""
from mcp.types import ToolAnnotations


def lesend(titel: str) -> ToolAnnotations:
    """Ein Werkzeug, das nur liest.

    ``idempotent`` bleibt offen statt ``True``: Zweimal dasselbe zu lesen kann
    Verschiedenes ergeben, wenn dazwischen jemand etwas geändert hat. Die
    Zusage, die hier zählt, ist ``read_only``."""
    return ToolAnnotations(
        title=titel, read_only_hint=True, destructive_hint=False, open_world_hint=False
    )


def schreibend(titel: str, *, idempotent: bool = False) -> ToolAnnotations:
    """Ein Werkzeug, das anlegt oder ändert — aber nichts zerstört.

    ``idempotent`` für die Werkzeuge, bei denen ein zweiter identischer Aufruf
    denselben Zustand ergibt (Ändern, Umsortieren, Status setzen). Beim Anlegen
    nicht: ein zweiter Aufruf erzeugt einen zweiten Konvoi."""
    return ToolAnnotations(
        title=titel,
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=idempotent,
        open_world_hint=False,
    )
