# Teilen & Öffentliche Ansicht

Ein **Tracking-Link** gibt einen Konvoi ohne Login frei. Er hat zwei Ausprägungen:

| Rolle | Slug-Rolle | Der Empfänger darf … |
|---|---|---|
| **Nur ansehen** (Viewer) | `track` | den Verband live verfolgen: Karte, Fahrzeugpositionen, Zeitplan |
| **Fahrer** | `driver` | zusätzlich **ein Fahrzeug wählen und dessen Position und Status senden** – ohne Benutzerkonto |

Der Fahrer-Link ist dafür gedacht, Kräfte einzubinden, die kein Konto in der
Organisation haben: Fahrer aus fremden Einheiten, kurzfristig gestellte
Fahrzeuge, Kräfte anderer Organisationen im gemeinsamen Marschverband.

---

## Link erstellen

1. Konvoi öffnen → **Teilen** (Dialog **Live-Tracking teilen**)
2. Unter **Neuen Tracking-Link erstellen** die Rolle wählen:
   - **Nur ansehen** – Empfänger sehen den Verband live (Viewer)
   - **Fahrer** – Empfänger können ohne Login ein Fahrzeug wählen und Position/Status senden
3. Passwortschutz wählen (siehe unten)
4. **Link erstellen**

Der fertige Link hat die Form `https://<deine-instanz>/track/<slug>`. Der Slug
ist eine zufällige 8-stellige Zeichenfolge aus Buchstaben und Ziffern.

> **Ein Fahrer-Link ist ein Schreibzugriff.** Jeder, der ihn hat, kann für ein
> beliebiges Fahrzeug des Konvois Position und Status senden. Der Dialog weist
> beim Anlegen ausdrücklich darauf hin und **empfiehlt für Fahrer-Links ein
> Passwort**. Ein falsch gesendeter Status („Ausfall") löst bei allen
> Beteiligten einen Alarm aus.

---

## Passwortschutz

Beim Anlegen stehen drei Möglichkeiten zur Wahl:

| Option | Wirkung |
|---|---|
| **Ohne Passwort (offen erreichbar)** | Wer den Link hat, kommt hinein |
| **Passwort generieren** | Die Instanz erzeugt ein zufälliges 10-stelliges Passwort |
| **Passwort selbst setzen** | Eigenes Passwort, mindestens 4 Zeichen |

Das generierte Passwort wird **nur unmittelbar nach dem Anlegen angezeigt** und
ist danach nicht mehr auslesbar – es wird serverseitig nur als bcrypt-Hash
gespeichert. Wer es verliert, legt einen neuen Link an.

Beim Öffnen eines geschützten Links erscheint eine Passwortmaske. Sie nennt den
Konvoi und die Rolle des Links – bei einem Fahrer-Link ausdrücklich
**„Fahrer-Anmeldung"**, damit niemand versehentlich als Fahrer beitritt, der
nur zusehen wollte. Nach der Eingabe gilt die Sitzung **24 Stunden**; danach
wird das Passwort erneut abgefragt.

> Die Rolle wird **serverseitig** durchgesetzt. Dass die Anmeldemaske sie schon
> vor der Passworteingabe nennt, ist reine Beschriftung und keine
> Rechteauskunft.

---

## Vorhandene Links verwalten

Der Teilen-Dialog listet alle Links des Konvois mit:

| Spalte | Bedeutung |
|---|---|
| **Slug** | Der Teil hinter `/track/` |
| **Rolle** | 👁 Viewer oder 🚗 Fahrer |
| **Passwort** | 🔒 = passwortgeschützt, — = offen |
| **Erstellt** / **Letzter Zugriff** / **Aufrufe** | Wann angelegt, wann zuletzt benutzt, wie oft |
| **Status** | *aktiv* oder *widerrufen* |

**Widerrufen** macht einen Link sofort ungültig. Er bleibt zur Nachvollziehbarkeit
in der Liste stehen und wird nach **30 Tagen** vom Retention-Container endgültig
gelöscht (`RETENTION_SHARE_LINKS_DAYS`). Erstellen und Widerrufen werden im
[Audit-Log](Sicherheit-und-Datenschutz) protokolliert.

Es können mehrere Links parallel bestehen – üblich ist ein passwortgeschützter
Fahrer-Link für die Besatzungen und ein Viewer-Link für die Leitung.

---

## Inhalte der öffentlichen Ansicht

| Inhalt | Beschreibung |
|--------|-------------|
| **Routenkarte** | Geplante Route mit allen Wegpunkten |
| **Konvoi-Info** | Name, Organisation, Startzeit |
| **Fahrzeuge** | Liste mit Funkrufname, Sonderfunktion und aktuellem Status |
| **Zeitplan** | Geplante Ankunfts- und Abfahrtszeiten je Wegpunkt (nur wenn geplant) |
| **Live-Positionen** | Aktuelle Fahrzeugpositionen, sobald übermittelt |

> **Nicht** enthalten: Fahrzeugdetails wie Kennzeichen, Abmessungen und
> Kraftstoffdaten, interne Notizen und der Marschbefehl-Volltext.

Bei einem **Fahrer-Link** kommt oben der Block **„Meine Position (Fahrer)"**
hinzu: Fahrzeugauswahl, GPS-Übertragung und Statusmeldung inklusive technischem
Halt und Ausfall – siehe [Live-Tracking](Live-Tracking). Ohne HTTPS steht kein
GPS zur Verfügung; die Position lässt sich dann per Tippen auf die Karte setzen.

Die Ansicht lässt sich als PWA auf den Homescreen legen; sie fragt beim Start
nach der Tracking-ID.

---

## Hinweise zur Datensicherheit

- Ein Link ist **nicht erratbar**, aber ohne Passwort **nicht geschützt** – wer
  ihn weiterleitet, gibt den Zugang weiter. Für Fahrer-Links deshalb immer ein
  Passwort setzen.
- Passwort und Link **getrennt** übermitteln (Link per Messenger, Passwort per
  Funk oder mündlich).
- Für dauerhafte interne Nutzung ist die Einbindung als Organisationsmitglied
  mit der Rolle `beobachter` bzw. `fahrer` der sauberere Weg – dort greifen
  Rollenmodell, MFA und Audit-Log vollständig.
- Nach dem Einsatz die Links **widerrufen**.
