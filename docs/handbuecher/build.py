#!/usr/bin/env python3
"""Baut die Handbücher als PDF: Markdown → Pandoc-HTML → Chromium.

Quelle sind das Wiki und die ``docs/`` der vier Repos. ConvoyPlan ist
öffentlich, Begleit-App, Tracker und EventTracker sind es nicht. Daraus folgen
zwei Sorten Buch:

- **öffentlich** (``ziel=OEFFENTLICH``): landet in ``frontend/static/handbuecher/``
  und damit auf jeder Instanz unter ``/handbuecher``. Darin nur, was ohnehin
  öffentlich ist oder für Anwender geschrieben wurde; Verweise in private Repos
  werden zu Text, weil sie draußen 404 ergäben.
- **privat**: landet in ``docs/handbuch/`` des jeweiligen Repos.

Die privaten Repos werden als Geschwister dieses Repos erwartet
(``../Convoyplan-Companion`` usw.). Fehlt eins, wird das Buch übersprungen.

Zwei Durchgänge je Buch: der erste ermittelt die Seitenzahlen fürs
Inhaltsverzeichnis (Suche der Überschriften per pdftotext), der zweite setzt sie.

Aufruf: ``python3 docs/handbuecher/build.py [slug …]`` — siehe README daneben.
"""
import html, json, re, subprocess, sys, datetime
from pathlib import Path

HIER = Path(__file__).resolve().parent
CP = HIER.parents[1]
ROOT = CP.parent
WORK = HIER / ".work"
CACHE = HIER / ".cache"
OEFFENTLICH = CP / "frontend/static/handbuecher"
KATALOG = CP / "frontend/src/lib/handbuecher/katalog.json"
MERMAID = "mermaid@11.4.1"

GH = {
    "ConvoyPlan": "RettTechSolutions/ConvoyPlan",
    "Convoyplan-Companion": "RettTechSolutions/Convoyplan-Companion",
    "ConvoyPlan-Tracker": "RettTechSolutions/ConvoyPlan-Tracker",
    "Convoyplan-EventTracker": "RettTechSolutions/Convoyplan-EventTracker",
}
PRIVAT = {"Convoyplan-Companion", "ConvoyPlan-Tracker", "Convoyplan-EventTracker"}

# Zeilen, die in eine Datei für Entwickler gehören, aber nicht ins Handbuch.
STREICHEN = {
    "Convoyplan-Companion/docs/ANLEITUNG.md": [r"^Für Besatzungen\. Vorgesehen für das Wiki.*$"],
}

W = "ConvoyPlan/wiki/"
C = "Convoyplan-Companion/"
T = "ConvoyPlan-Tracker/"
E = "Convoyplan-EventTracker/"
BOOKS = [
    dict(slug="ConvoyPlan-Anwenderhandbuch", title="Anwenderhandbuch", ziel=OEFFENTLICH,
         fuer="Planer, Fahrer und Beobachter",
         subtitle="Konvois planen, Fahrzeuge führen, live verfolgen — für Planer, Fahrer und Beobachter",
         product="ConvoyPlan", parts=[
            ("Einstieg", [W+"Home.md", W+"Funktionsumfang.md", W+"Erste-Schritte.md"]),
            ("Bedienung", [W+"Benutzerhandbuch.md", W+"Konvoi-Planung.md", W+"Fahrzeuge.md",
                           W+"Live-Tracking.md", W+"Marschbefehl-Export.md", W+"Teilen.md",
                           W+"Aktionsseite.md", W+"Tracker.md", W+"Rollen.md", W+"Meldungen.md"]),
            ("Fragen & Antworten", [W+"FAQ.md"]),
         ]),
    dict(slug="ConvoyPlan-Betriebshandbuch", title="Betriebs- und Administrationshandbuch", ziel=OEFFENTLICH,
         fuer="Betreiber und Administratoren einer Instanz",
         subtitle="Installation, Betrieb, Sicherheit, Lizenz und Schnittstellen einer ConvoyPlan-Instanz",
         product="ConvoyPlan", parts=[
            ("Installation & Architektur", [W+"Installation-und-Setup.md", W+"Systemuebersicht.md",
                                            W+"Multi-Tenancy.md", W+"Verkehrsdaten.md"]),
            ("Laufender Betrieb", [W+"Auto-Updater.md", "ConvoyPlan/docs/backup-restore.md",
                                   W+"Lizenz-und-Demo-Modus.md", W+"Sicherheit-und-Datenschutz.md"]),
            ("Schnittstellen", [W+"API-Dokumentation.md", W+"MCP-Server.md", W+"ChatGPT-verbinden.md",
                                W+"Agenten-Auskunft.md"]),
            ("Entwicklung", [W+"Entwicklung.md"]),
         ]),
    dict(slug="ConvoyPlan-Begleit-App", title="Begleit-App", ziel=OEFFENTLICH,
         fuer="Besatzungen und Planer unterwegs",
         subtitle="ConvoyPlan Companion für iOS und Android — anmelden, mitfahren, melden, am Autodisplay",
         product="ConvoyPlan Companion", parts=[
            ("Bedienung", [C+"docs/ANLEITUNG.md", C+"docs/GLOSSARY.md"]),
         ]),
    dict(slug="ConvoyPlan-Companion-Handbuch", title="Handbuch Begleit-App (intern)", ziel=ROOT / C / "docs/handbuch",
         subtitle="ConvoyPlan Companion — Bedienung, Autodisplay, Datenschutz, Schnittstelle, Bau und Verteilung",
         product="ConvoyPlan Companion", parts=[
            ("Für Besatzungen", [C+"docs/ANLEITUNG.md", C+"docs/GLOSSARY.md"]),
            ("Autodisplay & Datenschutz", [C+"docs/CARPLAY.md", C+"docs/ANDROID-AUTO.md", C+"docs/DATENSCHUTZ.md"]),
            ("Technik & Verteilung", [C+"README.md", C+"docs/API.md", C+"docs/DEVICE.md",
                                      C+"docs/TESTERBUILD.md", C+"docs/KACHELQUELLE.md"]),
         ]),
    dict(slug="ConvoyPlan-Tracker-Handbuch", title="Handbuch Tracker (intern)", ziel=ROOT / T / "docs/handbuch",
         subtitle="Feste Ortungsgeräte: Einrichtung in ConvoyPlan, Hardware, Firmware, Protokoll und Simulator",
         product="ConvoyPlan-Tracker", parts=[
            ("Tracker in ConvoyPlan", [W+"Tracker.md"]),
            ("Gerät", [T+"README.md", T+"hardware/STUECKLISTE.md", T+"firmware/README.md",
                       T+"docs/FIRMWARE-ABLAGE.md", T+"docs/BOARDTEST-FUNK.md"]),
            ("Protokoll & Prüfung", [T+"docs/PROTOKOLL.md", T+"simulator/README.md"]),
            ("Konzept", [T+"docs/PLAN.md"]),
         ]),
    dict(slug="ConvoyPlan-EventTracker-Handbuch", title="Handbuch Aktionsseite & EventTracker (intern)",
         ziel=ROOT / E / "docs/handbuch",
         subtitle="Öffentliche, verzögerte Konvoi-Karte für Presse, Spender und Veranstaltungen",
         product="Convoyplan-EventTracker", parts=[
            ("Aktionsseite in ConvoyPlan", [W+"Aktionsseite.md"]),
            ("EventTracker betreiben", [E+"README.md", E+"RELEASING.md"]),
         ]),
]


# Bildschirmfotos: docs/screenshots/ (älter) und bilder/ (aufgenommen am 28. und 31.10.2026 in einer
# Demo-Organisation; Namen, E-Mail-Adressen, Slug, IMEI und Bot-Name vor der Aufnahme ersetzt).
SHOTS = CP / "docs/screenshots"
LIVE = HIER / "bilder"
FIGURES = {
    "Erste-Schritte": [
        ("admin-00-Mitglieder.jpg", "Org-Admin, Reiter „Mitglieder“: bestehendes Konto hinzufügen, Rolle je Mitglied", "Mitglieder einladen"),
        (["start.jpg", "org-login.jpg"], "Startseite mit Organisations-Code (links) und Anmeldung in der Organisation (rechts)", "Registrierung & Login"),
        ("plan-plan.jpg", "Planungsansicht: Seitenleiste mit Reitern, Karte mit Route und Wegpunkten", "Oberfläche im Überblick"),
        ("tour.jpg", "Die Einführungstour beim ersten Anmelden — jederzeit über „?“ erneut startbar", "Oberfläche im Überblick"),
        (["tel-plan-schublade.jpg", "tel-plan.jpg"], "Planung am Telefon: Schublade mit Reitern (links) und Karte (rechts)", "Oberfläche im Überblick"),
    ],
    "Konvoi-Planung": [
        ("admin-01-Leitstellen.jpg", "Org-Admin, Reiter „Leitstellen“: Zuständigkeitsgebiete auf der Karte und gruppierte Liste", "Leitstellen & Kanalwechsel"),
        ("Routenplanung.png", "Routenplanung: Wegpunkte, Route und Marschverband", None),
        ("plan-route.jpg", "Reiter „Route“: Länge, Fahrzeit, zusammengelegte Halte, Durchfahrtshöhen und Gewichtsgrenzen", "Route festlegen"),
        ("plan-wegpunkte.jpg", "Reiter „Wegpunkte“: Kontrollpunkte und Tankhalt mit Haltedauer", "Wegpunkte hinzufügen"),
        ("plan-route-hinweise.jpg", "Aufgeklappte Hinweise: Brücken ohne Höhenangabe entlang der Route", "Durchfahrtshöhen"),
    ],
    "Fahrzeuge": [("plan-fahrzeuge.jpg", "Reiter „Fahrzeuge“: Fahrzeugpool mit Funkrufnamen, Stärke und Reichweite", "Fahrzeug einem Konvoi zuweisen")],
    "Live-Tracking": [
        ("LiveTracking.png", "Live-Tracking mit Fahrzeugpositionen und Status", None),
        ("tracking.jpg", "Tracking-Ansicht: Konvoistatus, eigene Position, Verbandsstärke und Betriebsstoff je Fahrzeug", "Übersicht"),
        (["fahrer-tel-karte.jpg", "fahrer-tel-schublade.jpg"], "Fahrer-Link am Telefon: Karte mit Hinweis auf den nächsten Wegpunkt (links), eigenes Fahrzeug mit Status und Stärke (rechts)", "Tracking als Fahrer starten"),
        ("teilen-qr.jpg", "QR-Code eines Fahrer-Links zum Weitergeben", "Den Link weitergeben (QR)"),
        ("tracking-status.jpg", "Reiter „Status“ in der Tracking-Ansicht", "Fahrzeugstatus melden"),
        ("fahrer-desktop.jpg", "Fahrer-Link am Schreibtisch: Status melden, Stärke melden, Fahrzeugliste", "Fahrzeugstatus melden"),
        ("tel-tracking.jpg", "Tracking am Telefon mit Hinweis auf den nächsten Wegpunkt", "Karte bedienen"),
    ],
    "Marschbefehl-Export": [
        ("admin-05-Marschbefehl.jpg", "Org-Admin, Reiter „Marschbefehl“: Word-Vorlage hochladen oder Beispielvorlage herunterladen", "Vorlage einrichten (Org-Admin)"),
        ("plan-export.jpg", "Reiter „Export“: GPX, JSON, Marschbefehl, Roadbook, Live-Tracking und Teilen", None),
        ("export-marschbefehl.jpg", "Marschbefehl ausfüllen, gegliedert nach dem 5-Punkte-Befehl", "Pflichtfelder befüllen"),
        ("export-pdf-s-1.jpg", "Erzeugter Marschbefehl (PDF), erste Seite", "PDF generieren"),
        ("export-roadbook-s-1.jpg", "Erzeugtes Roadbook (PDF), erste Seite mit Karte und Abbiegehinweisen", "Roadbook (PDF)"),
    ],
    "Teilen": [("teilen-dialog.jpg", "Teilen-Dialog: Lese- oder Fahrer-Link anlegen, vorhandene Links mit QR-Code und Widerruf", "Link erstellen")],
    "Rollen": [("admin-tel.jpg", "Mitgliederverwaltung am Telefon", "Rollenänderung"), ("Berechtigungen.png", "Rollen und Berechtigungen im Org-Admin", None)],
    "Benutzerhandbuch": [("Leitstellen.png", "Leitstellen und Kanalwechsel", "Leitstellen und Kanalwechsel"),
                         ("Branding.png", "Branding einer Organisation", "Organisationen"),
                         ("admin-06-Branding.jpg", "Org-Admin, Reiter „Branding“: App-Name, Logos und Farben der Organisation", "Branding anpassen")],
    "Tracker": [("admin-03-Tracker.jpg", "Org-Admin, Reiter „Tracker“: gekoppeltes Gerät mit Akku und Empfang, Sendetakt mit Volumenschätzung", "Einrichten"),
                ("admin-02-GPS-Freigaben.jpg", "Org-Admin, Reiter „GPS-Freigaben“: Position vom Tracker, „Tracker übersteuern“ und „GPS zurücksetzen“", "Tracker und Telefon am selben Fahrzeug")],
    "Aktionsseite": [("admin-04-Aktionsseiten.jpg", "Org-Admin, Reiter „Aktionsseiten“: Telegram-Bot, Seite mit Verzögerung, Thema und Abruf-Adresse", "Einrichten")],
    "MCP-Server": [("admin-07-KI-Zugriff.jpg", "Org-Admin, Reiter „KI-Zugriff“: Bereiche, Lese- und Schreibrechte, bestehende Verbindungen", "Und dann noch je Organisation")],
    "Sicherheit-und-Datenschutz": [
        ("admin-08-Datenexport.jpg", "Org-Admin, Reiter „Datenexport“: alle Daten der Organisation als ZIP", "Organisations-Export"),("plan-konto.jpg", "Reiter „Konto“: Passwort, Zwei-Faktor-Authentifizierung und Passkeys", "Passkeys")],
}


def _img(name):
    if (LIVE / name).exists():
        return (LIVE / name).as_uri()
    # Die älteren Bildschirmfotos sind PNG mit Fotoinhalt (Karte): als JPEG ein Viertel so groß.
    from PIL import Image
    jpg = WORK / (Path(name).stem + ".jpg")
    if not jpg.exists():
        im = Image.open(SHOTS / name).convert("RGB")
        im.thumbnail((1600, 2200))
        im.save(jpg, quality=80, optimize=True, progressive=True)
    return jpg.as_uri()


def figures(cid, body):
    for png, cap, heading in FIGURES.get(cid, []):
        imgs = png if isinstance(png, list) else [png]
        cls = " class='pair'" if len(imgs) > 1 else ""
        fig = (f"<figure{cls}><div class='imgs'>" + "".join(f"<img src='{_img(i)}' alt=''>" for i in imgs)
               + f"</div><figcaption>Abbildung: {html.escape(cap)}</figcaption></figure>")
        if heading:
            hs = list(re.finditer(r"<(h[234]) [^>]*>(.*?)</\1>", body, flags=re.S))
            m = next((h for h in hs if html.unescape(re.sub(r"<[^>]+>", "", h.group(2))).strip() == heading), None)
            if not m:
                print("  ! Überschrift fehlt:", cid, heading); continue
            nxt = body.find("<h", m.end())
            # hinter den ersten Absatz des Abschnitts, damit das Bild nicht vor dem Text steht
            pend = body.find("</p>", m.end())
            pos = pend + 4 if pend != -1 and (nxt == -1 or pend < nxt) else m.end()
            seg = body[m.end():pos]
            for tag in ("blockquote", "li", "table", "details"):
                if seg.count(f"<{tag}") > seg.count(f"</{tag}>"):
                    close = body.find(f"</{tag}>", pos)
                    pos = body.find(">", body.rfind(f"</{'ul' if tag == 'li' else tag}", 0, body.find("<h", close) if body.find("<h", close) != -1 else len(body))) + 1 if tag == "li" else close + len(f"</{tag}>")
            body = body[:pos] + fig + body[pos:]
        elif "<h2" in body:
            i = body.index("<h2"); body = body[:i] + fig + body[i:]
        else:
            body = fig + body
    return body


def stem_id(path):
    p = Path(path)
    return re.sub(r"[^A-Za-z0-9-]", "-", p.stem if p.stem != "README" else p.parent.name + "-README")


def rewrite(md, src, ids, oeffentlich=False):
    """Links und Bilder auf das Buch, auf lokale Dateien oder auf GitHub umbiegen."""
    repo = src.relative_to(ROOT).parts[0]
    me = ids[str(src)]
    by_stem = {}
    for k, v in ids.items():
        by_stem.setdefault(Path(k).stem, v)
        by_stem.setdefault(str(Path(k).relative_to(ROOT)), v)

    def target(t, image):
        if re.match(r"^(https?:|mailto:|data:)", t):
            m = re.match(r"https://raw\.githubusercontent\.com/RettTechSolutions/ConvoyPlan/main/(.+)", t)
            if image and m and (ROOT / "ConvoyPlan" / m.group(1)).exists():
                return (ROOT / "ConvoyPlan" / m.group(1)).as_uri()
            return t
        path, _, frag = t.partition("#")
        if image:
            f = (src.parent / path).resolve()
            return f.as_uri() if f.exists() else t
        if not path:
            return f"#{me}-{frag}" if frag else f"#{me}"
        # Wiki-Seiten ohne Endung, Repo-Dateien mit Pfad
        cand = (src.parent / path).resolve()
        key = Path(path).stem if src.parent.name == "wiki" and "/" not in path else None
        cid = None
        if cand.exists() and str(cand) in ids:
            cid = ids[str(cand)]
        elif key and key in by_stem and (ROOT / "ConvoyPlan/wiki" / (key + ".md")).exists() \
                and str(ROOT / "ConvoyPlan/wiki" / (key + ".md")) in ids:
            cid = ids[str(ROOT / "ConvoyPlan/wiki" / (key + ".md"))]
        if cid:
            return f"#{cid}-{frag}" if frag else f"#{cid}"
        if src.parent.name == "wiki" and "/" not in path and not path.endswith((".md", ".svg", ".png")):
            return f"https://github.com/{GH['ConvoyPlan']}/wiki/{path}" + (f"#{frag}" if frag else "")
        try:
            rel = cand.relative_to(ROOT / repo)
            kind = "tree" if cand.is_dir() else "blob"
            return f"https://github.com/{GH[repo]}/{kind}/main/{rel}" + (f"#{frag}" if frag else "")
        except ValueError:
            return t

    def privat(url):
        return oeffentlich and any(f"github.com/{GH[r]}" in url for r in PRIVAT)

    def md_link(m):
        bang, text, t, title = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        ziel = target(t, bool(bang))
        if not bang and privat(ziel):
            return text
        return f"{bang}[{text}]({ziel}{title})"

    out, in_code = [], False
    for line in md.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if not in_code:
            line = re.sub(r'(!?)\[([^\]]*)\]\(<?([^)\s>]+)>?(\s+"[^"]*")?\)', md_link, line)
            line = re.sub(r'(<img[^>]*src=")([^"]+)(")',
                          lambda m: m.group(1) + target(m.group(2), True) + m.group(3), line)
            line = re.sub(r'(<a[^>]*href=")([^"]+)(")',
                          lambda m: m.group(1) + target(m.group(2), False) + m.group(3), line)
        out.append(line)
    return "\n".join(out)


def chapter_html(src, ids, oeffentlich=False):
    md = src.read_text(encoding="utf-8")
    for muster in STREICHEN.get(str(src.relative_to(ROOT)), []):
        md = re.sub(muster, "", md, flags=re.M)
    m = re.search(r"^# (.+)$", md, flags=re.M)
    title = m.group(1).strip() if m else src.stem
    if m:
        md = md[:m.start()] + md[m.end():]
    md = rewrite(md, src, ids, oeffentlich)
    cid = ids[str(src)]
    res = subprocess.run(["pandoc", "-f", "gfm+attributes", "-t", "html5", f"--id-prefix={cid}-",
                          "--wrap=none"], input=md, capture_output=True, text=True, check=True)
    body = res.stdout
    # Mermaid-Blöcke als <pre class="mermaid">
    body = re.sub(r'<pre class="mermaid"><code>(.*?)</code></pre>',
                  r'<pre class="mermaid">\1</pre>', body, flags=re.S)
    body = figures(cid, body)
    h2s = [(i, html.unescape(re.sub(r"<[^>]+>", "", t))) for i, t in
           re.findall(r'<h2 id="([^"]+)"[^>]*>(.*?)</h2>', body, flags=re.S)]
    title_html = subprocess.run(["pandoc", "-f", "gfm", "-t", "html5"], input=title,
                                capture_output=True, text=True).stdout.strip()
    title_html = re.sub(r"^<p>|</p>$", "", title_html)
    return cid, title, title_html, body, h2s


def git_rev(repo):
    try:
        return subprocess.run(["git", "-C", str(ROOT / repo), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


CSS = (HIER / "style.css").read_text()


def build(book):
    files = [ROOT / f for _, fs in book["parts"] for f in fs]
    fehlt = [str(f.relative_to(ROOT)) for f in files if not f.exists()]
    if fehlt:
        print("  übersprungen, es fehlt:", ", ".join(fehlt))
        return None
    oeffentlich = book["ziel"] == OEFFENTLICH
    ids = {}
    for f in files:
        cid = stem_id(f)
        while cid in ids.values():
            cid += "-x"
        ids[str(f)] = cid
    parts = []
    for pi, (ptitle, fs) in enumerate(book["parts"], 1):
        parts.append((pi, ptitle, [chapter_html(ROOT / f, ids, oeffentlich) for f in fs]))

    repos = sorted({f.relative_to(ROOT).parts[0] for f in files})
    stand = datetime.date.today().strftime("%d.%m.%Y")
    quellen = ", ".join(f"{GH[r]}@{git_rev(r)}" for r in repos)

    def render(pages):
        toc = ["<nav class='toc'><h1 class='toc-title'>Inhalt</h1><ol class='toc-parts'>"]
        body = []
        n = 0
        for pi, ptitle, chs in parts:
            toc.append(f"<li class='toc-part'><span>Teil {pi} · {html.escape(ptitle)}</span><ol>")
            body.append(f"<section class='part' id='teil-{pi}'><div class='part-num'>Teil {pi}</div>"
                        f"<h1 class='part-title'>{html.escape(ptitle)}</h1><ul class='part-list'>"
                        + "".join(f"<li>{t}</li>" for _, _, t, _, _ in chs) + "</ul></section>")
            for cid, title, title_html, chbody, h2s in chs:
                n += 1
                pg = pages.get(cid, "")
                toc.append(f"<li class='toc-ch'><a href='#{cid}'><span class='n'>{n}</span>"
                           f"<span class='t'>{title_html}</span><span class='p'>{pg}</span></a>")
                if h2s:
                    toc.append("<ol class='toc-sec'>")
                    for i, (hid, ht) in enumerate(h2s, 1):
                        toc.append(f"<li><a href='#{hid}'><span class='n'>{n}.{i}</span>"
                                   f"<span class='t'>{html.escape(ht)}</span>"
                                   f"<span class='p'>{pages.get(hid, '')}</span></a></li>")
                    toc.append("</ol>")
                toc.append("</li>")
                body.append(f"<section class='chapter' id='{cid}'><div class='ch-num'>Kapitel {n}</div>"
                            f"<h1 class='ch-title'>{title_html}</h1>{chbody}</section>")
            toc.append("</ol></li>")
        toc.append("</ol></nav>")
        return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>{html.escape(book['product'])} – {html.escape(book['title'])}</title>
<style>{CSS}</style>
<script src="{(CACHE/'node_modules/mermaid/dist/mermaid.min.js').as_uri()}"></script>
</head><body>
<section class="impressum">
<h2>Über dieses Handbuch</h2>
<p>Dieses Handbuch fasst die Dokumentation von {html.escape(book['product'])} zu einem
druckbaren Dokument zusammen. Quelle sind die Markdown-Dateien in den Repositories
(Wiki und <code>docs/</code>); bei Abweichungen gilt der aktuelle Stand dort.</p>
<table><tr><th>Stand</th><td>{stand}</td></tr>
<tr><th>Quellen</th><td>{html.escape(quellen)}</td></tr>
<tr><th>Herausgeber</th><td>RettTech Solutions</td></tr></table>
<p class="hint">Verweise innerhalb des Handbuchs sind anklickbar. Verweise auf Dateien
und Seiten außerhalb führen nach GitHub. Die Bildschirmfotos stammen aus einer
Demo-Organisation; Namen und Kennungen darin sind Platzhalter.</p>
</section>
{''.join(toc)}
{''.join(body)}
<script>
mermaid.initialize({{startOnLoad:false, theme:'neutral', securityLevel:'loose', fontFamily:'Inter'}});
mermaid.run({{querySelector:'pre.mermaid'}}).then(()=>{{document.body.dataset.ready='1'}})
 .catch(e=>{{console.error(e);document.body.dataset.ready='1'}});
</script>
</body></html>""", parts

    def cover():
        logo = (CP / "logo/Hauptlogo.svg").as_uri()
        return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><style>{CSS}</style></head>
<body class="cover-body"><div class="cover">
<img class="cover-logo" src="{logo}">
<div class="cover-product">{html.escape(book['product'])}</div>
<h1 class="cover-title">{html.escape(book['title'])}</h1>
<p class="cover-sub">{html.escape(book['subtitle'])}</p>
<div class="cover-foot">Stand {stand} · RettTech Solutions</div>
</div></body></html>"""

    footer = (f"<div style='font-family:Inter,sans-serif;font-size:7.5pt;color:#6b7280;width:100%;"
              f"padding:0 18mm;display:flex;justify-content:space-between'>"
              f"<span>{html.escape(book['product'])} · {html.escape(book['title'])}</span>"
              f"<span><span class='pageNumber'></span> / <span class='totalPages'></span></span></div>")

    slug = book["slug"]
    (WORK / f"{slug}-cover.html").write_text(cover())
    # Durchgang 1
    h, _ = render({k: "000" for k in ids.values()} | {hid: "000" for _, _, chs in parts
                                                       for c in chs for hid, _ in c[4]})
    (WORK / f"{slug}.html").write_text(h)
    pdf(slug, footer)
    pages = locate(WORK / f"{slug}-body.pdf", parts)
    h, _ = render(pages)
    (WORK / f"{slug}.html").write_text(h)
    pdf(slug, footer)
    return merge(slug, book)


def pdf(slug, footer):
    subprocess.run(["node", str(HIER / "print.js"), str(WORK / f"{slug}.html"),
                    str(WORK / f"{slug}-body.pdf"), str(WORK / f"{slug}-cover.html"),
                    str(WORK / f"{slug}-cover.pdf"), footer], check=True)


def norm(s):
    return re.sub(r"\W+", "", s.lower())


def locate(pdfpath, parts):
    txt = subprocess.run(["pdftotext", "-layout", str(pdfpath), "-"], capture_output=True,
                         text=True).stdout.split("\f")
    pages = [norm(p) for p in txt]
    res, cur = {}, 0
    # Inhaltsverzeichnis überspringen: erstes "Teil 1" nach dem Verzeichnis
    for i, p in enumerate(pages):
        if p.startswith("teil1") :
            cur = i; break
    for _, _, chs in parts:
        for cid, title, _, _, h2s in chs:
            key = "kapitel" + norm(title)[:40]
            for i in range(cur, len(pages)):
                if key[:30] in pages[i][:200] or ("kapitel" in pages[i][:12] and norm(title)[:25] in pages[i][:250]):
                    cur = i; break
            res[cid] = cur + 1
            for hid, ht in h2s:
                k = norm(ht)[:35]
                for i in range(cur, len(pages)):
                    if k and k in pages[i]:
                        cur = i; break
                res[hid] = cur + 1
    return res


def merge(slug, book):
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    w.append(PdfReader(str(WORK / f"{slug}-cover.pdf")))
    w.append(PdfReader(str(WORK / f"{slug}-body.pdf")))
    w.add_metadata({"/Title": f"{book['product']} – {book['title']}", "/Author": "RettTech Solutions",
                    "/Subject": book["subtitle"]})
    w.page_mode = "/UseOutlines"
    ziel = book["ziel"] / f"{slug}.pdf"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with open(ziel, "wb") as fh:
        w.write(fh)
    return dict(datei=f"{slug}.pdf", titel=f"{book['product']} – {book['title']}",
                beschreibung=book["subtitle"], fuer=book.get("fuer", ""),
                seiten=len(w.pages), bytes=ziel.stat().st_size,
                stand=datetime.date.today().isoformat())


def mermaid_bereit():
    if not (CACHE / "node_modules/mermaid/dist/mermaid.min.js").exists():
        CACHE.mkdir(exist_ok=True)
        subprocess.run(["npm", "install", "--prefix", str(CACHE), "--no-save", "--silent", MERMAID], check=True)


if __name__ == "__main__":
    only = sys.argv[1:]
    WORK.mkdir(exist_ok=True)
    mermaid_bereit()
    katalog = json.loads(KATALOG.read_text()) if KATALOG.exists() else []
    for b in BOOKS:
        if only and b["slug"] not in only:
            continue
        print("→", b["slug"], flush=True)
        eintrag = build(b)
        if eintrag and b["ziel"] == OEFFENTLICH:
            katalog = [k for k in katalog if k["datei"] != eintrag["datei"]] + [eintrag]
    reihenfolge = [b["slug"] + ".pdf" for b in BOOKS]
    katalog.sort(key=lambda k: reihenfolge.index(k["datei"]) if k["datei"] in reihenfolge else 99)
    KATALOG.parent.mkdir(parents=True, exist_ok=True)
    KATALOG.write_text(json.dumps(katalog, ensure_ascii=False, indent="\t") + "\n")
