# Fehler melden und Funktionen vorschlagen

ConvoyPlan hat einen Melde-Knopf direkt in der Anwendung. Wer im Einsatz auf
etwas stößt, das nicht stimmt, soll es dort aufschreiben können, wo es passiert
— und nicht später aus dem Gedächtnis in einer E-Mail.

---

## Für Anwender: eine Meldung abschicken

**Wo der Knopf sitzt**

| Ort | Knopf |
|---|---|
| Planungsansicht | unten links in der Seitenleiste, neben *Hilfe* — **🐞 Melden** |
| Org-Admin | oben rechts neben *← Plan* — **🐞 Melden** |

**Was der Dialog fragt**

- **Art** — *Fehler* (etwas funktioniert nicht) oder *Wunsch* (etwas fehlt).
- **Überschrift** — ein Satz, an dem man die Meldung später wiedererkennt.
- **Beschreibung** — bei einem Fehler: was Sie getan haben, was passiert ist und
  was passieren sollte. Zeilenumbrüche bleiben erhalten, eine nummerierte
  Schrittfolge ist also ausdrücklich erwünscht.
- **Schweregrad** — *niedrig* bis *kritisch*. Das ist **Ihre** Einschätzung; sie
  bleibt erhalten, auch wenn der Betreiber die Sache anders priorisiert.
- **Bildschirmfoto** — freiwillig, hilft am meisten.

**Drei Wege zum Bildschirmfoto**

1. **📸 Bildschirm aufnehmen** — der Browser fragt, was geteilt werden soll
   (Tab, Fenster oder Bildschirm). Der Melde-Dialog blendet sich dafür kurz aus,
   damit das Bild die Anwendung zeigt und nicht den Dialog. Auf dem Telefon gibt
   es diesen Weg nicht — dort die beiden anderen nehmen.
2. **Einfügen** — Bildschirmfoto wie gewohnt machen (Windows: `Druck` oder
   `Win`+`Umschalt`+`S`) und im Dialog **Strg+V** drücken.
3. **📎 Datei wählen** — PNG, JPEG oder WebP.

Große Bilder werden vor dem Abschicken automatisch auf 1920 Pixel Kantenlänge
verkleinert. Ein angehängtes Bild lässt sich vor dem Abschicken wieder
**entfernen**.

**Was mitgeschickt wird**

Unter *Was mitgeschickt wird* steht es ausklappbar und mit den tatsächlichen
Werten:

| Feld | Inhalt |
|---|---|
| `page_url` | die Adresse der Seite, auf der Sie gerade sind |
| `user_agent` | die Kennung Ihres Browsers |
| `app_version` | die Fassung von ConvoyPlan |
| `viewport` | die Größe des Browserfensters |
| Konto | Name, E-Mail-Adresse und Organisation Ihrer Anmeldung |

Mehr nicht. **Sichtbar ist das alles nur für den Betreiber dieser Instanz** —
nicht für andere Organisationen und nicht öffentlich.

> **Ein Bildschirmfoto aus dem Einsatz zeigt Einsatzdaten.** Prüfen Sie vor dem
> Abschicken kurz, was darauf zu sehen ist — genauso, wie Sie es vor dem
> Weitergeben an eine andere Stelle tun würden.

Melden kann jedes angemeldete Mitglied, **auch aus einer Demo-Sitzung**.
Höchstens zehn Meldungen je Stunde.

---

## Für Betreiber: Meldungen sichten

Im Adminportal unter **Meldungen**. Am Reiter steht die Zahl der offenen
Meldungen, sobald das Portal geladen ist — man muss nicht erst hineinsehen, um
zu merken, dass etwas darin liegt.

**Die Kachelzeile**

| Kachel | Bedeutung |
|---|---|
| Offen | alles, was nicht *erledigt*, *abgelehnt* oder *Duplikat* ist |
| Fehler offen / Wünsche offen | dasselbe, getrennt nach Art |
| Kritisch offen | Priorität *kritisch* und noch offen |
| Neu (7 Tage) | eingegangen in der letzten Woche, unabhängig vom Status |

Die Kacheln zählen immer über den **ganzen** Bestand, auch wenn die Liste
darunter gefiltert ist. Sonst sagte „3 offen" nur noch etwas über den Filter aus.

**Die Liste** lässt sich nach Art und Status filtern; voreingestellt ist *nur
offene*. Ein Klick auf eine Zeile öffnet rechts die Meldung mit Beschreibung,
Bildschirmfoto (Klick öffnet es in voller Größe), Umgebung und Melder.

**Status** — `neu` → `gesichtet` → `geplant` → `in_arbeit` → `erledigt`, daneben
`abgelehnt` und `duplikat`. **Priorität** startet auf dem Schweregrad des
Melders und lässt sich davon unabhängig setzen; was der Melder angegeben hat,
steht weiterhin daneben (*„Gemeldet als …"*).

**Interne Notiz** — für Einordnung, Ticketnummer, Rückfrage. Der Melder sieht
sie nicht.

Titel, Beschreibung und Schweregrad lassen sich **nicht** ändern. Eine Meldung
ist die Aussage des Melders; wer sie umschreiben kann, kann sie auch
entschärfen.

**Löschen** entfernt Zeile und Bildschirmfoto endgültig. Jede Meldung, jeder
Statuswechsel und jede Löschung steht im Audit-Log
(`feedback.submitted`, `admin.feedback.updated`, `admin.feedback.deleted`).

---

## Betrieb

- **Ablage der Bilder:** `/uploads/feedback/` im Volume `logo_uploads`. Nicht
  statisch ausgeliefert — der Zugriff läuft über
  `GET /api/admin/feedback/{id}/screenshot` und verlangt eine
  Superadmin-Sitzung. Höchstens 4 MB je Bild, nur PNG, JPEG und WebP (erkannt
  am Inhalt, nicht am angegebenen Typ; SVG ist ausgeschlossen).
- **Sicherung:** die Bilder liegen im Volume, die Meldungen in der Datenbank.
  Wird nur die Datenbank zurückgespielt, steht die Meldung ohne Bild da — das
  Portal sagt das dann und liefert keinen Serverfehler.
- **Gelöschte Organisationen und Konten** nehmen ihre Meldungen nicht mit: die
  Verweise stehen auf `SET NULL`, Name, Kürzel und Adresse daneben als
  Textkopie. Ein Fehler ist nicht behoben, nur weil die Demo-Umgebung abgelaufen
  ist, in der er auftrat.
- **Ohne gültige Lizenz** bleibt das *Melden* erreichbar; das *Sichten* ist
  gewöhnliche Adminarbeit und bleibt lizenzpflichtig.

## Verwandte Seiten

- [Sicherheit und Datenschutz](Sicherheit-und-Datenschutz)
- [Systemübersicht](Systemuebersicht)
- [Rollen & Berechtigungen](Rollen)
