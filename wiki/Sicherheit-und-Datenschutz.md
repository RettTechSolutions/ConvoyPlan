# Sicherheit und Datenschutz

Diese Seite fasst die Sicherheits-Härtung, das Audit-Log, die DSGVO-Werkzeuge sowie Backup/Restore und Datenaufbewahrung zusammen.

---

## Härtung im Überblick

| Bereich | Umsetzung |
|---|---|
| **Fail-Closed JWT** | In Produktion (`APP_ENV=production`) startet das Backend nicht, wenn `JWT_SECRET` leer, Platzhalter oder < 32 Zeichen ist |
| **Brute-Force-Schutz** | Rate-Limiting auf Login, MFA-Verify und Passwort-Reset (HTTP 429) |
| **Kontingent-Drosselung** | Stundenbudget je Aufrufer auf Routing, Adresssuche und Verkehrslage (HTTP 429 mit `Retry-After`); Demo-Sitzungen mit kleinerem Budget und zusätzlich pro IP gezählt |
| **Passwort-Policy** | Mind. 10 Zeichen mit Buchstaben + Ziffern, Abgleich gegen Have-I-Been-Pwned (k-Anonymity, fail-open) |
| **E-Mail-Normalisierung** | Login-Adressen werden getrimmt und klein geschrieben gespeichert/verglichen — Login ist case-insensitive, doppelte Konten mit nur abweichender Groß-/Kleinschreibung sind ausgeschlossen (`lower(email)`-Unique-Index) |
| **Sitzung im HttpOnly-Cookie** | Das Zugriffstoken liegt nicht mehr im `localStorage`, sondern in einem `HttpOnly`-Cookie — JavaScript im Browser kommt nicht mehr an den Wert (siehe unten) |
| **CSRF-Schutz** | Cookie-Anmeldungen brauchen bei ändernden Methoden den Kopf `X-Requested-With: ConvoyPlan`; zusätzlich `SameSite=Lax` |
| **JWT-Revocation** | `token_version` entzieht alle Tokens bei Passwort-/MFA-Reset |
| **MFA at-rest** | TOTP-Secrets mit Fernet verschlüsselt gespeichert |
| **CORS-Lockdown** | In Produktion auf die eigene App-Origin beschränkt |
| **CSP & Security-Header** | Content-Security-Policy (Report-Only/Enforce) plus HSTS, X-Content-Type-Options u. a. über Caddy |
| **security.txt** | Vulnerability-Disclosure-Kontakt unter `/.well-known/security.txt` |
| **Dependency-Scanning** | Dependabot + CI-Job (`pip-audit`, `npm audit`) |

Sicherheitslücken bitte gemäß `SECURITY.md` bzw. `/.well-known/security.txt` melden.

---

## Die Sitzung im Browser

Das Zugriffstoken lag früher im `localStorage` und wurde von der Oberfläche in jeden API-Aufruf geschrieben. Das ist bequem und hat einen Preis: **jedes** Stück JavaScript auf der Seite konnte es lesen. Ein einziges Cross-Site-Scripting — in einer Abhängigkeit, in einem eingebetteten Namen, in einer Vorschau — hätte genügt, und das Token wäre abgeflossen. Es ist sieben Tage gültig (`JWT_EXPIRE_MINUTES`) und von jedem Rechner der Welt einlösbar; gestohlen ist es eine Woche lang eine vollwertige Anmeldung.

Jetzt liegt es in einem **`HttpOnly`-Cookie**. Der Browser schickt es von sich aus mit, Skripte kommen nicht mehr an den Wert heran.

> **Was das nicht leistet.** Läuft fremder Code auf der Seite, kann er weiterhin im Namen des Angemeldeten Anfragen stellen — das Cookie geht ja automatisch mit. Was er nicht mehr kann, ist das Token *mitnehmen*. Der Unterschied ist erheblich: ein Angriff endet mit der Sitzung im Browser, statt eine Woche lang von einem fremden Rechner aus weiterzulaufen. Er ist aber kein Freibrief, und deshalb steht er hier statt im Kleingedruckten.

**Eine Sitzung je Organisation.** In ConvoyPlan meldet man sich pro Organisation getrennt an, und man kann in zwei Tabs in zwei Organisationen arbeiten. Entsprechend gibt es ein Cookie je Organisation (`cp_session__<slug>`) plus eines für die organisationslose Superadmin-Sitzung (`cp_session`). Welche gemeint ist, sagt die Oberfläche über den Kopf `X-Org-Slug`.

**CSRF.** Ein Cookie schickt der Browser auch dann mit, wenn eine fremde Seite die Anfrage auslöst — das Problem, das es mit einem `Authorization`-Header nicht gab. Dagegen zwei Dinge: `SameSite=Lax` hält das Cookie bei Unterseiten-Anfragen fremder Ursprünge zu Hause, und alle ändernden Methoden verlangen den festen Kopf `X-Requested-With: ConvoyPlan`. Einen eigenen Header kann fremdes JavaScript nur nach einem CORS-Preflight setzen, und den beantwortet die Instanz nur für den eigenen Ursprung; ein Formular-POST von außen kann ihn gar nicht setzen.

**`Secure`-Flag.** Ob das Cookie nur über HTTPS gesendet wird, leitet sich aus `APP_BASE_URL` ab und **nicht** aus dem Schema der eingehenden Anfrage. Hinter dem Reverse Proxy spricht das Backend unverschlüsselt; eine Ableitung aus der Anfrage ergäbe in Produktion immer „http" und das Cookie nie `Secure`.

**Für API-Clients ändert sich nichts.** Der Weg über `Authorization: Bearer` bleibt bestehen, inklusive `access_token` in der Login-Antwort. Er war nie das Problem — das Problem war, das Token dafür im Browser zu lagern. Skripte, API-Keys und der MCP-Server sind unberührt.

> Wer schon angemeldet war, wird beim ersten Laden nach dem Update einmal zur Anmeldung geschickt: die alte Ablage wird nicht mehr gelesen, sondern aufgeräumt.

---

## Content-Security-Policy scharfschalten

Die CSP wird standardmäßig im **Report-Only**-Modus ausgeliefert (bricht die Karten-UI nicht, meldet nur Verstöße im Browser-Log). Zum Erzwingen:

1. `CSP_ENFORCE=true` in `.env` setzen.
2. Stack neu starten (`docker compose up -d caddy backend`).
3. Karte, Routing, Live-Tracking und Geocoding-Suche prüfen; bei Verstößen die betroffenen Quellen in der Policy ergänzen.

Die Policy erlaubt out-of-the-box `tile.openstreetmap.org` (Karten), `nominatim.openstreetmap.org` und `photon.komoot.io` (Geocoding), MapLibre-Worker (`blob:`) und Same-Origin-WebSockets.

---

## Audit-Log

Ein **append-only** Protokoll erfasst sicherheitsrelevante Ereignisse (Logins, MFA, Passwortänderungen, Benutzer-/Org-Anlage, Lizenzaktivierung) inklusive Akteur, Ziel, IP und User-Agent. Superadmins rufen es über `GET /api/admin/audit-log` (filterbar nach Aktion) ab.

---

## DSGVO-Werkzeuge

| Recht | Endpunkt | Wirkung |
|---|---|---|
| Auskunft (Art. 15) | `GET /api/admin/users/{id}/export` | Liefert alle personenbezogenen Daten als JSON |
| Löschung (Art. 17) | `DELETE /api/admin/users/{id}/data` | Löscht den Benutzer und pseudonymisiert den Audit-Trail |

---

## KI-Schnittstelle (MCP)

Standardmäßig **abgeschaltet**. Ohne `MCP_ENABLED=true` existiert weder `/mcp` noch ein
Discovery-Dokument.

Eingeschaltet gilt: Zugriff entsteht erst durch die ausdrückliche Zustimmung eines
angemeldeten Benutzers (inklusive MFA), gilt für genau eine Organisation und ist durch
dessen Rolle gedeckelt. Jeder schreibende Aufruf landet im Audit-Log mit Quelle `mcp` und
dem auslösenden Programm. Gelöscht werden kann über die Schnittstelle nichts.

Was ein Modell liest, verlässt dabei die Instanz und geht an den Anbieter des
KI-Programms — das ist der Zweck der Schnittstelle. Die datenschutzrechtliche Einordnung,
das Zeitfenster beim Widerruf und die Einstellungen stehen in
[MCP-Server](MCP-Server).

---

## Datenaufbewahrung (Retention)

Der `retention`-Container purgt periodisch abgelaufene Daten:

| Variable | Standard | Wirkung |
|---|---|---|
| `RETENTION_ENABLED` | `true` | Retention-Läufe aktiv |
| `RETENTION_INTERVAL` | `3600` | Sekunden zwischen den Läufen |
| `RETENTION_POSITIONS_HOURS` | `24` | Live-Positionen älter als … löschen |
| `RETENTION_AUDIT_DAYS` | `365` | Audit-Log-Einträge älter als … löschen |
| `RETENTION_SHARE_LINKS_DAYS` | `30` | Widerrufene Share-Links älter als … löschen |
| `RETENTION_DEMO_LEADS_DAYS` | `180` | Kontaktangaben aus dem Demo-Start älter als … löschen |

Im selben Durchgang laufen zwei Aufgaben ohne eigene Variable: Abgelaufene
Demo-Sitzungen samt ihrer Daten werden gelöscht (Frist im Admin-Portal), und
für abgelaufene Sitzungen geht die einmalige Nachfrage-Mail raus (siehe
[Lizenz und Demo-Modus](Lizenz-und-Demo-Modus#nachfrage-nach-ablauf-der-sitzung)).
Die Kontaktangabe hält bewusst länger als die Sitzung — daran hängen Nachfrage
und ein etwaiges Vertriebsgespräch —, aber nicht dauerhaft; einzelne Kontakte
lassen sich im Admin-Bereich sofort löschen.

---

## Backup & Restore

### Was gesichert werden muss

| Komponente | Volume | Inhalt |
|---|---|---|
| PostgreSQL | `…_postgres_data` | Benutzer, Orgs, Konvois, Fahrzeuge, Audit-Log, Einstellungen |
| Uploads | `…_logo_uploads` | Hochgeladene Branding-Logos |
| TLS / Caddyfile | `…_cert_uploads` | Persistierte Caddyfile + ggf. eigene Zertifikate |

> Nicht sicherungsbedürftig: `osm_data`, `gh_graph` (wird neu gebaut), `caddy_data` (ACME-Zertifikate werden neu ausgestellt).

### Backup

```bash
scripts/backup.sh
```

Erzeugt unter `./backups/<YYYYMMDD-HHMMSS>/` einen komprimierten `pg_dump`, die Volumes als `.tar.gz`, eine Kopie der Compose-Datei und `SHA256SUMS`. Konfiguration über `BACKUP_DIR` und `BACKUP_RETENTION_DAYS`.

**Cron (täglich 03:00):**

```cron
0 3 * * * /opt/convoyplan/scripts/backup.sh >> /var/log/convoyplan-backup.log 2>&1
```

> **Off-site:** Backups gehören zusätzlich verschlüsselt an einen zweiten Ort (`rsync`/`rclone`).

### Restore

```bash
scripts/restore.sh ./backups/20260603-030000
docker compose restart backend caddy
```

Das Skript ist **destruktiv** und verlangt zur Bestätigung die Eingabe `RESTORE`. Restore regelmäßig (z. B. vierteljährlich) auf einer separaten Instanz testen.

---

## Verschlüsselung at-rest

ConvoyPlan verschlüsselt Anwendungsgeheimnisse selektiv (MFA-TOTP-Secrets via Fernet). Die **vollständige** Verschlüsselung im Ruhezustand erfolgt auf Infrastruktur-Ebene:

- **LUKS (Linux):** `/var/lib/docker` bzw. die darunterliegende Partition auf einem LUKS-Container ablegen — schützt alle Volumes transparent.
- **Cloud:** verschlüsselte Block-Volumes des Hosters nutzen.
- **Backups:** Zielverzeichnis auf verschlüsseltem Volume ablegen oder Archive vor Off-site-Transfer verschlüsseln (`age`/`gpg`).

Schlüsselverwaltung: `.env` enthält Klartext-Geheimnisse → Dateirechte `chmod 600`, LUKS-Passphrase nicht neben den Daten ablegen. `MFA_ENCRYPTION_KEY` wird aus `JWT_SECRET` abgeleitet, falls nicht gesetzt — bei Rotation von `JWT_SECRET` ohne eigenen Schlüssel werden bestehende MFA-Secrets unlesbar.
