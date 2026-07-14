# Funktionsumfang

Vollständige Feature-Übersicht von ConvoyPlan mit Umsetzungsstatus. Eine kompakte Zusammenfassung findet sich auf der [Startseite](Home); die Bedienung einzelner Funktionen ist im [Benutzerhandbuch](Benutzerhandbuch) beschrieben.

---

## 🗺️ Planung und Routing

| Funktion | Beschreibung | Status |
|---|---|---:|
| Karte | Interaktive OSM-Karte mit Planungsansicht | ✅ |
| Wegpunkte | Start, Ziel, Wegpunkte, Kontrollpunkte und technische Halte | ✅ |
| Routenberechnung | GraphHopper-Routing über selbst gehosteten Dienst | ✅ |
| Zeitplan | Automatische Ankunfts- und Abfahrtszeiten | ✅ |
| Marschgeschwindigkeiten | Separate innerörtliche und außerörtliche Geschwindigkeit | ✅ |
| Kraftstoffplanung | Fahrzeugdaten und Tankstellenabfrage entlang der Route | ✅ |

---

## 👥 Verwaltung und Zusammenarbeit

| Funktion | Beschreibung | Status |
|---|---|---:|
| Login | Registrierung und JWT-basierte Authentifizierung | ✅ |
| Onboarding-Tour | Geführte Spotlight-Tour hebt reale Bedienelemente direkt in der App hervor | ✅ |
| Fahrzeuge | CRUD für Einsatzfahrzeuge und Konvoirollen | ✅ |
| Marschverbände | CRUD für Konvois und zugeordnete Fahrzeuge | ✅ |
| Teilverbände | Sub-Convoys mit Parent-Konvoi | ✅ |
| Mandanten | Organisationen mit Mitgliederverwaltung | ✅ |
| Multi-Tenancy | Org-Code-Slug, org-spezifische Login-Seite, Branding und Datenisolation pro Org | ✅ |
| Rollen | Admin, Planer, Fahrer und Beobachter | ✅ |
| MFA / TOTP | Zwei-Faktor-Authentifizierung per TOTP im Org-Admin-Panel einrichtbar | ✅ |
| SMTP-Dienst | Passwort-E-Mails direkt aus dem Admin-Panel versenden | ✅ |
| Freigabelink | Öffentliche Routenansicht per Share-Token | ✅ |
| Branding | Eigenes App-Logo, Farben und Name über Admin-UI konfigurierbar | ✅ |
| Leitstellen | Leitstellen und Kanalwechselpunkte entlang der Route | ✅ |
| Org-Leitstellen | Org-eigene Leitstellen mit Vorschlags-/Freigabe-Workflow, Übersichtskarte und Landkreis-Auswahl | ✅ |
| API-Schlüssel | Org-gebundene API-Keys für programmatischen Zugriff (Admin-Panel) | ✅ |

---

## 📡 Live und Export

| Funktion | Beschreibung | Status |
|---|---|---:|
| Live-Tracking | Positionsupdates per REST und WebSocket | ✅ |
| Fahrzeugstatus | Geplant, unterwegs, angekommen oder verspätet | ✅ |
| Wetter | Integration über Open-Meteo ohne API-Key | ✅ |
| Sperrungen | Sperrungen und Baustellen aus Overpass API, Autobahn-API (bund.dev), offenen regionalen Feeds (MobiData BW, Berlin VIZ) und optional DATEX-II/mobilithek, entlang der gesamten Route | ✅ |
| Verkehrslage | Live-Fließgeschwindigkeit/Stau über HERE oder TomTom entlang der Route (optionaler API-Key pro Installation) | ✅ |
| PDF | Marschbefehl als PDF | ✅ |
| GPX / JSON | Export und Import für Navigation, Dokumentation und Weiterverarbeitung | ✅ |
| PWA | Installierbare Web-App mit Tile-Caching | ✅ |
| Native Wrapper | Capacitor-Konfiguration für Android und iOS | ✅ |

---

## ⚙️ Betrieb und Administration

| Funktion | Beschreibung | Status |
|---|---|---:|
| Setup-Wizard | Ersteinrichtung per Browser ohne SSH-Zugang (4 Schritte inkl. Branding) | ✅ |
| Admin-Bereich | Benutzer- (inkl. optionalem Vor-/Nachname), Leitstellen- und Branding-Verwaltung | ✅ |
| Auto-Updater | Git-Polling-Container aktualisiert die Instanz automatisch bei neuem Commit | ✅ |
| Update-Status | Admin-UI zeigt Deploy-SHA und GitHub-Stand; manueller Trigger per Button | ✅ |
| Update-Kanal | Umschaltbar zwischen „Stable" (nur veröffentlichte Releases), „Beta" (nummerierte Vorabversionen / Release-Kandidaten) und „Nightly" (jeder Commit auf `main`) im Admin-Bereich — auch bei image-basierten Installationen | ✅ |
| Update-Modus | „Automatisch" installiert Updates selbstständig; „Benachrichtigen" verschickt nur eine E-Mail an Superadmins, Installation erfolgt manuell; optionale Bestätigungs-Mail nach automatischer Installation | ✅ |
| Live-Update-Log | Echtzeit-Ausgabe des Updater-Prozesses im Browser via SSE | ✅ |
| GitHub-Token in UI | `GITHUB_TOKEN` für Update-Fetch direkt in der Admin-UI konfigurierbar, kein Neustart | ✅ |
| Demo-Modus | Ohne Lizenzschlüssel: Lesezugriff uneingeschränkt, Schreibzugriff gesperrt (HTTP 402) | ✅ |
| Lizenzaktivierung | Schlüsseleingabe und Instanz-UUID im Admin-Bereich „System"; Cache-Reset ohne Neustart | ✅ |
| Backup / Restore | `scripts/backup.sh` und `scripts/restore.sh` für DB-Dump und Volumes inkl. Prüfsummen und Retention | ✅ |
| Host-Watchdog | systemd-Timer räumt verwaiste Updater-Container auf und startet abgestürzte Updater neu | ✅ |

---

## 🔐 Sicherheit und Datenschutz

| Funktion | Beschreibung | Status |
|---|---|---:|
| Brute-Force-Schutz | Rate-Limiting auf Login, MFA-Verify und Passwort-Reset (HTTP 429) | ✅ |
| Passwort-Policy | Mind. 10 Zeichen mit Buchstaben + Ziffern, Abgleich gegen Have-I-Been-Pwned | ✅ |
| JWT-Revocation | `token_version` entzieht alle Tokens bei Passwort-/MFA-Reset | ✅ |
| MFA at-rest | TOTP-Secrets mit Fernet verschlüsselt gespeichert | ✅ |
| CORS-Lockdown | In Produktion auf die eigene App-Origin beschränkt | ✅ |
| CSP & Security-Header | Content-Security-Policy (Report-Only/Enforce) plus HSTS, X-Content-Type-Options u. a. über Caddy | ✅ |
| Audit-Log | Append-only Protokoll sicherheitsrelevanter Ereignisse für Superadmins | ✅ |
| Datenexport (DSGVO Art. 15) | `GET /api/admin/users/{id}/export` liefert alle personenbezogenen Daten als JSON | ✅ |
| Datenlöschung (DSGVO Art. 17) | Löscht den Benutzer und pseudonymisiert den Audit-Trail | ✅ |
| Retention | `retention`-Container purgt Live-Positionen, Audit-Log und Share-Links nach Frist | ✅ |
| security.txt | Vulnerability-Disclosure-Kontakt unter `/.well-known/security.txt` | ✅ |
| Dependency-Scanning | Dependabot + CI-Job (`pip-audit`, `npm audit`) | ✅ |

> Details zu Härtung, Audit-Log, DSGVO und Backup/Restore: **[Sicherheit und Datenschutz](Sicherheit-und-Datenschutz)**.

---

## Roadmap-Ideen

Bereits umgesetzt:

- ~~Import vorhandener GPX-/GeoJSON-Routen~~ ✅ (seit 0.5.0)
- ~~CI-Pipeline für Backend-Tests, Frontend-Checks und Docker-Builds~~ ✅ (seit 0.4.0)
- ~~Demo-Modus und Lizenzaktivierung über Admin-UI~~ ✅ (seit 0.5.1)
- ~~Multi-Tenancy mit Org-Code-Slug und org-spezifischem Branding~~ ✅ (seit 0.8.5)
- ~~MFA / TOTP-Zwei-Faktor-Authentifizierung~~ ✅ (seit 0.8.5)
- ~~SMTP-Dienst für Passwort-E-Mails~~ ✅ (seit 0.8.5)
- ~~Security-Härtung (Brute-Force-Schutz, Passwort-Policy, JWT-Revocation, CSP)~~ ✅ (seit 1.0.0)
- ~~Security-Audit-Log sicherheitsrelevanter Ereignisse~~ ✅ (seit 1.0.0)
- ~~DSGVO-Werkzeuge (Datenexport/-löschung) und Datenaufbewahrung~~ ✅ (seit 1.0.0)
- ~~Backup-/Restore-Skripte~~ ✅ (seit 1.0.0)
- ~~Org-eigene Leitstellen mit Vorschlags-Workflow~~ ✅ (seit 1.0.0)

Geplant:

- Benachrichtigungen bei Verzögerungen oder Abweichungen von der Route.
- Audit-Log für fachliche Änderungen an Marschbefehlen und Konvois.
- Offline-First-Synchronisation für mobile Nutzung.
- Erweiterte Einsatzdokumentation und Einsatznachbereitung.
