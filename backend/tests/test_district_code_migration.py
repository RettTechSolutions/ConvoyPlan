"""Tests für die Schlüsselumstellung in Migration 0039.

Die Migration schreibt gespeicherte Nutzdaten um — geht dabei etwas schief,
verlieren Leitstellen ihr Zuständigkeitsgebiet. Die Transformationen sind
deshalb als eigene Funktionen herausgezogen und hier ohne Datenbank geprüft.
"""
import importlib.util
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic" / "versions" / "0039_district_codes_country_prefix.py"
)

_spec = importlib.util.spec_from_file_location("migration_0039", MIGRATION)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def test_bare_ags_gets_german_prefix():
    assert m.add_prefix(["08115", "09162"]) == ["DE-08115", "DE-09162"]


def test_add_prefix_is_idempotent():
    once = m.add_prefix(["08115"])
    assert m.add_prefix(once) == once
    # Auch gemischte Listen (Teil-Migration abgebrochen) laufen sauber durch.
    assert m.add_prefix(["DE-08115", "09162"]) == ["DE-08115", "DE-09162"]


def test_add_prefix_leaves_foreign_codes_alone():
    codes = ["AT-322", "CH-040", "LI-000"]
    assert m.add_prefix(codes) == codes


def test_strip_prefix_restores_old_schema():
    assert m.strip_prefix(["DE-08115", "DE-09162"]) == ["08115", "09162"]


def test_strip_prefix_drops_non_german_areas():
    # Ein Downgrade kann AT/CH/LI nicht abbilden — die Gebiete fallen weg,
    # statt als nicht auflösbare Nummern stehen zu bleiben.
    assert m.strip_prefix(["DE-08115", "AT-322", "CH-040"]) == ["08115"]


def test_roundtrip_is_lossless_for_german_codes():
    codes = ["08115", "11000", "09162"]
    assert m.strip_prefix(m.add_prefix(codes)) == codes
