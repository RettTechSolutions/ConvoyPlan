# Auto-Updater

ConvoyPlan bringt einen Updater-Container mit, der das GitHub-Repository pollt und neue Versionen automatisch deployt. Kanal und Modus lassen sich im Admin-Bereich (**Admin → Software-Update**) umschalten; die Env-Variablen dienen nur als Fallback vor dem ersten Setzen in der UI.

---

## GitHub-Token (optional)

Der Updater fragt Releases und Build-Stände über die GitHub-API ab. Das
Repository ist öffentlich, dafür braucht es **keinen Token**.

Ein **`GITHUB_TOKEN`** hebt nur das Rate-Limit: Ohne Token erlaubt GitHub 60
API-Anfragen pro Stunde **je IP-Adresse**, mit Token 5000. Eine einzelne Instanz
kommt mit dem kleinen Kontingent aus (der Updater prüft alle 5 Minuten). Eng wird
es erst, wenn mehrere Instanzen oder andere Werkzeuge hinter derselben öffentlichen
IP GitHub abfragen. Dann meldet die Instanz „GitHub nicht erreichbar", bis die
Stunde um ist.

Wer einen Token hinterlegt, nimmt einen
[fine-grained Token](https://github.com/settings/personal-access-tokens/new) mit
**„Public repositories (read-only)"** und **ohne** weitere Berechtigungen. Einen
klassischen Token mit `repo` oder `public_repo` nicht nehmen: beide erlauben
Schreibzugriff, `repo` sogar auf alle privaten Repositories des Kontos. Der Token
steht im Klartext in der `.env` bzw. in der Datenbank.

Hinterlegt wird er im Admin-Bereich unter **Software-Update** (wirkt ohne Neustart)
oder als Env-Variable. Die Installer fragen ihn nicht ab.

`GITHUB_REPO` legt das überwachte Repository fest (Standard `RettTechSolutions/ConvoyPlan`; bei Fork anpassen).

---

## Update-Kanäle

| Kanal | Verhalten | Docker-Tag |
|---|---|---|
| **Stable** (Standard, empfohlen) | Nur veröffentlichte GitHub-Releases | `:latest` |
| **Beta** | Nummerierte Vorabversionen / Release-Kandidaten (`vX.Y.Z-beta.N`) | `:beta` |
| **Nightly** | Jeder Commit auf `main` | `:nightly` |
| **LTS** (Wartungsvertrag) | Releases der aktuellen LTS-Linie: 12 Monate nur Sicherheits- und Fehlerkorrekturen | `:lts` |

Der Beta-Kanal funktioniert auch bei image-basierten Standard-Installationen.

Fallback-Env: `UPDATE_CHANNEL=stable|beta|nightly|lts`.

Der Updater trägt die Tags des gewählten Kanals auch in die `.env` im
Installationsverzeichnis ein (`BACKEND_IMAGE`, `FRONTEND_IMAGE`,
`GRAPHHOPPER_IMAGE`, `UPDATER_IMAGE`, `REGION_MERGE_IMAGE`) — beim Start und nach
jedem Kanalwechsel. Ein `docker compose pull && docker compose up -d` von Hand
zieht damit dieselben Images wie der Updater. Vorher las es die `.env` mit
`:latest` und tauschte eine Nightly-Installation still auf das ältere
Stable-Image zurück. Angefasst werden nur Einträge, die auf ein Image dieses
Projekts mit Tag zeigen; ein eigener Mirror oder ein Digest (`@sha256:…`) bleibt
stehen.

### LTS-Kanal

Der LTS-Kanal gehört zum Wartungsvertrag. Wählbar ist er nur, wenn der
Lizenzschlüssel eine LTS-Freigabe (`lts_until`) trägt und das Datum nicht
überschritten ist. Die Freigabe steht unter **Admin → Lizenz**.

- Eine LTS-Linie ist eine Version wie `2026.7`, die 12 Monate lang nur Sicherheits-
  und Fehlerkorrekturen bekommt (`v2026.7.1`, `v2026.7.2`, …), keine neuen Funktionen.
- Pro Jahr beginnt eine neue Linie. Dann wechselt der Kanal von selbst auf sie — im
  Modus **Benachrichtigen** erst nach Klick auf „Jetzt updaten“.
- Läuft die Freigabe ab, bleibt eine Installation auf dem LTS-Kanal stehen, statt
  ungefragt auf die neueste Stable-Version zu springen. Die Admin-Oberfläche weist
  darauf hin.

---

## Update-Modi

| Modus | Verhalten |
|---|---|
| **Automatisch** (`auto`, Standard) | Verfügbare Updates werden im gewählten Kanal automatisch installiert |
| **Benachrichtigen** (`notify`) | Es wird nicht automatisch installiert; stattdessen erhalten Superadmins eine E-Mail. Installation erfolgt manuell |

Ergänzende Env-Variablen:

| Variable | Beschreibung |
|---|---|
| `UPDATE_MODE` | `auto` oder `notify` (Fallback) |
| `UPDATE_NOTIFY_ON_AUTO` | Nur bei `auto`: `true` schickt zusätzlich eine Bestätigungs-Mail nach automatischer Installation (Standard `false`) |
| `UPDATE_NOTIFY_INTERVAL` | Prüfintervall in Sekunden für fällige Benachrichtigungen (Standard `1800`) |

> Der `notify`-Modus und `UPDATE_NOTIFY_ON_AUTO` setzen einen konfigurierten SMTP-Dienst voraus (Admin → SMTP).

---

## Update-Status und manueller Trigger

Der Admin-Bereich zeigt den aktuellen Deploy-SHA und den GitHub-Stand. Ein Update lässt sich per Button manuell anstoßen; der Updater-Prozess wird als Live-Log (SSE) im Browser mitgeschrieben.

Relevante Endpunkte:

| Methode | Endpunkt | Zweck |
|---|---|---|
| `POST` | `/api/admin/trigger-update` | Update manuell anstoßen |
| `GET` | `/api/admin/update-status` | Deploy-Stand abrufen |
| `GET` | `/api/admin/update-log` | Live-Update-Log (SSE) |
| `GET/PUT` | `/api/admin/settings/update-channel` | Kanal lesen/setzen |
| `GET/PUT` | `/api/admin/settings/update-mode` | Modus lesen/setzen |

---

## Selbstheilung bei fehlgeschlagenen Deployments

Ein Backend-Image, das älter als der DB-Migrationsstand ist (z. B. ein versehentliches Downgrade auf ein `:beta`-Image, das eine bereits angewendete Migration nicht kennt), konnte früher die gesamte API lautlos lahmlegen — Caddy lieferte auf alle `/api/*`-Routen 502, ohne dass jemand benachrichtigt wurde. Vier Schutzebenen verhindern das jetzt:

| Ebene | Wirkung |
|---|---|
| **Healthcheck** | Der `backend`-Dienst hat einen Docker-Healthcheck auf `/health`; Docker und der Updater erkennen einen crashenden Container, statt „gestartet" als Erfolg zu werten |
| **Robuster Boot-Entrypoint** (`backend/docker-entrypoint.sh`) | Erkennt „Image älter als DB-Schema", protokolliert eine klare Diagnose, hinterlegt einen Alert-Marker und bricht bewusst fail-closed ab |
| **Automatischer Rollback** | Der Updater merkt sich vor jedem Deploy das laufende Backend-Image (per Image-ID), wartet nach dem Deploy auf `healthy` und stellt bei Fehlschlag automatisch die vorherige Version wieder her (beide Updater-Varianten) |
| **Alert an Superadmins** | Der wieder gesunde Backend-Container liest den Alert-Marker und benachrichtigt alle Superadmins per E-Mail über den fehlgeschlagenen Deploy bzw. Rollback — genau einmal pro Ereignis |

---

## Routing-Graph: kein Deploy mitten im Import

GraphHopper baut aus den OSM-Daten einen Routing-Graphen. Bei den größeren Kartenregionen dauert das 45–75 Minuten, und in dieser Zeit routet die Instanz nicht. Ein Deploy, der den Container mitten darin austauscht, hinterlässt Bruchstücke im Graph-Volume — der Import beginnt anschließend von vorn.

Der Updater nimmt den `graphhopper`-Dienst deshalb aus dem Deploy heraus, solange dort ein Import läuft, und zieht ihn nach, sobald der Graph fertig ist. Im Update-Log steht dann:

```
GraphHopper baut gerade den Routing-Graphen (kein /data/graph/edges) — dieser
Dienst wird aus dem Deploy herausgenommen und nach dem Import nachgezogen;
alle anderen werden aktualisiert.
```

Alle übrigen Dienste werden normal aktualisiert; das Update gilt als erfolgreich. Nach spätestens vier Stunden ohne fertigen Graphen wird der Dienst trotzdem mitgetauscht — sonst käme ein Container, der aus einem anderen Grund nie fertig wird (zu wenig Speicher, volle Platte), nie an das Update, das den Fehler behebt.

Bleibt trotzdem ein unvollständiger Graph zurück (Host-Neustart, abgeschossener Container), erkennt GraphHopper das beim nächsten Start selbst, räumt das Verzeichnis und baut neu. Das kostet den Import erneut, aber die Instanz routet danach wieder statt in einer Neustart-Schleife zu hängen.

Sichtbar ist ein laufender Bau an zwei Stellen. Die öffentliche Statusseite (`/status`) nennt ihn als Grund, warum die Routenplanung gerade nicht verfügbar ist. Im Admin-Portal steht er unter **System → Kartenregion**, mit Beginn und Dauer:

- **Kartendaten werden heruntergeladen**: Es liegt noch kein Extract vor, GraphHopper lädt es und baut danach.
- **Routing-Graph wird neu aufgebaut**: Der Import läuft, die Karte zeigt, seit wann.
- **Import ohne Abschluss**: Seit mehr als vier Stunden gibt es keinen fertigen Graphen. Das ist dieselbe Frist wie oben. Die Ursache steht im Container-Log (`docker compose logs graphhopper`), meist zu wenig Speicher oder eine volle Platte. Ein Neustart des Containers räumt den Rest weg und baut neu. Die Statusseite meldet diesen Fall nicht mehr als Neuaufbau, sondern als Störung.

Solange heruntergeladen oder importiert wird, startet kein Regionswechsel **sofort**: „Wechsel starten" ist gesperrt, und auch die API lehnt ab (409). Ein Wechsel liefe parallel zum laufenden Import, konkurrierte mit ihm um den Speicher und würfe ihn am Ende weg. **Einplanen** geht dagegen. Der Updater startet einen geplanten Wechsel erst, wenn sein Termin erreicht **und** der Aufbau fertig ist, und schreibt das Warten einmal ins Log. Die Karte zeigt dann „Fällig, aber GraphHopper baut gerade seinen Routing-Graphen". Ein hängender Import hält nichts auf: Dann kann ein Wechsel auf eine kleinere Region gerade der Ausweg sein.

Abgelesen wird das an den Dateien im Graph-Volume, nicht am Container. Einen Lebensbeweis für den Import gibt es dabei nicht: Ein Container, der mitten im Import angehalten wurde und nicht wiederkommt, sieht bis zum Ablauf der Frist aus wie ein laufender Import.

---

## Host-Watchdog

Ein systemd-Timer (`scripts/updater-watchdog.sh`) räumt verwaiste Updater-Container auf und startet abgestürzte Updater neu. Er wird vom Linux-Installer eingerichtet.

> In Portainer übernimmt der Stack-Update-Mechanismus von Portainer selbst das Deployment neuer Images; der `updater`-Container ist nur in `docker-compose.yml` enthalten.
