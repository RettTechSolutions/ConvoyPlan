# Handbücher (PDF)

`build.py` setzt aus dem Wiki und den `docs/` der vier Repos Handbücher als PDF
zusammen: Deckblatt, Inhaltsverzeichnis mit Seitenzahlen, Lesezeichen, klickbare
Querverweise, gezeichnete Mermaid-Diagramme und Bildschirmfotos an den passenden
Stellen.

| Buch | Ziel | Sichtbar |
|---|---|---|
| Anwenderhandbuch | `frontend/static/handbuecher/` | öffentlich, auf jeder Instanz unter `/handbuecher` |
| Betriebs- und Administrationshandbuch | `frontend/static/handbuecher/` | öffentlich |
| Begleit-App (Anleitung, Glossar) | `frontend/static/handbuecher/` | öffentlich |
| Begleit-App, Tracker, EventTracker (vollständig) | `docs/handbuch/` im jeweiligen Repo | nur dort — die Repos sind privat |

**Was öffentlich wird, entscheidet `ziel` in `BOOKS`.** Ein öffentliches Buch steht
in diesem Repo und auf jeder Instanz. Darin nur, was ohnehin öffentlich ist (Wiki)
oder für Anwender geschrieben wurde. Verweise in private Repos werden dort zu Text.

## Erzeugen

Die privaten Repos als Geschwister dieses Repos auschecken (`../Convoyplan-Companion`,
`../ConvoyPlan-Tracker`, `../Convoyplan-EventTracker`); fehlt eins, wird sein Buch
übersprungen. Dann:

```bash
python3 docs/handbuecher/build.py
```

Nur einzelne Bücher: die Namen anhängen, z. B. `build.py ConvoyPlan-Anwenderhandbuch`.
Der Lauf schreibt neben den PDFs `frontend/src/lib/handbuecher/katalog.json`
(Seitenzahl, Größe, Stand) — die Seite `/handbuecher` liest sie. PDFs und Katalog
gehören in denselben Commit.

Gebraucht werden `pandoc`, `pdftotext` (poppler), Python mit `pypdf` und `Pillow`,
Node mit Playwright samt Chromium (das aus `frontend/` genügt) und die Schriften
Inter und DejaVu. Mermaid holt sich das Skript beim ersten Lauf nach `.cache/`.

## Wann neu erzeugen

Wenn sich ein Kapitel nennenswert ändert, und vor einem Release. Die PDFs sind kein
Abbild jedes Commits; was zwischen zwei Läufen im Wiki dazukommt, steht im Wiki.

## Bildschirmfotos

Die meisten Bilder in `bilder/` stammen aus einer Demo-Organisation auf `web.convoyplan.de`
(28. und 31.10.2026). Fahrer-Link und Teilen-Dialog (`fahrer-*`, `teilen-*`) sind gestellt wie
in den E2E-Tests und entstehen mit `npm run wiki:bilder` in `frontend/`
(`wiki-bilder/fahrer-link.bilder.ts`) — ein echter Fahrer-Link hieße, Positionen freizugeben.
Die Bilder der Begleit-App (`app-*`) sind die rohen Geräteaufnahmen aus dem Companion-Repo
(`store/*/screenshots/quelle/`), dieselben wie in den Store-Einträgen. **Vor jeder Aufnahme ersetzt**: Namen und E-Mail-Adressen echter
Mitglieder, der Slug in der Abruf-Adresse einer Aktionsseite, die IMEI eines Trackers
und der Name des Telegram-Bots. Wer neue aufnimmt, tut dasselbe — ein Handbuch hier
ist öffentlich. Wo welches Bild steht, sagt `FIGURES` (Kapitel und Überschrift);
fehlt eine Überschrift nach einer Wiki-Änderung, meldet der Lauf `! Überschrift fehlt`.
