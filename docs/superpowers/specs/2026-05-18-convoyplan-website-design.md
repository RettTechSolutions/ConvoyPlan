# ConvoyPlan Website – Design Spec

**Datum:** 2026-05-18  
**Repo:** `RettTechSolutions/convoyplan-website` (neu)  
**Domain:** `convoyplan.de` → GitHub Pages (CNAME)  
**Tech-Stack:** Astro 4, reines CSS (kein Tailwind), Web3Forms für Kontaktformular

---

## Ziel

Öffentliche Marketing-Seite für ConvoyPlan. Zielgruppe: Planer und Führungskräfte in BOS-Organisationen (Feuerwehr, THW, Bundeswehr, Hilfsorganisationen). Primäres Ziel: Demo anfragen. Sekundäres Ziel: Self-hosted-Variante entdecken.

---

## Design-Entscheidungen

| Entscheidung | Wahl | Begründung |
|---|---|---|
| Farbschema | Dark Professional | Dunkel (#0f172a Hintergrund, #3b82f6 Akzent) |
| Layout | Vollständig (SaaS-Standard) | Hero → Features → Workflow → Pricing → Kontakt → Footer |
| Primärer CTA | Demo anfragen | BOS kauft nicht impulsiv, braucht persönlichen Kontakt |
| Formular-Backend | Web3Forms | Kostenlos, kein Account, Mails an christoph@zeitler.tech |
| Sprache | Deutsch | Zielgruppe ist DACH/BOS |
| Framework | Astro 4 | Statisch, component-basiert, GitHub Pages native |

---

## Seitenstruktur

### Hauptseite (`/`)

**Nav**
- Logo (SVG aus ConvoyPlan-Repo) + Wortmarke "ConvoyPlan"
- Links: Features · Preise · Docs (→ GitHub Wiki) · GitHub (Icon)
- CTA-Button rechts: "Demo anfragen" (→ Kontaktformular-Sektion, Anchor-Link)
- Sticky, blur-backdrop auf Scroll

**Hero**
- Badge: "Für BOS-Organisationen · Open Source · AGPL-3.0"
- Headline (H1): "Marschverbandsplanung die wirklich funktioniert."
- Subline: "Route planen. Zeitplan berechnen. Marschbefehl exportieren. Live-Tracking. Alles in einem Browser-Tab – self-hosted oder verwaltet."
- CTA primär: "Demo anfragen" (Button, blau)
- CTA sekundär: "GitHub ansehen" (Ghost-Button, Icon)
- Hintergrund: subtiler radialer Gradient (#1e3a5f → #0f172a)

**Features** (6 Cards, 3×2 Grid)
1. 🗺️ Kartenrouting — GraphHopper, OSM, selbst gehostet
2. 📡 Live-Tracking — WebSocket, Browser-Geolocation, Fahrzeugstatus
3. 📄 Marschbefehl-PDF — Automatisch generiert aus Wegpunkten und Zeitplan
4. 🏢 Leitstellen — Zuständigkeitsgrenzen, automatische Kanalwechselpunkte
5. 🔐 Rollenmodell — Admin · Planer · Fahrer · Beobachter pro Organisation
6. 🎨 Branding — Eigenes Logo, Farben und App-Name konfigurierbar

**Wie es funktioniert** (4 Schritte, horizontal mit Verbindungspfeilen)
1. Route zeichnen — Wegpunkte auf OSM-Karte setzen
2. Zeitplan berechnen — Startzeit, Geschwindigkeiten, Haltezeiten eingeben
3. Marschbefehl exportieren — PDF, GPX oder JSON generieren
4. Live verfolgen — Fahrzeuge per WebSocket auf der Karte tracken

**Preise** (3 Spalten)

| Tier | Preis | Inhalt |
|---|---|---|
| Self-hosted | Kostenlos | Vollständiger Funktionsumfang, AGPL-3.0, Community-Support, Docker Compose |
| Starter (empfohlen) | 29 €/Monat | 1 Organisation, verwaltet, Updates inklusive, E-Mail-Support |
| Pro | 79 €/Monat | Mehrere Organisationen, Priority-Support, SLA |

Starter-Karte ist visuell hervorgehoben (Rahmen, "Empfohlen"-Badge).

**Kontakt / Demo anfragen**
- Abschnitts-Headline: "Überzeug dich selbst."
- Subline: "Wir zeigen dir ConvoyPlan in einer Live-Demo – für deine Organisation, deine Anforderungen."
- Formularfelder: Name · Organisation · E-Mail · Nachricht (optional) · Absenden
- Backend: Web3Forms (`action="https://api.web3forms.com/submit"`, access key als env-Variable in Astro)
- Erfolgsmeldung inline (kein Redirect)
- Pflichtfelder: Name, E-Mail (HTML5 validation)

**Footer**
- Logo + Slogan: "Strukturierte Marschverbandsplanung für moderne Einsatzorganisationen."
- Links: GitHub · Dokumentation · Impressum · Datenschutz
- Copyright: © 2026 RettTechSolutions · AGPL-3.0

---

### Unterseiten

**`/impressum`**
- Vollständiges Impressum gemäß § 5 TMG
- Angaben: Christoph Zeitler, christoph@zeitler.tech
- Astro-Seite, gleiches Layout wie Hauptseite (Nav + Footer)

**`/datenschutz`**
- DSGVO-konforme Datenschutzerklärung
- Hinweise zu: Web3Forms (Formular), GitHub Pages (Hosting), keine Cookies, keine Analytics
- Astro-Seite, gleiches Layout

---

## Technische Architektur

```
convoyplan-website/
├── public/
│   ├── logo/           # Kopiert aus ConvoyPlan-Repo (SVG + PNG)
│   ├── favicon.svg
│   └── CNAME           # convoyplan.de
├── src/
│   ├── components/
│   │   ├── Nav.astro
│   │   ├── Hero.astro
│   │   ├── Features.astro
│   │   ├── HowItWorks.astro
│   │   ├── Pricing.astro
│   │   ├── Contact.astro
│   │   └── Footer.astro
│   ├── layouts/
│   │   └── Base.astro  # HTML-Grundgerüst, Meta-Tags, Font
│   ├── pages/
│   │   ├── index.astro
│   │   ├── impressum.astro
│   │   └── datenschutz.astro
│   └── styles/
│       └── global.css  # CSS Custom Properties, Reset, Typo
├── astro.config.mjs    # output: static, adapter: none
└── package.json
```

**CSS-Strategie:** Kein Tailwind. CSS Custom Properties für Farben/Spacing, komponentenlokale `<style>`-Tags in Astro. Konsistent mit ConvoyPlan-Branding-Tokens.

**GitHub Actions:** Workflow `deploy.yml` — `astro build` → `gh-pages`-Branch pushen → GitHub Pages.

**Keine Analytics, keine Cookies** — DSGVO-konform ohne Banner.

---

## Farbpalette

```css
--bg-base:    #0f172a;   /* Seitenhintergrund */
--bg-card:    #1e293b;   /* Karten, Nav */
--bg-hero:    #1e3a5f;   /* Hero-Gradient-Ziel */
--accent:     #3b82f6;   /* Primärfarbe, CTAs */
--text-high:  #f8fafc;   /* Überschriften */
--text-mid:   #94a3b8;   /* Body-Text */
--text-low:   #64748b;   /* Labels, Footer */
--border:     #334155;   /* Kartenrahmen */
```

---

## Deploy-Ablauf

1. Repo `RettTechSolutions/convoyplan-website` auf GitHub anlegen
2. GitHub Pages aktivieren (Branch: `gh-pages`)
3. `CNAME`-Datei: `convoyplan.de`
4. Beim Domain-Registrar: CNAME `convoyplan.de` → `retttechsolutions.github.io`
5. Web3Forms Access Key als GitHub Secret `WEB3FORMS_KEY`
6. Push auf `main` → GitHub Action baut und deployt automatisch

---

## Out of Scope

- Mehrsprachigkeit (englisch)
- Blog / Changelog-Seite
- Authentifizierung oder Backend
- Cookie-Banner (keine Cookies gesetzt)
