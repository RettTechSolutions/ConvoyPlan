# Marschbefehl & Export

## Marschbefehl (PDF)

Der Marschbefehl ist das Führungsdokument für den Konvoi. ConvoyPlan setzt ihn nach dem **Muster für einen Marschbefehl der FwDV 100, Anlage 4** — oder als Word-Dokument aus der eigenen Vorlage der Organisation (siehe [unten](#marschbefehl-als-word-dokument-eigene-vorlage)).

Die FwDV sagt dazu: *„Es ist nicht immer zu jedem Punkt etwas anzuordnen. Die Reihenfolge der Hauptziffern ist aber immer einzuhalten.“* Deshalb steht im PDF jeder Punkt in dieser Reihenfolge; was nicht angeordnet ist, steht mit „-“ da.

### Gliederung und woher die Angaben kommen

Öffne den Konvoi, Tab **Export** → **Marschbefehl ausfüllen**. Was ConvoyPlan aus Route, Fahrzeugen und Wegpunkten kennt, muss nicht eingetragen werden.

| FwDV-Punkt | Im Formular | Sonst |
|---|---|---|
| **Kopf:** Befehlende Stelle | – | Organisation des Konvois |
| Abgangsort | **Abgangsort** | |
| Abgangsdatum, Abgangszeit | – | Zeitpunkt des Exports |
| Befehl für den Marsch in den Raum … | **Marsch in den Raum** | Marschziel |
| Karte | **Karte** | |
| **1. Lage:** Gefahren- / Schadenlage | **Gefahren- / Schadenlage** (Pflicht) | |
| Eigene Lage | **Eigene Lage** | |
| **2. Auftrag:** Zuteilung, Unterstellung und Abgabe von Kräften | **Zuteilung, Unterstellung …** | |
| Erhaltener Auftrag | **Erhaltener Auftrag** (Pflicht) | |
| **3. Durchführung:** Marschziel, Marschweg, Marschentfernung | – | letzter Wegpunkt, „von A über B nach C“, Länge der Route |
| Marschform | **Marschform** | |
| Marschfolge | – | Fahrzeuge in Reihenfolge, mit Funkrufname, Kennzeichen, Mobiltelefon, Sonderfunktion |
| Marschführer/in | **Marschführer/in** | |
| Führer/innen der Einzelgruppen | **Führer/innen der Einzelgruppen** | |
| Schließende/r | – | Fahrzeug mit Sonderfunktion „Schließender“, sonst das letzte |
| Marschabstand | **Marschabstand** | |
| Fahrzeugabstand | (Konvoi-Einstellungen) | innerorts, außerorts, Autobahn |
| Ablaufpunkt, Ablaufzeit, Ablaufführer/in | **Ablaufpunkt** (Pflicht), **Ablaufzeit** (Pflicht), **Ablaufführer** | |
| Marschgeschwindigkeit | (Konvoi-Einstellungen) | Ø aus Marschentfernung und Fahrzeit ohne Halte (*theoretische Durchschnittsgeschwindigkeit*), dazu die Höchstwerte innerorts/außerorts |
| Beleuchtung | **Beleuchtung** | Abblendlicht auch am Tag; Katastrophenschutz: blaues Blinklicht ohne Einsatzhorn |
| Marschüberwachung und Verkehrssicherung | **Marschüberwachung …** | |
| Marschpausen a) Technische Halte, b) Raste | – | Halte der Route: Technische Halte sowie Tank- und Wartungshalte unter a), alle übrigen Halte unter b) |
| Besondere Einzelheiten je nach Lage | **Besondere Einzelheiten** | dazu Beflaggung, Durchlaufpunkte, Fahrzeuge im Verband (Höhe, Gewicht), Durchfahrtshöhen und Gewichtsgrenzen (siehe [Konvoi planen](Konvoi-Planung#durchfahrtshöhen)) |
| **4. Versorgung:** Verpflegung | **Verpflegung** | |
| Betriebsstoff | **Betriebsstoff** | „Alle Fahrzeuge haben sich grundsätzlich vollgetankt am Ablaufpunkt einzufinden.“ |
| Instandsetzungsdienst | **Instandsetzungsdienst** | |
| Ärztliche Versorgung | **Ärztliche Versorgung** | Fahrzeuge mit Sonderfunktion „Sanitätsdienst“ |
| **5. Führung und Verbindung:** Kommunikationsverbindungen während des Marsches | **Funkgruppe** | dazu die Kanalwechsel an Leitstellengrenzen |
| Sonstige Verbindungen, Lotsenstellen und Verkehrsleitpunkte | **Sonstige Verbindungen …** | |
| Platz der Führungskraft | **Platz der Führungskraft** | Fahrzeug mit Sonderfunktion „Führungsfahrzeug“ |
| **Anlagen** (ohne Ziffer) | **Anlagen** | |
| **Verteiler** | **Verteiler** | |
| **Unterschrift** (Name, Dienststellung) | **Name**, **Dienststellung** | Linie zum Unterschreiben |

Ein Text, der vor dieser Gliederung unter **Versorgung** eingetragen wurde, bleibt erhalten und steht unter 4. als „Ergänzend“.

### Marschform-Optionen

| Option | Bedeutung |
|--------|-----------|
| **Geschlossener Gesamtverband** | Alle Fahrzeuge fahren gemeinsam als Einheit |
| **Einzelgruppen** | Fahrzeuggruppen mit Marschabstand |
| **Individuelle Anreise** | Fahrzeuge fahren unabhängig voneinander |

### PDF generieren

Im Formular **Speichern & PDF**, oder im Tab **Export** → Marschbefehl als PDF. Eine Karte enthält der Marschbefehl nicht; die steht im [Roadbook](#roadbook-pdf), das sich als Anlage eignet.

---

## Marschbefehl als Word-Dokument (eigene Vorlage)

Viele Organisationen haben ihr eigenes Marschbefehl-Formular: Wappen im Kopf, eigene Gliederung, feste Textbausteine. Dafür gibt es neben dem PDF den Export **📝 Speichern & Word** im Marschbefehl-Dialog. Er füllt eine Word-Vorlage (`.docx`) mit den Daten des Konvois.

### Vorlage einrichten (Org-Admin)

1. **Org-Admin → Marschbefehl → Beispielvorlage herunterladen.** Die Datei hat die Gliederung des PDF-Marschbefehls, mit Platzhaltern statt Werten, und am Ende eine **Feldübersicht** aller Platzhalter. Die Übersicht wird beim Export nicht mitgedruckt.
2. In Word anpassen: Kopf, Logo, Schriften, Reihenfolge, eigene Texte. Platzhalter verschieben, löschen oder neu einsetzen.
3. **Vorlage hochladen.** ConvoyPlan prüft die Datei sofort und meldet Fehler mit dem Namen des Feldes (z. B. „Unbekanntes Feld ‚nmae‘"). Eine fehlerhafte Vorlage wird nicht gespeichert, und die bisherige gilt weiter.

Solange keine eigene Vorlage hochgeladen ist, exportiert ConvoyPlan aus der Beispielvorlage. **Eigene Vorlage entfernen** kehrt dorthin zurück. Hochladen und Entfernen stehen im Protokoll der Organisation.

### Platzhalter

| Was | Schreibweise | Beispiel |
|---|---|---|
| Ein Feld | doppelte geschweifte Klammern | `{{ konvoi.name }}`, `{{ konvoi.funkgruppe }}` |
| Ersatz, wenn leer | `or` | `{{ konvoi.funkgruppe or '-' }}` |
| Abschnitt nur, wenn gefüllt | eigener Absatz davor und danach | `{%p if konvoi.lage %}` … `{%p endif %}` |
| Eine Tabellenzeile je Eintrag | eigene Tabellenzeile darüber und darunter | `{%tr for f in fahrzeuge %}` … `{%tr endfor %}` |

Die Steuerzeilen mit `{%p …%}` und `{%tr …%}` fallen beim Export samt Absatz bzw. Tabellenzeile weg. Die Beispielvorlage zeigt sie grau und klein; am einfachsten kopiert man sie von dort.

Die Gruppen der Felder:

- **`konvoi`**: Name, befehlende Stelle, Datum/Uhrzeit, Lage, Auftrag, Marschziel, Marschweg, Marschstrecke, Marschform, Ablaufpunkt/-zeit/-führer, Geschwindigkeiten, Abstände, Versorgung, Funkgruppe, Anlagen, Zahl der Fahrzeuge, höchstes und schwerstes Fahrzeug; dazu alle Punkte der FwDV 100, Anlage 4 (Abgangsort, -datum, -zeit, Raum, Karte, Eigene Lage, Kräfte, Marschentfernung, Marschführer/in, Führer/innen der Einzelgruppen, Schließende/r, Marschabstand, Durchschnittsgeschwindigkeit, Beleuchtung, Marschüberwachung, Besondere Einzelheiten, Verpflegung, Betriebsstoff, Instandsetzungsdienst, Ärztliche Versorgung, Sonstige Verbindungen, Platz der Führungskraft, Verteiler, Unterschrift Name und Dienststellung). `marschstrecke` und `marschentfernung` sind derselbe Wert; ältere Vorlagen funktionieren weiter.
- **`organisation`**, **`erstellt`**: Name der Organisation, Datum und Uhrzeit des Exports
- **Listen** (für Tabellen): `fahrzeuge`, `wegpunkte`, `durchlaufpunkte`, `marschpausen`, `technische_halte`, `raste`, `kanalwechsel`, `durchfahrtshoehen`, `gewichtsgrenzen`

Die vollständige Liste mit allen Unterfeldern steht in der Feldübersicht der Beispielvorlage und im Org-Admin unter **Verfügbare Platzhalter**.

**Gut zu wissen:**

- Werte kommen fertig formatiert („412,3 km", „07.11.2026", „18.000 kg"). Ein fehlender Wert ist leer, nicht „-".
- Die Formatierung des Platzhalters (Schrift, Größe, fett) gilt für den eingesetzten Wert.
- Word ersetzt gerade Anführungszeichen beim Tippen durch typografische („ "). In Platzhaltern müssen sie gerade bleiben; direkt nach dem Tippen hilft Strg+Z.
- Ausgegeben wird ein **Word-Dokument**, kein PDF. So lässt es sich vor dem Druck noch von Hand ergänzen. Als PDF speichert es Word selbst.
- Nur `.docx`. Dokumentvorlagen (`.dotx`) und Dateien mit Makros (`.docm`) werden abgewiesen, ebenso Dateien über 5 MB.
- Platzhalter sind bewusst eingeschränkt: Rechnen mit großen Zahlen, Zählschleifen oder Formatierer mit Breitenangabe lehnt die Prüfung ab. Was eine Vorlage braucht (Felder, Bedingungen, Tabellenzeilen, `upper`, `join`, `length` …), geht.

---

## Roadbook (PDF)

Das Roadbook ist die Route zum Ausdrucken: oben eine Übersichtskarte mit Start (**S**), Ziel (**Z**) und den nummerierten Wegpunkten, darunter **jede Navigationsanweisung** der Route — für Beifahrer, Kradmelder oder als Rückfallebene, wenn das Navi ausfällt.

1. Route berechnen (Tab **Plan** → **Route berechnen**)
2. Tab **Export** → **🧭 Roadbook (PDF)**

Jede Zeile der Tabelle enthält:

| Spalte | Inhalt |
|---|---|
| **Nr.** | laufende Nummer der Anweisung |
| Symbol | Richtungspfeil (↑ geradeaus, → rechts, ↺ Kreisverkehr, ◉ Wegpunkt, ⚑ Ziel …) |
| **Anweisung** | Abbiegehinweis mit Straßenname und -nummer (z. B. „Rechts abbiegen auf Pragstraße (B 10)"), bei Autobahnen die Zielangabe („Richtung München") |
| **bei km** | Kilometrierung ab Start, an der das Manöver kommt |
| **dann** | Strecke bis zur nächsten Anweisung |

Wegpunkte sind farbig hervorgehoben und tragen dieselbe Nummer wie auf der Karte, dazu Typ, geplante Ankunft/Abfahrt, Haltedauer mit Zweck und die Notiz. Die Ziel-Zeile nennt die geplante Ankunft.

Zwischen den Anweisungen stehen an ihrem Kilometer Hinweise ohne Nummer:

| Symbol | Hinweis |
|---|---|
| ↕ | **Durchfahrtshöhe** mit Spielraum zum höchsten Fahrzeug — auch die freien, damit klar ist, wo es gut passt |
| ⚖ | **Gewichtsgrenze** mit Reserve zum schwersten Fahrzeug und Ausnahme („Anlieger frei"), **Achslastgrenze** mit Reserve zur größten Achslast |
| ⚠ | **Brücke ohne Höhenangabe** über der Route (nicht auf Autobahn und Kraftfahrstraße) |

Rot hinterlegt sind Stellen, an denen es eng wird (unter 10 cm Spielraum) oder die Route über eine Gewichtsgrenze führt.

**Gut zu wissen:**

- Die Anweisungen entstehen bei der **Routenberechnung** und werden mit der Route gespeichert. Eine Route, die vor diesem Update berechnet wurde, hat noch keine — das Roadbook sagt das und bittet um eine Neuberechnung.
- Eine **importierte** Route (GPX/GeoJSON) hat keine Anweisungen; das Roadbook zeigt dann nur die Karte.
- Zeiten stammen aus dem Zeitplan des Konvois (Marschgeschwindigkeiten), nicht aus der Pkw-Fahrzeit des Routers.
- Den Kartenhintergrund lädt der Server von OpenStreetMap. Ist der Kachelserver nicht erreichbar, enthält die Karte nur die Route auf neutralem Grund. Andere Kachelquelle oder offline: `ROADBOOK_TILE_URL` (leer = ohne Hintergrund).
- Vor Ort gilt die Beschilderung — die Anweisungen beruhen auf OpenStreetMap-Daten.

---

## GPX-Export

Der GPX-Export enthält:
- **Wegpunkte** (Start, Ziel, alle Zwischenpunkte mit Namen und Zeiten)
- **Routengeometrie** (Fahrtweg als Track)

Verwendungszweck: Navigation auf Garmin-Geräten, Smartphone-Apps (OsmAnd, Maps.me) oder Übergabe an andere Einsatzkräfte.

1. Klicke auf **Exportieren** → **GPX herunterladen**
2. Die Datei kann direkt in Navigationsgeräte oder Apps importiert werden

---

## JSON-Export

Der vollständige JSON-Export enthält alle Konvoidaten:
- Fahrzeugliste, Marschbefehls-Felder, Wegpunkte, Geschwindigkeiten, Zeitplan
- Geeignet für Archivierung oder Import in andere Systeme

---

## Import-Funktionen

### GPX importieren

1. Klicke auf **Importieren** → **GPX-Datei auswählen**
2. Wähle, ob die importierten Punkte bestehende Wegpunkte **ersetzen** oder **ergänzen** sollen
3. GPX-Tracks werden in Wegpunkte umgewandelt und in die Routenplanung übernommen

### GeoJSON importieren

Externe Routengeometrien (z. B. aus GIS-Systemen) können als GeoJSON importiert werden. Die Geometrie wird auf der Karte dargestellt und kann als Routenbasis genutzt werden.

---

## Nächste Schritte

- [Konvoi teilen →](Teilen)
- [Rollen & Berechtigungen →](Rollen)
