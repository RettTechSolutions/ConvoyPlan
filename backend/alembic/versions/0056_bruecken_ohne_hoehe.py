"""Brücken über der Route ohne bekannte Durchfahrtshöhe (services/bruecken.py).

Zwei Spalten an ``routes``:

- ``bruecken``: das Ergebnis der Suche, ``{"geprueft_at": …, "eintraege": […]}``.
  Gesucht wird nach der Berechnung über Overpass, nicht in ihr — die Abfrage
  dauert, und eine Routenberechnung soll nicht an einem fremden Dienst hängen.
  NULL heißt „nicht gesucht"; jede Neuberechnung setzt es zurück.
- ``schnellstrassen``: Meterbereiche auf Autobahn und Kraftfahrstraße aus
  GraphHoppers ``road_class``, festgehalten bei der Berechnung. Die Suche läuft
  später und braucht sie, um dort zu zählen statt aufzulisten.

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("routes", sa.Column("bruecken", sa.JSON(), nullable=True))
    op.add_column("routes", sa.Column("schnellstrassen", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("routes", "schnellstrassen")
    op.drop_column("routes", "bruecken")
