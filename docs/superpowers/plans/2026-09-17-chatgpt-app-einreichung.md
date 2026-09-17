# ConvoyPlan als ChatGPT-App — Metadaten und Einreichung

Schwesterdokument zu `2026-09-17-chatgpt-app.md`. Dort steht, was der MCP-Server
können muss; hier steht, was die Einreichung verlangt — und **warum die
öffentliche Veröffentlichung nicht so läuft, wie die Projektbeschreibung
annimmt**.

---

## 1. Der Haken: eine App, eine Adresse

Die Projektbeschreibung sieht als Ziel das öffentliche ChatGPT-App-Verzeichnis
mit einem `[Connect]`-Knopf. Das funktioniert so nur für Produkte, bei denen
**alle Benutzer denselben Server ansprechen**.

ConvoyPlan ist self-hosted. Jede Organisation betreibt ihre eigene Instanz unter
ihrer eigenen Domain; `web.convoyplan.de` ist die Instanz des Herstellers und
kennt die Konten anderer Betreiber nicht. Eine Einreichung mit dieser Adresse
ergäbe einen Verzeichniseintrag, der für **jeden Kunden mit eigener Instanz
nutzlos** wäre: Der `[Connect]`-Knopf führte zu einer Anmeldung, bei der er kein
Konto hat.

OpenAI kennt dafür **templated URLs** — eine Adressvorlage, in die der Benutzer
beim Verbinden seine eigene Domain einsetzt. Die gibt es aber nach eigener
Aussage nur für Entwickler, zu denen bereits eine Geschäftsbeziehung besteht.
Ohne diesen Weg bleibt:

| Weg | Für wen | Aufwand |
|---|---|---|
| **Developer Mode** (eigener Connector) | jeder Betreiber, für die eigene Instanz | ein Formular, kein Review |
| **Workspace-App** | ein Betreiber für seine eigene Organisation | Veröffentlichung im eigenen Workspace |
| **Öffentliches Verzeichnis** | nur sinnvoll für die Hersteller-Instanz — oder mit templated URL | Review durch OpenAI |

**Empfehlung:** Der Developer Mode ist für Bestandskunden der eigentliche Weg
und funktioniert heute. Die Anwenderdokumentation muss ihn erklären, nicht das
Verzeichnis. Eine öffentliche Einreichung lohnt für die Hersteller-Instanz —
als Schaufenster und als Voraussetzung dafür, überhaupt in die Lage zu kommen,
templated URLs anzufragen.

Das ist keine Lücke in der Umsetzung, sondern eine Eigenschaft des Produkts:
Self-Hosting und ein zentrales App-Verzeichnis widersprechen sich an dieser
Stelle.

---

## 2. Was jetzt vorbereitet ist

### 2.1 Nachweis der Domain

OpenAI verlangt vor der Aufnahme einen Beleg, dass der Einreichende den Host des
MCP-Servers kontrolliert: ein Token unter
`/.well-known/openai-apps-challenge`. Geprüft wird die **Wurzel** des Hosts,
der Pfad des Endpunkts spielt keine Rolle — für `https://<domain>/mcp` also
`https://<domain>/.well-known/openai-apps-challenge`.

Umgesetzt im Verteiler (`frontend/src/lib/server/agent/dispatch.ts`), Token über
`OPENAI_APPS_CHALLENGE`. **Ohne Eintrag gibt es den Pfad nicht** — dieselbe
Regel wie beim Rest der Agenten-Auskunft: nichts ankündigen, was es auf dieser
Instanz nicht gibt.

### 2.2 Nutzungsbedingungen

`/terms` gab es nicht; die Einreichungsmaske fragt danach, und die Definition of
Done nennt sie. Die Seite entsteht wie die übrigen Informationsseiten aus
`documents.ts`, hat ihre Markdown-Fassung unter `/terms.md` und steht in
Sitemap, `llms.txt` und der Fußzeile der Startseite.

**Was sie ist:** eine Zusammenfassung der Lizenzlage aus `LICENSE` und
`COMMERCIAL_LICENSE.md` — AGPL, wann eine kommerzielle Lizenz nötig wird,
Gewährleistungsausschluss, und die Einordnung der KI-Schnittstelle.

**Was sie nicht ist:** ein von einem Anwalt geprüfter Vertragstext. Sie sagt das
selbst und verweist für Verbindliches auf die Lizenztexte, auf den Hersteller
und auf den Betreiber der jeweiligen Instanz. Vor einer öffentlichen Einreichung
gehört sie einmal durch eine juristische Prüfung — insbesondere die Abgrenzung
zwischen Hersteller- und Betreiberpflichten bei einem BOS-Werkzeug.

---

## 3. Die Metadaten

Zum Abtippen in die Einreichungsmaske. Quelle für alles Inhaltliche ist
`frontend/src/lib/agent/facts.ts`; wer dort etwas ändert, ändert es hier mit.

| Feld | Wert |
|---|---|
| **Name** | ConvoyPlan |
| **Kurzbeschreibung** | Marschverbände und Konvois planen: Route, Wegpunkte, Marschbefehl und Live-Status. |
| **Short description (EN)** | Plan and run convoys and march columns: routes, waypoints, march order and live status. |
| **Kategorie** | Produktivität / Branchenlösung (BusinessApplication) |
| **Website** | https://convoyplan.de |
| **MCP-Endpunkt** | `https://web.convoyplan.de/mcp` (Hersteller-Instanz, siehe Abschnitt 1) |
| **Authentifizierung** | OAuth 2.1, Authorization Code + PKCE (`S256`), Refresh Tokens; DCR und CIMD |
| **Datenschutz** | https://web.convoyplan.de/privacy |
| **Nutzungsbedingungen** | https://web.convoyplan.de/terms |
| **Support** | https://web.convoyplan.de/contact · anfrage@convoyplan.de |
| **Entwickler** | RettTech Solutions |

### Ausführliche Beschreibung (Entwurf)

> ConvoyPlan plant Marschverbände und Konvoifahrten für Einsatzorganisationen:
> Fahrzeuge in Marschordnung, Wegpunkte und technische Halte, berechnete Routen
> mit Zeitschätzung und den Marschbefehl als Dokument. Über diese App lassen
> sich die Konvois der eigenen Organisation abfragen, anlegen und ändern und der
> Marschstatus unterwegs verfolgen.
>
> Die Verbindung gilt für genau eine Organisation und ist durch die Rolle des
> verbundenen Benutzers gedeckelt. Kein Werkzeug löscht Daten; jeder schreibende
> Aufruf wird protokolliert. ConvoyPlan wird selbst betrieben — die Daten
> bleiben auf der Instanz der Organisation.

### Funktionsübersicht

- Konvois auflisten, nach Zeitraum, Status und Name filtern
- Konvoi mit Marschbefehl und Fahrzeugen in Marschordnung ansehen
- Marschstatus je Fahrzeug, Ausfälle zuerst
- Fahrzeuge anlegen, zuordnen, umsortieren
- Wegpunkte pflegen, Routen berechnen
- Fahrzeugstatus und Positionen unterwegs melden

### Bildmaterial

Im Repository vorhanden und verwendbar:

- **Icon/Logo**: `logo/Favicon.svg`, `logo/Hauptlogo.svg`, `logo/Logo Horizontal.svg`
  (dazu PNG-Fassungen und je ein Satz für hellen und dunklen Hintergrund)
- **Screenshots der Anwendung**: `docs/screenshots/` — Routenplanung,
  Live-Tracking, Marschbefehl-Export, Berechtigungen, Leitstellen, Branding

**Offen:** Screenshots der **Oberflächen in ChatGPT** gibt es noch keine. Die
Einreichungsmaske will Bilder, die zeigen, was die App im Gespräch tut — die
vorhandenen zeigen die Weboberfläche. Sie entstehen beim ersten Durchgang im
Developer Mode (Abschnitt 4).

---

## 4. Reihenfolge

1. [ ] CIMD-Schalter auf der Hersteller-Instanz umlegen (Portal → System → KI-Schnittstelle)
2. [ ] Im **Developer Mode** verbinden, Werkzeuge einlesen, den Testkatalog aus
       `2026-09-17-chatgpt-app.md` Abschnitt 6 durchgehen
3. [ ] Dabei die Oberflächen ansehen und **Screenshots aufnehmen**
4. [ ] `/terms` juristisch prüfen lassen
5. [ ] Als **Workspace-App** veröffentlichen und im Alltag benutzen
6. [ ] Erst danach öffentliche Einreichung: Entwicklerverifizierung bei OpenAI,
       `OPENAI_APPS_CHALLENGE` setzen, Metadaten aus Abschnitt 3 eintragen
7. [ ] Bei Interesse an einem Verzeichniseintrag, der **allen Betreibern** nützt:
       templated URLs bei OpenAI anfragen (Abschnitt 1)

Die Schritte 1–3 sind Voraussetzung für alles Weitere und lassen sich nicht
automatisieren — sie brauchen ein ChatGPT-Konto mit Developer Mode
(Pro, Team, Enterprise oder Edu).

---

## 5. Was die Einreichung sonst noch prüft

Aus den Entwicklerrichtlinien, gegen den Bestand gehalten:

| Anforderung | Stand |
|---|---|
| Server öffentlich über HTTPS erreichbar | erfüllt |
| Werkzeugnamen sprechend, Beschreibungen erklären *wann* | erfüllt |
| Kein Sammeln des Gesprächsverlaufs, keine überflüssigen Eingabefelder | erfüllt — die Werkzeuge nehmen nur Fachparameter |
| Stabil und vollständig, keine Demo-Fassung | erfüllt |
| Testzugang für den Review | **offen** — ein Konto auf der Hersteller-Instanz mit Beispieldaten anlegen |
| Keine verbotene Kategorie, keine Werbung | erfüllt |
| Kein Verkauf digitaler Güter über die App | erfüllt — die App verkauft nichts |
| `readOnlyHint` / `destructiveHint` an den Werkzeugen | erfüllt, siehe unten |

### Annotationen an den Werkzeugen

Die Richtlinien nennen `readOnlyHint`, `destructiveHint` und `openWorldHint`.
Jedes der 22 Werkzeuge trägt sie jetzt (`app/mcp/annotations.py`), samt einem
sprechenden Titel für die Anzeige im Client.

Die Zusage, auf die es ankommt, ist `destructive = False` an **jedem** Werkzeug
— die Positivliste in anderer Form. `fahrzeug_aus_konvoi_entfernen` löst eine
Zuordnung; der Datensatz bleibt, und der Aufruf lässt sich zurücknehmen.

Drei Tests halten das fest: jedes Werkzeug hat eine Annotation mit Titel, keines
gibt sich als zerstörend aus, und `read_only_hint` stimmt mit `WRITE_TOOLS`
überein. Der letzte fängt den Fall ab, der sonst still falsch würde — ein
Werkzeug von lesend auf schreibend umbauen und die Annotation stehen lassen.
