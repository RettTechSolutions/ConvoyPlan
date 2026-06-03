# Security Policy

## Eine Schwachstelle melden

Wir nehmen Sicherheit ernst. Wenn du eine Sicherheitslücke in ConvoyPlan
findest, melde sie bitte **verantwortungsvoll und nicht öffentlich**:

- **E-Mail:** anfrage@convoyplan.de
- Bitte gib eine Beschreibung, betroffene Version/Commit und – wenn möglich –
  eine Reproduktion oder einen Proof-of-Concept an.
- Veröffentliche Details bitte erst nach Abstimmung mit uns (Coordinated
  Disclosure).

Wir bestätigen den Eingang in der Regel innerhalb weniger Werktage und halten
dich über den Fortschritt der Behebung auf dem Laufenden.

## Unterstützte Versionen

Sicherheitsupdates werden für die jeweils aktuelle Release-Linie auf `main`
bereitgestellt. Self-hosted-Instanzen sollten den Auto-Updater aktivieren oder
regelmäßig auf den neuesten Stand aktualisieren.

## Betrieb / Härtung

Hinweise zur sicheren Konfiguration (starkes `JWT_SECRET`, TLS, Backups,
Aufbewahrung von Standortdaten) finden sich in `README.md` sowie in
`docs/iso-certifications-review.md`.
