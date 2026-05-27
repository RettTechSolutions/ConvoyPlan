# Installer Design — ConvoyPlan v0.5

**Datum:** 2026-05-24  
**Status:** Approved

---

## Ziel

Ein interaktiver One-Command-Installer für Linux (`install.sh`) und Windows (`install.ps1`), der ConvoyPlan ohne manuelles Konfigurieren von Dateien installiert. Aufruf-URL über convoyplan.de für saubere Doku-Integration.

---

## Dateien

| Datei | Zweck |
|---|---|
| `scripts/install.sh` | Linux-Installer (bash) |
| `scripts/install.ps1` | Windows-Installer (PowerShell) |
| convoyplan.de `/install.sh` | 301-Redirect → raw GitHub |
| convoyplan.de `/install.ps1` | 301-Redirect → raw GitHub |

**Aufruf auf der Doku-Seite:**

```bash
curl -sSL https://convoyplan.de/install.sh | bash
```

```powershell
irm https://convoyplan.de/install.ps1 | iex
```

---

## Installer-Ablauf

Beide Scripts folgen demselben Ablauf:

### 1. Banner
```
ConvoyPlan Installer v0.5
```

### 2. Voraussetzungen prüfen
- `docker` vorhanden und Daemon erreichbar?
- `docker compose` Plugin vorhanden?
- Bei fehlendem Dependency: Fehlermeldung mit Installationshinweis, Abbruch.

### 3. Interaktive Prompts

| Eingabe | Default | Pflicht | Hinweis |
|---|---|---|---|
| Installationsverzeichnis | `~/convoyplan` | nein | |
| Domain | — | ja | FQDN, z.B. `convoy.example.com` |
| ACME-E-Mail | — | ja | Für Let's Encrypt |
| Datenbankpasswort | — | ja | Versteckte Eingabe + Bestätigung |
| OSM-Region | — | ja | Auswahl aus Menü (siehe unten) |
| Lizenzschlüssel | — | nein | Enter = überspringen → Demo-Modus |
| GitHub Token | — | nein | Enter = überspringen |

**OSM-Regions-Menü:**
```
1) Deutschland (~4 GB)
2) Bayern      (~1 GB)
3) Berlin      (~30 MB, für Tests)
4) Eigene URL eingeben
```

### 4. JWT_SECRET auto-generieren
- Linux: `openssl rand -hex 32`
- Windows: `[System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)` → hex-kodiert

### 5. portainer-stack.yml herunterladen
Von `https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main/portainer-stack.yml` ins Installationsverzeichnis.

### 6. .env schreiben
Alle gesammelten Werte als `.env` im Installationsverzeichnis ablegen.

### 7. Stack starten
```bash
docker compose -f portainer-stack.yml pull
docker compose -f portainer-stack.yml up -d
```

### 8. Abschlussmeldung
```
ConvoyPlan läuft!
Setup-Wizard aufrufen: https://<DOMAIN>/setup
```

---

## Fehlerbehandlung

- `install.sh` läuft mit `set -euo pipefail` — jeder Fehler bricht ab
- Jeder kritische Schritt (pull, up) prüft Exit-Code und gibt klare Fehlermeldung aus
- Bereits vorhandenes Installationsverzeichnis mit `.env`: Nutzer wird gefragt ob überschrieben werden soll → bei Nein: Abbruch

---

## Plattform-Unterschiede

| Funktion | `install.sh` | `install.ps1` |
|---|---|---|
| Passwort-Input | `read -s` | `Read-Host -AsSecureString` |
| JWT generieren | `openssl rand -hex 32` | `[System.Security.Cryptography.RandomNumberGenerator]` |
| Datei-Download | `curl` | `Invoke-WebRequest` |
| Voraussetzungsprüfung | `command -v docker` | `Get-Command docker` |

---

## convoyplan.de Redirects (Astro)

Zwei statische Redirect-Seiten in der Astro-Site:

- `src/pages/install.sh.ts` → Response mit `Location`-Header (301) auf raw GitHub URL
- `src/pages/install.ps1.ts` → analog

---

## Nicht im Scope

- Upgrade-Pfad (übernimmt der Auto-Updater im Admin-Bereich)
- Uninstall-Script
- macOS-spezifischer Installer (funktioniert mit `install.sh`)
