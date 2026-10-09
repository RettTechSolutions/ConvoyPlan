# Leitstellengebiete zwischen Instanzen abgleichen

Stand: Überlegung, nicht umgesetzt. Bezug: Betriebsart (`INSTANCE_MODE`,
`services/betriebsart.py`).

## Das Problem

Eine frisch installierte, selbst gehostete Instanz hat **keine einzige Leitstelle**.
Der Kanalwechsel entlang der Route (`api/routes/routing.py`, Hinweise im
Marschbefehl) bleibt damit leer, bis jemand jedes Gebiet von Hand anlegt. Und das,
obwohl der Hosting-Server den gepflegten Bestand längst hat. Umgekehrt pflegen
Selbsthoster Gebiete, die auf dem Hosting-Server fehlen, und es gibt keinen Weg
zurück.

Innerhalb **einer** Instanz gibt es den Weg schon (`models/leitstelle.py`):
`local` → Vorschlag einreichen → `pending` → Superadmin prüft → `global` oder
`rejected`. Der Abgleich soll genau diesen Ablauf über die Instanzgrenze tragen,
statt einen zweiten zu erfinden.

## Vorab: Sind die Daten überhaupt teilbar?

Das muss vor allem anderen geklärt sein, denn es entscheidet über die Architektur.

- **Gebietsgrenzen** sind unkritisch: sie sind `district_codes` aus amtlichen
  Verwaltungsgrenzen (BKG dl-de/by-2-0, Statistik Austria CC BY 4.0, Eurostat), mit
  Namensnennung frei. Freie Polygone sind eigene Arbeit des Erstellers.
- **Anrufgruppen und Zusatzkanäle** sind es womöglich **nicht**. Rufgruppen-
  und Kanalpläne im BOS-Digitalfunk sind in vielen Ländern als *VS – Nur für den
  Dienstgebrauch* eingestuft oder werden mindestens so behandelt. Ein Katalog, den
  jede Installation anonym abrufen kann, wäre faktisch eine Veröffentlichung.
  Ob die Daten im Hosting-Bestand das betrifft, hängt davon ab, *was* dort steht
  (Klarnamen wie „ILS Oberland“ sind harmlos, TMO-Gruppennummern eher nicht).

**Empfehlung:** Geteilt wird zunächst nur, was ohne Zweifel öffentlich ist —
Name der Leitstelle und Gebiet. Anrufgruppe und Zusatzkanäle gehen nur an
Instanzen mit gültigem Lizenzschlüssel (die damit einem Vertrag unterliegen),
oder gar nicht, und werden lokal ergänzt. Das ist eine Entscheidung für den
Hersteller, nicht für den Code; ohne sie sollte nichts davon gebaut werden.

## Entwurf

### 1. Zentralen Stand holen (Hosting → Selbsthoster)

**Endpunkt auf dem Hosting-Server:** `GET /api/public/leitstellen/katalog`, nur bei
`INSTANCE_MODE=hosting`. Liefert alle `global`-Leitstellen mit stabiler Kennung,
`geändert_am`, Name, `district_codes` bzw. Geometrie und, je nach Entscheidung oben,
Funkangaben. Dazu Gelöschtes (`entfernt: [id, …]`) seit einem `?seit=`-Zeitstempel,
damit Löschungen ankommen. Ausgeliefert mit `ETag`, damit ein unveränderter Katalog
nichts kostet.

**Auf der selbst gehosteten Instanz:** neue Spalten an `leitstellen`:

| Spalte | Bedeutung |
|---|---|
| `zentral_id` | Kennung auf dem Hosting-Server; `NULL` = hier entstanden |
| `zentral_stand` | `geändert_am` des übernommenen Stands |
| `lokal_geaendert` | lokal überschrieben, wird vom Abgleich nicht mehr angefasst |

Übernommene Einträge stehen als `global` da (sichtbar für alle Organisationen der
Instanz, wie heute). Abgleich:

- **Wann:** einmal direkt nach der Ersteinrichtung (`routes/setup.py`), danach als
  Knopf im Adminportal („Zentralen Stand holen“) und optional täglich. Nicht nur
  automatisch: wer gerade ein Gebiet pflegt, soll nicht mitten hinein überschrieben
  werden.
- **Neu zentral** → anlegen. **Geändert zentral, lokal unberührt** → überschreiben.
  **Geändert zentral, lokal überschrieben** → nicht anfassen, im Portal als Konflikt
  zeigen („Zentral geändert am …, übernehmen?“). **Zentral entfernt** → lokal
  entfernen, außer `lokal_geaendert`.
- **Gebietskollision:** Ein übernommenes Gebiet überschneidet sich mit einer lokalen
  Leitstelle (`district_codes` gleich oder Polygone überlappend). Nicht still
  doppeln: der Kanalwechsel wüsste nicht, welche gilt. Die lokale gewinnt, die
  zentrale wird als Konflikt angezeigt.

Die Entscheidungen gehören in ein Modul ohne Netz und Datenbank
(`services/leitstellen_abgleich.py`, eine Funktion `plan(lokal, zentral) → Aktionen`),
geprüft wie `waypoint_order.py`. Netz und Datenbank sind dann nur noch Ausführung.

### 2. Gepflegte Gebiete einreichen (Selbsthoster → Hosting)

Der vorhandene Knopf „Vorschlag einreichen“ (`POST /api/org/leitstellen/{id}/submit`)
bekommt auf einer selbst gehosteten Instanz eine zweite Stufe. Der lokale
Superadmin gibt frei (`global`) und kann **zusätzlich** an den Hersteller
einreichen. Bewusst nicht automatisch und nicht in einem Schritt: Was eine
Organisation pflegt, ist ihre Arbeit, und ob sie geteilt wird, entscheidet sie.

**Endpunkt auf dem Hosting-Server:** `POST /api/leitstellen/eingang`, gebaut wie
`/api/feedback/eingang` (Betriebsart prüfen, Vertrag mit `extra="forbid"`,
wiederholbar über Instanz + Kennung, Limit je IP). Er legt eine Leitstelle mit
`status="pending"` an, und zwar mit neuen Feldern `herkunft_instanz`/`herkunft_url`
statt `proposed_by_org_id`. Die Prüfung im Adminportal ist dann dieselbe wie heute;
freigegeben ist sie beim nächsten Abgleich auf allen Instanzen, auch auf der
einreichenden (dort über `zentral_id` mit dem lokalen Eintrag verknüpft, nicht
gedoppelt).

Rückmeldung an den Einreicher: Beim Abgleich steht im Katalog nicht nur, was
freigegeben ist, sondern für die eigenen Einreichungen auch `abgelehnt` samt
`review_note`. Damit braucht der Hosting-Server keinen Rückkanal zur Instanz.
Die Instanz holt ab, wie beim Katalog.

Übertragen wird dasselbe wie beim Katalog. Gilt die Einschränkung bei den
Funkangaben, dann gilt sie in beide Richtungen.

### 3. Was es dafür nicht braucht

- Keine Konten auf dem Hosting-Server für Selbsthoster. Die Instanzkennung
  (`license.instance_id`) und, wo vorhanden, der Lizenzschlüssel reichen.
- Kein Echtzeitabgleich. Leitstellengebiete ändern sich im Jahresrhythmus.
- Keine Organisationen übertragen. Die Leitstelle hängt auf dem Hosting-Server
  an keiner Organisation, sondern an der Herkunft.

## Offene Fragen an den Hersteller

1. Funkangaben teilen: ja, nur mit Lizenz, oder nein (siehe oben)?
2. Soll eine kostenlose Installation einreichen dürfen? Technisch ja, die Prüfung
   ist ohnehin menschlich, aber das öffnet den Hosting-Server für Spam.
3. Wer haftet für einen zentralen Eintrag, der falsch ist und eine Kolonne auf die
   falsche Rufgruppe schickt? Mindestens gehört an jede übernommene Leitstelle ein
   sichtbares „zentral gepflegt, Stand …“ und an den Marschbefehl der Hinweis,
   die Angaben vor dem Einsatz zu prüfen.

## Reihenfolge

1. Entscheidung zu Frage 1.
2. Abgleich holen (Teil 1) mit Entscheidungsmodul und Tests: das ist der
   eigentliche Nutzen, denn eine leere Instanz ist das Problem.
3. Einreichen (Teil 2).
