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

### Images werden nur gebaut, wenn es einen Grund gibt

`graphhopper`, `updater` und `osmium` hängen nicht am Anwendungscode. Gebaut
wurden sie trotzdem bei jedem Lauf — und jeder Bau erzeugt einen neuen Digest,
weil `metadata-action` Commit-SHA und Zeitstempel als Label in die
Image-Konfiguration schreibt und die zum Digest gehört. Der Updater vergleicht
Image-IDs, sieht eine neue und tauscht den Container: bei GraphHopper mit
minutenlangem Routing-Ausfall für das erneute Laden des Graphen, im
Nightly-Kanal mehrmals täglich, ohne dass sich ein Byte geändert hätte.

`.github/actions/build-or-reuse/` entscheidet deshalb vor jedem dieser drei
Bauten. Gebaut wird bei geändertem Quelltext (Tree-Hash des Verzeichnisses,
liegt als `de.convoyplan.source-tree` im Image), bei bewegtem Base-Image
(Digest der letzten `FROM`-Zeile, `de.convoyplan.base-digest`) oder wenn das
veröffentlichte Image älter als `max-age-days` ist — das Auffangnetz für
Paketupdates, die den Base-Digest nicht bewegen. Sonst bleibt der bewegliche
Tag (`latest`/`beta`/`nightly`) stehen, wo er steht, und genau das ist der
Punkt: nur er wird auf den Installationen gezogen.

Zwei Folgen, die man kennen muss. Ein weiterverwendetes Image bekommt in einem
Release **keine** Versionstags — es zieht sie niemand, `_apply_channel_images`
in `update-images.sh` schreibt jede Angabe auf den Kanaltag um. Und es wird
nicht erneut signiert, weil `cosign` den Digest signiert und der unverändert
ist. Die Entscheidung selbst steht in `decide.sh`, getrennt von der
Registry-Abfrage, und wird von `tests/test_image_wiederverwendung.sh` ohne
Docker und ohne Registry geprüft.

### Der Routing-Graph und der Deploy

Zwei Dateien entscheiden hier, und man muss sie auseinanderhalten.
`.graph_fingerprint` (Region + Encoded Values) schreibt `graphhopper/
entrypoint.sh` **vor** dem Import — er sagt, *wofür* ein Graph gebaut wurde, und
belegt **nicht**, dass er fertig ist. `edges` legt GraphHopper erst bei einem
vollständigen Graphen an; das ist der Vollständigkeitsbeleg, und alle drei
Stellen benutzen inzwischen ihn.

Am 2026-09-19 fehlte diese Unterscheidung und das Routing war weg: Ein
Auto-Deploy (nightly, mehrmals täglich) traf einen laufenden Import und ließ
einen Torso zurück — Bruchstücke plus den `location_index` eines anderen
Graphen, dazu einen passenden Fingerprint. Der Entrypoint sah „Fingerprint
stimmt", ließ alles liegen, GraphHopper importierte 13 Minuten neu, las den
fremden Index und starb an `location index was opened with incorrect graph`.
`restart: unless-stopped` fing von vorn an.

Drei Stellen, jede mit eigenem Test:

- **`graphhopper/entrypoint.sh`** wirft ein Verzeichnis ohne `edges` weg und baut
  neu (`tests/test_entrypoint_graph_zustand.sh`). Der Wipe ist weiter
  `rm -rf "$GRAPH_DIR"/*` und fasst damit Punktdateien **nicht** an — auf
  `.staging`/`.old` verlässt sich der Regionswechsel; wer hier auf `find -delete`
  oder `dotglob` umstellt, löscht einem laufenden Wechsel den halb gebauten
  Graphen.
- **`docker/updater/graphhopper-deploy.sh`** nimmt den Dienst aus dem Deploy,
  solange er baut, und zieht ihn danach nach. Von **beiden** Updater-Varianten
  gesourct — dieselbe Begründung wie bei `region-hook.sh`. Gedeckelt durch
  `GH_IMPORT_GRACE` (4 h), sonst schnitte ein Container, der aus einem anderen
  Grund nie fertig wird, den Dienst dauerhaft von Updates ab.
  `tests/test_graphhopper_import_deploy.sh` prüft die Entscheidung ohne Docker
  und die Verdrahtung in `update-images.sh` mit.
- **`switch-region.sh`**, Notbremse in `_on_exit`: startet GraphHopper nur gegen
  ein Verzeichnis mit Fingerprint **und** `edges` (`test_switch_region.sh`,
  Fall 12b).

### Speicher: Import im Heap, Betrieb per MMAP

`graphhopper/entrypoint.sh` startet in **zwei Phasen**, wenn `GH_COMMAND=server`
und kein `edges` da ist: erst `import` mit `RAM_STORE` und nur `JAVA_OPTS`, dann
`server` mit `GH_DATAACCESS` (Standard `MMAP`) und zusätzlich
`GH_SERVER_JAVA_OPTS`. `-Xmx` in `JAVA_OPTS` bemisst also den **Import** — darauf
beziehen sich Installer, Wiki und der Regionswechsel (`region.py` erzeugt es aus
der RAM-Schätzung) —, im Betrieb liegt der Graph im Seitencache und die JVM
bleibt weit darunter. Das Dateiformat ist bei beiden Zugriffsarten dasselbe.
`GH_COMMAND=import` (Regionswechsel) bleibt einphasig mit `RAM_STORE`. Wer die
Server-Phase anders konfiguriert, setzt `GH_SERVER_JAVA_OPTS` komplett, nicht
ergänzend; die Vorgabe (Heap im Leerlauf zurückgeben, bei OOM beenden) steht nur
im Entrypoint.

### Die Wegpunktreihenfolge gehört dem Menschen

`order_index` ist die Wahrheit, und `calculate_route` leitet ihn **nicht** aus der
fertigen Route ab. Einmal tat sie es, und dabei schloss sich ein Kreis: die Punkte
gingen nach ihrer Lage entlang der *alten* Route in die Anfrage, und danach wurde
`order_index` aus der *neuen* zurückgeschrieben. Ein Umsortieren von Hand ging
zweimal verloren — es kam nie in die Anfrage hinein und wurde nach der Antwort
überschrieben; die Route blieb, wie sie war, die Liste sprang zurück.

Die Ausnahme sind die automatisch vorgeschlagenen Halte: das Frontend hängt
Technische Halte und Tankstopps ans **Ende** der Liste, obwohl sie in der Mitte
liegen, und ohne Einordnen führe der Konvoi an ihnen vorbei und wieder zurück
(der gemeldete Umweg von mehreren hundert Kilometern). Eingeordnet werden sie
anhand ihrer Projektion auf die **vorherige** Route — und nur einmal: danach
steht so ein Halt mitten in der Liste und ist ein Wegpunkt wie jeder andere.

Wer eingeordnet wird, sagt die Spalte `pending_placement` und **nicht** die
Position in der Liste (Migration `0046`). Zuerst wurde geraten — „der
zusammenhängende Lauf von `technical_stop` am Listenende" —, und das traf den
Normalfall, verschob aber auch einen Technischen Halt, den jemand bewusst als
*letzten* Wegpunkt gesetzt hatte. Die Marke kommt von der Herkunft: gesetzt beim
Anlegen eines Vorschlags (nur die beiden Stellen im Frontend setzen sie),
gelöscht, sobald der Wegpunkt einen Platz hat — durch die Routenberechnung,
durch Ziehen in der Liste oder durch ein ausdrücklich gesetztes `order_index`.
Dass sie **verfällt**, ist kein Detail: eine Marke, die bliebe, ließe denselben
Halt bei jedem Lauf erneut wandern, auch dorthin, wo ihn gerade jemand weggezogen
hat.

Die Entscheidung steht in `app/services/waypoint_order.py`, getrennt von Datenbank
und Routing-Dienst, und wird von `tests/test_wegpunkt_reihenfolge.py` ohne beides
geprüft — samt den drei Stellen, an denen die Marke verfällt. Der Backfill der
Migration steht aus demselben Grund als Funktion daneben und nicht in einer
`WHERE`-Bedingung (`tests/test_wegpunkt_platzierung_migration.py`, wie bei
`0039`): er entscheidet über Bestandsdaten.

Die Kilometrierung für den Zeitplan kommt weiter aus der Projektion, sortiert aber
nichts mehr um. Sie wird monoton gehalten (`cumulative_along_route`): wo die Route
ein Stück doppelt befährt, trifft die Suche nach dem nächsten Streckenpunkt sonst
die falsche Vorbeifahrt, und aus der negativen Teilstrecke wird eine rückwärts
laufende Ankunftszeit.

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

#### Die Richtlinie je Organisation

Über dem Instanzschalter liegt eine zweite Ebene: **jede Organisation nimmt erst
teil, wenn ihr Admin sie einschaltet** (`services/org_mcp_policy.py`, Tabelle
`organization_mcp_policies`, Portal: Org-Admin → **KI-Zugriff**). Keine Zeile heißt
aus — der Standard steht damit an *einer* Stelle (`org_mcp_policy.AUS`) und nicht in
einem `server_default`. Migration `0042` schaltet nur die Organisationen ein, an denen
schon eine aktive Verbindung hängt, mit genau deren Scopes; alles andere bleibt aus.

Zwei Achsen, die als **Und** wirken: **Bereiche** (`app/mcp/areas.py` — Konvois,
Fahrzeuge, Wegpunkte, Routen, Status) sagen *worauf*, die Scopes sagen *wie weit*.
`convoy:read` ist dabei keine Wahl, sondern Voraussetzung: ohne ihn käme ein Token
nicht an `AuthSettings.required_scopes` vorbei, also ergänzt `setzen()` ihn bei jeder
eingeschalteten Richtlinie.

Die Freigabe kennt **keine Scope-Hierarchie** — das ist der Unterschied zu
`mcp/scopes.py`. Dort sagt die Hierarchie, was ein erteiltes *Recht* einschließt; hier
geht es darum, was eine Organisation *freigeben will*, und „planen ja, Positionen
nein" muss ausdrückbar bleiben. Aus demselben Grund greift `policy.zuschneiden()` im
Consent **nach** `effective()`: davor brächte `convoy:write` ein `fleet:status` mit.

Im Adminportal listet der Reiter **MCP** alle Organisationen mit ihrem Zustand
(`GET /api/admin/mcp/organizations`, LEFT JOIN auf die Richtlinien — ein Join über
`organization_mcp_policies` ließe die Mehrheit weg, denn keine Zeile ist der Normalfall).
Die Liste ist **rein lesend**: wer die Instanz betreibt, sieht *dass* eine Organisation
teilnimmt, entscheidet aber nicht über ihre Einsatzdaten. Genau dafür gibt es die zweite
Ebene.

Durchgesetzt wird an vier Stellen, und die maßgebliche ist die dritte:
Zustimmungsbildschirm, `tools/list` (`OrgPolicyToolsMiddleware`), **jeder Aufruf**
(`McpContext.require_werkzeug`, aus `mcp_context(werkzeug=…)` heraus) und die
Resources/Abos (`require_bereich`). Die Prüfung sitzt zentral in `mcp_context`, weil 23
Prüfungen in 23 Werkzeugen genau eine sind, die jemand beim 24. vergisst; der Preis ist,
dass jedes Werkzeug seinen Namen durchreicht, und genau das hält
`tests/test_org_mcp_policy.py` per AST gegen den Quelltext — zusammen mit der Regel,
dass jedes Werkzeug einen Bereich hat oder in `GRUNDWERKZEUGE` steht.

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

### Meldungen aus der Anwendung (Fehler und Wünsche)

Der Melde-Knopf sitzt in der Planungsansicht (Seitenleiste, neben *Hilfe*) und
im Org-Admin. Der Dialog hängt **einmal** im Org-Layout
(`routes/o/[slug]/+layout.svelte`) und wird über `stores/feedback.ts` geöffnet —
ein Store und keine Prop-Kette, weil Auslöser und Dialog nicht beieinander
stehen.

Das Bildschirmfoto entsteht im Browser (`lib/screenshot.ts`) über
`getDisplayMedia`, Einfügen oder Dateiauswahl und geht als **Data-URL im
JSON-Körper** mit, nicht als zweiter Multipart-Aufruf: sonst stünde die Meldung
zwischen beiden Aufrufen ohne ihr Bild da, und zwar genau dann, wenn das Netz
wackelt. Kein `html2canvas` — ein Nachzeichner malt das DOM nach, und bei Karte,
Schriften und überlagerten Ebenen kommt dabei etwas anderes heraus als auf dem
Schirm stand.

Erkannt wird das Format an den **Magic Bytes** (`services/feedback.py`), nicht
am angegebenen Typ, und SVG ist ausgeschlossen — ein Bildschirmfoto ist nie
eines, und es ist das einzige Bildformat, das Skript trägt. Abgelegt wird unter
`/uploads/feedback/`, ausgeliefert nur über
`GET /api/admin/feedback/{id}/screenshot`: ein ratbarer Pfad unter `/uploads/`
wäre für die ganze Instanz lesbar, und auf einem Bild aus dem Einsatz stehen
Einsatzdaten.

Melden und Sichten liegen in **einer** Datei (`api/routes/feedback.py`, zwei
Router). Die Herkunft einer Meldung kommt aus der Sitzung, nie aus dem Körper;
`melder()` probiert dafür erst `get_org_context` und fällt auf
`get_current_person` zurück, weil der Dialog auch außerhalb einer Organisation
aufgeht. `/api/feedback` steht in `_EXEMPT_PREFIXES` des Lizenzwächters — der
Demo-Modus ist der Zustand, in dem am ehesten jemand melden will.

Zwei Einschätzungen, die getrennt bleiben: `severity` gehört dem Melder und wird
nicht angefasst, `priority` dem Betreiber. In einem Feld verlöre man die erste
beim ersten Triage-Klick, und genau die sagt, wie schlimm es sich *im Einsatz*
angefühlt hat.

`frontend/e2e/feedback-melden.spec.ts` hält die Zusage fest, die man der
Oberfläche nicht ansieht: der abgeschickte Aufruf enthält die Felder, die der
Ausklapper „Was mitgeschickt wird" nennt — und kein Feld mehr. Anwenderdoku:
`wiki/Meldungen.md`.

## Test-Konventionen

Was in `.github/workflows/ci.yml` blockierend läuft, ist die verbindliche Liste:

- **Backend** — `ruff check app/` und `pytest tests/` (`backend/`). Tests sind
  `async` (`asyncio_mode = "auto"`), sprechen die App über
  `AsyncClient(transport=ASGITransport(app=app))` an und brauchen eine
  PostGIS-Datenbank (`DATABASE_URL`). Autouse-Fixtures in `tests/conftest.py`
  schalten Rate-Limiting, HIBP-Abfrage und Update-Check ab; ein Test, der genau
  das prüft, aktiviert es selbst wieder.
- **Frontend** — `npm run check` (svelte-check) und `npm run test:e2e`
  (Playwright, Job `Frontend – E2E (Playwright)`) in `frontend/`. Die Tests
  liegen in `frontend/e2e/` und starten sich ihre Server selbst: den **gebauten**
  Stand der App (`build` + `preview`, nicht `vite dev` — der übersetzt beim ersten
  Zugriff und lässt parallele Tests in den Zeitablauf laufen) und eine schlanke
  Komponentenhülle (`e2e/harness/`) für alles, was in der App hinter der Anmeldung
  sitzt. Ein Backend braucht es nicht: `mockTrack` beantwortet die Tracking-API,
  die Hülle stubbt `$lib/api`, und `blockExternal` bricht alles ab, was nicht von
  der Testinstanz kommt — ohne das hängen die Tests ohne Netz an den Kartenkacheln.
  Die Hülle ist **kein** Teil des Produktionsbaus; eine Testroute unter `src/routes/`
  wäre eine, die mit ausgeliefert wird. Ihre Vite-Konfiguration spiegelt den
  `<style>`-Block aus `src/app.html` in die Seite und setzt `__APP_VERSION__` —
  ein Test, der Geometrie misst, misst sonst gegen Farben und Schriftgrößen, die
  es in der App gar nicht gibt. Der Job läuft im **Playwright-Image**
  (`mcr.microsoft.com/playwright:v1.63.0-noble`), weil `npx playwright install` auf
  dem Runner nach dem Download beim Entpacken stehenblieb — ohne Ausgabe, ohne
  Abbruch. Dessen Marke muss zur Fassung von `@playwright/test` passen: Wer die
  Abhängigkeit hebt, hebt die Marke in `ci.yml` mit.

  **Lokal** braucht es den Browser einmalig: `npx playwright install chromium`
  in `frontend/`. Bleibt der Befehl nach dem Download ohne Ausgabe stehen, liegt
  es an der Node-Fassung — dann entweder eine ältere nehmen oder die Suite im
  selben Image fahren wie die CI:
  `docker run --rm -v "$PWD":/w -w /w/frontend mcr.microsoft.com/playwright:v1.63.0-noble
  sh -c 'npm ci && npm run test:e2e'`.
- **Shell** — die Suiten unter `docker/updater/tests/` und für den
  GraphHopper-Entrypoint; sie tragen den Regionswechsel und laufen im Job
  `Shell – Updater und Entrypoint`. Derselbe Job fährt auch die beiden Suiten
  unter `.github/`, die **Shell in einer YAML-Datei** prüfen: die Entscheidung
  in `.github/actions/build-or-reuse/` und den Nachweisschritt des Region-Jobs
  (`.github/workflows/tests/`). Beide **schneiden ihr Original aus der
  YAML-Datei heraus**, statt es nachzubauen — ein Nachbau prüft die Kopie. Wer
  dort einen weiteren Test anlegt, braucht nichts zu verdrahten: der Job
  sammelt `test_*.sh` aus allen vier Verzeichnissen ein.
- **Container** — Trivy scannt alle fünf Images (`backend`, `frontend`,
  `graphhopper`, `updater`, `osmium`) auf HIGH/CRITICAL mit verfügbarem Fix.
  Ausnahmen gehören mit Begründung in `.trivyignore`.

Neue Tests liegen neben den bestehenden in `backend/tests/` und werden nach dem
geprüften Verhalten benannt (`test_<thema>.py`), nicht nach der Implementierung.
Dasselbe gilt vorne: Was in `frontend/e2e/` geprüft wird, ist eine Zusage an den
Anwender — dass der QR-Code die Adresse und **kein** Sitzungstoken trägt, dass
weder Passwort noch Seiteninhalt auf dem Ausdruck landen, dass ein widerrufener
Link keinen QR-Knopf hat. Solche Zusagen sieht man einem Bildschirmfoto nicht an,
und still falsch werden sie trotzdem.
