# Plan: T5 Retention/Löschkonzept & T5b Betroffenenrechte

> Bezug: `docs/iso-certifications-review.md` (T5, T5b) · ISO/IEC 27701, DSGVO Art. 5(1)(e), 15, 17, 30, 32
> Status: **Planungsentwurf** — Umsetzung erst nach Klärung der offenen Fragen (§7).

Dieses Dokument beschreibt, wie ConvoyPlan (a) personenbezogene Daten nach definierten Fristen automatisch löscht und (b) Betroffenenrechte (Auskunft/Export und Löschung) technisch umsetzt.

---

## 1. Ziele

- **T5 — Aufbewahrung & Löschung:** Personenbezogene Daten werden nicht länger als nötig gespeichert; abgelaufene Daten werden automatisch und nachvollziehbar gelöscht.
- **T5b — Betroffenenrechte:** Für eine betroffene Person können alle gespeicherten Daten **exportiert** (Art. 15) und **gelöscht** (Art. 17) werden.

Beides ist Pflicht für die DSGVO-Konformität und damit Voraussetzung für ISO/IEC 27701.

---

## 2. Dateninventar (Ist-Stand)

| Tabelle | Personenbezug | Heutiges Verhalten | Relevanz |
|---|---|---|---|
| `vehicle_positions` | **Hoch** — Live-Standort (lat/lon, speed, heading, `recorded_at`) | Upsert: nur **letzte** Position pro (Konvoi, Fahrzeug); keine Historie | T5 (Standortdaten) |
| `audit_logs` | Mittel — `actor_email`, `ip`, `user_agent`, `actor_id` | Append-only, keine Löschung | T5 (Logdaten) |
| `users` | **Hoch** — E-Mail, Passwort-Hash, `mfa_secret`, `created_at` | Löschung nur manuell durch Admin | T5b |
| `vehicles` | Mittel — Funkrufname, Kennzeichen | Cascade-Delete am Owner | T5b |
| `convoys`, `waypoints`, `routes` | Niedrig–mittel — Einsatzbezug, evtl. Klarnamen in Notizen | Cascade-Delete am Owner | T5b |
| `convoy_share_links` | Niedrig — `created_by_id`, Zugriffszähler | Cascade am Konvoi | T5 (Zugriffslogs) |
| `user_organizations` | Niedrig — Mitgliedschaft/Rolle | Cascade | T5b |

**Wichtige Erkenntnis:** Durch das Upsert-Design fällt bei `vehicle_positions` keine Bewegungshistorie an (Datenminimierung ✅). Der Restbedarf ist das **Aufräumen veralteter Positionen** nach Einsatzende.

---

## 3. T5 — Retention-Policy (Vorschlag)

Fristen als **konfigurierbare Einstellungen** (System-/Org-Setting), mit konservativen Defaults:

| Datenart | Vorgeschlagene Default-Frist | Konfig-Schlüssel | Begründung |
|---|---|---|---|
| Live-Positionen (`vehicle_positions`) | Löschen, wenn `recorded_at` älter als **24 h** *oder* Konvoi abgeschlossen | `retention.positions_hours` | Standortdaten nur für laufenden Einsatz nötig |
| Audit-Log (`audit_logs`) | **365 Tage** | `retention.audit_days` | Sicherheits-/Nachweisinteresse vs. Minimierung; deckt typische Audit-Zyklen |
| Abgelaufene/widerrufene Share-Links | **30 Tage** nach Ablauf/Widerruf | `retention.share_links_days` | Zugriffszähler/Token nicht dauerhaft halten |

> Die konkreten Fristen sind **mit dem Verantwortlichen abzustimmen** (siehe §7) — sie sind teils rechtlich/organisatorisch getrieben, nicht rein technisch.

### Umsetzungsmechanik

1. **Service `app/services/retention.py`** mit Funktionen:
   - `purge_stale_positions(db, max_age_hours)`
   - `purge_old_audit_logs(db, max_age_days)`
   - `purge_expired_share_links(db, grace_days)`
   Jede gibt die Anzahl gelöschter Zeilen zurück und schreibt einen Audit-Eintrag (`retention.purge`).
2. **Auslösung** (eine der Optionen, in §7 zu entscheiden):
   - (a) Hintergrund-Task im FastAPI-Lifespan (`asyncio`-Loop, z. B. stündlich) — keine zusätzliche Infrastruktur.
   - (b) Separater Cron/Container (analog zum Updater) — robuster bei mehreren Replicas.
   - **Empfehlung:** (a) für den Single-Instance-Self-Hosted-Fall, mit Lock/Flag gegen Doppelausführung.
3. **Beobachtbarkeit:** Jede Löschung erzeugt einen Audit-Eintrag mit Zähler; optional Admin-UI-Anzeige „zuletzt aufgeräumt".

### Migrationen / Schema

- Keine neue Tabelle nötig. Optional: Index auf `vehicle_positions.recorded_at` und `audit_logs.created_at` (Letzterer existiert bereits) für effiziente Purges.
- Retention-Fristen als Zeilen in `system_settings` (bestehende Tabelle) bzw. pro Org.

---

## 4. T5b — Betroffenenrechte

### 4.1 Auskunft / Export (Art. 15)

**Endpoint:** `GET /api/admin/users/{user_id}/export` (Superadmin; org-scoped Variante für Org-Admins später).

Liefert ein JSON-Bündel aller Daten zur Person:

```jsonc
{
  "exported_at": "…",
  "user": { "id", "email", "is_active", "is_superadmin", "created_at" },   // ohne Passwort-Hash/MFA-Secret
  "organizations": [ { "org_id", "name", "role" } ],
  "vehicles": [ … ],
  "convoys": [ … inkl. waypoints/routes … ],
  "share_links_created": [ … ],
  "audit_log": [ … Einträge mit actor_id == user … ]
}
```

- **Keine Geheimnisse** im Export (Passwort-Hash, `mfa_secret`, Tokens werden ausgelassen).
- Format maschinenlesbar (JSON) — erfüllt „in einem strukturierten, gängigen Format".

### 4.2 Löschung (Art. 17)

**Endpoint:** `DELETE /api/admin/users/{user_id}/data` (Superadmin) — geht über das heutige `DELETE /users/{user_id}` hinaus.

Ablauf:
1. **Harte Löschung** von `users` (Cascade entfernt `vehicles`, `convoys`, `waypoints`, `routes`, `user_organizations`, eigene Share-Links).
2. **Audit-Log — Pseudonymisierung statt Löschung:** `audit_logs` sind ein Sicherheitsnachweis (append-only) und werden über die Retention-Frist (§3) gehalten. Bei einem Löschverlangen werden die Einträge **pseudonymisiert** (`actor_email` → `null`, `ip` → gekürzt/`null`), `actor_id` bleibt als technische Referenz. So bleibt die Integrität des Audit-Trails erhalten, ohne weiterhin Klardaten der Person zu speichern.
3. **Verbleibende Verweise:** `vehicle_positions` referenzieren Fahrzeuge → durch den Vehicle-Cascade ebenfalls entfernt.
4. **Nachweis:** Es wird ein Audit-Eintrag `user.data_erased` geschrieben (mit `target_id`, ohne Klardaten).

> **Spannungsfeld (zu dokumentieren in der DSGVO-Doku):** Recht auf Löschung (Art. 17) vs. berechtigtes Interesse an Sicherheitsprotokollen (Art. 17(3)(b/e)). Die Pseudonymisierung des Audit-Logs ist der gewählte Kompromiss und muss in den TOMs/Löschkonzept begründet werden.

### 4.3 Selbstbedienung (optional, später)

Ein eingeloggter Nutzer könnte seinen eigenen Export über `GET /api/auth/me/export` anstoßen. Löschung bleibt aus Sicherheitsgründen Admin-initiiert (Vier-Augen-Prinzip).

---

## 5. Tests

- **Retention:** Positions/Audit/Share-Links mit künstlich alten `recorded_at`/`created_at` anlegen → Purge löscht nur Abgelaufenes, schreibt Audit-Eintrag, gibt korrekte Zähler zurück.
- **Export:** enthält erwartete Sektionen, **keine** Geheimnisse (Passwort-Hash/`mfa_secret`/Token).
- **Löschung:** User + Cascade weg; Audit-Einträge pseudonymisiert (kein `actor_email`/`ip`), aber vorhanden; `user.data_erased`-Eintrag geschrieben.
- **Berechtigung:** Endpunkte nur für Superadmin (401/403 sonst).

---

## 6. Phasen / Reihenfolge

1. **Phase 1 — Retention** (`services/retention.py` + Lifespan-Task + Settings + Tests). Geringes Risiko, sofortiger Minimierungsgewinn.
2. **Phase 2 — Export** (read-only, risikoarm).
3. **Phase 3 — Löschung inkl. Audit-Pseudonymisierung** (höchstes Risiko — sorgfältige Tests, irreversibel).
4. **Phase 4 — Admin-UI** (Buttons „Daten exportieren" / „Daten löschen" im Benutzer-Modal; Anzeige letzter Purge-Lauf).

---

## 7. Offene Fragen (vor Umsetzung zu klären)

1. **Aufbewahrungsfristen:** Sind die Defaults (Positionen 24 h, Audit 365 Tage, Share-Links 30 Tage) für den Einsatzbetrieb passend? Gibt es rechtliche/organisatorische Vorgaben (BOS-/Behördenkontext)?
2. **Auslösung des Purges:** Lifespan-Task (einfach) vs. separater Cron-Container (robust für Multi-Replica)?
3. **Org-spezifische Fristen:** Sollen Fristen pro Organisation konfigurierbar sein oder global?
4. **Audit-Pseudonymisierung:** Ist die Beibehaltung pseudonymisierter Audit-Einträge bei Löschverlangen rechtlich abgesegnet (vs. vollständige Löschung)?
5. **Konvoi-„abgeschlossen":** Gibt es einen verlässlichen Status, um Positionen einsatzbezogen statt nur zeitbasiert zu löschen?

> Sobald §7 geklärt ist, kann Phase 1 direkt umgesetzt werden.
