# Öffentliche Aktionsseite

Konvois öffentlich zeigen — zum Teilen, für die Presse, auf einem Bildschirm
bei einer Veranstaltung. Gedacht für Hilfskonvois, bei denen viele Menschen
mitfiebern, aber niemand wissen soll, wo die beladenen Lkw gerade stehen.

## Was die Öffentlichkeit sieht — und was nicht

| Sichtbar | Nicht sichtbar |
|---|---|
| ein Punkt je Konvoi, die gefahrene Strecke | einzelne Fahrzeuge, Rufnamen, Kennzeichen |
| Status: noch nicht los, unterwegs, Pause, angekommen | Stärke, Betriebsstoff, Alarme, Telefonnummern |
| gefahrene und verbleibende Kilometer | der interne Konvoiname |
| Ziel als Text, auf Wunsch als grober Punkt | die geplante Route und die Wegpunkte |

Dazu drei Regeln, die der Server durchsetzt — nicht die Seite im Browser:

- **Verzögert.** Alles ist mindestens eine Stunde alt (einstellbar bis sechs
  Stunden, empfohlen zwei). Die Seite sagt das offen dazu.
- **Vergröbert, sobald ein Konvoi steht.** Steht er länger als 20 Minuten,
  zeigt die Seite nur noch eine Fläche von etwa zehn Kilometern, und die Linie
  endet davor. Sonst stünde der Rastplatz trotz Verzögerung die ganze Nacht
  metergenau auf der Seite.
- **Nur freigegebene Felder.** Was nicht in der Tabelle oben links steht, geht
  nicht hinaus.

## Einrichten

**Org-Admin → Aktionsseiten → „+ Neue Aktionsseite"** (Rolle *Admin*):

1. Titel, optional Untertitel und eine Zeile Fakten („3 Konvois · 36 Lkw").
2. Verzögerung, Gestaltung (*Neutral* oder *Weihnachten*), optional „Sichtbar bis".
3. Konvois ankreuzen und **öffentlich benennen** — „Konvoi Bosnien" statt des
   internen Namens. Ziel und Farbe sind optional.
4. Anlegen. Danach steht das **Abruf-Token genau einmal** da, zusammen mit dem
   fertigen Eintrag für den EventTracker. Übernehmen, bevor die Seite verlassen
   wird — gespeichert ist nur ein Hash. Der Eintrag enthält auch die Adresse
   dieser Instanz (`"convoyplan":"https://<instanz>"`); der EventTracker nimmt
   sie von dort, sie muss nicht getrennt eingetragen werden.

Ausgeliefert wird die öffentliche Seite **nicht** von ConvoyPlan, sondern vom
[Convoyplan-EventTracker](https://github.com/RettTechSolutions/Convoyplan-EventTracker).
Der holt den Stand einmal pro Minute mit dem Token ab — egal, wie viele Leute
zuschauen, ConvoyPlan merkt davon nichts. Einrichtung dort in der README. Die Abruf-Adresse beginnt immer mit `https://`;
wurde früher eine mit `http://` im EventTracker eingetragen, auf `https://`
umstellen — sonst bleibt die öffentliche Seite leer.

## Im Betrieb

- **Vorschau** zeigt genau das, was gerade hinausgeht, mit derselben Verzögerung.
- **Token erneuern** macht das alte sofort ungültig; der EventTracker zeigt die
  Seite erst wieder, wenn dort das neue eingetragen ist.
- **Ausschalten** oder **„Sichtbar bis" überschritten**: Die öffentliche Seite
  sagt „beendet" und zeigt nichts mehr.
- **Löschen** entfernt Seite und Zuordnung. Der Positionsverlauf geht nach
  45 Tagen von selbst (`RETENTION_POSITION_TRAIL_DAYS`).

## Datenschutz

Positionen werden für die Aktionsseite nur aufgezeichnet, solange ein Konvoi an
einer eingeschalteten, nicht abgelaufenen Seite hängt — ein Bewegungsprofil
jedes Einsatzes entsteht nicht. Die Fahrerinnen und Fahrer sollten vorher
wissen, dass die Position ihres Konvois verzögert und vergröbert öffentlich
gezeigt wird.

## Was die Seite zuverlässig macht

Die Seite ist nur so gut wie die Positionen, die ankommen:

- Im Spitzenfahrzeug die **Begleit-App** mit Dauerstrom. Der Fahrer-Link im
  Browser sendet nur bei eingeschaltetem Bildschirm.
- Außerhalb der EU (z. B. Albanien, Bosnien und Herzegowina, Serbien) kostet
  mobiles Internet je nach Vertrag extra — vorher klären.
- Fällt das Spitzenfahrzeug aus, nimmt die Seite das Fahrzeug mit der
  frischesten Position.
