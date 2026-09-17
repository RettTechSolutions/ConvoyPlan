# ConvoyPlan als ChatGPT-App — Bestandsaufnahme und Plan

**Ausgangslage:** Der MCP-Server steht (Plan `2026-09-16-mcp-server`, Phasen 0–3
abgeschlossen). Die Frage dieses Plans ist nicht mehr „wie baut man den Server",
sondern: **was fehlt, damit ChatGPT ihn benutzen kann** — und welche Annahmen aus
der Projektbeschreibung sich am tatsächlichen Datenmodell nicht halten lassen.

**Prüfgegenstand:** `https://web.convoyplan.de/mcp`, Stand 17.09.2026.

---

## 1. Befund: der bestehende Endpunkt

```
MCP Status: OK
```

Geprüft wurde von außen gegen die Produktivinstanz (unauthentifiziert sowie über
eine erteilte Verbindung):

| Prüfpunkt | Befund |
|---|---|
| Transport | Streamable HTTP auf `POST /mcp`, ohne Schrägstrich, ohne Umleitung |
| `initialize` | funktioniert; Protokollversion `2025-06-18` ausgehandelt |
| `tools/list` | 21 Werkzeuge (jetzt 22, siehe unten) |
| Authentifizierung | `401` mit `WWW-Authenticate: Bearer error="invalid_token", scope="convoy:read", resource_metadata="…"` |
| Resource Metadata | `/.well-known/oauth-protected-resource/mcp` nach RFC 9728, nennt den eigenen Issuer |
| Authorization Server | `/.well-known/oauth-authorization-server`: `authorization_code` + `refresh_token`, PKCE `S256`, `registration_endpoint`, `revocation_endpoint`, `authorization_response_iss_parameter_supported: true` |
| Session-Handling | `Mcp-Session-Id`, Sitzung über den Session-Manager des SDK |
| Mandantentrennung | Token gilt für **genau eine** Organisation (`org_id` im Token, bei jedem Aufruf frisch gegen die Datenbank geprüft) |
| Benutzerberechtigungen | Scopes sind eine Projektion von `ROLE_ORDER`; entzogene Mitgliedschaft und herabgestufte Rolle wirken sofort |
| Fehlerbehandlung | `McpError` erreicht das Modell im Klartext statt als „Error executing tool …" |
| Rate Limiting | pro Token/Minute und pro Benutzer für Fremdleistungen (GraphHopper/HERE) |
| Audit | jeder schreibende Aufruf mit Quelle `mcp`, Client-ID und Benutzer |

**Vorhandene Werkzeuge** (Positivliste in `backend/app/mcp/__init__.py`):

```
Lesend    organisation_details*, konvois_auflisten, konvoi_details,
          unterkonvois_auflisten, fahrzeuge_auflisten, fahrzeug_details,
          wegpunkte_auflisten, route_abrufen, fahrzeugpositionen_abrufen,
          konvoi_status
Schreibend konvoi_anlegen, konvoi_aktualisieren, fahrzeug_anlegen,
          fahrzeug_aktualisieren, fahrzeug_zu_konvoi_hinzufuegen,
          fahrzeug_aus_konvoi_entfernen, konvoi_fahrzeuge_umsortieren,
          wegpunkt_anlegen, wegpunkt_aktualisieren, wegpunkte_umsortieren,
          route_berechnen, fahrzeugstatus_setzen
                                                      (* neu in diesem Schritt)
```

Dazu drei Resources (Marschbefehl-PDF, GPX, JSON), ein Prompt und Live-Abos.

Der Zuschnitt entspricht bereits der Vorgabe aus der Projektbeschreibung: klar
abgegrenzte fachliche Aktionen, kein `execute_api`, kein `execute_sql`, kein
generisches Löschwerkzeug — **kein Werkzeug löscht überhaupt Daten.**

---

## 2. Was der Projektbeschreibung widerspricht

### 2.1 Teilnehmer und Fahrer gibt es in ConvoyPlan nicht

Die Beschreibung verlangt `list_participants`, `get_participant`,
`add_participant`, `remove_participant` und `assign_driver`. **Dafür gibt es
kein Datenmodell.** Im Schema kommt „Fahrer" an genau zwei Stellen vor:

- als **Mitgliedschaftsrolle** (`beobachter | fahrer | planer | admin`) — eine
  Berechtigung, keine Zuordnung zu einem Fahrzeug;
- als **Geltungsbereich eines Teilen-Links** (`scope="driver"`), über den eine
  Besatzung ohne Login Position und Status meldet.

Ein Personendatensatz, der einem Fahrzeug oder einem Konvoi zugeordnet wäre,
existiert nicht. Das Nächstliegende ist `ConvoyVehicle.mobile_phone` (eine
Telefonnummer am Fahrzeug im Konvoi) und `Convoy.ablaufführer` (ein Freitext im
Marschbefehl).

**Folge:** „Weise Christoph als Fahrer zu" ist kein fehlendes Werkzeug, sondern
ein fehlendes Feature. Es umzusetzen hieße: Datenmodell, Migration, REST-API,
Oberfläche, Rechte, DSGVO-Einordnung (Personendaten von Einsatzkräften in einem
BOS-Produkt) — und **danach** ein MCP-Werkzeug. Das ist ein eigenes Vorhaben,
kein Teil der ChatGPT-Anbindung. Es steht deshalb unten unter „Später".

### 2.2 `delete_convoy` bleibt bewusst aus

Die Beschreibung führt `delete_convoy`, `remove_vehicle` und
`remove_participant` als „kritische Aktionen" auf. ConvoyPlan hat sich
gegenteilig entschieden: **kein Werkzeug löscht Daten**, abgesichert über eine
Positivliste samt Test. `fahrzeug_aus_konvoi_entfernen` löst nur die Zuordnung.
Das bleibt so — ein Löschwerkzeug, das ein Modell auslösen kann, ist in einem
BOS-Produkt kein Feature.

---

## 3. Was ChatGPT tatsächlich verlangt

Aus der Apps-SDK- und Developer-Mode-Dokumentation von OpenAI, gegen den
Bestand gehalten:

| Anforderung | Stand | Anmerkung |
|---|---|---|
| Streamable HTTP unter stabiler URL | **erfüllt** | `https://web.convoyplan.de/mcp` |
| HTTPS, kein stdio | **erfüllt** | |
| OAuth 2.1 mit PKCE | **erfüllt** | `S256`, Refresh-Tokens rollierend |
| Client-Registrierung | **erfüllt** | DCR läuft; CIMD ist implementiert und jetzt im Portal schaltbar (Standard weiter aus). OpenAI bevorzugt CIMD |
| Scope-Aushandlung über `scopes_supported` | **war der Bruch** | siehe unten |
| Step-up bei `insufficient_scope` | teilweise | ConvoyPlan antwortet auf Transportebene mit `403` + Challenge; ChatGPT erwartet zusätzlich `_meta["mcp/www_authenticate"]` am Werkzeugergebnis. Das SDK (`mcp==2.2.0`) kennt kein `securitySchemes` am Werkzeug |
| Handlungsorientierte Namen und Beschreibungen | **erfüllt** | |
| Apps-SDK-UI (`openai/outputTemplate`) | **erfüllt** | drei Ansichten, siehe 4.4; der Server läuft unverändert ohne sie |
| `structuredContent` am Werkzeugergebnis | **erfüllt** | Voraussetzung dafür, dass eine Oberfläche Daten sieht — siehe 4.5 |

### 3.1 Der Bruch: die Verbindung wäre für immer lesend gewesen

ChatGPT liest `scopes_supported` aus der Protected Resource Metadata und fragt
beim Verbinden **einmal** an. Dort stand nur `convoy:read` — mit der damals
richtigen Überlegung, ein Client möge Schreibrechte per Step-up nachfordern
statt sie vorsorglich zu verlangen.

Das setzt einen Client voraus, der Step-up beherrscht. ChatGPT fragt beim
Verbinden und danach nicht mehr. Ergebnis: „Füge Fahrzeug XY dem Konvoi hinzu"
wäre in ChatGPT **immer** an einem Rechtefehler gescheitert, ohne dass der
Benutzer einen Weg gehabt hätte, das zu ändern — die Verbindung neu zu erteilen
hätte dasselbe Ergebnis gebracht.

**Behoben in diesem Schritt** (siehe Abschnitt 4).

---

## 4. Umgesetzt

### 4.1 Rechte werden auf dem Zustimmungsbildschirm ausgewählt

- `scopes_supported` weist jetzt aus, **was die Resource versteht**
  (alle drei Scopes) statt nur das Minimum. Davon getrennt ist neu
  `REQUIRED_SCOPES` — die Schwelle des Endpunkts, weiterhin `convoy:read`.
  Die beiden Begriffe teilten sich vorher eine Konstante; hätte man sie
  gemeinsam verbreitert, hätte `RequireAuthMiddleware` von **jedem** Token
  sämtliche Scopes verlangt und jede lesende Verbindung abgewiesen.
- Der Zustimmungsbildschirm zeigt die Rechte als Ankreuzfelder: vorausgewählt
  ist das Angefragte, darunter steht ankreuzbar, was die eigene Rolle darüber
  hinaus hergibt. Die Auswahl kann die Anfrage des Clients erweitern **und**
  beschneiden.
- **Die Rolle bleibt die Obergrenze.** `grantable()` schneidet jede Auswahl auf
  die Mitgliedschaft zurecht; ein Beobachter bekommt `convoy:write` auch durch
  Ankreuzen nicht.
- Erteilte Scopes werden **ausgeschrieben** gespeichert (`effective()`): ein
  Token mit nur `convoy:write` wäre an `RequireAuthMiddleware` gescheitert, die
  ohne Hierarchie prüft. Das war eine latente Falle, die erst durch die
  Auswahlmöglichkeit erreichbar geworden wäre.

### 4.2 `konvois_auflisten` filtert

Neue Parameter `von`, `bis`, `status`, `suche`, `nur_hauptkonvois`, `limit`.
„Welche Konvois habe ich nächste Woche?" ist damit eine Abfrage statt eines
Komplettabzugs mit anschließender Aussortierung im Modell. Eine obere
Zeitgrenze ohne Uhrzeit meint den ganzen Tag; Zeitzonenangaben werden
abgeschnitten, nicht umgerechnet (`start_time` ist Ortszeit der Instanz). Ein
abgeschnittenes Ergebnis sagt, dass es abgeschnitten ist.

### 4.3 `organisation_details`

Sagt, für welche Organisation die Verbindung gilt, welche Rolle der Benutzer
dort hat, welche Rechte erteilt sind und welche Werkzeuge damit — und mit der
Lizenz dieser Instanz — tatsächlich durchgehen. Beantwortet zwei Fragen, die
sonst nur durch Ausprobieren zu klären waren.

### 4.4 Oberflächen für ChatGPT

Drei Ansichten in `app/mcp/widgets.py`: **Konvoi-Liste** (zu
`konvois_auflisten`), **Konvoi-Übersicht** mit Marschbefehl und Fahrzeugen in
Marschordnung (zu `konvoi_details`) und **Marschstatus** mit Ausfällen zuerst
(zu `konvoi_status`).

Drei Festlegungen dazu:

- **Zugabe, nicht Voraussetzung.** Ein Client ohne Oberflächen bekommt
  unverändert dieselbe Antwort. Es gibt kein Werkzeug, das ohne Ansicht nicht
  ginge, und keines, dessen Ergebnis nur dort steht.
- **Nichts wird nachgeladen** — kein Skript, kein Zeichensatz, kein Bild.
  Deshalb auch kein Bauschritt und kein Framework: Handarbeit in einer Datei.
  Als Test festgehalten, weil es sonst beim nächsten Umbau still verloren geht.
- **Der Rahmen ist geteilt.** Auspacken der Antwort und Maskieren fremder
  Texte stehen genau einmal in `widgets/rahmen.html`. Beides sind Stellen, an
  denen ein Fehler nicht auffällt: eine leere Fläche oder eine Skriptlücke.

Das Auspacken ist dabei bewusst tolerant. Die Dokumentation beschreibt
`window.openai.toolOutput` als das `structuredContent`; in Beispielen steht
daneben `toolOutput.result.structuredContent`. Beide Lesarten sind im Umlauf,
also wird ausgepackt, was da ist, statt auf eine Form zu wetten.

### 4.5 Alle Werkzeuge antworten strukturiert

Die Rückgabetypen lauten jetzt `dict[str, Any]` statt `dict`. Erst damit
leitet das SDK ein Ausgabeschema ab und liefert die Antwort zusätzlich als
`structuredContent` — genau das Feld, das eine Oberfläche liest. Mit bloßem
`dict` weigert sich das SDK ausdrücklich („not serializable for structured
output"), und ohne Schema bleibt `structuredContent` leer.

Der Textteil bleibt daneben bestehen; ein Client ohne Schemaunterstützung
verliert nichts. Ein Modell gewinnt: die Felder sind benannt, statt aus einem
Textblock gefischt zu werden.

### 4.6 CIMD ist schaltbar

`MCP_ALLOW_CIMD` brauchte einen Neustart. Der Schalter sitzt jetzt im Portal
neben dem Hauptschalter, mit demselben Vorrang (Datenbank schlägt Umgebung)
und demselben Standard: **aus**. Eingeschaltet ruft die Instanz eine Adresse
ab, die der Anfragende bestimmt; das bleibt eine Entscheidung des Betreibers
und keine Voreinstellung.

Zwei Stellen mussten dafür nachziehen:

- Die Prüfung in `loese_cimd_auf()` steht **vor** dem Zwischenspeicher.
  Stünde sie dahinter, liefe ein einmal abgerufenes Dokument nach dem
  Zudrehen weiter — als Test festgehalten.
- Die AS-Metadata entsteht je Anfrage statt beim Start. Sonst bliebe die
  Ankündigung bis zum nächsten Neustart falsch. Was bleibt: der Handler setzt
  `Cache-Control: max-age=3600`, ein Client sieht eine Änderung also unter
  Umständen erst nach einer Stunde.

---

## 5. Offen

### Als Nächstes

- [x] **CIMD schaltbar gemacht.** Lag als Umgebungsvariable vor, die einen
      Neustart brauchte; sitzt jetzt als Schalter im Portal neben dem
      Hauptschalter (`mcp_config.is_cimd_allowed`, Datenbank schlägt
      Umgebung). Standard bleibt aus — eingeschaltet ruft die Instanz eine
      Adresse ab, die der Anfragende bestimmt.
- [ ] **Den Schalter auf der Produktivinstanz umlegen** und gegen ChatGPT
      prüfen. **Manuell** — ein Klick im Portal, kein Deployment.
- [ ] **Verbindung im ChatGPT Developer Mode herstellen** (Settings → Apps →
      Advanced → Developer mode, „Create App", Endpunkt eintragen, Tools
      einlesen). Erfordert ChatGPT Pro/Team/Enterprise/Edu. **Manuell, nicht
      automatisierbar.**
- [ ] Dabei prüfen: Welche Scopes fragt ChatGPT tatsächlich an? Kommt der
      Zustimmungsbildschirm im Popup sauber durch? Wird `refresh_token`
      benutzt?
- [ ] **Testkatalog abarbeiten** (Abschnitt 6).

### Danach

- [ ] Step-up für ChatGPT: `_meta["mcp/www_authenticate"]` am Werkzeugergebnis.
      Hängt am SDK — `mcp==2.2.0` kennt weder `securitySchemes` am Werkzeug
      noch einen Weg, `_meta` an einen Werkzeugfehler zu hängen. Vor einem
      SDK-Sprung nicht sinnvoll anzufassen; die Ankreuzfelder lösen den
      Anwendungsfall bis dahin vollständig.
- [x] **Apps-SDK-Oberflächen** für Konvoi-Liste, Konvoi-Übersicht und
      Marschstatus (`app/mcp/widgets.py`). Handarbeit ohne Bauschritt und
      ohne Nachladen von außen; der Server funktioniert unverändert ohne sie.
      Dafür geben alle Werkzeuge jetzt `structuredContent` zurück — die
      Grundlage, auf der eine Oberfläche überhaupt Daten sieht.
- [ ] Die Oberflächen im Developer Mode ansehen. Gerendert wurden sie bisher
      nur gegen Beispieldaten, nicht in ChatGPT selbst.
- [x] **App-Metadaten, Nutzungsbedingungen, Domainnachweis** — eigenes
      Dokument: `2026-09-17-chatgpt-app-einreichung.md`. `/terms` gab es nicht
      und ist neu; `/.well-known/openai-apps-challenge` liefert den Nachweis
      der Domain, sobald ein Token gesetzt ist.
- [ ] Veröffentlichung im Workspace, danach öffentlich. **Achtung:** Ein
      öffentlicher Verzeichniseintrag nennt *eine* Serveradresse und nützt
      damit keinem Betreiber mit eigener Instanz. Warum das so ist und was
      stattdessen der Weg ist, steht in Abschnitt 1 des Einreichungsdokuments.

### Später (eigenes Vorhaben)

- [ ] **Teilnehmer- und Fahrerverwaltung** als Fachfunktion — siehe 2.1. Erst
      Datenmodell und Oberfläche, dann Werkzeuge.

---

## 6. Testkatalog

Was sich automatisiert prüfen lässt, steht in `backend/tests/test_mcp_*.py`.
Der folgende Katalog ist für den **manuellen** Durchgang in ChatGPT gedacht,
nachdem die App dort eingerichtet ist.

### Lesend

| Frage | Erwartung |
|---|---|
| „Mit welcher Organisation bist du verbunden?" | `organisation_details`, nennt Organisation und Rolle |
| „Welche Konvois stehen nächste Woche an?" | `konvois_auflisten` mit `von`/`bis`, nicht der Komplettabzug |
| „Welche Fahrzeuge sind Konvoi X zugeordnet?" | `konvoi_details` |
| „Wo steht Konvoi X gerade?" | `fahrzeugpositionen_abrufen` |
| „Wann startet Konvoi Z?" | aus `konvois_auflisten` oder `konvoi_details` |
| „Zeig mir den Marschbefehl von X" | `konvoi_details`, die sieben Abschnitte |

### Schreibend

| Auftrag | Erwartung |
|---|---|
| „Lege einen Testkonvoi an" | `konvoi_anlegen`, Quittung nennt Name und ID |
| „Füge Fahrzeug X hinzu" | `fahrzeug_zu_konvoi_hinzufuegen` |
| „Ändere die Startzeit auf 06:30" | `konvoi_aktualisieren` |
| „Berechne die Route" | `route_berechnen`, Kontingent wird belastet |
| „Entferne Fahrzeug X" | `fahrzeug_aus_konvoi_entfernen`; Antwort sagt ausdrücklich, dass das Fahrzeug **nicht gelöscht** wurde |
| „Lösche den Konvoi" | **kein Werkzeug vorhanden**; das Modell muss das sagen, statt etwas anderes zu tun |

### Randfälle

| Fall | Erwartung |
|---|---|
| Konvoi-ID gibt es nicht | „Kein Konvoi mit der ID … in der Organisation …" |
| Konvoi einer **fremden** Organisation | dieselbe Meldung wie „gibt es nicht" — keine Auskunft darüber, dass die ID anderswo existiert |
| Rechte reichen nicht | Meldung nennt das fehlende Recht und den Weg (Verbindung neu erteilen) |
| Token abgelaufen | ChatGPT erneuert über `refresh_token`, ohne Zutun |
| Ungültiges Datum | „… ist keine lesbare Zeitangabe. Erwartet wird ISO-8601 …" |
| Doppelte Zuordnung | Fehler aus der wiederverwendeten Route, übersetzt |
| Pflichtfeld fehlt | Schema-Fehler des SDK, bevor das Werkzeug läuft |
| Zu viele Aufrufe | Kontingentmeldung mit Wartezeit, kein nacktes 429 |
| MCP im Portal abgeschaltet | Endpunkt existiert nicht mehr (404), auch die Well-Known-Dokumente |

---

## 7. Sicherheitsbetrachtung zu diesem Schritt

Die Änderung an der Zustimmungsstrecke erweitert, was ein Benutzer erteilen
**kann**. Drei Punkte dazu:

1. **Die Rolle bleibt die harte Grenze.** Jede Auswahl geht durch
   `grantable()`; über die Mitgliedschaft hinaus geht nichts. Ein bösartiger
   Client, der sich `convoy:write` in die Anfrage schreibt, kommt bei einem
   Beobachter keinen Schritt weiter.
2. **Erteilt wird nur, was ein angemeldeter Mensch angekreuzt hat** — mit
   Klartextbeschriftung, nicht als `convoy:write`. Eine leere Auswahl ist keine
   Zustimmung und wird mit `403` abgewiesen.
3. **Der Client erfährt den erteilten Umfang**: die Token-Antwort trägt `scope`
   (RFC 6749 §3.3). Eine Erteilung über das Angefragte hinaus ist damit für den
   Client erkennbar und nicht still.

Unverändert: kein Löschwerkzeug, kein Zugriff auf Instanz-Ebene, ein Token pro
Organisation, Audit-Eintrag bei jedem schreibenden Aufruf, Widerruf pro
Verbindung im Admin-Portal.
