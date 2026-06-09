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

## Behebungsfristen (Patch-SLA)

Diese Zielfristen gelten ab Bestätigung einer Schwachstelle (intern gemeldet
oder durch automatisiertes Scanning erkannt) bis zur Bereitstellung eines Fixes
auf `main`. Sie decken sowohl eigenen Code als auch Abhängigkeiten/Container-
Images ab (überwacht über Dependabot, `pip-audit`/`npm audit` und Trivy in der
CI — siehe `docs/iso-certifications-review.md`, T10).

| Schweregrad (CVSS v3.1) | Zielfrist bis Fix |
|---|---|
| Kritisch (9.0–10.0) | **7 Tage** |
| Hoch (7.0–8.9) | **30 Tage** |
| Mittel (4.0–6.9) | **90 Tage** |
| Niedrig (0.1–3.9) | Nächster regulärer Release |

Lässt sich eine Schwachstelle nicht fristgerecht beheben (z. B. fehlender
Upstream-Patch), wird das Risiko dokumentiert und – wo möglich – durch
ausgleichende Maßnahmen (Mitigations) reduziert.

## Betrieb / Härtung

Hinweise zur sicheren Konfiguration (starkes `JWT_SECRET`, TLS, Backups,
Aufbewahrung von Standortdaten) finden sich in `README.md` sowie in
`docs/iso-certifications-review.md`.
