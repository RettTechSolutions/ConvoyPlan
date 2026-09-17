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
| Client-Registrierung | **erfüllt über DCR** | CIMD ist implementiert, aber per `MCP_ALLOW_CIMD` **aus**; OpenAI bevorzugt CIMD |
| Scope-Aushandlung über `scopes_supported` | **war der Bruch** | siehe unten |
| Step-up bei `insufficient_scope` | teilweise | ConvoyPlan antwortet auf Transportebene mit `403` + Challenge; ChatGPT erwartet zusätzlich `_meta["mcp/www_authenticate"]` am Werkzeugergebnis. Das SDK (`mcp==2.2.0`) kennt kein `securitySchemes` am Werkzeug |
| Handlungsorientierte Namen und Beschreibungen | **erfüllt** | |
| Apps-SDK-UI (`openai/outputTemplate`) | offen | ausdrücklich optional |

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

---

## 5. Offen

### Als Nächstes

- [ ] **CIMD einschalten** (`MCP_ALLOW_CIMD=true`) und gegen ChatGPT prüfen.
      Implementiert und getestet (`tests/test_mcp_cimd.py`, inklusive
      SSRF-Schutz), nur nicht aktiv. OpenAI bevorzugt CIMD vor DCR; DCR
      funktioniert weiterhin als Rückfallweg.
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
- [ ] Apps-SDK-UI (Konvoiübersicht, Fahrzeugliste, Statusanzeige) — optional,
      der Server funktioniert ohne.
- [ ] App-Metadaten, Datenschutz, Nutzungsbedingungen, Support-URL. Die Seiten
      existieren bereits unter `/privacy`, `/contact` und `/developers` jeder
      Instanz (siehe `wiki/Agenten-Auskunft.md`); für eine öffentliche
      Einreichung müssen sie auf eine feste Instanz zeigen.
- [ ] Veröffentlichung im Workspace, danach öffentlich.

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
