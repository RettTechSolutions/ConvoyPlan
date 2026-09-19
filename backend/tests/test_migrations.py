"""Der Migrationsgraph — genau ein Kopf, keine doppelte Kennung.

Diese Prüfung gibt es, weil der Fehler eingetreten ist: zwei Zweige, die
unabhängig voneinander die nächste freie Nummer nahmen, ergaben zweimal `0043`
und damit zwei Köpfe. `alembic upgrade head` bleibt darauf stehen — nicht beim
Entwickeln, sondern erst nach dem Zusammenführen, also genau dann, wenn niemand
mehr an die Migration denkt.

Am Graphen und nicht an den Dateinamen: die Nummer im Dateinamen ist Konvention,
`revision`/`down_revision` sind die Wahrheit. Gelesen wird über Alembics eigenes
`ScriptDirectory` — dieselbe Stelle, die auch `alembic upgrade` benutzt —, und
das braucht dafür keine Datenbank.
"""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def skripte() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))


def test_es_gibt_genau_einen_kopf(skripte: ScriptDirectory):
    """Zwei Köpfe heißen: `alembic upgrade head` weiß nicht, wohin."""
    koepfe = skripte.get_heads()
    assert len(koepfe) == 1, (
        f"Mehrere Köpfe: {koepfe}. Die jüngere Migration muss auf die ältere "
        "zeigen (`down_revision`), statt neben ihr zu stehen."
    )


def test_keine_kennung_kommt_zweimal_vor(skripte: ScriptDirectory):
    """Zwei Dateien mit derselben `revision` — der Fall, der 0043 traf."""
    kennungen = [skript.revision for skript in skripte.walk_revisions()]
    doppelt = {k for k in kennungen if kennungen.count(k) > 1}
    assert not doppelt, f"Doppelt vergebene Revisionskennungen: {sorted(doppelt)}"


def test_jede_migration_haengt_an_der_vorigen(skripte: ScriptDirectory):
    """Nur die erste Migration darf ohne Vorgänger dastehen."""
    ohne_vorgaenger = [s.revision for s in skripte.walk_revisions() if s.down_revision is None]
    assert len(ohne_vorgaenger) == 1, (
        f"Migrationen ohne `down_revision`: {sorted(ohne_vorgaenger)} — es darf "
        "nur den einen Anfang geben."
    )
