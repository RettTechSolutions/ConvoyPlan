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
- **Versetzt, sobald ein Konvoi steht.** Hält er, erscheint er nicht am
  Rastplatz, sondern 10 bis 25 Kilometer davor oder dahinter auf seiner Route,
  und die Linie endet vorher. Das gilt schon auf den letzten Kilometern vor
  dem Halt und noch eine Strecke danach — sonst verriete die letzte genaue
  Position den Ort. Ohne berechnete Route zeigt die Seite die Mitte eines
  Rasters von etwa zehn Kilometern. Sonst stünde der Rastplatz trotz
  Verzögerung die ganze Nacht metergenau auf der Seite.
- **Nur freigegebene Felder.** Was nicht in der Tabelle oben links steht, geht
  nicht hinaus.

## Einrichten

**Org-Admin → Aktionsseiten → „+ Neue Aktionsseite"** (Rolle *Admin*):

1. Titel, optional Untertitel und eine Zeile Fakten („3 Konvois · 36 Lkw").
2. Verzögerung, Gestaltung (*Neutral* oder *Weihnachten*), optional „Sichtbar bis".
3. Konvois ankreuzen und **öffentlich benennen** — „Konvoi Bosnien" statt des
   internen Namens. Ziel und Farbe sind optional.
   **Zielpunkt auf der Karte:** Ohne Angabe gilt der letzte Wegpunkt des
   Konvois. Der ist oft nicht das Ziel — wer bis zur Fähre in Bari plant,
   fährt nach Albanien weiter. Dann den Zielort über die Ortssuche setzen; er
   zählt auch für „angekommen". Auf der Karte erscheint er nur mit dem Haken
   „Zielort als Punkt auf der Karte zeigen", und auch dann grob.
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

## Fotos von unterwegs (Telegram)

Fahrer und Begleiter posten Fotos mit ein paar Worten in eine Telegram-Gruppe.
Die Presse gibt sie dort frei; erst dann erscheinen sie auf der Aktionsseite —
**nach denselben Regeln wie der Konvoi selbst**:

- **Verzögert** wie die Positionen. Ein Foto von 14:00 Uhr erscheint bei zwei
  Stunden Verzögerung frühestens um 16:00 Uhr.
- **Dort, wo der Konvoi zu der Zeit war**, aus seinem Positionsverlauf — nie aus
  den GPS-Daten im Foto. Die werden beim Eingang entfernt, das Bild neu
  gespeichert.
- **Fotos von einem Halt** (Rastplatz, Autohof, Übernachtung) erscheinen erst,
  wenn der Konvoi auf der Seite wieder fährt, und dann an seinem versetzten
  Punkt. Ein Foto zeigt den Ort auch ohne Koordinate — Ortsschild, Rastplatz,
  Kirchturm. Am Ziel kommen die Übergabefotos, sobald er angekommen ist.
- **Nichts über die Absender.** Auf der Seite steht der Konvoi und die Uhrzeit,
  nicht wer das Foto geschickt hat. Hinaus geht nur der Text, den die Presse
  freigegeben hat.

### Einrichten

**Org-Admin → Aktionsseiten** (Rolle *Admin*):

1. **Bot anlegen** bei [@BotFather](https://t.me/BotFather) mit `/newbot` und
   den Token oben in der Karte *Telegram-Bot* eintragen. Er wird verschlüsselt
   gespeichert und nie wieder angezeigt. ConvoyPlan legt dabei die Befehle im
   Bot ab: Wer `/` tippt, bekommt im Privatchat `/presse` und in der Gruppe
   `/verbinden` und `/ab` angeboten — bei @BotFather ist dafür nichts zu tun.
2. **Privacy Mode abschalten:** bei @BotFather `/setprivacy` → den Bot wählen →
   *Disable*. Sonst sieht der Bot in Gruppen keine Fotos; die Karte zeigt das
   gelb an. Alternativ den Bot in jeder Gruppe zum Admin machen.
3. **Bot in die Gruppe holen** — eine Gruppe je Konvoi oder eine Gruppe mit
   *Themen*, ein Thema je Konvoi (empfohlen ab drei Konvois).
4. **Verbinden:** In der Aktionsseite unter *Fotos von unterwegs* beim Konvoi
   *Code erzeugen* und `/verbinden CODE` in die Gruppe bzw. das Thema schreiben
   (15 Minuten gültig). Der Bot bestätigt in der Gruppe, was mit den Fotos
   geschieht.
5. **Presse eintragen:** *Presse-Code erzeugen* und an die Pressestelle geben.
   Jede Person schickt dem Bot **privat** `/presse CODE` (24 Stunden gültig,
   für mehrere Personen).

### Im Betrieb

- Auf jeden Beitrag antwortet der Bot mit **einer** Karte und Knöpfen:
  *Freigeben*, *Text ändern*, *Ablehnen*, nach der Freigabe *Zurückziehen*.
  Drücken darf nur, wer als Presse eingetragen ist. Die Karte zeigt, wann der
  Beitrag frühestens erscheint, und später „Öffentlich seit …".
- **Später zeigen:** `/ab 18:00` als Antwort auf die Karte (oder das Foto)
  hält einen Beitrag bis dahin zurück, etwa bis zur Pressekonferenz. `18:00`
  ist das nächste 18:00, `/ab 27.12. 18:00` ein bestimmter Tag, `/ab -` nimmt
  den Termin weg; höchstens sieben Tage voraus. Früher als die Verzögerung geht
  nie — eine frühere Zeit beantwortet der Bot mit der, die ohnehin gilt. Im
  Org-Admin heißt es *Erst ab …*.
- **Alben** sind ein Beitrag. **Weitergeleitete** Fotos nimmt der Bot nicht an.
- **Links zu Instagram, YouTube, Facebook oder TikTok** werden ebenfalls ein
  Beitrag, mit derselben Freigabe. Als **Antwort auf ein Foto** (oder auf die
  Karte des Bots) gehört der Link zu dessen Zeit und Ort, sonst zur Zeit der
  Nachricht. Auf der Seite erscheint ein Polaroid mit dem Symbol des Dienstes;
  den Link öffnet erst ein Klick — eingebettet wird nichts, die Seite lädt
  weiter nichts von außen. Tracking-Anhänge wie `?igsh=…` oder `?si=…` entfernt
  der Bot, die Karte zeigt die Adresse, wie sie hinausgeht. Andere Adressen
  nimmt er nicht als Link-Beitrag an.
- Ändert jemand nach der Freigabe seinen Text in Telegram, bleibt öffentlich
  der freigegebene; die Karte weist darauf hin.
- **Zurückziehen** über den Knopf, nicht durch Löschen in Telegram — das
  bekommt der Bot nicht mit.
- Ist die Aktionsseite nicht aktiv (abgelaufen, abgeschaltet) oder die
  Tagesgrenze erreicht (300 Fotos bzw. 100 Links in 24 Stunden je Gruppe),
  **sagt der Bot es in der Gruppe** — einmal, nicht auf jedes Foto. Was er dann
  nicht annimmt, wird nicht gespeichert.
- Bremst Telegram den Bot (viele Fotos in kurzer Zeit), kommen seine Karten
  etwas später, aber sie kommen.
- Im Org-Admin stehen alle Beiträge mit Zähler („3 warten …") und denselben
  Aktionen — für den Fall, dass in Telegram gerade niemand erreichbar ist.
- **Gruppe trennen** nimmt keine neuen Fotos mehr an; vorhandene Beiträge
  bleiben. Fotos werden nach 45 Tagen gelöscht, abgelehnte und
  zurückgezogene nach 7, nie bearbeitete nach 30 Tagen.

Auf Fotos sind Menschen. Wer freigibt, entscheidet auch, ob die Abgebildeten
einverstanden sein dürften — Grenzbeamte, Empfänger, Kinder bei der Übergabe.


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
