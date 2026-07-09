# Lizenz und Demo-Modus

ConvoyPlan läuft ohne gültigen Lizenzschlüssel im **Demo-Modus**. Lesezugriffe sind uneingeschränkt möglich; alle schreibenden Operationen sind gesperrt.

---

## Demo-Modus

| Aspekt | Verhalten |
|---|---|
| Lesezugriffe (GET) | uneingeschränkt |
| Schreibzugriffe (POST/PUT/PATCH/DELETE) | mit **HTTP 402** gesperrt |
| Eignung | Tests und Evaluierung — **nicht** für den Einsatzbetrieb |

---

## Lizenz beantragen und aktivieren

1. **Instanz-UUID abrufen** — im Admin-Bereich unter **System** oder per API:

   ```http
   GET /api/license/instance-id
   ```

   Die UUID wird während der Installation erzeugt und identifiziert die Instanz.

2. **Lizenzschlüssel anfordern** — mit der UUID beim Anbieter (ConvoyPlan-Lizenzmanager) einen Schlüssel erstellen lassen.

3. **Aktivieren** — Schlüssel im Admin-Bereich **System** eintragen oder per API:

   ```http
   POST /api/license/activate
   { "key": "<lizenzschlüssel>" }
   ```

   Der Schlüssel wird validiert, gespeichert und der Lizenz-Cache ohne Neustart zurückgesetzt.

---

## Schlüsselquelle: Env vs. Datenbank

Der Lizenzschlüssel kann auf zwei Wegen gesetzt werden:

| Quelle | Setzen über | Persistenz |
|---|---|---|
| `LICENSE_KEY` | Umgebungsvariable | im Container-Env |
| Admin-UI | Admin → System → Lizenz | in der Datenbank |

`GET /api/license/status` liefert `demo_mode`, den aktuellen Status und `key_source` (woher der aktive Schlüssel stammt).

---

## Lizenzmodell des Quellcodes

Der Quellcode selbst steht unter einem **Dual-Lizenz-Modell** (AGPL-3.0 bzw. kommerzielle Lizenz) — das betrifft die Nutzung/Weitergabe des Codes und ist unabhängig vom obigen Laufzeit-Lizenzschlüssel. Siehe `LICENSE`, `COMMERCIAL_LICENSE.md` und `CLA.md` im Repository.
