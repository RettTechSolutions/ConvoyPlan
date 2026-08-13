# Systemübersicht

Der Reiter **Systemübersicht** im Admin-Portal (`/admin`, Superadmin) zeigt, wie
es der Maschine unter ConvoyPlan geht: Auslastung der Hardware, Zustand der
Container, Belegung und Druck auf den Platten sowie die Nutzung des Portals —
live, im Verlauf und als Monatsbericht zum Ablegen.

Alle Zahlen sind auch über die API abrufbar (siehe
[API-Dokumentation](API-Dokumentation#systemübersicht-superadmin)), etwa für ein
eigenes Monitoring oder eine Tabellenkalkulation.

---

## Was erfasst wird

| Bereich | Kennzahlen |
|---|---|
| **CPU** | Auslastung in Prozent, Kernzahl, Load Average (1/5/15 Min.) |
| **Arbeitsspeicher** | belegt/verfügbar/gesamt, Prozent, Swap |
| **Massenspeicher** | Belegung je Mountpoint, Lese-/Schreibdurchsatz, Busy-Zeit |
| **Druck (PSI)** | Wartezeit-Anteil für I/O, CPU und Speicher |
| **Container** | Zustand und Healthcheck je Container, CPU/RAM je Container |
| **Datenbank** | Größe, offene Verbindungen, Anzahl Benutzer/Organisationen/Kolonnen |
| **Portalnutzung** | gleichzeitig aktive Benutzer, eindeutige Benutzer je Tag, Anmeldungen, Requests, Serverfehler, Antwortzeit |

### Warum „Druck" und nicht nur „Auslastung"

Eine Platte kann bei 100 % Auslastung völlig entspannt sein und bei 30 %
bereits der Flaschenhals — entscheidend ist, ob Prozesse *warten* müssen. Genau
das misst **PSI** (Pressure Stall Information, Linux ab 4.20): der Anteil der
Zeit, in dem mindestens ein Task auf die Ressource wartet. Als Faustregel:

- **unter 10 %** — unauffällig,
- **10–25 %** — spürbar, im Auge behalten,
- **über 40 %** — die Ressource ist der Engpass.

Liefert der Kernel keine PSI-Werte, bleiben die entsprechenden Anzeigen leer;
alles andere funktioniert unverändert weiter.

### Host oder Container?

CPU, Arbeitsspeicher und Platten-I/O liest das Backend aus dem procfs, das im
Container die Werte des **Hosts** zeigt — die Übersicht beschreibt also die
Maschine, auf der der Stack läuft, nicht nur den Backend-Container. Die
Plattenbelegung wird über die tatsächlich eingehängten Pfade ermittelt
(`/`, `/uploads`, `/update_status`); Pfade auf demselben Dateisystem werden
zusammengefasst.

---

## Historie und Auflösung

Ein Hintergrund-Job im Backend schreibt alle **5 Minuten** eine Stichprobe. Nach
Mitternacht verdichtet er jeden abgeschlossenen Tag zu einer Tageszeile.

| Datenart | Auflösung | Aufbewahrung (Standard) |
|---|---|---|
| Stichproben | 5 Minuten | 90 Tage |
| Tageswerte | 1 Tag | 3 Jahre |
| Nutzung je Benutzer und Tag | 1 Tag | 3 Jahre |

Die Verlaufsdiagramme wählen die Auflösung automatisch passend zum Zeitraum
(Rohdaten → Stundenmittel → Tageswerte), sodass auch ein Jahresverlauf zügig
lädt. Monatsberichte greifen auf die Tageswerte zu und funktionieren deshalb
auch dann noch, wenn die Rohdaten des Monats längst gelöscht sind.

> **Hinweis zur Deutung:** Zustandsgrößen (CPU, RAM, Belegung, aktive Benutzer)
> werden je Zeitfenster gemittelt, Zähler (Requests, Fehler, Anmeldungen)
> aufsummiert.

---

## Monatsberichte exportieren

Im Abschnitt **Monatsbericht** den Monat wählen und exportieren:

- **CSV** — Semikolon-getrennt mit deutschem Dezimalkomma, öffnet sich in Excel
  ohne Nacharbeit. Enthält Kopfdaten, Zusammenfassung und alle Tageswerte.
- **PDF** — Querformat, Kennzahlen-Zusammenfassung plus Tagestabelle; gedacht
  zum Ablegen, z. B. als Betriebsnachweis.

Über die API geht dasselbe direkt:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://web.convoyplan.de/api/admin/system/reports/monthly?month=2026-07&format=csv" \
  -o bericht.csv
```

Der laufende Monat ist jederzeit abrufbar — der heutige Tag wird beim Abruf
frisch verdichtet.

---

## Container-Zustand (Docker)

Den Zustand der Container holt das Backend über die Docker-Engine-API. Dabei
bekommt das Backend **keinen Docker-Socket**: Zugriff auf `/var/run/docker.sock`
ist gleichbedeutend mit Root auf dem Host, und das Backend ist von außen
erreichbar. Stattdessen läuft im Stack der Sidecar `dockerproxy`
([docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy)), der
ausschließlich lesende Aufrufe (`/containers`, `/info`, `/version`) durchlässt;
schreibende Aufrufe sind gesperrt (`POST=0`), Container lassen sich darüber also
weder starten noch stoppen noch erzeugen.

Ist der Sidecar nicht erreichbar, zeigt die Übersicht bei „Container" einen
Hinweis samt Grund — alle übrigen Kennzahlen bleiben verfügbar.

Wer den Sidecar nicht möchte, setzt `DOCKER_METRICS_ENABLED=false` (dann
entfällt nur die Container-Anzeige) oder lässt das Backend über
`DOCKER_API_URL=unix:///var/run/docker.sock` direkt mit dem Socket reden — dann
muss der Socket bewusst selbst ins Backend gemountet werden, mit der oben
genannten Konsequenz.

---

## Datenschutz

Die Nutzungshistorie speichert je Benutzer und Tag **eine** Zeile: Benutzer-ID,
Organisation, erster und letzter Zugriff sowie die Zahl der Requests. Es werden
**keine** aufgerufenen Seiten, IP-Adressen oder Inhalte protokolliert — die
Auswertung beantwortet „wie viele Leute waren wann im Portal", nicht „wer hat
was getan" (dafür gibt es das Audit-Log). Die Daten unterliegen der oben
genannten Aufbewahrungsfrist und werden danach automatisch gelöscht.

---

## Konfiguration

Alle Werte sind optional; die Standards passen für den Normalbetrieb.

| Variable | Standard | Bedeutung |
|---|---|---|
| `SYSTEM_METRICS_ENABLED` | `true` | Erfassung insgesamt an/aus |
| `SYSTEM_METRICS_INTERVAL` | `300` | Sekunden zwischen zwei Stichproben |
| `SYSTEM_METRICS_RETENTION_DAYS` | `90` | Aufbewahrung der Stichproben |
| `SYSTEM_METRICS_DAILY_RETENTION_DAYS` | `1095` | Aufbewahrung der Tageswerte |
| `SYSTEM_METRICS_DISK_PATHS` | `/,/uploads,/update_status` | überwachte Pfade |
| `DOCKER_METRICS_ENABLED` | `true` | Container-Zustand erfassen |
| `DOCKER_API_URL` | `http://dockerproxy:2375` | Docker-API (alternativ `unix://…`) |
| `DOCKER_STATS_ENABLED` | `true` | CPU/RAM je Container mitmessen |

Eine kürzere Taktung erhöht die Detailtiefe und den Speicherbedarf
entsprechend: 5 Minuten ergeben rund 8.600 Zeilen pro Monat, 1 Minute rund
43.000.

---

## Fehlerbehebung

**„Noch keine Messwerte für diesen Zeitraum"**
Nach der Installation dauert es ein Sampling-Intervall, bis der erste Punkt da
ist. Mit **Jetzt messen** lässt sich sofort eine Stichprobe erzwingen.

**Container zeigen „n. v."**
Der `dockerproxy`-Sidecar läuft nicht oder ist nicht erreichbar. Prüfen:
`docker compose ps dockerproxy` und `docker compose logs dockerproxy`.

**Plattendruck bleibt leer**
Der Kernel liefert keine PSI-Werte (Linux < 4.20 oder ohne `CONFIG_PSI`). Der
Durchsatz in Bytes pro Sekunde wird trotzdem erfasst.

**Monatsbericht ist leer**
Tageswerte entstehen erst nach Mitternacht aus den Stichproben. Für den
laufenden Monat wird der heutige Tag beim Abruf verdichtet — liegen für ihn noch
keine Stichproben vor, bleibt der Bericht leer.
