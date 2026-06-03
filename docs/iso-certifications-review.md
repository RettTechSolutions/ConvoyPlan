# ISO-Zertifizierungen — Bewertung & Gap-Analyse für ConvoyPlan

> Stand: 2026-06-03 · Bezug: ConvoyPlan (Backend FastAPI, Frontend, Docker/Caddy, Self-hosted + SaaS-Modell)
> Zielgruppe: BOS-Organisationen (Behörden und Organisationen mit Sicherheitsaufgaben) in Deutschland.

Dieses Dokument bewertet, welche ISO-Zertifizierungen für ConvoyPlan relevant sind, priorisiert sie nach Aufwand/Nutzen und enthält eine **konkrete Gap-Analyse gegen den aktuellen Code-Stand** mit Empfehlungen, was technisch und organisatorisch geändert werden müsste.

---

## 1. Kontext & Schutzbedarf

ConvoyPlan verarbeitet Daten mit erhöhtem Schutzbedarf:

- **Standort-/Bewegungsdaten** in Echtzeit (Live-Tracking von Fahrzeugen → personenbeziehbar).
- **Personenbezogene Daten**: Benutzer (E-Mail, Passwort-Hash, MFA-Secret), Fahrzeuge (Kennzeichen, Funkrufname).
- **Einsatzkritische Verfügbarkeit**: Bei realen Märschen/Konvois muss das System laufen.
- **Mandantenfähigkeit (SaaS)**: ConvoyPlan agiert als Auftragsverarbeiter mehrerer Organisationen mit Pflicht zur Datenisolation.

Daraus ergeben sich drei Treiber: **Informationssicherheit**, **Datenschutz (DSGVO)** und **Verfügbarkeit**.

---

## 2. Bewertungskriterien

Jede Norm wird bewertet nach:

| Kriterium | Bedeutung |
|---|---|
| **Relevanz** | Wie stark adressiert die Norm den Schutzbedarf / Kundenerwartung? |
| **Marktnachfrage** | Wird sie von BOS-Kunden / öffentlichen Ausschreibungen verlangt? |
| **Aufwand** | Einführungsaufwand (ISMS, Doku, Audit, laufender Betrieb). |
| **Abhängigkeit** | Setzt sie eine andere Zertifizierung voraus? |
| **Nutzen/Aufwand** | Gesamtempfehlung. |

---

## 3. Bewertung der Normen

### 3.1 ISO/IEC 27001 — Informationssicherheits-Managementsystem (ISMS) ⭐ PRIORITÄT 1

| Kriterium | Bewertung |
|---|---|
| Relevanz | **Sehr hoch** — zentrale Norm, Basis aller 270xx-Erweiterungen |
| Marktnachfrage | **Sehr hoch** — im BOS-/Behördenumfeld faktisch Pflicht in Ausschreibungen |
| Aufwand | Hoch (ISMS-Aufbau, Risiko-Management, Doku, externes Audit) |
| Abhängigkeit | Keine — ist selbst die Grundlage |
| Nutzen/Aufwand | **Empfehlung: zuerst umsetzen** |

Wenn nur eine Zertifizierung angegangen wird, dann diese. Sie liefert das Fundament (ISMS), auf dem 27701/27017/27018 als Add-ons aufsetzen.

### 3.2 ISO/IEC 27701 — Privacy Information Management (PIMS) ⭐ PRIORITÄT 2

| Kriterium | Bewertung |
|---|---|
| Relevanz | **Sehr hoch** — wegen Standort-/Personendaten und SaaS-Auftragsverarbeitung |
| Marktnachfrage | Hoch — belegt DSGVO-Konformität gegenüber Auftraggebern |
| Aufwand | Mittel (Erweiterung des bestehenden ISMS) |
| Abhängigkeit | **Setzt ISO 27001 voraus** |
| Nutzen/Aufwand | **Empfehlung: direkt nach 27001** |

Bildet die DSGVO-Anforderungen strukturiert ab (Rolle als Auftragsverarbeiter, Betroffenenrechte, Löschkonzepte).

### 3.3 ISO/IEC 27017 & 27018 — Cloud-Sicherheit & PII in der Cloud · PRIORITÄT 3

| Kriterium | Bewertung |
|---|---|
| Relevanz | Hoch für **SaaS-Hosting**, gering für reine Self-hosted-Kunden |
| Marktnachfrage | Mittel (in DE oft durch BSI C5 abgedeckt, siehe §5) |
| Aufwand | Niedrig–mittel (Add-on zu 27001) |
| Abhängigkeit | Setzt ISO 27001 voraus |
| Nutzen/Aufwand | **Empfehlung: mitnehmen, sobald SaaS-Angebot wächst** |

### 3.4 ISO 22301 — Business Continuity Management (BCM) · PRIORITÄT 4

| Kriterium | Bewertung |
|---|---|
| Relevanz | Hoch — ConvoyPlan ist ein einsatzkritisches Tool |
| Marktnachfrage | Mittel — bei kritischen Einsatzszenarien relevant |
| Aufwand | Mittel–hoch (eigenes Managementsystem) |
| Abhängigkeit | Eigenständig, ergänzt 27001 gut |
| Nutzen/Aufwand | **Empfehlung: wenn produktiver Einsatzbetrieb mit SLA angeboten wird** |

### 3.5 ISO 9001 — Qualitätsmanagement · OPTIONAL

| Kriterium | Bewertung |
|---|---|
| Relevanz | Gering (kein Sicherheitsbezug) |
| Marktnachfrage | Punktuell — manche öffentliche Ausschreibungen fordern es als Eignungsnachweis |
| Aufwand | Mittel |
| Nutzen/Aufwand | **Nur umsetzen, wenn konkret in Ausschreibungen gefordert** |

---

## 4. Empfohlene Roadmap

1. **ISO 27001** — ISMS-Fundament aufbauen (ggf. „auf Basis IT-Grundschutz" bei starkem Behördenfokus).
2. **ISO 27701** — Datenschutz/DSGVO-Abdeckung ergänzen.
3. **BSI C5** (siehe §5) + **ISO 27017/27018** — fürs SaaS-Hosting.
4. **ISO 22301** — Verfügbarkeit für Einsatzbetrieb.
5. **ISO 9001** — nur bei konkreter Ausschreibungsanforderung.

---

## 5. Wichtig: Deutsche/EU-Frameworks (kein ISO, aber im BOS-Umfeld oft entscheidend)

| Framework | Relevanz für ConvoyPlan |
|---|---|
| **BSI C5** (Cloud Computing Compliance Criteria Catalogue) | De-facto-Standard für Cloud-Dienste im deutschen Behördenumfeld — fürs SaaS oft wichtiger als 27017/27018. |
| **BSI IT-Grundschutz** | Weg zur „ISO 27001 auf Basis IT-Grundschutz" — im Behördenkontext häufig bevorzugt. |
| **DSGVO** (rechtlich Pflicht) | AV-Vertrag, TOMs (Art. 32), Verzeichnis von Verarbeitungstätigkeiten, Löschkonzept für Standortdaten. |
| **NIS2** | Prüfen, ob BOS-Kunden als KRITIS/wichtige Einrichtungen euch als Zulieferer in die Pflicht nehmen. |

---

## 6. Gap-Analyse gegen den aktuellen Code-Stand

### 6.1 Bereits vorhandene Stärken ✅

Folgendes ist bereits umgesetzt und zahlt direkt auf 27001/27701 ein:

- **Passwort-Hashing** mit bcrypt + gensalt (`auth.py`). ✔ A.8.24
- **MFA/TOTP** inkl. Setup-/Confirm-/Disable-Flow und Pending-Token (5 min TTL). ✔ A.8.5
- **Mandanten-Datenisolation** über `get_org_context` + Membership-Prüfung. ✔ A.5.15
- **Rollenmodell** (Admin, Planer, Fahrer, Beobachter) via `guards.py`. ✔ A.5.15/A.8.3
- **Account-Enumeration-Schutz**: Timing-Normalisierung bei `/org-lookup`, `/password-reset`, einheitliche Fehlermeldungen. ✔ A.8.5
- **DB-Re-Check** des Superadmin-Claims (Stale-Token-Schutz). ✔
- **TLS** automatisiert über Caddy/ACME; Caddy-Admin-Port nicht extern exponiert. ✔ A.8.20
- **Caddyfile-Injection-Schutz** (DOMAIN-Validierung). ✔
- **Kryptografisch sichere Tokens** für Share-Links (`secrets`, base62, bcrypt-Passwort, Session-TTL 24 h). ✔
- **Datenminimierung beim Tracking**: `VehiclePosition` ist ein Upsert (nur letzte Position pro Fahrzeug, keine Bewegungshistorie). ✔ DSGVO Art. 5(1)(c)
- **Pinned Dependencies** + CI-Pipeline. ✔ teilw. A.8.8

### 6.2 Technische Lücken (mit Control-Bezug)

> Sortiert nach Priorität. „Quick Win" = mit überschaubarem Aufwand umsetzbar.

| # | Lücke | Control (ISO 27001 Anhang A / 27701) | Empfohlene Änderung | Aufwand |
|---|---|---|---|---|
| T1 ✅ | **Audit-Log** — *umgesetzt.* | A.8.15 Logging, A.5.28 Beweissicherung, 27701 Betroffenenrechte | Append-only `audit_logs`-Tabelle (Migration 0018) + Service `audit.record()`. Erfasst Login (Erfolg/Fehlschlag), MFA-Änderung, Passwortänderung/-Reset, Benutzer-/Org-CRUD, Lizenzaktivierung inkl. Akteur, Ziel, IP, User-Agent. Lesbar über `GET /api/admin/audit-log`. Offen: Konvoi-/Marschbefehl-Änderungen, Share-Link-Erstellung. | Mittel |
| T2 ✅ | **Brute-Force-Schutz / Rate-Limiting** — *umgesetzt.* | A.8.5 Sichere Authentisierung | In-Process-Limiter (`services/rate_limit.py`) auf Login, MFA-Verify, Password-Reset (HTTP 429 + `Retry-After`). Offen: persistenter/geteilter Store (Redis) für Multi-Replica, echtes Account-Lockout. | Quick Win |
| T3 ✅ | **`JWT_SECRET`-Default** — *umgesetzt.* | A.8.24 Kryptografie, A.5.17 | Fail-Closed: Backend verweigert Start im Produktionsmodus, wenn Secret = Default/leer oder < 32 Zeichen (`APP_ENV=development` relaxt). | Quick Win |
| T4 ✅ | **Security-Header** — *teilweise umgesetzt.* | A.8.26 Anwendungssicherheit | HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy im Caddyfile ergänzt. Offen: **CSP** (bewusst noch nicht gesetzt — muss pro Deployment für Kartentiles/GraphHopper/Wetter getunt und getestet werden). | Quick Win |
| T5 ✅ | **Retention/Löschkonzept** — *umgesetzt.* | DSGVO Art. 5(1)(e), 27701 7.4.7/8.4 | `services/retention.py` + Cron-Container `retention` purgt Positionen (>24 h), Audit-Logs (>365 Tage) und widerrufene Share-Links (>30 Tage); Fristen via `RETENTION_*` konfigurierbar, jeder Lauf erzeugt einen Audit-Eintrag. Offen: org-spezifische Fristen, einsatzbezogene Positions-Löschung. | Mittel |
| T5b ✅ | **Betroffenenrechte** — *umgesetzt.* | 27701 7.3, DSGVO Art. 15/17 | `GET /api/admin/users/{id}/export` (JSON-Bündel ohne Geheimnisse) und `DELETE /api/admin/users/{id}/data` (Löschung + Cascade, Audit-Trail wird **pseudonymisiert** statt gelöscht). | Mittel |
| T6 ✅ | **JWT-Revocation** — *umgesetzt.* | A.5.18 Zugriffsrechte, A.8.5 | `token_version`-Claim (`tv`) im JWT, geprüft gegen `users.token_version`. Bei Passwortänderung, Passwort-Reset (Self/Admin) und MFA-Reset wird die Version erhöht → alle bestehenden Tokens der Person werden ungültig. Self-Change erhält ein frisches Token zurück. Offen: kurzlebige Access- + Refresh-Token-Rotation. | Mittel |
| T7 ✅ | **MFA-Secret verschlüsselt at-rest** — *umgesetzt.* | A.8.24, A.8.11 Datenmaskierung | `services/crypto.py` verschlüsselt das TOTP-Secret mit Fernet (Key aus `MFA_ENCRYPTION_KEY` oder aus `JWT_SECRET` abgeleitet); Spalte auf 255 verbreitert (Migration 0019). Legacy-Klartext bleibt abwärtskompatibel lesbar. | Mittel |
| T8 ✅ | **Passwort-Policy + Breach-Check** — *umgesetzt.* | A.5.17 Authentisierungs­informationen | Zentrale `validate_password()` (min. 10 Zeichen, Buchstaben + Ziffern) plus `assert_password_not_breached()` (HIBP-k-Anonymity, fail-open offline) — konsistent in Registrierung, Passwortänderung und Admin-Benutzerverwaltung. | Quick Win |
| T9 ✅ | **CORS-Lockdown** — *umgesetzt.* | A.8.26 | In Produktion fällt CORS auf die eigene App-Origin zurück (kein `*` mehr); explizite Allowlist via `CORS_ORIGINS`; `*` nur in Dev bzw. bei expliziter Konfiguration (mit Warnung). | Quick Win |
| T10 ✅ | **SCA / Schwachstellen­überwachung** — *umgesetzt (erste Stufe).* | A.8.8 Technisches Schwachstellen­management | `.github/dependabot.yml` (pip/npm/actions/docker) + CI-Job `dependency-audit` (`pip-audit` + `npm audit`), zunächst **advisory** (`continue-on-error`). Offen: blockierend schalten nach Triage des Backlogs, Container-Image-Scan (Trivy), dokumentierter Patch-SLA. | Quick Win |
| T11 | **Backup/Restore nicht dokumentiert/erzwungen** (DB + `/uploads`). | A.8.13 Backup, ISO 22301 | Backup-Strategie + regelmäßiger Restore-Test dokumentieren; ggf. Backup-Hook im Docker-Setup. | Mittel |
| T12 | **Kein Verschlüsselungs­nachweis at-rest** für DB/Uploads (hängt vom Deployment ab). | A.8.24 | Volume-/DB-Verschlüsselung dokumentieren oder bereitstellen. | Mittel |
| T13 ✅ | **`security.txt` / Vulnerability-Disclosure** — *umgesetzt.* | A.5.5 / A.6.8 | `/.well-known/security.txt` + `SECURITY.md` mit Meldekanal. | Quick Win |

### 6.3 Organisatorische Lücken (der Großteil von ISO 27001 ist *kein* Code)

Diese Punkte sind für die Zertifizierung mindestens so wichtig wie der Code:

- **ISMS-Grundlagen**: Scope-Definition, Informationssicherheits-Leitlinie, Risikobewertung + Risikobehandlungsplan, **Statement of Applicability (SoA)**.
- **Asset- & Daten-Inventar** inkl. Datenklassifizierung (welche personenbezogenen Daten, wo, wie lange).
- **Zugriffskontroll-Policy** + Joiner/Mover/Leaver-Prozess (auch für interne Admins/Superadmins).
- **Lieferanten-Management**: GraphHopper, Open-Meteo, OSM/Overpass, SMTP-Provider, Hosting (`s-lx04-docker`/Portainer), GitHub. Auftragsverarbeitungs-Verträge (Sub-Prozessoren) für 27701/DSGVO.
- **Incident-Management-Prozess** (Erkennung, Meldung, Eskalation, 72-h-DSGVO-Meldepflicht).
- **Business Continuity / Disaster Recovery Plan** (RTO/RPO) — Basis für ISO 22301.
- **Change-Management** (teilweise durch Git/CI abgedeckt — formalisieren).
- **Awareness/Schulung** der Beteiligten; **interne Audits** und **Management-Review**.
- **DSGVO-Dokumente**: Verzeichnis von Verarbeitungstätigkeiten, TOMs (Art. 32), AV-Vertrags-Template für Kunden, Datenschutz­erklärung, Löschkonzept.

---

## 7. Empfohlene erste Schritte (Quick Wins im Code)

Diese Punkte verbessern die Sicherheitslage sofort und sind Voraussetzung für mehrere 27001-Controls — unabhängig davon, wann das formale Audit startet.

**Bereits umgesetzt** (siehe CHANGELOG):

1. ✅ **T1** Audit-Log — größter Hebel für die Zertifizierung.
2. ✅ **T2** Rate-Limiting auf Auth-Endpunkten.
3. ✅ **T3** Fail-Closed bei Default-`JWT_SECRET`.
4. ✅ **T4** Security-Header im Caddyfile (ohne CSP).
5. ✅ **T8** Passwort-Policy + HIBP-Breach-Check.
6. ✅ **T13** `security.txt` + Vulnerability-Disclosure.
7. ✅ **T9** CORS-Lockdown in Produktion.
8. ✅ **T10** Dependabot + `pip-audit`/`npm audit` in CI (advisory).

9. ✅ **T5 / T5b** Retention/Löschkonzept + Betroffenenrechte — Detailplan in [`docs/iso-t5-retention-plan.md`](iso-t5-retention-plan.md).

10. ✅ **T6** JWT-Revocation (`token_version`).
11. ✅ **T7** MFA-Secret verschlüsselt at-rest.

**Als Nächstes empfohlen:**

12. **T4 (Rest)** CSP pro Deployment tunen und aktivieren.
13. **T2 (Rest)** Account-Lockout + geteilter Rate-Limit-Store für Multi-Replica.
14. **T10 (Rest)** `dependency-audit` blockierend schalten + Trivy-Image-Scan.
15. **T6 (Rest)** kurzlebige Access- + Refresh-Token-Rotation.
16. **T11/T12** Backup-/Restore-Strategie + Verschlüsselung at-rest dokumentieren.

> Hinweis: Eine Zertifizierung wird **nicht** durch Code allein erreicht — sie verlangt ein gelebtes Managementsystem (Abschnitt 6.3). Die Code-Maßnahmen sind notwendige, aber nicht hinreichende Bausteine.
