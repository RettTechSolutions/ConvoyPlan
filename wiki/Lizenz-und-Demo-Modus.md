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

## Offene Demo-Sitzungen verwalten (Admin)

Jede Demo-Nutzung läuft als eigene, befristete Organisation. Der Admin-Bereich (**Admin** → **Demo-Sitzungen**) listet alle offenen Sitzungen mit Name, Ablaufzeit, Anzahl angelegter Konvois und **Herkunft**.

Die Herkunft (Stadt/Region/Land) wird beim Start der Sitzung aus der Client-IP ermittelt und per Hintergrund-Geolokation (ipapi.co) angereichert — ein langsamer oder nicht erreichbarer Geo-Dienst verzögert den Demo-Start nie, die Anfrage läuft als Background-Task nach der Antwort. Private oder ungültige IPs (z. B. lokale Entwicklung) werden nicht abgefragt und bleiben ohne Herkunftsangabe. Die Daten helfen, Demo-Sitzungen Interessenten zuzuordnen.

Sitzungen lassen sich hier verlängern oder sofort beenden. Herkunftsdaten (`created_ip`, `created_location`) werden zusammen mit der Demo-Organisation vom bestehenden Retention-Job gelöscht — es gibt keine gesonderte Aufbewahrungsfrist dafür.

### Eine Demo je IP-Adresse (Karenzzeit)

Damit die Demo eine Vorführung bleibt und nicht als Dauerbetrieb genutzt wird, kann je Client-IP nur **eine** Sitzung pro Karenzzeit gestartet werden — Standard **24 Stunden**, einstellbar unter **Admin** → **Demo-Modus** → „Karenzzeit je IP" (`0` schaltet die Sperre ab) bzw. über `DEMO_IP_COOLDOWN_HOURS`. Ein weiterer Versuch innerhalb des Fensters wird mit **HTTP 429** und `Retry-After` abgewiesen.

Der Besucher sieht dabei den Grund der Absage, nicht nur die Absage: Startseite und `/demo` zeigen die Begründung des Backends unverändert an — welche Karenzzeit gilt, wann der nächste Versuch möglich ist, oder dass der Demo-Modus gerade abgeschaltet ist. Nur wenn keine Antwort des Backends vorliegt (Netzwerkfehler), erscheint der allgemeine Hinweis „Bitte später nochmal versuchen".

Die Sperre wird in der Datenbank geführt (Tabelle `demo_origins`) und hat damit zwei Eigenschaften, die ein reiner Zähler im Arbeitsspeicher nicht hätte: Sie übersteht einen **Neustart des Backends** (also jedes Update), und sie gilt auch dann noch, wenn die Demo-Organisation längst abgelaufen und gelöscht ist — bei kurzer Sitzungslaufzeit ist das der Normalfall.

Hinter einem Firmenanschluss oder einem Messe-WLAN teilen sich alle Besucher eine Adresse. Für diesen Fall listet der Abschnitt **Gesperrte IP-Adressen** die aktuell blockierten Adressen mit Zeitpunkt der letzten Demo, Freigabezeitpunkt und Gesamtzahl der Sitzungen — einzelne Sperren lassen sich dort direkt aufheben. Abgelaufene Einträge löscht der Retention-Job; die Adressen werden also nicht länger gespeichert als die Sperre gilt.

### Dauerhaft freigestellte Adressen

Manche Anschlüsse sollen gar nicht erst gesperrt werden: der eigene Vertrieb, ein Firmenanschluss beim Interessenten, das WLAN auf einer Messe oder in einer Schulung. Dort einzeln zu entsperren wäre nach jeder Vorführung erneut nötig. Der Abschnitt **Dauerhaft freigestellte Adressen** (Admin → Demo-Modus) nimmt solche Anschlüsse dauerhaft von der Karenzzeit aus.

Eingetragen wird entweder eine einzelne Adresse (`203.0.113.7`) oder ein ganzes Netz in CIDR-Schreibweise (`203.0.113.0/24`, ebenso IPv6: `2001:db8::/32`) — Letzteres, weil ein Firmenanschluss selten auf eine feste Adresse festgelegt ist. Dazu gehört eine Notiz, damit in einem Jahr noch nachvollziehbar ist, warum ausgerechnet dieses Netz freigestellt ist.

Zwei Dinge geschehen dabei automatisch:

- **Eine laufende Sperre für die Adresse wird mit aufgehoben.** Wer einen Anschluss freistellt, will ihn jetzt freigeschaltet haben und nicht erst nach Ablauf der Karenzzeit.
- **Freigestellte Adressen werden nicht mehr mitgeschrieben.** Sie tauchen in der Liste der gesperrten Adressen also gar nicht erst auf.

Hostbits werden beim Speichern verworfen: Aus `203.0.113.7/24` wird `203.0.113.0/24`, damit der Eintrag das bedeutet, was dort steht. Ein Netz ohne Präfixlänge (`0.0.0.0/0`) wird abgelehnt — das würde die Karenzzeit stillschweigend für alle abschalten; dafür gibt es die Einstellung „Karenzzeit 0". Anlegen und Entfernen werden im Audit-Log vermerkt.

> 📖 Endpunkte: siehe [API-Dokumentation → Demo-Sitzungen](API-Dokumentation#demo-sitzungen).

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
