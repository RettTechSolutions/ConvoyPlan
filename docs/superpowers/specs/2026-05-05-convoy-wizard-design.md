# Convoy-Wizard: Geführte Erstellung mit Kartenklick

**Datum:** 2026-05-05  
**Status:** Approved

## Ziel

Einen neuen Marschverband per geführtem 3-Schritt-Wizard anlegen: Name vergeben, dann Startpunkt, Zielpunkt und Wegpunkte per Kartenklick oder Adresssuche setzen.

## Vereinfachtes Erstellungs-Modal

Das bestehende Modal wird auf **Name** (Pflicht) und **Startzeit** (optional) reduziert. Alle anderen Felder (Lage, Auftrag, Marschform, Funkgruppe usw.) bleiben im Plan-Tab für spätere Bearbeitung erhalten. Nach dem Erstellen startet automatisch der Wizard (Schritt 1).

## Wizard-Flow (3 Schritte)

Der Wizard ersetzt den Tab-Inhalt der Sidebar solange er aktiv ist. Zustand: `wizardStep: 0 | 1 | 2 | 3` in `+page.svelte` (0 = inaktiv).

### Schritt 1 — Startpunkt
- `mapMode` wird auf `'set-start'` gesetzt
- Sidebar zeigt: Überschrift "Startpunkt setzen", `LocationSearch`-Komponente, Hinweis "oder direkt auf Karte klicken ↗", Link "Überspringen"
- Nach Kartenklick oder Auswahl aus Suche → Koordinaten werden per `convoysApi.update()` gespeichert → automatisch weiter zu Schritt 2

### Schritt 2 — Zielpunkt
- `mapMode` wird auf `'set-end'` gesetzt
- Identisches Layout wie Schritt 1
- Nach Setzen → weiter zu Schritt 3

### Schritt 3 — Wegpunkte
- `mapMode` wird auf `'add-waypoint'` gesetzt
- Sidebar zeigt: Suchfeld, optionales Name-Feld (Fallback: "WP 1", "WP 2" …), Liste bereits gesetzter Wegpunkte
- Modus bleibt aktiv; jeder Klick/jede Suche fügt einen Wegpunkt hinzu
- Button "Fertig" beendet den Wizard (`wizardStep = 0`, `mapMode = 'idle'`)
- Link "Überspringen" überspringt ohne Wegpunkte

## Neue Komponente: `LocationSearch.svelte`

```
Props:
  placeholder: string
  onSelect: (lat: number, lon: number, label: string) => void

Verhalten:
  - Debounced Input (300 ms)
  - GET https://nominatim.openstreetmap.org/search?q=…&format=json&limit=5
  - Ergebnisse als Dropdown, Klick → onSelect(), Dropdown schließt
  - Bei leerem Input: kein Request
  - User-Agent-Header: 'MarschPlan/1.0'
```

Wird in allen 3 Wizard-Schritten sowie bei Wegpunkten in Schritt 3 verwendet.

## Bestehende Teile die sich nicht ändern

- `mapMode`-Store: unverändert
- `handleMapClick` in `+page.svelte`: unverändert — der Wizard nutzt denselben Handler
- Sidebar-Buttons (📍 Start, 🏁 Ziel, ➕ Wegpunkt): bleiben für spätere Bearbeitung erhalten
- Backend-API: keine Änderungen

## Abgrenzung

- Der Wizard ist nur bei der **initialen Erstellung** aktiv
- Für nachträgliche Änderungen bleiben die bestehenden Sidebar-Buttons zuständig
- Keine Änderungen am Routing, Export oder anderen Features
