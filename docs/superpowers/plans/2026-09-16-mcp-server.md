# MCP-Server für ConvoyPlan — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine ConvoyPlan-Instanz stellt unter `https://<domain>/mcp` einen Remote-MCP-Server bereit, den MCP-Clients (Claude Desktop, Claude Code, claude.ai, ChatGPT-Connectoren) nach einem OAuth-2.1-Login der jeweiligen Organisation anbinden können. Der Server liest Konvois, Fahrzeuge, Wegpunkte, Routen und Positionen und legt sie auch an bzw. ändert sie — **löscht aber nichts**.

**Architecture:** Der MCP-Server läuft **in-process in der bestehenden FastAPI-App**, nicht als eigener Container. Die Tool-Schicht ruft die vorhandenen `app/services/*`-Funktionen direkt auf, nicht die eigene REST-API über HTTP. ConvoyPlan ist gleichzeitig **Resource Server und Authorization Server** — eine On-Prem-Installation hat keinen externen IdP, und Benutzer, Passwörter, MFA, Organisationen und die Rollenhierarchie liegen bereits in der eigenen Datenbank. Das Python-SDK (`mcp`) liefert Transport, `/authorize`, `/token`, `/register`, `/revoke` und beide Metadaten-Dokumente fertig mit; zu implementieren ist der `OAuthAuthorizationServerProvider` gegen Postgres plus eine Consent-Seite im Frontend.

**Tech Stack:** `mcp==2.2.0` (Python-SDK, `MCPServer` + Streamable HTTP), FastAPI, SQLAlchemy 2 async, Alembic, PyJWT, Svelte 5 mit Runes (Consent-Seite, Admin-Reiter), pytest, Caddy.

**Spec-Stand:** MCP-Revision **2026-07-28**. Wichtig, weil sich die Autorisierung gegenüber älteren Revisionen verschoben hat — siehe „Was sich gegenüber der Erwartung geändert hat".

---

## Was sich gegenüber der Erwartung geändert hat

Drei Punkte, die den Zuschnitt beeinflussen und vor dem ersten Task bekannt sein müssen:

1. **Dynamic Client Registration (RFC 7591) ist in der aktuellen Spec `MAY` und ausdrücklich als deprecated markiert.** Vorgesehener Weg sind **OAuth Client ID Metadata Documents** (`draft-ietf-oauth-client-id-metadata-document-00`, `SHOULD`). DCR bleibt „für Rückwärtskompatibilität". Das Python-SDK implementiert serverseitig **nur DCR**; CIMD gibt es dort bisher ausschließlich auf der Client-Seite. CIMD selbst zu bauen heißt: eine per `client_id` übergebene HTTPS-URL abrufen — also eine SSRF-Fläche, die ein BOS-Produkt sauber absichern muss. **Empfehlung: Phase 1 mit DCR ausliefern, CIMD als Phase 4.** Alle heute relevanten Clients kommen mit DCR klar.

2. **`MUST` für den Resource Server ist RFC 9728 (Protected Resource Metadata)**, nicht DCR. Das liefert das SDK.

3. **RFC 9207 (`iss` in der Authorization-Response) ist `SHOULD` und wird das SDK-seitig nicht abgedeckt** — `build_metadata()` setzt `authorization_response_iss_parameter_supported` nicht, und der Authorization-Handler gibt kein `iss` aus. Eine künftige Spec-Revision hebt das auf `MUST`. Da wir die Redirect-URL in der Consent-Strecke ohnehin selbst bauen, ist es hier billig — deshalb in Phase 1 statt später.

**Aufwand, ehrlich:** Der OAuth-Authorization-Server ist der Löwenanteil, nicht die Tools. Grobschätzung **10–14 Personentage** für Phase 0–3. Zum Vergleich: dieselben Tools hinter dem bereits vorhandenen `X-API-Key` wären ~2–3 Tage gewesen. Der Aufpreis kauft ein: Anbindung per Klick aus claude.ai statt Key-Copy-Paste, benutzergebundene Tokens statt eines Org-Keys, Widerruf pro Verbindung und ein Consent-Screen, der festhält, wer wem was erlaubt hat.

---

## Global Constraints

- **Standardmäßig aus.** `MCP_ENABLED=false` ist der Auslieferungszustand. Eine Bestandsinstallation, die nichts konfiguriert, verhält sich bitgleich zu heute — kein offener Endpunkt, keine neuen Well-Known-Routen, kein Caddy-Verhalten, das sich ändert.
- **Kein Löschen.** Es wird **kein** Tool implementiert, das einen `DELETE`-Pfad oder eine löschende Service-Funktion aufruft. Kein `convoy:delete`-Scope existiert. Ein Test prüft, dass die registrierte Toolliste keinen Namen mit `delete`/`remove` enthält.
- **MCP-Tokens sind keine ConvoyPlan-Tokens.** Sie tragen `typ="mcp"`. `app/api/deps.py::_decode_token` akzeptiert nur `typ in ("access", "stream")` — damit ist ein MCP-Token an der REST-API strukturell wertlos. Umgekehrt akzeptiert der `TokenVerifier` nur `typ="mcp"`. Beide Richtungen bekommen einen Test.
- **Audience-Bindung ist Pflicht.** Jedes Access-Token trägt `aud` = kanonische Resource-URI (`https://<domain>/mcp`). `AuthSettings.validate_token_resource=True`. Ein Token für Instanz A darf an Instanz B nicht funktionieren.
- **Die Rollenhierarchie bleibt die einzige Wahrheit.** Scopes sind eine Projektion von `ROLE_ORDER` aus `app/api/guards.py`, keine zweite Berechtigungslogik. Ein Token kann nie mehr dürfen als die Mitgliedschaft des Benutzers in der gewählten Organisation.
- **Kein Zugriff auf Instanz-Ebene.** Keine Tools für `/api/admin/*`, Systemmetriken, Lizenz, Benutzerverwaltung, Regionswechsel, Branding oder Leitstellen-Konfiguration. Der MCP-Server ist eine Fachdaten-Schnittstelle, kein Admin-Kanal.
- **Mandantentrennung.** Ein Token ist an genau **eine** Organisation gebunden (zur Consent-Zeit gewählt). Es gibt kein „alle meine Orgs"-Token.
- Kommentare, Docstrings, Tool-Beschreibungen und Fehlermeldungen auf **Deutsch** — die Tool-Beschreibungen sieht das Modell, und die Domäne (Marschbefehl, Leitstelle, Konvoi) ist deutsch.

---

## File Structure

**Neu:**

| Datei | Verantwortung |
|---|---|
| `backend/app/mcp/__init__.py` | `build_mcp_server()` — baut die `MCPServer`-Instanz, registriert Tools |
| `backend/app/mcp/mount.py` | ASGI-Verdrahtung: Transport unter `/mcp`, OAuth- und Well-Known-Routen an der Wurzel, Session-Manager in den Lifespan |
| `backend/app/mcp/scopes.py` | Scope-Definitionen und die Abbildung Scope ↔ Rolle (`ROLE_ORDER`) |
| `backend/app/mcp/context.py` | Aus dem `AccessToken` die `OrgCtx` (User, Organization, Rolle) auflösen — das MCP-Pendant zu `get_org_context` |
| `backend/app/mcp/tools_read.py` | Lesende Tools |
| `backend/app/mcp/tools_write.py` | Schreibende Tools (ohne Löschen) |
| `backend/app/mcp/resources.py` | MCP-Resources (Marschbefehl-PDF, GPX, GeoJSON) |
| `backend/app/mcp/prompts.py` | Ein bis zwei Prompt-Vorlagen („Marschbefehl erstellen") |
| `backend/app/services/oauth_provider.py` | `OAuthAuthorizationServerProvider`-Implementierung gegen Postgres |
| `backend/app/services/oauth_tokens.py` | Minten/Prüfen der `typ="mcp"`-JWTs, Refresh-Token-Rotation |
| `backend/app/models/oauth_client.py` | DCR-Registrierungen |
| `backend/app/models/oauth_code.py` | Kurzlebige Authorization Codes (PKCE, `resource`, `subject`, `org_id`) |
| `backend/app/models/oauth_refresh_token.py` | Refresh-Token-Familien, Rotation, Widerruf |
| `backend/app/api/routes/mcp_consent.py` | `GET /api/mcp/consent/{rid}` (Anfragedetails), `POST /api/mcp/consent/{rid}` (Zustimmung → Redirect-URL) |
| `backend/alembic/versions/<rev>_mcp_oauth.py` | Drei neue Tabellen |
| `backend/tests/test_mcp_auth.py` | Discovery, 401/403-Verhalten, PKCE, Code-Replay, Audience, Token-Trennung |
| `backend/tests/test_mcp_tools.py` | Tools gegen die In-Memory-Session des SDK |
| `backend/tests/test_mcp_scopes.py` | Scope↔Rolle, Insufficient-Scope, Cross-Org-Isolation, keine Delete-Tools |
| `frontend/src/routes/oauth/consent/+page.svelte` | Consent-Screen (Login/MFA/Org-Wahl wiederverwendet) |
| `frontend/src/lib/components/admin/McpConnections.svelte` | Admin: registrierte Clients und aktive Verbindungen, Widerruf |
| `wiki/MCP-Server.md` | Benutzerdoku: Verbinden, Scopes, Widerruf, Grenzen |

**Geändert:**

| Datei | Änderung |
|---|---|
| `backend/requirements.txt` | `mcp==2.2.0` |
| `backend/app/config.py` | `mcp_enabled`, `mcp_public_url`, `mcp_access_token_ttl`, `mcp_refresh_token_ttl`, `mcp_allow_dcr` |
| `backend/app/main.py` | Lifespan: `session_manager.run()`; Routen-Montage; CORS `expose_headers` |
| `backend/app/middleware/license_guard.py` | `/mcp` und `/.well-known/oauth-*` in `_EXEMPT_PREFIXES` |
| `backend/app/models/__init__.py` | Drei neue Modelle importieren |
| `backend/app/api/routes/admin.py` | Endpunkte: Clients/Verbindungen listen und widerrufen |
| `caddy/entrypoint.sh` | `handle /mcp` und `handle /.well-known/oauth-*` → Backend |
| `backend/app/services/caddy_config.py` | Dieselben Handles; **Reparaturpfad für persistierte Caddyfiles** |
| `frontend/src/routes/admin/+page.svelte` | Reiter „MCP" |
| `frontend/src/lib/api/index.ts` | Admin-Aufrufe für MCP-Verbindungen |
| `.env.example` | Die neuen `MCP_*`-Variablen dokumentieren |
| `CHANGELOG.md` | Eintrag unter Unreleased |

---

## Phase 0 — Spike

### Task 0.1: Montage-Form verifizieren

Der unsicherste Punkt des ganzen Plans, und er ist eine bekannte Stolperstelle des SDK (`python-sdk#1367`). `MCPServer.streamable_http_app()` gibt eine **Starlette-App** zurück, deren Routen so aussehen:

```
Route("/mcp",                                        RequireAuthMiddleware(transport))
Route("/.well-known/oauth-authorization-server",     Metadata)
Route("/.well-known/oauth-protected-resource/mcp",   ProtectedResourceMetadata)
Route("/authorize"), Route("/token"), Route("/register"), Route("/revoke")
```

Zwei Fallen:

- **`Route`, nicht `Mount`.** Ein `app.mount("/mcp", mcp_app)` ergäbe `/mcp/mcp`, und die Well-Known-Pfade landeten unter `/mcp/.well-known/…` — RFC 9728 verlangt sie an der **Wurzel**.
- **Lifespan.** Die zurückgegebene App trägt `lifespan=lambda app: session_manager.run()`. Eine gemountete Sub-App bekommt ihren Lifespan von Starlette **nicht** ausgeführt. Ohne das läuft die Session-Task-Group nie an, und jeder Request hängt.

**Empfohlene Form (C):** Nicht `streamable_http_app()` verwenden, sondern selbst verdrahten —
`create_auth_routes(...)` und `create_protected_resource_routes(...)` aus `mcp.server.auth.routes` als reguläre Routen an der FastAPI-Wurzel registrieren (das sind öffentliche Metadaten- und OAuth-Endpunkte, sie brauchen keine Bearer-Middleware), und **nur den Transport** als kleine Starlette-App mit `AuthenticationMiddleware(BearerAuthBackend(...))` + `AuthContextMiddleware` + `RequireAuthMiddleware` unter `/mcp` einhängen. `mcp.session_manager.run()` kommt in ConvoyPlans eigenen `_lifespan` in `main.py`.

**Fallback (B):** Die SDK-App als **letzte** Route mit `app.mount("/", mcp_app)` einhängen. Funktioniert, weil Starlette der Reihe nach matcht und alle `/api/*`-Routen vorher registriert sind — verschluckt aber alle unbekannten Pfade und ändert den 404-Körper des Backends.

- [ ] Prototyp beider Formen in `/tmp`, gegen `mcp==2.2.0`
- [ ] Prüfen: `GET /.well-known/oauth-protected-resource/mcp` → 200 **an der Wurzel**
- [ ] Prüfen: `POST /mcp` ohne Token → 401 mit `WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource/mcp"`
- [ ] Prüfen: `GET /api/version` verhält sich unverändert (keine Auth-Middleware auf ConvoyPlan-Routen)
- [ ] Prüfen: eine echte MCP-Session (initialize → tools/list) läuft durch, d. h. der Session-Manager wurde gestartet
- [ ] Entscheidung dokumentieren; der Rest des Plans baut darauf auf

**Acceptance:** Form C läuft, oder es ist schriftlich begründet, warum auf B ausgewichen wird.

### Task 0.2: Abhängigkeits-Fallout prüfen

`mcp==2.2.0` zieht `mcp-types`, `httpx2>=2.5.0`, `sse-starlette>=3.0.0`, `opentelemetry-api`, `jsonschema`, `pyjwt[crypto]`.

- [ ] `httpx2` ist ein **eigenes** Distributionspaket und kollidiert nicht mit dem gepinnten `httpx==0.28.1` — aber das Image trägt dann zwei HTTP-Stacks. Größenzuwachs messen und bewerten
- [ ] `starlette>=0.48.0` (ab Python 3.14) — das Repo pinnt `1.6.0`, passt
- [ ] `pydantic>=2.12.0` — Repo hat `2.13.5`, passt
- [ ] Trivy-Scan über das neue Image; `.trivyignore` nur falls unvermeidbar erweitern
- [ ] Alle transitiven Abhängigkeiten in `requirements.txt` pinnen, dem Stil der Datei folgend (Begründung als Kommentar, wo eine Version sicherheitsrelevant ist)

---

## Phase 1 — Autorisierung und lesende Tools

### Task 1.1: Datenmodell und Migration

Access-Tokens bleiben **zustandslose JWTs** (wie die bestehende Auth) und liegen in keiner Tabelle. Persistiert werden nur Clients, Codes und Refresh-Tokens.

- [ ] `oauth_clients`: `client_id` (PK), `client_secret_hash` (bcrypt, NULL für Public Clients), `redirect_uris` (JSON), `client_name`, `grant_types`, `token_endpoint_auth_method`, `scope`, `created_at`, `client_secret_expires_at`, `revoked`
- [ ] `oauth_codes`: `code_hash` (PK), `client_id`, `user_id`, `organization_id`, `scopes`, `code_challenge`, `redirect_uri`, `redirect_uri_provided_explicitly`, `resource`, `expires_at`, `consumed_at`
- [ ] `oauth_refresh_tokens`: `token_hash` (PK), `family_id`, `client_id`, `user_id`, `organization_id`, `scopes`, `resource`, `expires_at`, `revoked`, `rotated_from`, `created_at`, `last_used_at`
- [ ] Codes werden **gehasht** gespeichert, nie im Klartext — gleiche Begründung wie bei `ApiKey.key_hash`
- [ ] Alembic-Migration; Down-Pfad testen
- [ ] Aufräumjob für abgelaufene Codes und Refresh-Tokens in `app/jobs/` (die Retention-Mechanik existiert bereits — dort andocken)

**Acceptance:** `alembic upgrade head` und `downgrade -1` laufen gegen eine frische und eine bestehende DB durch.

### Task 1.2: Scopes definieren

- [ ] `convoy:read` → Mindestrolle `beobachter`
- [ ] `fleet:status` → Mindestrolle `fahrer` (Fahrzeugstatus und Positionen setzen)
- [ ] `convoy:write` → Mindestrolle `planer` (anlegen, ändern, Route berechnen)
- [ ] Hierarchie: `convoy:write` impliziert `fleet:status` impliziert `convoy:read` — die Spec verlangt ausdrücklich, dass der Server Scope-Hierarchien bei der Prüfung berücksichtigt
- [ ] **Kein** Scope für Löschen, Admin oder Instanz-Ebene
- [ ] `scopes_supported` in der Protected Resource Metadata = minimaler Satz für Grundfunktion (`convoy:read`), nicht die Gesamtmenge — so verlangt es die Scope-Minimierung der Spec
- [ ] Einheitentest: für jede Rolle die Menge der zulässigen Scopes

### Task 1.3: Token-Dienst

- [ ] `mint_access_token(user, org, scopes, resource)` → JWT mit `typ="mcp"`, `sub`, `aud`=Resource-URI, `org_id`, `scope` (Leerzeichen-getrennt), `tv` (`token_version`), `client_id`, kurzer `exp` (Default **15 min**)
- [ ] `mint_refresh_token(...)` → Zufallswert, nur Hash in die DB, Default-TTL **30 Tage**, **rotierend**: jeder Einlöseversuch gibt ein neues aus und invalidiert das alte
- [ ] **Wiederverwendungserkennung:** wird ein bereits rotiertes Refresh-Token noch einmal vorgelegt, die **gesamte Familie** widerrufen (Standard-Gegenmaßnahme gegen Token-Diebstahl)
- [ ] `TokenVerifier.verify_token`: `typ="mcp"` prüfen, Signatur, `exp`, `aud` gegen die eigene Resource-URI, `token_version` gegen den Benutzer, Benutzer aktiv, Mitgliedschaft in der Org **weiterhin** vorhanden und Rolle nicht unter den Scopes zurückgefallen
- [ ] Ein `token_version`-Bump (Passwortwechsel, „überall abmelden") entwertet auch MCP-Tokens — das ist gewollt und bekommt einen Test
- [ ] **Widerruf von Access-Tokens** ist mit zustandslosen JWTs nur über `token_version` möglich. Deshalb 15 Minuten TTL, und die Admin-Aktion „Verbindung trennen" widerruft die Refresh-Familie. Das verbleibende Fenster von ≤15 min wird in `wiki/MCP-Server.md` benannt statt versteckt

### Task 1.4: `OAuthAuthorizationServerProvider`

Zehn Methoden gegen die Tabellen aus 1.1.

- [ ] `register_client` — DCR. Nur wenn `MCP_ALLOW_DCR=true`. `redirect_uris` validieren: HTTPS, oder `http://127.0.0.1[:port]/…` bzw. `http://localhost…` für lokale Clients; **keine** offenen Redirects, kein Wildcard
- [ ] `get_client` — Lookup; widerrufene und abgelaufene Clients geben `None`
- [ ] `authorize` — **kein** Code hier. PKCE-Parameter, `redirect_uri`, `state`, `scopes` und `resource` in einem kurzlebigen Request-Datensatz ablegen und `https://<domain>/oauth/consent?rid=<opaque>` zurückgeben. `resource` gegen die eigene kanonische URI prüfen und bei Abweichung ablehnen
- [ ] `load_authorization_code` / `exchange_authorization_code` — PKCE `S256` verifizieren, `redirect_uri` exakt gegenprüfen, Einmalverwendung durchsetzen (`consumed_at`); ein zweiter Einlöseversuch widerruft zusätzlich die daraus entstandene Token-Familie
- [ ] `load_refresh_token` / `exchange_refresh_token` — Rotation und Wiederverwendungserkennung aus 1.3; angeforderte Scopes dürfen die ursprünglichen nie überschreiten
- [ ] `load_access_token` / `revoke_token` — `RevocationOptions(enabled=True)`
- [ ] `exchange_identity_assertion` — nicht unterstützt, `identity_assertion_enabled=False`
- [ ] Jede Methode bekommt einen Test, die Fehlerpfade zuerst

### Task 1.5: Consent-Strecke

Der Punkt, an dem das Ganze ein Produkt statt eines Protokolls wird.

- [ ] `GET /api/mcp/consent/{rid}` — liefert Client-Name, angeforderte Scopes (deutsch ausformuliert), die wählbaren Organisationen des angemeldeten Benutzers und die Ablaufzeit der Anfrage
- [ ] `POST /api/mcp/consent/{rid}` — verlangt eine **gültige ConvoyPlan-Sitzung** (regulärer Bearer-Token, also inklusive MFA), prüft die Mitgliedschaft in der gewählten Org, mintet den Code und gibt die vollständige Redirect-URL zurück
- [ ] Die Redirect-URL trägt `code`, `state` **und `iss`** (RFC 9207)
- [ ] `authorization_response_iss_parameter_supported: true` in der AS-Metadata — dafür den vom SDK gebauten `OAuthMetadata`-Datensatz nach `build_metadata()` ergänzen, bevor der Handler registriert wird
- [ ] Frontend `/oauth/consent`: nicht angemeldet → bestehende Login-Strecke mit `redirect`-Parameter; angemeldet → Zustimmungsdialog mit Org-Auswahl, „Zulassen" / „Ablehnen"
- [ ] **`client_name` stammt aus der DCR-Registrierung und ist damit vom Anfragenden frei wählbar.** Er wird escaped ausgegeben und sichtbar als *unbestätigt* gekennzeichnet; die `redirect_uri`-Domain wird daneben angezeigt, weil sie das Einzige ist, was tatsächlich überprüft wurde. Das ist die Gegenmaßnahme gegen den Confused-Deputy-Fall, den die Spec für dynamisch registrierte Clients ausdrücklich nennt
- [ ] „Ablehnen" → Redirect mit `error=access_denied` **und `iss`**
- [ ] Jede erteilte Zustimmung landet im `audit_log` (Benutzer, Org, Client, Scopes, IP)

### Task 1.6: Montage und Konfiguration

- [ ] `config.py`: `mcp_enabled` (Default `False`), `mcp_public_url` (Default aus `app_base_url` + `/mcp`), `mcp_access_token_ttl`, `mcp_refresh_token_ttl`, `mcp_allow_dcr`
- [ ] Bei `mcp_enabled=False` wird **nichts** montiert — keine Routen, keine Well-Known-Dokumente
- [ ] Montage nach der in 0.1 gewählten Form; Session-Manager in `_lifespan`
- [ ] `license_guard.py`: `/mcp` und `/.well-known/oauth-` in `_EXEMPT_PREFIXES`. **Begründung:** MCP ist reines POST; die Middleware würde ohne Lizenz auch das Lesen blockieren, während die REST-API im Demo-Modus lesend offen bleibt. Die Lizenzprüfung wandert stattdessen in die Tool-Schicht (Task 2.4), womit dieselbe Semantik gilt: lesen ja, schreiben nein
- [ ] CORS in `main.py`: `Mcp-Session-Id` und `MCP-Protocol-Version` in `allow_headers`, `Mcp-Session-Id` in `expose_headers` — sonst scheitern browserbasierte Clients wie der MCP Inspector
- [ ] `.env.example` dokumentieren, im Stil der Datei

### Task 1.7: Caddy

Heute leitet Caddy ausschließlich `/api/*` und `/ws/*` ans Backend; alles andere geht ans Frontend. `/mcp` und die Well-Known-Pfade müssen an der **Wurzel** liegen (RFC 9728), lassen sich also nicht unter `/api/` verstecken.

- [ ] `caddy/entrypoint.sh`: `handle /mcp` und `handle /.well-known/oauth-*` → `backend:$BACKEND_PORT`, mit `flush_interval -1` für den MCP-Handle (Streamable HTTP kann SSE zurückgeben und darf nicht gepuffert werden)
- [ ] `backend/app/services/caddy_config.py`: dieselben Handles im generierten Caddyfile
- [ ] **Retrofit:** Bestandsinstallationen haben ein persistiertes `/certs/Caddyfile`. Die vorhandene Reparaturmechanik (`caddy_config.py`, analog zur Nachrüstung der Security-Header) muss die MCP-Handles ebenfalls nachtragen — sonst läuft MCP nur auf Neuinstallationen
- [ ] Warnhinweis in `caddy/entrypoint.sh` analog zum bestehenden Header-Check
- [ ] Test für den Generator und für den Reparaturpfad

### Task 1.8: Lesende Tools

Jedes Tool löst über `app/mcp/context.py` aus dem `AccessToken` eine `OrgCtx` auf und ruft dann dieselben Service-Funktionen wie die REST-Route — **nicht** die eigene API über HTTP.

- [ ] `konvois_auflisten`, `konvoi_details`, `unterkonvois_auflisten`
- [ ] `fahrzeuge_auflisten`, `fahrzeug_details`
- [ ] `wegpunkte_auflisten`
- [ ] `route_abrufen` (die **gespeicherte** Route; Berechnung ist ein Schreib-Tool)
- [ ] `fahrzeugpositionen_abrufen`, `konvoi_status`
- [ ] Alle verlangen `convoy:read`; Positionen zusätzlich prüfen, ob die Org Live-Tracking aktiviert hat
- [ ] Antworten sind kompakte, modelllesbare Strukturen — keine rohen ORM-Dumps, keine internen UUID-Ketten ohne Kontext, Zeiten als ISO-8601 mit Zeitzone
- [ ] Tool-Beschreibungen nennen die Domäne beim Namen (Konvoi, Marschbefehl, Leitstelle), damit das Modell nicht raten muss

### Task 1.9: Sicherheitstests

Diese Liste ist die Abnahme für Phase 1.

- [ ] Unauthentisiertes `POST /mcp` → 401 mit korrektem `WWW-Authenticate` inkl. `resource_metadata` und `scope`
- [ ] PRM-Dokument liegt exakt auf `/.well-known/oauth-protected-resource/mcp` und nennt den eigenen Issuer
- [ ] Token mit fremdem `aud` → 401
- [ ] ConvoyPlan-Access-Token (`typ="access"`) an `/mcp` → 401
- [ ] MCP-Token (`typ="mcp"`) an `/api/convoys` → 401
- [ ] PKCE-Verifier falsch → Token-Request abgelehnt
- [ ] Code zweimal eingelöst → zweiter Versuch abgelehnt **und** Familie widerrufen
- [ ] `redirect_uri` nicht registriert → `authorize` abgelehnt, **kein** Redirect
- [ ] Rotiertes Refresh-Token erneut vorgelegt → gesamte Familie tot
- [ ] Token für Org A sieht keine Daten von Org B
- [ ] `token_version`-Bump entwertet bestehende MCP-Tokens
- [ ] Registrierte Toolliste enthält kein Tool, das löscht
- [ ] Mit `MCP_ENABLED=false` antworten `/mcp` und beide Well-Known-Pfade mit 404

---

## Phase 2 — Schreibende Tools

### Task 2.1: Schreib-Tools (ohne Löschen)

- [ ] `konvoi_anlegen`, `konvoi_aktualisieren`
- [ ] `fahrzeug_anlegen`, `fahrzeug_aktualisieren`
- [ ] `fahrzeug_zu_konvoi_hinzufuegen`, `konvoi_fahrzeuge_umsortieren`
- [ ] `wegpunkt_anlegen`, `wegpunkt_aktualisieren`, `wegpunkte_umsortieren`
- [ ] `route_berechnen`
- [ ] `fahrzeugstatus_setzen` (Scope `fleet:status`)
- [ ] Alle übrigen verlangen `convoy:write`
- [ ] Bei fehlendem Scope: **403 mit `WWW-Authenticate: Bearer error="insufficient_scope", scope="…", resource_metadata="…"`**, alle für die Operation nötigen Scopes in **einer** Challenge — die Spec verlangt ausdrücklich, nicht inkrementell nachzufordern
- [ ] Eingaben über Pydantic-Schemas validieren, dieselben wie in `app/schemas/`

**Offen, vor Umsetzung zu entscheiden:** `fahrzeug_aus_konvoi_entfernen` ist technisch ein `DELETE`, semantisch aber „Zuordnung lösen" und kein Datenverlust. Nach der Vorgabe „Schreiben ja, Löschen nein" bleibt es vorerst **draußen**. Falls es hineinsoll, gehört es unter `convoy:write` und in die Audit-Liste.

### Task 2.2: Audit

- [ ] Jeder Schreibaufruf schreibt über `app/services/audit.py` einen Eintrag mit Benutzer, Org, **`client_id` des MCP-Clients**, Tool-Name und Parametern
- [ ] Die Quelle ist als `mcp` gekennzeichnet, damit im Audit-Log unterscheidbar bleibt, was ein Mensch und was ein Modell getan hat. Für ein BOS-Produkt ist das keine Kür
- [ ] Test: ein Schreib-Tool erzeugt genau einen Audit-Eintrag mit korrekter Quelle

### Task 2.3: Quota und Rate Limiting

`route_berechnen` und Geocoding verbrauchen GraphHopper-CPU bzw. HERE/TomTom-Kontingent. Die vorhandenen Schutzmechanismen (`app/api/quota.py`) sind FastAPI-`Depends` und greifen im MCP-Pfad nicht.

- [ ] In der Tool-Schicht direkt `app/services/rate_limit.check()` aufrufen, gekeyt auf `(user_id, "mcp:<bucket>")`
- [ ] Budgets aus denselben `QUOTA_*`-Einstellungen ableiten — keine zweite Zahlenwelt
- [ ] Zusätzlich eine Obergrenze für Tool-Aufrufe pro Minute und Token; ein Modell in einer Schleife ist ein realistisches Lastprofil
- [ ] Bei Überschreitung ein klarer Tool-Fehler, den das Modell versteht, statt eines nackten 429

### Task 2.4: Lizenzstatus in der Tool-Schicht

- [ ] Ohne gültige Lizenz sind nur die lesenden Tools registriert; `tools/list` zeigt die schreibenden erst gar nicht an
- [ ] Der Lizenzstatus wird beim Verbindungsaufbau ausgewertet, nicht einmalig beim Start
- [ ] Test: Instanz ohne Lizenz → `tools/list` enthält kein Schreib-Tool

### Task 2.5: Resources und Prompts

- [ ] Resource `convoyplan://konvoi/{id}/marschbefehl.pdf` über `app/services/pdf.py`
- [ ] Resources für GPX- und GeoJSON-Export über `app/services/export.py`
- [ ] Ein Prompt „Marschbefehl erstellen", der Konvoi, Fahrzeuge, Wegpunkte und Route zu einer Vorlage bündelt
- [ ] Resource-URIs gehen durch dieselben Zugriffsprüfungen wie die Tools

---

## Phase 3 — Verwaltung und Dokumentation

### Task 3.1: Admin-Oberfläche

- [ ] Neuer Reiter „MCP" in `/admin`
- [ ] Schalter für `MCP_ENABLED` und `MCP_ALLOW_DCR` zur Laufzeit
- [ ] Liste registrierter Clients: Name (als unbestätigt gekennzeichnet), `redirect_uris`, Registrierungszeitpunkt, letzte Nutzung, Widerruf
- [ ] Liste aktiver Verbindungen pro Org: Benutzer, Client, Scopes, letzte Nutzung, „Verbindung trennen" (widerruft die Refresh-Familie)
- [ ] Die Verbindungs-URL zum Kopieren, plus ein Hinweis, dass Clients sie als Remote-MCP-Server eintragen
- [ ] Nur für Superadmin und Org-Admin; Org-Admins sehen ausschließlich ihre eigene Org

### Task 3.2: Dokumentation

- [ ] `wiki/MCP-Server.md`: Was der Server kann und was nicht, Verbinden Schritt für Schritt, Scope-Tabelle, Widerruf, das 15-Minuten-Fenster bei Access-Tokens, DSGVO-Einordnung (welche Daten an welchen Modellanbieter fließen — bei einem BOS-Produkt der Punkt, an dem Kunden hängenbleiben)
- [ ] `wiki/_Sidebar.md` und `wiki/API-Dokumentation.md` verlinken
- [ ] `wiki/Sicherheit-und-Datenschutz.md` um den MCP-Abschnitt ergänzen
- [ ] `README.md`: eine Zeile im Funktionsumfang
- [ ] `CHANGELOG.md` unter Unreleased
- [ ] `CLAUDE.md`: MCP-Endpunkt neben dem `/docs`-Abschnitt erwähnen

### Task 3.3: Ende-zu-Ende-Abnahme

- [ ] Gegen eine lokale Instanz mit `tls internal` mit dem MCP Inspector verbinden: Discovery, DCR, Consent, Token, `tools/list`, ein Lese- und ein Schreib-Tool
- [ ] Mit einem echten MCP-Client (Claude Desktop oder Claude Code) als Remote-Server verbinden
- [ ] Widerruf über die Admin-Oberfläche → Client verliert den Zugriff
- [ ] Upgrade-Pfad: bestehende Installation mit persistiertem Caddyfile, `MCP_ENABLED=true` setzen, prüfen dass die Handles nachgetragen wurden

---

## Phase 4 — Optional, nach Bedarf

- [ ] **Client ID Metadata Documents** (`SHOULD` der Spec). `get_client()` erkennt ein HTTPS-`client_id`, ruft das Dokument ab, validiert `client_id`-Übereinstimmung und `redirect_uris`, cached. **Zwingend mit SSRF-Schutz**: nur HTTPS, keine privaten oder Link-Local-Adressen, keine Redirects, harte Timeouts, Größenlimit — im Zweifel das Muster von `validate_region_url` übernehmen. Danach `client_id_metadata_document_supported: true` in die AS-Metadata und DCR abschaltbar machen
- [ ] **Step-up-Autorisierung** vollständig: ein Token mit nur `convoy:read` bekommt beim Schreib-Tool eine Scope-Challenge und der Client holt inkrementell nach
- [ ] **Stdio-Wrapper** für Clients ohne Remote-Unterstützung
- [ ] **Subscriptions**: Positions- und Statusänderungen als MCP-Subscription, gestützt auf den bestehenden WebSocket-/SSE-Pfad

---

## Risiken

| Risiko | Bewertung | Gegenmaßnahme |
|---|---|---|
| Ein Modell ändert Einsatzdaten falsch | Real, keine hypothetische Sorge | Kein Löschen; Scopes an Rollen gebunden; jeder Schreibaufruf im Audit-Log mit Quelle `mcp`; Schreiben verlangt `planer` |
| Confused Deputy über frei wählbaren `client_name` | Bekannter Angriff auf DCR | `client_name` escaped und als unbestätigt gekennzeichnet; geprüfte `redirect_uri`-Domain daneben; Zustimmung pro Client und Org |
| SSRF über CIMD | Erst in Phase 4 relevant | Phase 4 ist ohne den Schutzwall aus Task 4.1 nicht abnahmefähig |
| Access-Token bleibt nach Widerruf ≤15 min gültig | Folge zustandsloser JWTs | Kurze TTL; Widerruf tötet die Refresh-Familie; Fenster dokumentiert statt verschwiegen |
| SDK-Breaking-Changes | `mcp` ist jung, 2.2.0 ist vom 07.09.2026 | Exakter Pin; die Montage-Verdrahtung aus Task 0.1 ist der empfindliche Punkt und bekommt einen Test, der beim Upgrade bricht statt still kaputtzugehen |
| Bestandsinstallationen ohne Caddy-Handles | Betrifft jede Installation, die vor diesem Release lief | Reparaturpfad in `caddy_config.py`, Test dafür |
| Datenabfluss an den Modellanbieter | Der Punkt, an dem BOS-Kunden nachfragen | Default aus; Freischaltung pro Instanz; Scopes minimal; Doku benennt klar, welche Daten das Haus verlassen |
