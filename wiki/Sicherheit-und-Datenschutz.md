# Sicherheit und Datenschutz

Diese Seite fasst die Sicherheits-Härtung, das Audit-Log, die DSGVO-Werkzeuge sowie Backup/Restore und Datenaufbewahrung zusammen.

---

## Härtung im Überblick

| Bereich | Umsetzung |
|---|---|
| **Fail-Closed JWT** | In Produktion (`APP_ENV=production`) startet das Backend nicht, wenn `JWT_SECRET` leer, Platzhalter oder < 32 Zeichen ist |
| **Brute-Force-Schutz** | Rate-Limiting auf Login, MFA-Verify und Passwort-Reset (HTTP 429) |
| **Passwort-Policy** | Mind. 10 Zeichen mit Buchstaben + Ziffern, Abgleich gegen Have-I-Been-Pwned (k-Anonymity, fail-open) |
| **JWT-Revocation** | `token_version` entzieht alle Tokens bei Passwort-/MFA-Reset |
| **MFA at-rest** | TOTP-Secrets mit Fernet verschlüsselt gespeichert |
| **CORS-Lockdown** | In Produktion auf die eigene App-Origin beschränkt |
| **CSP & Security-Header** | Content-Security-Policy (Report-Only/Enforce) plus HSTS, X-Content-Type-Options u. a. über Caddy |
| **security.txt** | Vulnerability-Disclosure-Kontakt unter `/.well-known/security.txt` |
| **Dependency-Scanning** | Dependabot + CI-Job (`pip-audit`, `npm audit`) |

Sicherheitslücken bitte gemäß `SECURITY.md` bzw. `/.well-known/security.txt` melden.

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

## Datenaufbewahrung (Retention)

Der `retention`-Container purgt periodisch abgelaufene Daten:

| Variable | Standard | Wirkung |
|---|---|---|
| `RETENTION_ENABLED` | `true` | Retention-Läufe aktiv |
| `RETENTION_INTERVAL` | `3600` | Sekunden zwischen den Läufen |
| `RETENTION_POSITIONS_HOURS` | `24` | Live-Positionen älter als … löschen |
| `RETENTION_AUDIT_DAYS` | `365` | Audit-Log-Einträge älter als … löschen |
| `RETENTION_SHARE_LINKS_DAYS` | `30` | Widerrufene Share-Links älter als … löschen |

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
