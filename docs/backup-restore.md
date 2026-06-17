# Backup, Restore & Verschlüsselung at-rest

> Bezug: `docs/iso-certifications-review.md` (T11 Backup, T12 Verschlüsselung at-rest) ·
> ISO/IEC 27001 A.8.13 (Backup), A.8.24 (Kryptografie), ISO 22301 (Business Continuity)

---

## 1. Was gesichert werden muss

| Komponente | Speicherort | Inhalt |
|---|---|---|
| **PostgreSQL** | Volume `…_postgres_data` | Benutzer, Organisationen, Konvois, Fahrzeuge, Audit-Log, Einstellungen |
| **Uploads** | Volume `…_logo_uploads` (`/uploads`) | Hochgeladene Branding-Logos |
| **TLS / Caddyfile** | Volume `…_cert_uploads` (`/certs`) | Persistierte Caddyfile + ggf. eigene Zertifikate |

> Nicht sicherungsbedürftig: `osm_data`, `gh_graph` (GraphHopper-Routing-Graph, wird bei Bedarf neu gebaut), `caddy_data`/`caddy_config` (ACME-Zertifikate werden automatisch neu ausgestellt).

---

## 2. Backup

```bash
scripts/backup.sh
```

Erzeugt unter `./backups/<YYYYMMDD-HHMMSS>/`:

- `database.sql.gz` — komprimierter `pg_dump` (mit `--clean --if-exists`, direkt per `psql` einspielbar)
- `uploads.tar.gz`, `certs.tar.gz` — die Named Volumes
- `docker-compose.yml` — Kopie der Stack-Definition
- `SHA256SUMS` — Integritäts-Prüfsummen

**Automatisierung (Cron, täglich 03:00):**

```cron
0 3 * * * /opt/convoyplan/scripts/backup.sh >> /var/log/convoyplan-backup.log 2>&1
```

**Konfiguration** (Env-Variablen oder `.env`):

| Variable | Default | Zweck |
|---|---|---|
| `BACKUP_DIR` | `./backups` | Zielverzeichnis |
| `BACKUP_RETENTION_DAYS` | `30` | Ältere Backup-Ordner werden gelöscht |
| `COMPOSE_PROJECT_NAME` | `convoyplan` | Prefix der Volume-/Container-Namen |
| `DB_CONTAINER` | `<project>-db-1` | Name des Postgres-Containers |

> **Off-site:** Backups gehören zusätzlich an einen zweiten Ort (verschlüsselt) — z. B. per `rsync`/`rclone` auf externen Speicher. Lokale Backups allein schützen nicht vor Hardware-/Standortausfall (ISO 22301).

---

## 3. Restore

```bash
scripts/restore.sh ./backups/20260603-030000
```

Das Skript ist **destruktiv** (überschreibt DB + Dateien) und verlangt zur Bestätigung die Eingabe `RESTORE`. Danach:

```bash
docker compose restart backend caddy
```

**Restore regelmäßig testen** — ein ungetestetes Backup ist kein Backup. Empfehlung: vierteljährlich auf einer separaten Instanz einspielen und Login + Kartenansicht prüfen.

---

## 4. Verschlüsselung at-rest (T12)

ConvoyPlan verschlüsselt **Anwendungsgeheimnisse selektiv** (MFA-TOTP-Secrets via Fernet, siehe `services/crypto.py`). Die **vollständige** Verschlüsselung der Daten im Ruhezustand erfolgt auf **Infrastruktur-Ebene** und ist deployment-abhängig:

### 4.1 Festplatten-/Volume-Verschlüsselung (empfohlen)

- **LUKS (Linux):** Das gesamte Docker-Daten-Verzeichnis (`/var/lib/docker`) bzw. die darunterliegende Partition auf einem LUKS-Container ablegen. Schützt alle Volumes (DB, Uploads, Backups) transparent.
- **Cloud:** Verschlüsselte Block-Volumes nutzen (z. B. „encryption at rest" des Hosters aktivieren).

### 4.2 Datenbank-Ebene (optional, zusätzlich)

- PostgreSQL-TDE-Varianten oder verschlüsselte Tablespaces, falls regulatorisch gefordert. Für die meisten Self-hosted-BOS-Setups ist LUKS auf Host-Ebene ausreichend und einfacher zu betreiben.

### 4.3 Backups

- Backup-Zielverzeichnis ebenfalls auf verschlüsseltem Volume ablegen **oder** die Archive vor dem Off-site-Transfer verschlüsseln (z. B. `age`/`gpg`):

  ```bash
  age -r <recipient-key> -o backup.tar.gz.age backup.tar.gz
  ```

### 4.4 Schlüsselverwaltung

| Geheimnis | Quelle | Hinweis |
|---|---|---|
| `JWT_SECRET` | `.env` / Secrets-Store | Stark (`openssl rand -hex 32`), nicht rotieren ohne Grund |
| `MFA_ENCRYPTION_KEY` | `.env` (optional) | Wird sonst aus `JWT_SECRET` abgeleitet — bei Rotation müssen MFA-Secrets neu eingerichtet werden |
| `POSTGRES_PASSWORD` | `.env` | Stark wählen |
| LUKS-Passphrase | Host / TPM / KMS | Nicht neben den Daten ablegen |

> `.env` enthält Klartext-Geheimnisse → Dateirechte `chmod 600`, nicht ins Backup-Archiv mit Off-site-Versand ohne zusätzliche Verschlüsselung.

---

## 5. Content-Security-Policy (CSP) scharfschalten

Die CSP wird standardmäßig im **Report-Only**-Modus ausgeliefert (bricht die Karten-UI nicht, meldet nur Verstöße im Browser-Log). Zum Erzwingen:

1. `CSP_ENFORCE=true` in `.env` setzen.
2. Stack neu starten (`docker compose up -d caddy backend`).
3. Karte, Routing, Live-Tracking und Geocoding-Suche im Browser prüfen; bei Verstößen in der Konsole die betroffenen Quellen in der Policy ergänzen (`caddy/entrypoint.sh` bzw. `setup.py::_security_header_block`).

Die Policy erlaubt out-of-the-box `tile.openstreetmap.org` (Karten), `nominatim.openstreetmap.org` und `photon.komoot.io` (Adress-Suche/Geocoding), MapLibre-Worker (`blob:`) und Same-Origin-WebSockets.
