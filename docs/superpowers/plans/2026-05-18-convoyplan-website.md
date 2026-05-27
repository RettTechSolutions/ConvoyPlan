# ConvoyPlan Website Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy the `convoyplan.de` marketing site as a static Astro 4 site on GitHub Pages.

**Architecture:** New repo `RettTechSolutions/convoyplan-website`, Astro 4 with `output: static`, component-per-section structure. Contact form posts to Web3Forms (no backend needed). GitHub Actions builds and deploys to `gh-pages` branch on every push to `main`.

**Tech Stack:** Astro 4, plain CSS (custom properties), Web3Forms, GitHub Pages, `withastro/action` + `peaceiris/actions-gh-pages`

---

## File Map

| File | Responsibility |
|---|---|
| `src/layouts/Base.astro` | HTML shell, `<head>`, font, global CSS import, meta tags |
| `src/styles/global.css` | CSS custom properties, reset, typography, utility classes |
| `src/components/Nav.astro` | Sticky nav bar: logo, links, CTA button |
| `src/components/Hero.astro` | Full-width hero: badge, H1, subline, 2 CTAs, gradient bg |
| `src/components/Features.astro` | 3×2 feature card grid |
| `src/components/HowItWorks.astro` | 4-step horizontal flow with arrows |
| `src/components/Pricing.astro` | 3-column pricing table, Starter highlighted |
| `src/components/Contact.astro` | Web3Forms contact form, inline success state |
| `src/components/Footer.astro` | Logo, slogan, links, copyright |
| `src/pages/index.astro` | Assembles all section components |
| `src/pages/impressum.astro` | Impressum § 5 TMG |
| `src/pages/datenschutz.astro` | DSGVO Datenschutzerklärung |
| `public/CNAME` | `convoyplan.de` for GitHub Pages custom domain |
| `public/logo/*` | Copied SVG/PNG assets from ConvoyPlan repo |
| `public/favicon.svg` | Favicon (copied from ConvoyPlan repo) |
| `astro.config.mjs` | `output: static`, `site: https://convoyplan.de` |
| `.github/workflows/deploy.yml` | Build + deploy to gh-pages on push to main |

---

## Pre-requisite: Web3Forms Access Key

Before Task 7 (Contact form), get a free Web3Forms access key:
1. Go to https://web3forms.com
2. Enter `christoph@zeitler.tech` → click "Create Access Key"
3. Check inbox for the key (format: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)
4. Add as GitHub repo secret: Settings → Secrets → `WEB3FORMS_KEY`

For local dev, create `convoyplan-website/.env` (gitignored):
```
PUBLIC_WEB3FORMS_KEY=your-key-here
```

---

## Task 1: Bootstrap Astro Project + GitHub Repo

**Files:**
- Create: `astro.config.mjs`
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `src/env.d.ts`

- [ ] **Step 1: Create GitHub repo**

```bash
gh repo create RettTechSolutions/convoyplan-website \
  --public \
  --description "ConvoyPlan marketing website – convoyplan.de" \
  --clone
cd convoyplan-website
```

- [ ] **Step 2: Scaffold Astro project**

```bash
npm create astro@latest . -- --template minimal --typescript strict --no-install --no-git
npm install
```

- [ ] **Step 3: Replace astro.config.mjs**

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';

export default defineConfig({
  output: 'static',
  site: 'https://convoyplan.de',
});
```

- [ ] **Step 4: Verify build works**

```bash
npm run build
```

Expected: `dist/` folder created, no errors.

- [ ] **Step 5: Create .gitignore and .env placeholder**

```bash
cat >> .gitignore << 'EOF'
.env
.env.local
EOF

echo "PUBLIC_WEB3FORMS_KEY=replace-me" > .env.example
```

- [ ] **Step 6: Initial commit**

```bash
git add -A
git commit -m "feat: bootstrap Astro 4 project"
git push -u origin main
```

---

## Task 2: Global CSS + Base Layout

**Files:**
- Create: `src/styles/global.css`
- Create: `src/layouts/Base.astro`
- Create: `src/env.d.ts` (already scaffolded, verify it exists)

- [ ] **Step 1: Write global.css**

```css
/* src/styles/global.css */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg-base:   #0f172a;
  --bg-card:   #1e293b;
  --bg-hero:   #1e3a5f;
  --accent:    #3b82f6;
  --accent-hv: #2563eb;
  --text-high: #f8fafc;
  --text-mid:  #94a3b8;
  --text-low:  #64748b;
  --border:    #334155;
  --radius:    8px;
  --font:      'Inter', system-ui, sans-serif;
}

html { scroll-behavior: smooth; }

body {
  background: var(--bg-base);
  color: var(--text-mid);
  font-family: var(--font);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

h1, h2, h3, h4 { color: var(--text-high); line-height: 1.2; }
h1 { font-size: clamp(2rem, 5vw, 3.5rem); font-weight: 800; letter-spacing: -0.03em; }
h2 { font-size: clamp(1.5rem, 3vw, 2.25rem); font-weight: 700; letter-spacing: -0.02em; }
h3 { font-size: 1.125rem; font-weight: 600; }

a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-hv); }

.container {
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 1.5rem;
}

.section {
  padding: 5rem 0;
}

.label {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--accent);
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: var(--accent);
  color: #fff;
  font-weight: 600;
  font-size: 0.9375rem;
  padding: 0.75rem 1.5rem;
  border-radius: var(--radius);
  border: none;
  cursor: pointer;
  transition: background 0.15s;
  text-decoration: none;
}
.btn-primary:hover { background: var(--accent-hv); color: #fff; }

.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: transparent;
  color: var(--text-mid);
  font-weight: 500;
  font-size: 0.9375rem;
  padding: 0.75rem 1.5rem;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
  text-decoration: none;
}
.btn-ghost:hover { border-color: var(--text-mid); color: var(--text-high); }
```

- [ ] **Step 2: Write Base.astro**

```astro
---
// src/layouts/Base.astro
export interface Props {
  title?: string;
  description?: string;
}
const {
  title = 'ConvoyPlan – Marschverbandsplanung für BOS',
  description = 'Kartenbasierte Marschplanung, automatischer Zeitplan, Marschbefehl-PDF und Live-Tracking für Feuerwehr, THW, Bundeswehr und Hilfsorganisationen.',
} = Astro.props;
---
<!doctype html>
<html lang="de">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="description" content={description} />
    <title>{title}</title>
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
  </head>
  <body>
    <slot />
  </body>
</html>
<style is:global>
  @import '../styles/global.css';
</style>
```

- [ ] **Step 3: Verify build**

```bash
npm run build
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/styles/global.css src/layouts/Base.astro
git commit -m "feat: add global CSS and Base layout"
```

---

## Task 3: Copy Logo Assets + CNAME

**Files:**
- Create: `public/CNAME`
- Create: `public/favicon.svg`
- Create: `public/logo/Logo Horizontal.svg`
- Create: `public/logo/Hauptlogo.svg`

- [ ] **Step 1: Copy assets from ConvoyPlan repo**

```bash
mkdir -p public/logo
cp /Users/working_chris/GitHub/MarschPlan/logo/Favicon.svg public/favicon.svg
cp "/Users/working_chris/GitHub/MarschPlan/logo/Logo Horizontal.svg" "public/logo/Logo Horizontal.svg"
cp /Users/working_chris/GitHub/MarschPlan/logo/Hauptlogo.svg public/logo/Hauptlogo.svg
cp "/Users/working_chris/GitHub/MarschPlan/logo/Logo Horizontal.png" "public/logo/Logo Horizontal.png"
```

- [ ] **Step 2: Create CNAME**

```bash
echo "convoyplan.de" > public/CNAME
```

- [ ] **Step 3: Commit**

```bash
git add public/
git commit -m "feat: add logo assets and CNAME"
```

---

## Task 4: Nav Component

**Files:**
- Create: `src/components/Nav.astro`

- [ ] **Step 1: Write Nav.astro**

```astro
---
// src/components/Nav.astro
---
<header class="nav">
  <div class="container nav-inner">
    <a href="/" class="nav-logo" aria-label="ConvoyPlan">
      <img src="/logo/Logo Horizontal.svg" alt="ConvoyPlan" height="28" />
    </a>
    <nav class="nav-links" aria-label="Hauptnavigation">
      <a href="#features">Features</a>
      <a href="#preise">Preise</a>
      <a href="https://github.com/RettTechSolutions/ConvoyPlan/wiki" target="_blank" rel="noopener">Docs</a>
      <a href="https://github.com/RettTechSolutions/ConvoyPlan" target="_blank" rel="noopener" class="nav-github" aria-label="GitHub">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.477 2 2 6.477 2 12c0 4.418 2.865 8.166 6.839 9.489.5.092.682-.217.682-.482 0-.237-.009-.868-.013-1.703-2.782.604-3.369-1.341-3.369-1.341-.454-1.154-1.11-1.462-1.11-1.462-.908-.62.069-.608.069-.608 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.269 2.75 1.025A9.578 9.578 0 0 1 12 6.836a9.59 9.59 0 0 1 2.504.337c1.909-1.294 2.747-1.025 2.747-1.025.546 1.377.202 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.741 0 .267.18.578.688.48C19.138 20.163 22 16.418 22 12c0-5.523-4.477-10-10-10z"/></svg>
      </a>
    </nav>
    <a href="#kontakt" class="btn-primary nav-cta">Demo anfragen</a>
  </div>
</header>

<style>
  .nav {
    position: sticky;
    top: 0;
    z-index: 100;
    background: rgba(15, 23, 42, 0.85);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border);
  }
  .nav-inner {
    display: flex;
    align-items: center;
    gap: 2rem;
    height: 64px;
  }
  .nav-logo img { display: block; }
  .nav-links {
    display: flex;
    align-items: center;
    gap: 1.5rem;
    margin-left: auto;
  }
  .nav-links a {
    color: var(--text-mid);
    font-size: 0.9375rem;
    font-weight: 500;
    transition: color 0.15s;
  }
  .nav-links a:hover { color: var(--text-high); }
  .nav-github { display: flex; align-items: center; }
  .nav-cta { font-size: 0.875rem; padding: 0.5rem 1.125rem; }
  @media (max-width: 640px) {
    .nav-links { display: none; }
  }
</style>
```

- [ ] **Step 2: Verify build**

```bash
npm run build
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/Nav.astro
git commit -m "feat: add Nav component"
```

---

## Task 5: Hero Component

**Files:**
- Create: `src/components/Hero.astro`

- [ ] **Step 1: Write Hero.astro**

```astro
---
// src/components/Hero.astro
---
<section class="hero">
  <div class="container hero-inner">
    <div class="label">Für BOS-Organisationen · Open Source · AGPL-3.0</div>
    <h1>Marschverbandsplanung<br />die wirklich funktioniert.</h1>
    <p class="hero-sub">
      Route planen. Zeitplan berechnen. Marschbefehl exportieren. Live-Tracking.<br />
      Alles in einem Browser-Tab – self-hosted oder verwaltet.
    </p>
    <div class="hero-ctas">
      <a href="#kontakt" class="btn-primary">Demo anfragen</a>
      <a href="https://github.com/RettTechSolutions/ConvoyPlan" target="_blank" rel="noopener" class="btn-ghost">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.477 2 2 6.477 2 12c0 4.418 2.865 8.166 6.839 9.489.5.092.682-.217.682-.482 0-.237-.009-.868-.013-1.703-2.782.604-3.369-1.341-3.369-1.341-.454-1.154-1.11-1.462-1.11-1.462-.908-.62.069-.608.069-.608 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.269 2.75 1.025A9.578 9.578 0 0 1 12 6.836a9.59 9.59 0 0 1 2.504.337c1.909-1.294 2.747-1.025 2.747-1.025.546 1.377.202 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.741 0 .267.18.578.688.48C19.138 20.163 22 16.418 22 12c0-5.523-4.477-10-10-10z"/></svg>
        GitHub ansehen
      </a>
    </div>
    <div class="hero-tags">
      <span>Feuerwehr</span>
      <span>THW</span>
      <span>Bundeswehr</span>
      <span>Hilfsorganisationen</span>
    </div>
  </div>
</section>

<style>
  .hero {
    background: radial-gradient(ellipse at 60% 0%, var(--bg-hero) 0%, var(--bg-base) 65%);
    padding: 6rem 0 5rem;
    text-align: center;
  }
  .hero-inner { display: flex; flex-direction: column; align-items: center; gap: 1.5rem; }
  .hero h1 { max-width: 720px; }
  .hero-sub {
    max-width: 560px;
    font-size: 1.125rem;
    color: var(--text-mid);
    line-height: 1.7;
  }
  .hero-ctas { display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center; }
  .hero-tags {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    justify-content: center;
    margin-top: 0.5rem;
  }
  .hero-tags span {
    font-size: 0.75rem;
    color: var(--text-low);
    background: var(--bg-card);
    border: 1px solid var(--border);
    padding: 0.25rem 0.75rem;
    border-radius: 20px;
  }
</style>
```

- [ ] **Step 2: Add to index page and verify dev server**

Create `src/pages/index.astro`:

```astro
---
// src/pages/index.astro
import Base from '../layouts/Base.astro';
import Nav from '../components/Nav.astro';
import Hero from '../components/Hero.astro';
---
<Base>
  <Nav />
  <main>
    <Hero />
  </main>
</Base>
```

```bash
npm run dev
```

Open http://localhost:4321 — verify hero section renders correctly with gradient background and two CTA buttons.

- [ ] **Step 3: Commit**

```bash
git add src/components/Hero.astro src/pages/index.astro
git commit -m "feat: add Hero component"
```

---

## Task 6: Features + HowItWorks Components

**Files:**
- Create: `src/components/Features.astro`
- Create: `src/components/HowItWorks.astro`

- [ ] **Step 1: Write Features.astro**

```astro
---
// src/components/Features.astro
const features = [
  { icon: '🗺️', title: 'Kartenrouting', desc: 'GraphHopper auf OSM-Basis, self-hosted. Wegpunkte per Klick setzen, Route sofort berechnen.' },
  { icon: '📡', title: 'Live-Tracking', desc: 'WebSocket-basiertes Echtzeit-Tracking mit Browser-Geolocation und Fahrzeugstatus.' },
  { icon: '📄', title: 'Marschbefehl-PDF', desc: 'Automatisch generiert aus Wegpunkten, Zeitplan und Fahrzeugdaten – inklusive Kanalwechseln.' },
  { icon: '🏢', title: 'Leitstellen', desc: 'Zuständigkeitsgrenzen als GeoJSON/KML importieren. Kanalwechselpunkte werden automatisch berechnet.' },
  { icon: '🔐', title: 'Rollenmodell', desc: 'Admin · Planer · Fahrer · Beobachter pro Organisation. Feingranulare Zugriffskontrolle.' },
  { icon: '🎨', title: 'Branding', desc: 'Eigenes Logo, Farben und App-Name. Jede Organisation richtet ConvoyPlan für sich ein.' },
];
---
<section class="section" id="features">
  <div class="container">
    <div class="section-header">
      <div class="label">Features</div>
      <h2>Alles was ein Marschverband braucht.</h2>
      <p>Entwickelt für die realen Anforderungen von BOS-Organisationen.</p>
    </div>
    <div class="features-grid">
      {features.map(f => (
        <div class="feature-card">
          <div class="feature-icon">{f.icon}</div>
          <h3>{f.title}</h3>
          <p>{f.desc}</p>
        </div>
      ))}
    </div>
  </div>
</section>

<style>
  .section-header { text-align: center; margin-bottom: 3rem; }
  .section-header h2 { margin: 0.75rem 0 0.75rem; }
  .section-header p { color: var(--text-mid); max-width: 480px; margin: 0 auto; }
  .features-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1.25rem;
  }
  @media (max-width: 768px) {
    .features-grid { grid-template-columns: repeat(2, 1fr); }
  }
  @media (max-width: 480px) {
    .features-grid { grid-template-columns: 1fr; }
  }
  .feature-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.5rem;
    transition: border-color 0.15s;
  }
  .feature-card:hover { border-color: var(--accent); }
  .feature-icon { font-size: 1.75rem; margin-bottom: 0.75rem; }
  .feature-card h3 { margin-bottom: 0.5rem; }
  .feature-card p { font-size: 0.9375rem; color: var(--text-mid); line-height: 1.6; }
</style>
```

- [ ] **Step 2: Write HowItWorks.astro**

```astro
---
// src/components/HowItWorks.astro
const steps = [
  { num: '01', title: 'Route zeichnen', desc: 'Wegpunkte auf der OSM-Karte setzen. GraphHopper berechnet die optimale Route.' },
  { num: '02', title: 'Zeitplan berechnen', desc: 'Startzeit, Geschwindigkeiten und Haltezeiten eingeben – Ankunftszeiten werden automatisch berechnet.' },
  { num: '03', title: 'Befehl exportieren', desc: 'Marschbefehl als PDF, GPX oder JSON exportieren und an die Fahrzeugführer weitergeben.' },
  { num: '04', title: 'Live verfolgen', desc: 'Fahrzeuge senden ihren Standort per Browser. Alle sehen den aktuellen Stand auf der Karte.' },
];
---
<section class="section how" id="wie-es-funktioniert">
  <div class="container">
    <div class="section-header">
      <div class="label">Wie es funktioniert</div>
      <h2>Von der Route zum laufenden Konvoi.</h2>
    </div>
    <div class="steps">
      {steps.map((s, i) => (
        <div class="step">
          <div class="step-num">{s.num}</div>
          <h3>{s.title}</h3>
          <p>{s.desc}</p>
          {i < steps.length - 1 && <div class="step-arrow">→</div>}
        </div>
      ))}
    </div>
  </div>
</section>

<style>
  .how { background: var(--bg-card); }
  .section-header { text-align: center; margin-bottom: 3rem; }
  .section-header h2 { margin: 0.75rem 0 0; }
  .steps {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0;
    position: relative;
  }
  @media (max-width: 768px) {
    .steps { grid-template-columns: repeat(2, 1fr); gap: 1.5rem; }
    .step-arrow { display: none; }
  }
  .step {
    position: relative;
    padding: 1.5rem 1rem 1.5rem 0;
    text-align: center;
  }
  .step-num {
    font-size: 2.5rem;
    font-weight: 800;
    color: var(--accent);
    opacity: 0.25;
    line-height: 1;
    margin-bottom: 0.75rem;
  }
  .step h3 { margin-bottom: 0.5rem; font-size: 1rem; }
  .step p { font-size: 0.875rem; color: var(--text-mid); line-height: 1.6; }
  .step-arrow {
    position: absolute;
    right: -0.75rem;
    top: 50%;
    transform: translateY(-50%);
    color: var(--border);
    font-size: 1.5rem;
    z-index: 1;
  }
</style>
```

- [ ] **Step 3: Add both to index.astro**

```astro
---
import Base from '../layouts/Base.astro';
import Nav from '../components/Nav.astro';
import Hero from '../components/Hero.astro';
import Features from '../components/Features.astro';
import HowItWorks from '../components/HowItWorks.astro';
---
<Base>
  <Nav />
  <main>
    <Hero />
    <Features />
    <HowItWorks />
  </main>
</Base>
```

- [ ] **Step 4: Check dev server — verify 6 feature cards and 4 steps render**

```bash
npm run dev
```

- [ ] **Step 5: Commit**

```bash
git add src/components/Features.astro src/components/HowItWorks.astro src/pages/index.astro
git commit -m "feat: add Features and HowItWorks components"
```

---

## Task 7: Pricing Component

**Files:**
- Create: `src/components/Pricing.astro`

- [ ] **Step 1: Write Pricing.astro**

```astro
---
// src/components/Pricing.astro
const tiers = [
  {
    name: 'Self-hosted',
    price: 'Kostenlos',
    sub: 'für immer',
    highlight: false,
    features: [
      'Vollständiger Funktionsumfang',
      'Docker Compose Setup',
      'AGPL-3.0 Lizenz',
      'Community-Support (GitHub)',
      'Updates selbst einspielen',
    ],
    cta: { label: 'GitHub ansehen', href: 'https://github.com/RettTechSolutions/ConvoyPlan', external: true },
  },
  {
    name: 'Starter',
    price: '29 €',
    sub: 'pro Monat',
    highlight: true,
    badge: 'Empfohlen',
    features: [
      '1 Organisation',
      'Verwalteter Betrieb',
      'Automatische Updates',
      'SSL & Domain inklusive',
      'E-Mail-Support',
    ],
    cta: { label: 'Demo anfragen', href: '#kontakt', external: false },
  },
  {
    name: 'Pro',
    price: '79 €',
    sub: 'pro Monat',
    highlight: false,
    features: [
      'Mehrere Organisationen',
      'Verwalteter Betrieb',
      'Automatische Updates',
      'Priority-Support',
      'SLA auf Anfrage',
    ],
    cta: { label: 'Demo anfragen', href: '#kontakt', external: false },
  },
];
---
<section class="section" id="preise">
  <div class="container">
    <div class="section-header">
      <div class="label">Preise</div>
      <h2>Transparent. Kein Vendor Lock-in.</h2>
      <p>Self-hosted ist und bleibt kostenlos. Hosted-Variante für alle die einfach loslegen wollen.</p>
    </div>
    <div class="pricing-grid">
      {tiers.map(t => (
        <div class:list={['pricing-card', { highlight: t.highlight }]}>
          {t.badge && <div class="pricing-badge">{t.badge}</div>}
          <div class="pricing-name">{t.name}</div>
          <div class="pricing-price">
            {t.price} <span class="pricing-sub">{t.sub}</span>
          </div>
          <ul class="pricing-features">
            {t.features.map(f => <li><span class="check">✓</span>{f}</li>)}
          </ul>
          {t.cta.external
            ? <a href={t.cta.href} target="_blank" rel="noopener" class:list={[t.highlight ? 'btn-primary' : 'btn-ghost', 'pricing-cta']}>{t.cta.label}</a>
            : <a href={t.cta.href} class:list={[t.highlight ? 'btn-primary' : 'btn-ghost', 'pricing-cta']}>{t.cta.label}</a>
          }
        </div>
      ))}
    </div>
  </div>
</section>

<style>
  .section-header { text-align: center; margin-bottom: 3rem; }
  .section-header h2 { margin: 0.75rem 0 0.75rem; }
  .section-header p { color: var(--text-mid); max-width: 480px; margin: 0 auto; }
  .pricing-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1.25rem;
    align-items: start;
  }
  @media (max-width: 768px) { .pricing-grid { grid-template-columns: 1fr; max-width: 400px; margin: 0 auto; } }
  .pricing-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 2rem 1.5rem;
    position: relative;
  }
  .pricing-card.highlight {
    border-color: var(--accent);
    background: #1a2d4a;
  }
  .pricing-badge {
    position: absolute;
    top: -0.75rem;
    left: 50%;
    transform: translateX(-50%);
    background: var(--accent);
    color: #fff;
    font-size: 0.6875rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    padding: 0.25rem 0.75rem;
    border-radius: 20px;
    white-space: nowrap;
  }
  .pricing-name { font-size: 0.875rem; font-weight: 600; color: var(--text-mid); margin-bottom: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .pricing-price { font-size: 2rem; font-weight: 800; color: var(--text-high); margin-bottom: 0.25rem; }
  .pricing-sub { font-size: 0.875rem; font-weight: 400; color: var(--text-low); }
  .pricing-features { list-style: none; margin: 1.5rem 0; display: flex; flex-direction: column; gap: 0.625rem; }
  .pricing-features li { font-size: 0.9375rem; color: var(--text-mid); display: flex; align-items: baseline; gap: 0.5rem; }
  .check { color: var(--accent); font-weight: 700; flex-shrink: 0; }
  .pricing-cta { width: 100%; justify-content: center; }
</style>
```

- [ ] **Step 2: Add to index.astro**

```astro
---
import Base from '../layouts/Base.astro';
import Nav from '../components/Nav.astro';
import Hero from '../components/Hero.astro';
import Features from '../components/Features.astro';
import HowItWorks from '../components/HowItWorks.astro';
import Pricing from '../components/Pricing.astro';
---
<Base>
  <Nav />
  <main>
    <Hero />
    <Features />
    <HowItWorks />
    <Pricing />
  </main>
</Base>
```

- [ ] **Step 3: Verify 3 pricing cards render, Starter is highlighted**

```bash
npm run dev
```

- [ ] **Step 4: Commit**

```bash
git add src/components/Pricing.astro src/pages/index.astro
git commit -m "feat: add Pricing component"
```

---

## Task 8: Contact Form Component

**Pre-requisite:** Web3Forms access key must be in `.env` as `PUBLIC_WEB3FORMS_KEY`.

**Files:**
- Create: `src/components/Contact.astro`

- [ ] **Step 1: Write Contact.astro**

```astro
---
// src/components/Contact.astro
const key = import.meta.env.PUBLIC_WEB3FORMS_KEY ?? '';
---
<section class="section contact-section" id="kontakt">
  <div class="container">
    <div class="contact-inner">
      <div class="contact-text">
        <div class="label">Demo anfragen</div>
        <h2>Überzeug dich selbst.</h2>
        <p>Wir zeigen dir ConvoyPlan in einer Live-Demo – für deine Organisation, deine Anforderungen. Kein Verkaufsgespräch, einfach das Tool in Aktion.</p>
        <ul class="contact-bullets">
          <li>✓ Kostenlose Demo</li>
          <li>✓ Keine Vertragsbindung</li>
          <li>✓ Antwort innerhalb von 24 Stunden</li>
        </ul>
      </div>
      <div class="contact-form-wrap">
        <form
          id="demo-form"
          action="https://api.web3forms.com/submit"
          method="POST"
          class="contact-form"
        >
          <input type="hidden" name="access_key" value={key} />
          <input type="hidden" name="subject" value="ConvoyPlan Demo-Anfrage" />
          <input type="hidden" name="redirect" value="false" />
          <input type="checkbox" name="botcheck" style="display:none" tabindex="-1" autocomplete="off" />

          <div class="form-row">
            <label for="name">Name <span class="required">*</span></label>
            <input type="text" id="name" name="name" required placeholder="Max Mustermann" />
          </div>
          <div class="form-row">
            <label for="org">Organisation</label>
            <input type="text" id="org" name="organisation" placeholder="Feuerwehr Musterstadt" />
          </div>
          <div class="form-row">
            <label for="email">E-Mail <span class="required">*</span></label>
            <input type="email" id="email" name="email" required placeholder="max@beispiel.de" />
          </div>
          <div class="form-row">
            <label for="msg">Nachricht</label>
            <textarea id="msg" name="message" rows="3" placeholder="Kurze Beschreibung eurer Anforderungen (optional)"></textarea>
          </div>
          <button type="submit" class="btn-primary submit-btn">Demo anfragen</button>
          <p id="form-success" class="form-success" hidden>
            ✓ Nachricht gesendet! Wir melden uns innerhalb von 24 Stunden.
          </p>
          <p id="form-error" class="form-error" hidden>
            Etwas ist schiefgelaufen. Bitte versuch es erneut oder schreib direkt an
            <a href="mailto:christoph@zeitler.tech">christoph@zeitler.tech</a>.
          </p>
        </form>
      </div>
    </div>
  </div>
</section>

<script>
  const form = document.getElementById('demo-form') as HTMLFormElement;
  const success = document.getElementById('form-success')!;
  const error = document.getElementById('form-error')!;
  const btn = form?.querySelector('button[type="submit"]') as HTMLButtonElement;

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    btn.disabled = true;
    btn.textContent = 'Wird gesendet…';
    try {
      const res = await fetch(form.action, { method: 'POST', body: new FormData(form) });
      const data = await res.json();
      if (data.success) {
        form.reset();
        success.hidden = false;
        error.hidden = true;
      } else {
        throw new Error('not ok');
      }
    } catch {
      error.hidden = false;
      success.hidden = true;
    } finally {
      btn.disabled = false;
      btn.textContent = 'Demo anfragen';
    }
  });
</script>

<style>
  .contact-section { background: var(--bg-card); }
  .contact-inner {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4rem;
    align-items: start;
  }
  @media (max-width: 768px) { .contact-inner { grid-template-columns: 1fr; gap: 2rem; } }
  .contact-text h2 { margin: 0.75rem 0 1rem; }
  .contact-text p { color: var(--text-mid); line-height: 1.7; }
  .contact-bullets { list-style: none; margin-top: 1.25rem; display: flex; flex-direction: column; gap: 0.5rem; }
  .contact-bullets li { font-size: 0.9375rem; color: var(--text-mid); }
  .contact-form-wrap {
    background: var(--bg-base);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 2rem;
  }
  .contact-form { display: flex; flex-direction: column; gap: 1.25rem; }
  .form-row { display: flex; flex-direction: column; gap: 0.375rem; }
  .form-row label { font-size: 0.875rem; font-weight: 500; color: var(--text-high); }
  .required { color: var(--accent); }
  .form-row input,
  .form-row textarea {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-high);
    font-size: 0.9375rem;
    font-family: var(--font);
    padding: 0.625rem 0.875rem;
    transition: border-color 0.15s;
    outline: none;
  }
  .form-row input:focus,
  .form-row textarea:focus { border-color: var(--accent); }
  .form-row input::placeholder,
  .form-row textarea::placeholder { color: var(--text-low); }
  .form-row textarea { resize: vertical; min-height: 80px; }
  .submit-btn { align-self: flex-start; }
  .form-success { color: #4ade80; font-size: 0.9375rem; }
  .form-error { font-size: 0.9375rem; color: #f87171; }
  .form-error a { color: #f87171; text-decoration: underline; }
</style>
```

- [ ] **Step 2: Add to index.astro**

```astro
---
import Base from '../layouts/Base.astro';
import Nav from '../components/Nav.astro';
import Hero from '../components/Hero.astro';
import Features from '../components/Features.astro';
import HowItWorks from '../components/HowItWorks.astro';
import Pricing from '../components/Pricing.astro';
import Contact from '../components/Contact.astro';
---
<Base>
  <Nav />
  <main>
    <Hero />
    <Features />
    <HowItWorks />
    <Pricing />
    <Contact />
  </main>
</Base>
```

- [ ] **Step 3: Test form locally**

```bash
npm run dev
```

Fill in the form and submit. Expected: success message appears inline, no page redirect. Check `christoph@zeitler.tech` inbox for test email.

- [ ] **Step 4: Commit**

```bash
git add src/components/Contact.astro src/pages/index.astro
git commit -m "feat: add Contact form with Web3Forms"
```

---

## Task 9: Footer Component + Complete Index Page

**Files:**
- Create: `src/components/Footer.astro`
- Modify: `src/pages/index.astro`

- [ ] **Step 1: Write Footer.astro**

```astro
---
// src/components/Footer.astro
const year = new Date().getFullYear();
---
<footer class="footer">
  <div class="container footer-inner">
    <div class="footer-brand">
      <img src="/logo/Logo Horizontal.svg" alt="ConvoyPlan" height="22" />
      <p>Strukturierte Marschverbandsplanung<br />für moderne Einsatzorganisationen.</p>
    </div>
    <nav class="footer-links" aria-label="Footer-Navigation">
      <a href="https://github.com/RettTechSolutions/ConvoyPlan" target="_blank" rel="noopener">GitHub</a>
      <a href="https://github.com/RettTechSolutions/ConvoyPlan/wiki" target="_blank" rel="noopener">Dokumentation</a>
      <a href="/impressum">Impressum</a>
      <a href="/datenschutz">Datenschutz</a>
    </nav>
    <p class="footer-copy">© {year} RettTechSolutions · AGPL-3.0</p>
  </div>
</footer>

<style>
  .footer {
    border-top: 1px solid var(--border);
    padding: 3rem 0 2rem;
  }
  .footer-inner {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1.5rem;
    text-align: center;
  }
  .footer-brand { display: flex; flex-direction: column; align-items: center; gap: 0.75rem; }
  .footer-brand p { font-size: 0.875rem; color: var(--text-low); line-height: 1.6; }
  .footer-links { display: flex; gap: 1.5rem; flex-wrap: wrap; justify-content: center; }
  .footer-links a { font-size: 0.875rem; color: var(--text-low); transition: color 0.15s; }
  .footer-links a:hover { color: var(--text-mid); }
  .footer-copy { font-size: 0.8125rem; color: var(--text-low); }
</style>
```

- [ ] **Step 2: Complete index.astro with all components**

```astro
---
import Base from '../layouts/Base.astro';
import Nav from '../components/Nav.astro';
import Hero from '../components/Hero.astro';
import Features from '../components/Features.astro';
import HowItWorks from '../components/HowItWorks.astro';
import Pricing from '../components/Pricing.astro';
import Contact from '../components/Contact.astro';
import Footer from '../components/Footer.astro';
---
<Base>
  <Nav />
  <main>
    <Hero />
    <Features />
    <HowItWorks />
    <Pricing />
    <Contact />
  </main>
  <Footer />
</Base>
```

- [ ] **Step 3: Full build check**

```bash
npm run build && npm run preview
```

Open http://localhost:4321 — scroll through entire page, verify all sections render.

- [ ] **Step 4: Commit**

```bash
git add src/components/Footer.astro src/pages/index.astro
git commit -m "feat: add Footer, complete index page"
```

---

## Task 10: Impressum + Datenschutz Pages

**Files:**
- Create: `src/pages/impressum.astro`
- Create: `src/pages/datenschutz.astro`

- [ ] **Step 1: Write impressum.astro**

```astro
---
// src/pages/impressum.astro
import Base from '../layouts/Base.astro';
import Nav from '../components/Nav.astro';
import Footer from '../components/Footer.astro';
---
<Base title="Impressum – ConvoyPlan">
  <Nav />
  <main class="legal-page">
    <div class="container">
      <h1>Impressum</h1>
      <p>Angaben gemäß § 5 TMG</p>

      <h2>Verantwortlich</h2>
      <p>
        Christoph Zeitler<br />
        RettTechSolutions<br />
        E-Mail: <a href="mailto:christoph@zeitler.tech">christoph@zeitler.tech</a>
      </p>

      <h2>Haftungsausschluss</h2>
      <p>Die Inhalte dieser Website wurden mit größtmöglicher Sorgfalt erstellt. Für die Richtigkeit, Vollständigkeit und Aktualität der Inhalte übernehmen wir keine Gewähr.</p>

      <h2>Streitbeilegung</h2>
      <p>Die Europäische Kommission stellt eine Plattform zur Online-Streitbeilegung (OS) bereit: <a href="https://ec.europa.eu/consumers/odr" target="_blank" rel="noopener">https://ec.europa.eu/consumers/odr</a>. Wir sind nicht bereit und nicht verpflichtet, an einem Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.</p>
    </div>
  </main>
  <Footer />
</Base>
```

- [ ] **Step 2: Write datenschutz.astro**

```astro
---
// src/pages/datenschutz.astro
import Base from '../layouts/Base.astro';
import Nav from '../components/Nav.astro';
import Footer from '../components/Footer.astro';
---
<Base title="Datenschutz – ConvoyPlan">
  <Nav />
  <main class="legal-page">
    <div class="container">
      <h1>Datenschutzerklärung</h1>

      <h2>1. Verantwortlicher</h2>
      <p>Christoph Zeitler, RettTechSolutions, christoph@zeitler.tech</p>

      <h2>2. Hosting</h2>
      <p>Diese Website wird über GitHub Pages (GitHub Inc., 88 Colin P Kelly Jr St, San Francisco, CA 94107, USA) gehostet. GitHub erhebt beim Aufruf der Website möglicherweise Server-Logfiles. Weitere Informationen: <a href="https://docs.github.com/en/site-policy/privacy-policies/github-privacy-statement" target="_blank" rel="noopener">GitHub Privacy Statement</a>.</p>

      <h2>3. Kontaktformular</h2>
      <p>Wenn du das Demo-Formular nutzt, werden deine Angaben (Name, E-Mail, Organisation, Nachricht) über den Dienst Web3Forms (web3forms.com) verarbeitet und per E-Mail an uns übermittelt. Die Daten werden ausschließlich zur Bearbeitung deiner Anfrage verwendet und nicht an Dritte weitergegeben. Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO.</p>

      <h2>4. Cookies und Tracking</h2>
      <p>Diese Website setzt keine Cookies und verwendet keine Analyse- oder Tracking-Dienste.</p>

      <h2>5. Deine Rechte</h2>
      <p>Du hast das Recht auf Auskunft, Berichtigung, Löschung und Einschränkung der Verarbeitung deiner Daten sowie das Recht auf Datenübertragbarkeit. Wende dich dafür an: <a href="mailto:christoph@zeitler.tech">christoph@zeitler.tech</a></p>
    </div>
  </main>
  <Footer />
</Base>
```

- [ ] **Step 3: Add legal page styles to global.css**

Append to `src/styles/global.css`:

```css
/* Legal pages */
.legal-page {
  padding: 4rem 0 6rem;
}
.legal-page h1 {
  margin-bottom: 0.5rem;
}
.legal-page h2 {
  font-size: 1.125rem;
  margin: 2rem 0 0.5rem;
}
.legal-page p {
  color: var(--text-mid);
  line-height: 1.7;
  max-width: 680px;
}
.legal-page a {
  color: var(--accent);
}
```

- [ ] **Step 4: Build and verify both pages exist**

```bash
npm run build
ls dist/impressum/index.html dist/datenschutz/index.html
```

Expected: both files present.

- [ ] **Step 5: Commit**

```bash
git add src/pages/impressum.astro src/pages/datenschutz.astro src/styles/global.css
git commit -m "feat: add Impressum and Datenschutz pages"
```

---

## Task 11: GitHub Actions Deploy Workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Enable GitHub Pages on the repo**

```bash
gh api repos/RettTechSolutions/convoyplan-website \
  --method PATCH \
  --field has_pages=true
```

- [ ] **Step 2: Write deploy.yml**

```yaml
# .github/workflows/deploy.yml
name: Deploy to GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
      - run: npm ci
      - run: npm run build
        env:
          PUBLIC_WEB3FORMS_KEY: ${{ secrets.WEB3FORMS_KEY }}
      - uses: actions/upload-pages-artifact@v3
        with:
          path: dist

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/deploy-pages@v4
        id: deployment
```

- [ ] **Step 3: Add WEB3FORMS_KEY secret to GitHub repo**

```bash
gh secret set WEB3FORMS_KEY --repo RettTechSolutions/convoyplan-website
# paste your Web3Forms access key when prompted
```

- [ ] **Step 4: Commit and push — triggers first deploy**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add GitHub Pages deploy workflow"
git push
```

- [ ] **Step 5: Monitor deploy**

```bash
gh run watch --repo RettTechSolutions/convoyplan-website
```

Expected: workflow completes successfully, site live at `https://retttechsolutions.github.io/convoyplan-website/`.

---

## Task 12: Custom Domain Setup

**Pre-requisite:** Access to DNS settings for `convoyplan.de` at your domain registrar.

- [ ] **Step 1: Verify CNAME file exists in dist**

```bash
npm run build && cat dist/CNAME
```

Expected output: `convoyplan.de`

- [ ] **Step 2: Configure DNS at registrar**

Add these DNS records at your registrar for `convoyplan.de`:

```
Type   Name   Value
A      @      185.199.108.153
A      @      185.199.109.153
A      @      185.199.110.153
A      @      185.199.111.153
CNAME  www    retttechsolutions.github.io
```

- [ ] **Step 3: Enable custom domain in GitHub Pages settings**

```bash
gh api repos/RettTechSolutions/convoyplan-website/pages \
  --method PUT \
  --field cname=convoyplan.de \
  --field https_enforced=true
```

- [ ] **Step 4: Wait for DNS propagation and verify**

```bash
dig convoyplan.de +short
# Expected: one of the 4 GitHub IPs above

curl -I https://convoyplan.de
# Expected: HTTP/2 200
```

DNS propagation can take up to 24 hours. GitHub will automatically provision an SSL certificate via Let's Encrypt once DNS resolves.

---

## Self-Review

**Spec coverage check:**
- ✅ Dark Professional design (global.css color palette)
- ✅ Nav: logo, links, sticky, CTA
- ✅ Hero: badge, H1, subline, 2 CTAs, gradient
- ✅ Features: 6 cards 3×2 grid
- ✅ HowItWorks: 4 steps
- ✅ Pricing: 3 tiers, Starter highlighted
- ✅ Contact: Web3Forms, inline success, christoph@zeitler.tech
- ✅ Footer: logo, links, copyright
- ✅ /impressum page
- ✅ /datenschutz page (DSGVO, Web3Forms mention)
- ✅ CNAME: convoyplan.de
- ✅ GitHub Actions deploy workflow
- ✅ No cookies/analytics (confirmed in Datenschutz)
- ✅ Logo assets copied from ConvoyPlan repo

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:** No TypeScript types beyond Astro Props interface. All component imports use consistent filenames matching the File Map.
