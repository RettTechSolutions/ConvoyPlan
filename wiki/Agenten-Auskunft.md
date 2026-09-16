# Auskunft für Suchmaschinen und KI-Agenten

Eine ConvoyPlan-Instanz liefert unter ihrer eigenen Domain aus, **was sie ist** und
**wie man sie programmatisch anspricht**. Das ist kein Marketing-Anhängsel: ein
Sprachmodell, das nach einer Konvoiplanung gefragt wird, und ein Agent, der auf einer
Instanz landet, brauchen beide dieselbe Auskunft, und beide lesen sie lieber als Text
als aus einer Single-Page-App, die erst Javascript starten muss.

Alles hier beschreibt die **Software**, nicht ihren Inhalt. Es gibt keinen Pfad in
dieser Liste, der Daten einer Organisation zeigt. Wer trotzdem nichts über die Instanz
verraten will, schaltet sie mit `AGENT_DISCOVERY=false` ab — siehe unten.

## Was ausgeliefert wird

Alle Pfade sind relativ zur Adresse der Instanz (`https://<DOMAIN>/…`).

### Einstiege

| Pfad | Inhalt |
| --- | --- |
| `/llms.txt` | Der Navigationsindex. Beginnt mit dem, was ConvoyPlan ist, und sagt dann ausdrücklich, **wann ein Agent ConvoyPlan aufrufen soll und wann nicht** |
| `/llms-full.txt` | Dieselbe Auskunft als Langfassung, alle Dokumente hintereinander |
| `/agents.md` | Kurzanleitung für KI-Agenten: Fähigkeiten, nötige Scopes, Regeln |
| `/auth.md` | Wie ein Agent an Zugangsdaten kommt, nach der [auth.md-Spezifikation](https://github.com/workos/auth.md) gegliedert |
| `/api.md` | Die REST-Oberfläche in Prosa: Endpunkte, Fehlercodes, Grenzen |
| `/openapi.json` | OpenAPI 3.1 der **anmeldefreien** Endpunkte plus der Sicherheitsschemata |
| `/ask` | Fragen über ConvoyPlan, beantwortet mit passenden Seiten (NLWeb, `GET` und `POST`, auf Wunsch als SSE-Stream) |

Abschnittsweise gibt es zusätzlich `/api/llms.txt`, `/docs/llms.txt` und
`/developers/llms.txt` — für einen Agenten, der nur einen Teilbereich braucht.

### Well-Known-Dokumente

| Pfad | Standard |
| --- | --- |
| `/.well-known/agent-card.json` | A2A Agent Card |
| `/.well-known/agent-skills/index.json` | Agent-Skills-Index |
| `/.well-known/ard.json` | [Agentic Resource Discovery](https://agenticresourcediscovery.org/) |
| `/.well-known/mcp/server-card.json` | Kurzbeschreibung des MCP-Servers |
| `/.well-known/api-catalog` | API-Katalog nach RFC 9727 |
| `/.well-known/oauth-protected-resource` | RFC 9728 für die REST-API |
| `/.well-known/oauth-protected-resource/mcp` | RFC 9728 für den MCP-Server — **nur bei eingeschalteter KI-Schnittstelle** |

### Seiten

`/about`, `/pricing`, `/developers`, `/docs`, `/contact` und `/privacy` beschreiben das
Produkt, den Betrieb, die Lizenzmodelle und die Schnittstellen. Sie stehen hinter keiner
Anmeldung, weil sie genau denen etwas sagen sollen, die noch keine haben.

Dazu kommen `/robots.txt` (mit `Sitemap:`- und `Schemamap:`-Verweis und einer
ausdrücklichen Erlaubnis für die großen KI-Crawler), `/sitemap.xml`, `/schema-map.xml`
und die Feeds unter `/feeds/`.

## Markdown statt HTML

Jede Seite hat eine Markdown-Fassung, und beide entstehen aus **derselben Quelle**
(`frontend/src/lib/server/agent/documents.ts`). Sie können deshalb nicht auseinanderlaufen.

Drei Wege führen dorthin:

```bash
curl https://<DOMAIN>/about.md                          # direkt
curl -H 'Accept: text/markdown' https://<DOMAIN>/about  # ausgehandelt
curl https://<DOMAIN>/about?mode=agent                  # maschinenlesbare Übersicht
```

Die HTML-Fassung kündigt die Markdown-Fassung über
`<link rel="alternate" type="text/markdown">` und über einen `Link`-Kopf (RFC 8288) an,
der außerdem auf Sitemap, `llms.txt`, OpenAPI und den API-Katalog zeigt.

**Nicht** nach User-Agent unterschieden: ein Crawler bekommt dieselbe Seite wie ein
Mensch. Unterschiedliche Inhalte je nach Kennung wären Cloaking, und seit die Seiten
ihren Inhalt serverseitig ausliefern, hätte ein Bot davon auch nichts.

Ein Pfad, den es nicht gibt, antwortet mit `404` — auf Wunsch als Markdown mit
Wegweiser statt als leere App-Hülle.

## Was die Auskunft über die Instanz sagt

Die Dokumente werden **je Anfrage** aus der tatsächlichen Lage der Instanz gebaut:
unter welcher Domain sie läuft, ob der MCP-Server montiert ist, ob ein Demo-Zugang
freigeschaltet ist. Grundlage ist `GET /api/status/capabilities` (ohne Anmeldung
abfragbar).

Das ist der Grund für den Aufwand: eine Instanz unter `feuerwehr.example` darf nicht auf
`convoyplan.de` verweisen, und ein `server-card.json`, das einen MCP-Endpunkt ankündigt,
den der Betreiber abgeschaltet hat, wäre schlechter als gar keines. Ist die
KI-Schnittstelle aus, sagen die Dokumente das — und nennen den REST-Weg.

## Die öffentliche OpenAPI-Beschreibung

`/openapi.json` ist **nicht** die vollständige Beschreibung. Die bleibt in Produktion
abgeschaltet und wird per `DOCS_API_KEY` geschützt (siehe
[API-Dokumentation](API-Dokumentation)). Veröffentlicht wird eine kuratierte Teilmenge:

- nur Endpunkte, die ohnehin ohne Anmeldung erreichbar sind,
- dazu die Sicherheitsschemata (`bearerAuth`, `apiKeyAuth`, `oauth2`), damit ein Agent
  erfährt, wie er an ein Token kommt,
- mit eigenen Beschreibungen statt der Docstrings aus dem Quelltext, und
- nur mit den Schemata, die diese Endpunkte wirklich brauchen.

Struktur (Parameter, Antwortschemata) kommt aus der laufenden App und kann deshalb nicht
veralten; die Liste der öffentlichen Operationen steht ausdrücklich in
`backend/app/api/routes/public_meta.py` und wird von `tests/test_public_openapi.py` in
beide Richtungen geprüft.

## Werkzeuge im Browser (WebMCP)

Die Startseite meldet vier **lesende** Werkzeuge an, wenn der Browser das Modell kennt:
Produktauskunft, Seitenverzeichnis, Instanzstatus und die Prüfung eines
Organisations-Codes. Schreibende Werkzeuge gibt es dort bewusst nicht — dafür ist der
MCP-Server da, mit ausdrücklicher Zustimmung und Audit-Log.

## Abschalten

```env
AGENT_DISCOVERY=false
```

Danach gibt es keinen der oben genannten Pfade mehr (404), und die Startseite zeigt
wieder nur die Anmeldung. Der Rest der Anwendung ist davon unberührt. Standard ist `true`.

## Was nicht im Code liegt

Ein Teil dessen, was KI-Suchen über ein Produkt finden, entsteht außerhalb der Software:
ein Wikidata-Eintrag, Presseerwähnungen, Einträge in App-Verzeichnissen, veröffentlichte
SDK-Pakete. Ebenso entscheidet ein vorgelagertes CDN oder eine WAF darüber, ob ein
KI-Crawler die Instanz überhaupt erreicht — die `robots.txt` erlaubt es, die Firewall
kann es trotzdem verhindern.

## Verwandt

- [MCP-Server (KI-Schnittstelle)](MCP-Server)
- [API-Dokumentation](API-Dokumentation)
- [Sicherheit und Datenschutz](Sicherheit-und-Datenschutz)
