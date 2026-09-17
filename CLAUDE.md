# ConvoyPlan — Claude Instructions

## Repos

| Repo | Zweck |
|---|---|
| **ConvoyPlan** (dieses Repo) — https://github.com/RettTechSolutions/ConvoyPlan | App (Backend, Frontend, Docker) |
| **convoyplan-website** — https://github.com/RettTechSolutions/convoyplan-website | Marketingsite (Astro) |

Weitere, nicht-öffentliche Repos und die Zuordnung lokaler Arbeitskopien stehen
in `CLAUDE.local.md` (nicht eingecheckt, siehe `.gitignore`).

## Installer-Scripts

`scripts/install.sh` (Linux) und `scripts/install.ps1` (Windows) sind die Quelle
der Wahrheit für die Installation. `https://convoyplan.de/install.sh` und
`https://convoyplan.de/install.ps1` sind Weiterleitungen auf die Raw-Dateien aus
diesem Repo — eine Änderung hier ist nach dem Push auf `main` sofort wirksam,
ein Sync in ein anderes Repo ist nicht nötig.

Die Weiterleitungen selbst liegen im Website-Repo; ihre Einrichtung ist in
`.github/repo-setup-checklist.md` beschrieben und nur für Maintainer relevant.

## Deployment

Die Produktivinstanz läuft über Docker Compose (`docker-compose.yml`); der
Updater in `docker/updater/` rollt neue Images aus. Die Marketingsite wird aus
dem Website-Repo heraus als statisches Astro-Build deployt.

### API-Docs (Swagger/OpenAPI)

`/docs`, `/redoc` und `/openapi.json` sind in Produktion **standardmäßig deaktiviert**
(404). Eine extern erreichbare Instanz sollte sie **per API-Key** absichern statt
offen zu schalten:

- **`DOCS_API_KEY=<geheim>`** (empfohlen): Docs sind erreichbar, aber geschützt.
  Der Browser-Einstieg läuft über `/docs`, das ohne gültiges Cookie ein
  Anmeldeformular zeigt; nach erfolgreicher Eingabe merkt ein HttpOnly-Cookie
  die Freigabe. Programmatischer Zugriff via Header `X-API-Key: <geheim>`.
- **`ENABLE_DOCS=true`**: Docs offen erreichbar (ohne Key) — nur für Dev/intern.

Ein `?key=…` im Query-String wird nicht akzeptiert. Siehe `backend/app/api/docs_ui.py`
(Türsteher, Formular, Cookie) und `backend/app/config.py` (`docs_api_key`, `enable_docs`).

### MCP-Server (KI-Schnittstelle)

`/mcp` stellt Konvois, Fahrzeuge, Wegpunkte, Routen und Status als
Model-Context-Protocol-Server bereit. **Standardmäßig aus** — abgeschaltet wird
kein Endpunkt montiert, auch keine Well-Known-Dokumente.

Der Schalter sitzt im Admin-Portal unter **System → KI-Schnittstelle** und wirkt
ohne Neustart; `MCP_ENABLED` ist nur noch der Ausgangswert (Datenbank schlägt
Umgebung, `app/services/mcp_config.py`). Er *entfernt* die Routen, statt sie mit
404 zu bedecken — `app/mcp/mount.py` trennt dafür Bauen (`mount`) von Anhängen
(`aktivieren`/`deaktivieren`). `tests/test_mcp_toggle.py` prüft die Routentabelle
selbst, nicht nur den Statuscode; wer daran etwas ändert, sieht zuerst dort nach.

Die Instanz ist dabei Resource Server *und* OAuth-2.1-Authorization-Server; Zugriff
entsteht erst durch die Zustimmung eines angemeldeten Benutzers auf `/oauth/consent`
und gilt für genau eine Organisation, gedeckelt durch dessen Rolle. Kein Werkzeug
löscht Daten. Jeder schreibende Aufruf landet im Audit-Log mit Quelle `mcp`.

Bei den Scopes (`app/mcp/scopes.py`) sind zwei Listen auseinanderzuhalten, die einmal
eine waren: `SCOPES_SUPPORTED` weist aus, *was es gibt* (Protected Resource Metadata),
`REQUIRED_SCOPES` ist die Schwelle des Endpunkts. Steht die volle Liste versehentlich
an der zweiten Stelle, verlangt `RequireAuthMiddleware` von jedem Token sämtliche
Scopes und weist jede lesende Verbindung ab. Erteilt wird ausgeschrieben
(`effective()`), weil dieselbe Middleware ohne Hierarchie prüft — ein Token mit nur
`convoy:write` käme sonst nicht einmal an `/mcp` vorbei.

Welche Rechte eine Verbindung bekommt, entscheidet der Mensch auf dem
Zustimmungsbildschirm, nicht der Client: er kreuzt an, was seine Rolle hergibt. Das ist
kein Komfort, sondern Voraussetzung dafür, dass ChatGPT mehr als lesen kann — es fragt
einmalig beim Verbinden und fordert nie nach. Hintergrund und offene Punkte der
ChatGPT-Anbindung: `docs/superpowers/plans/2026-09-17-chatgpt-app.md`.

Für Clients mit Oberfläche (ChatGPT Apps SDK) liegen drei Ansichten in
`app/mcp/widgets.py` samt `widgets/`. Sie sind **Zugabe, nicht Voraussetzung**: kein
Werkzeug braucht sie, und ihr Inhalt ist eine leere Vorlage — die Daten kommen erst
aus dem Werkzeugaufruf. Vier Regeln hält `tests/test_mcp_widgets.py` fest: jeder
`_meta`-Verweis zeigt auf eine Resource, die es gibt, **nichts wird von außen
nachgeladen**, die Zeichenfunktion steht im HTML **vor** dem Aufruf durch den Rahmen,
und jedes Widget bringt mit, was es aufruft. Die letzten beiden sind nachgetragen, weil
beide Fälle eingetreten sind und beide dasselbe ergeben: eine leere Fläche, deren
Ausnahme der Rahmen abfängt. Was zwei Widgets brauchen, gehört deshalb in `rahmen.html`
und kommt über `w`. Damit die Ansichten Daten bekommen, geben alle Werkzeuge
`dict[str, Any]` zurück statt `dict` — nur so leitet das SDK ein Ausgabeschema ab und
liefert `structuredContent`.

Jedes Werkzeug trägt Verhaltenszusagen (`app/mcp/annotations.py`). Sie sind
unverbindlich — Rechte entscheiden Scopes und Rolle —, aber sie können still falsch
werden: Wer ein Werkzeug von lesend auf schreibend umbaut, muss die Annotation
mitziehen. `tests/test_mcp_widgets.py` hält `read_only_hint` gegen `WRITE_TOOLS` und
verbietet `destructive_hint` an jedem Werkzeug.

Der Aussteller (`oauth_tokens.issuer_url()`) ist **eine** Zeichenkette, normalisiert über
`AnyHttpUrl` — dieselbe, die Pydantic ins Metadatendokument schreibt. Wer sie dort
„vereinfacht", baut die Lücke wieder ein, an der ChatGPT einmal abgebrochen ist: RFC 9207
verlangt den `iss`-Parameter zeichengenau gleich dem Aussteller aus der Metadata, und ein
Test, der dabei `rstrip("/")` benutzt, prüft genau das Falsche.

Der CIMD-Schalter sitzt wie der Hauptschalter im Portal (`mcp_config.is_cimd_allowed`,
Datenbank schlägt Umgebung). Die AS-Metadata wird deshalb je Anfrage fertiggestellt und
nicht beim Start — stünde die Ankündigung im vorgebauten Dokument, bliebe sie bis zum
nächsten Neustart falsch.

Code in `backend/app/mcp/` (Werkzeuge, Scopes, Montage), `backend/app/services/
oauth_provider.py` und `oauth_tokens.py`. Verwaltung im Admin-Portal unter **MCP**.
Anwenderdoku: `wiki/MCP-Server.md`.

Die ASGI-Verdrahtung in `app/mcp/mount.py` hängt an internen Details des SDK —
`mcp` ist deshalb exakt gepinnt, und `tests/test_mcp_auth.py` prüft das beobachtbare
Verhalten. Bei einem SDK-Upgrade zuerst dort nachsehen.

### Auskunft für Agenten (llms.txt, Well-Known, Markdown)

Jede Instanz liefert unter ihrer eigenen Domain aus, was sie ist und wie man sie
programmatisch anspricht: `/llms.txt`, `/agents.md`, `/auth.md`, `/api.md`,
`/openapi.json`, `/sitemap.xml`, `/robots.txt`, die Well-Known-Dokumente
(`agent-card.json`, `agent-skills/index.json`, `ard.json`, `mcp/server-card.json`,
`api-catalog`), `/ask` (NLWeb) und die Seiten `/about`, `/pricing`, `/developers`,
`/docs`, `/contact`, `/privacy`, `/terms`.

Dazu `/.well-known/openai-apps-challenge`, sobald `OPENAI_APPS_CHALLENGE` gesetzt ist —
der Nachweis der Domain für eine ChatGPT-App-Einreichung. Ohne Eintrag gibt es den Pfad
nicht; Hintergrund in `docs/superpowers/plans/2026-09-17-chatgpt-app-einreichung.md`.

Alles davon **liegt im Frontend**, nicht im Backend: Caddy reicht nur `/api/*`, `/mcp`,
`/.well-known/oauth-*` und die OAuth-Endpunkte ans Backend durch, der Rest geht ans
Frontend. Verteilt wird in `frontend/src/lib/server/agent/dispatch.ts`, aufgerufen aus
`hooks.server.ts` — eine Tabelle statt je einer SvelteKit-Route, weil der
Dateisystem-Router ein Verzeichnis mit führendem Punkt (`.well-known`) übergeht.

Die Texte stehen in `lib/server/agent/documents.ts`, die Produktfakten in
`lib/agent/facts.ts`, der Seitenkatalog in `lib/agent/pages.ts`. **HTML und Markdown
entstehen aus derselben Quelle** (`render.ts` rendert dasselbe Dokument, das unter
`/<seite>.md` ausgeliefert wird) — wer eine Seite ändert, ändert beide Fassungen.

Die Startseite ist die Ausnahme von `render.ts`: sie trägt die Anmeldekarte und bleibt
deshalb eine Svelte-Seite (`routes/+page.svelte`). Deckungsgleich mit `/index.md` bleibt
sie über die Fakten statt über den Renderer — Titel aus `PAGES`, Untertitel und
Fließtext aus `PRODUCT`, Kacheln aus `FEATURES`. Dieselbe `FEATURES`-Liste füllt die
`featureList` im JSON-LD und die Aufzählung in `indexMd()`; Produktprosa gehört deshalb
nach `facts.ts` und nicht ins Markup.

Zwei Regeln, die den Aufwand erklären:

- **Nichts ankündigen, was es auf dieser Instanz nicht gibt.** Die Dokumente werden je
  Anfrage aus `GET /api/status/capabilities` gebaut (Domain, MCP an/aus, Demo an/aus).
  Ein `server-card.json`, das auf einen abgeschalteten `/mcp` zeigt, wäre schlechter als
  keines.
- **Nicht nach User-Agent unterscheiden.** Markdown gibt es über `Accept: text/markdown`,
  über `.md` und über `?mode=agent` — nicht, weil ein Crawler sich als Crawler zu
  erkennen gibt. Das wäre Cloaking.

Abschaltbar über `AGENT_DISCOVERY=false` (Standard an); dann existieren diese Pfade
nicht. Anwenderdoku: `wiki/Agenten-Auskunft.md`.

`/openapi.json` ist bewusst **nicht** die vollständige Beschreibung — die bleibt hinter
`DOCS_API_KEY`. Das Frontend reicht `/api/public/openapi.json` durch; das Backend baut
dort eine kuratierte Teilmenge aus der laufenden App
(`backend/app/api/routes/public_meta.py`). Die Liste der öffentlichen Operationen steht
ausdrücklich in `PUBLIC_OPERATIONS`, mit **eigenen** Beschreibungen statt der Docstrings:
Docstrings erklären hier Entscheidungen, und die gehören nicht in ein offenes Dokument.
`tests/test_public_openapi.py` prüft die Liste in beide Richtungen — jeder Eintrag
existiert, und keiner hängt an einem Guard. Wer dort etwas ändert, sieht zuerst in diesem
Test nach.

## Test-Konventionen

Was in `.github/workflows/ci.yml` blockierend läuft, ist die verbindliche Liste:

- **Backend** — `ruff check app/` und `pytest tests/` (`backend/`). Tests sind
  `async` (`asyncio_mode = "auto"`), sprechen die App über
  `AsyncClient(transport=ASGITransport(app=app))` an und brauchen eine
  PostGIS-Datenbank (`DATABASE_URL`). Autouse-Fixtures in `tests/conftest.py`
  schalten Rate-Limiting, HIBP-Abfrage und Update-Check ab; ein Test, der genau
  das prüft, aktiviert es selbst wieder.
- **Frontend** — `npm run check` (svelte-check) in `frontend/`.
- **Shell** — die Suiten unter `docker/updater/tests/` und für den
  GraphHopper-Entrypoint; sie tragen den Regionswechsel und laufen im Job
  `Shell – Updater und Entrypoint`.
- **Container** — Trivy scannt alle fünf Images (`backend`, `frontend`,
  `graphhopper`, `updater`, `osmium`) auf HIGH/CRITICAL mit verfügbarem Fix.
  Ausnahmen gehören mit Begründung in `.trivyignore`.

Neue Tests liegen neben den bestehenden in `backend/tests/` und werden nach dem
geprüften Verhalten benannt (`test_<thema>.py`), nicht nach der Implementierung.
