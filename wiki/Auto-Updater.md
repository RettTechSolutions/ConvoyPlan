# Auto-Updater

ConvoyPlan bringt einen Updater-Container mit, der das GitHub-Repository pollt und neue Versionen automatisch deployt. Kanal und Modus lassen sich im Admin-Bereich (**Admin → Software-Update**) umschalten; die Env-Variablen dienen nur als Fallback vor dem ersten Setzen in der UI.

---

## Voraussetzung: GitHub-Token

Damit der Updater Commit-Stände und Releases von GitHub abrufen kann, wird ein **`GITHUB_TOKEN`** (Classic PAT mit `repo`-Leseberechtigung) benötigt. Es kann per Env-Variable oder direkt in der Admin-UI hinterlegt werden (kein Neustart nötig).

`GITHUB_REPO` legt das überwachte Repository fest (Standard `RettTechSolutions/ConvoyPlan`; bei Fork anpassen).

---

## Update-Kanäle

| Kanal | Verhalten | Docker-Tag |
|---|---|---|
| **Stable** (Standard, empfohlen) | Nur veröffentlichte GitHub-Releases | `:latest` |
| **Beta** | Nummerierte Vorabversionen / Release-Kandidaten (`vX.Y.Z-beta.N`) | `:beta` |
| **Nightly** | Jeder Commit auf `main` | `:nightly` |

Der Beta-Kanal funktioniert auch bei image-basierten Standard-Installationen.

Fallback-Env: `UPDATE_CHANNEL=stable|beta|nightly`.

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

## Host-Watchdog

Ein systemd-Timer (`scripts/updater-watchdog.sh`) räumt verwaiste Updater-Container auf und startet abgestürzte Updater neu. Er wird vom Linux-Installer eingerichtet.

> In Portainer übernimmt der Stack-Update-Mechanismus von Portainer selbst das Deployment neuer Images; der `updater`-Container ist nur in `docker-compose.yml` enthalten.
