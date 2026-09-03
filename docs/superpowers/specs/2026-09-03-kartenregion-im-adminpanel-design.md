# Design-Spec: Kartenregion im Admin-Panel wechseln

Status: **Entwurf zur Abstimmung** · Stand: 2026-09-03

Die Kartenregion einer Instanz lässt sich heute nur durch Bearbeiten der
Umgebungsvariablen und einen Neustart des GraphHopper-Containers ändern — also
per SSH auf dem Host. Diese Spezifikation beschreibt, wie derselbe Wechsel aus
dem Admin-Panel heraus bedienbar wird, ohne die bestehende Vertrauensgrenze
zwischen Backend und Docker aufzuweichen und ohne die Routenplanung für die
Dauer des Graph-Baus abzuschalten.

---

## 1. Ausgangslage

### Wie ein Regionswechsel heute abläuft

Der GraphHopper-Container liest zwei Variablen (`docker-compose.yml`):

```yaml
OSM_DOWNLOAD_URL: ${OSM_DOWNLOAD_URL:-https://download.geofabrik.de/europe/dach-latest.osm.pbf}
OSM_FILENAME:     ${OSM_FILENAME:-dach-latest.osm.pbf}
JAVA_OPTS:        ${JAVA_OPTS:--Xmx8g -Xms1g -XX:+UseG1GC}
```

`graphhopper/entrypoint.sh` bildet daraus einen Fingerprint aus Dateiname und
Encoded Values (`entrypoint.sh:61`). Weicht er vom gespeicherten ab, wird der
vorhandene Graph verworfen und neu gebaut — der Mechanismus aus #420. Der
schwierige Teil eines Regionswechsels ist damit bereits gelöst; es fehlt nur
der bedienbare Weg dorthin.

### Die Vertrauensgrenze, die bestehen bleibt

Das Backend hat **bewusst keinen Docker-Socket**. Container-Zustände liest es
über einen `dockerproxy`-Sidecar mit deaktiviertem POST. Der Kommentar in
`docker-compose.yml` begründet das ausdrücklich: Socket-Zugriff ist faktisch
Root auf dem Host, und ein von außen erreichbarer Container darf ihn nicht
haben.

Der Updater-Container dagegen besitzt Docker-CLI, den Host-Pfad zur
Compose-Datei (`STACK_FILE_PATH`) und alle durchgereichten Service-Variablen.
Er ist der vorhandene privilegierte Aktor.

### Die vorhandene Brücke

Beide Container teilen sich das Volume `update_status`. Das Backend schreibt
dort Absichtsdateien (`trigger`, `channel`, `mode`), der Updater pollt sie alle
10 Sekunden und schreibt `update.log` und `status.json` zurück, die das Panel
per SSE ausliefert. Der Regionswechsel nutzt exakt diesen Weg — es entsteht
kein neuer Mechanismus und keine neue Berechtigung.

---

## 2. Entscheidungen und ihre Begründung

| Entscheidung | Gewählt | Verworfen |
|---|---|---|
| Regionsauswahl | jede Geofabrik-Region | kuratierte Liste |
| Ausfallzeit | nahtlos (Sekunden) | Vollausfall während des Baus |
| Umsetzung „nahtlos" | Import-Container, dann kurzer Schwenk | zweite servende GraphHopper-Instanz |

### Warum kein Blue/Green mit zweiter Instanz

Zwei parallel **servende** GraphHopper-Prozesse brauchen zwei Heaps. DACH läuft
mit `-Xmx8g`; zwei davon überschreiten die 15,6 GB der Zielmaschine. Ausgerechnet
für große Regionen — den eigentlichen Anwendungsfall — wäre die Variante nicht
darstellbar. Sie bliebe erst ab deutlich mehr Hauptspeicher eine Option.

Der gewählte Weg baut den Graphen stattdessen in einem **Wegwerf-Container**,
der nur importiert und danach endet. Der laufende GraphHopper bleibt währenddessen
unangetastet in Betrieb; erst der fertige Graph erfordert einen Neustart. Aus
Stunden Ausfall werden Sekunden, und der Speicherbedarf fällt nur einmal an.

### Warum keine Schreibzugriffe auf die Host-`.env`

Die neue Region muss einen `docker compose up` überleben. Der naheliegende Weg
— der Updater schreibt `OSM_DOWNLOAD_URL` in die `.env` neben `STACK_FILE_PATH`
— erfordert neue Schreibrechte auf Host-Dateien, kollidiert mit dem Installer
als zweitem Schreiber und bringt Quoting-Fallstricke mit.

Stattdessen legt der Updater die aktive Region als Datei `.region` in das
`osm_data`-Volume, das beide Container ohnehin mounten. `entrypoint.sh` liest
sie und zieht sie den Env-Vorgaben vor; fehlt sie, gilt unverändert
`OSM_DOWNLOAD_URL`. Bestandsinstallationen ändern ihr Verhalten dadurch nicht.

`.region` trägt **drei** Werte: `OSM_DOWNLOAD_URL`, `OSM_FILENAME` und
`JAVA_OPTS`. Der Heap muss mit der Region wandern — die Installer setzen ihn
heute je Region unterschiedlich (`-Xmx8g` für DACH, `-Xmx6g` für Deutschland).
Bliebe er beim alten Wert, liefe eine größere Region mit zu kleinem Heap ins
OOM und eine kleinere würde dauerhaft Speicher blockieren, den sie nicht
braucht.

---

## 3. Ablauf

Fünf Phasen, jede mit eigenem Status, die ersten drei abbrechbar.

### Phase 1 — Prüfen

Geofabrik-Index lesen, Extract-Größe per HTTP-HEAD ermitteln, gegen freien
Platz auf `osm_data` und `gh_graph` sowie gegen den Host-RAM aus der
Systemübersicht rechnen. Reicht es nicht, endet der Vorgang hier mit einer
Begründung im Klartext — nicht nach drei Stunden mit einem OOM.

### Phase 2 — Laden

Das neue `.osm.pbf` wird unter seinem regionseigenen Namen **neben** das alte
gelegt und gegen Geofabriks `.md5` geprüft. Bei Abweichung wird die Teil-Datei
verworfen.

### Phase 3 — Importieren

Ein Wegwerf-Container aus demselben GraphHopper-Image baut den Graphen in ein
Staging-Verzeichnis. Der laufende GraphHopper wird nicht berührt.

> **Zu verifizierende Annahme:** ob `graphhopper.jar import` in der gepinnten
> Version 9.1 sauber ohne Server-Start durchläuft. Im Repo wird ausschließlich
> `server` verwendet (`entrypoint.sh:132`). Trifft es nicht zu, startet der
> Wegwerf-Container regulär mit `server`, baut dabei wie heute den Graphen und
> wird beendet, sobald er hörbereit ist. Der Plan klärt das als erstes.

### Phase 4 — Schwenken

Der alte Graph wird **beiseitegeschoben, nicht gelöscht**. Staging-Graph an
seine Stelle, `.graph_fingerprint` und `.region` schreiben,
`docker compose up -d graphhopper`. Besteht der neue Container den Health-Check
nicht, wandert der alte Graph zurück und der Wechsel endet als Fehlschlag — mit
laufendem Routing.

Dies ist der einzige Moment mit Ausfall: die Sekunden eines Neustarts.

### Phase 5 — Aufräumen

Erst **nach** bestandenem Health-Check werden altes Extract und alter Graph
gelöscht. Dass Aufräumen eine eigene Phase ist, ist die Voraussetzung für den
Rollback in Phase 4.

### Dateien im geteilten Volume

| Datei | Schreiber | Inhalt |
|---|---|---|
| `region_request.json` | Backend | Ziel-URL, Dateiname, Import-Heap, Auslöser, Zeitpunkt |
| `region_status.json` | Updater | Phase, Fortschritt, Abbruchgrund |
| `region.log` | Updater | Live-Ausgabe für das Panel |
| `region.cancel` | Backend | Abbruchwunsch; der Updater prüft ihn an jeder Phasengrenze |
| `region.lock` | beide | Gegenseitiger Ausschluss mit dem Update-Trigger |

Den **Import-Heap** in `region_request.json` berechnet das Backend aus der
Schätzformel (Abschnitt 6) — dieselbe Zahl, die `preview` dem Operator vorher
angezeigt hat. Er landet nach erfolgreichem Wechsel als `JAVA_OPTS` in
`.region`. Der Updater übernimmt ihn nicht ungeprüft, sondern deckelt ihn auf
den tatsächlich verfügbaren Host-RAM abzüglich einer Reserve; das Backend kennt
den Hostzustand nur aus zwischengespeicherten Metriken, der Updater sieht ihn
zum Ausführungszeitpunkt.

**Abbruch** wirkt an Phasengrenzen, nicht mitten in einem Schritt: Ein laufender
Download wird zu Ende geführt oder verworfen, ein laufender Import bis zum Ende
oder Abbruch des Wegwerf-Containers. Ab Phase 4 ist kein Abbruch mehr möglich —
dort läuft der Schwenk mit Rollback, und ein Abbruch mittendrin wäre gefährlicher
als das Durchlaufen.

---

## 4. Backend-API

Alle Endpunkte hinter `require_superadmin`.

| Methode | Pfad | Zweck |
|---|---|---|
| `GET` | `/api/admin/regions` | Geofabrik-Index, im Speicher gecacht |
| `GET` | `/api/admin/region` | Aktuelle Region, Heap, Graph-Baudatum, Belegung |
| `POST` | `/api/admin/region/preview` | Vorab-Rechnung, ohne Nebenwirkung |
| `POST` | `/api/admin/region` | Wechsel auslösen → `202` |
| `GET` | `/api/admin/region/status` | Phase und Fortschritt |
| `GET` | `/api/admin/region/log` | SSE-Strom, Stream-Ticket wie `update-log` |
| `POST` | `/api/admin/region/cancel` | Abbruch in Phase 1–3 |

### `preview`

Liefert zu einer URL: Extract-Größe (HTTP-HEAD), geschätzter Graph- und
RAM-Bedarf, freier Platz, freier RAM, geschätzte Dauer — und daraus ein Urteil
`ok` / `knapp` / `reicht nicht` mit Begründung. Getrennt vom auslösenden `POST`,
damit das Panel Zahlen zeigen kann, ohne etwas anzustoßen.

### URL-Validierung

Die URL wandert vom Backend zu einem Container mit Docker-Socket, der sie
herunterlädt und in einen Graph-Bau füttert. Ohne Einschränkung wäre das ein
Primitiv, um beliebige Inhalte über den privilegierten Container zu ziehen.

Zulässig ist deshalb ausschließlich: Schema `https`, Host exakt
`download.geofabrik.de`, Pfad endet auf `-latest.osm.pbf`. Redirects werden
nicht verfolgt. Innerhalb Geofabriks bleibt jede Region frei wählbar.

**Der Updater prüft dieselbe Regel erneut**, statt dem Backend zu vertrauen.

### Nebenläufigkeit

Regionswechsel und Update fassen denselben Compose-Stack an und dürfen sich
nicht überlappen. `POST /region` gibt `409`, wenn ein Update läuft; der
bestehende `trigger-update` bekommt spiegelbildlich dieselbe Prüfung.

### Datenmodell

**Keine neue Tabelle.** Laufzeitzustand liegt in `region_status.json`, die
Wahrheit über die aktive Region in `.region`. Persistiert wird nur die Historie
— über das vorhandene `AuditLog` (`backend/app/models/audit_log.py`) mit
`action` aus `region.switch_requested` / `region.switch_completed` /
`region.switch_failed`, `target_type="region"` und den Details im `detail`-JSON.

### Fehlerbehandlung

Folgt `trigger-update` (`admin.py:1141`): sofortige erste Log-Zeile, damit das
Terminal nicht leer bleibt, während der Updater bis zu 10 s schläft; `OSError`
auf dem geteilten Volume wird mit derselben klaren Meldung abgefangen
(„Volume nicht beschreibbar, Updater repariert die Rechte beim nächsten Lauf").

---

## 5. Panel-Oberfläche

Neue Karte **„Kartenregion"** im `system`-Tab, unter der Update-Karte — dieselbe
betriebliche Nachbarschaft, dieselbe Terminal-Darstellung (`.update-terminal`).
Kein neuer Reiter, keine zweite Log-Ansicht.

**Ruhezustand:** aktuelle Region, Extract-Größe, Graph-Baudatum,
Plattenbelegung. Darunter „Region wechseln".

**Auswahl:** Suchfeld mit Pfadanzeige („Europe › Germany › Bayern"), da der
Geofabrik-Index mehrere hundert Einträge umfasst und ein flaches Dropdown
unbedienbar wäre. Die vier Installer-Regionen stehen als Schnellauswahl oben.

**Vorab-Rechnung:** benötigt gegen verfügbar, für Platte und RAM getrennt, mit
geschätzter Dauer. Bei `reicht nicht` ist der Knopf deaktiviert und daneben
steht, *warum* und *was fehlt*.

**Während des Wechsels:** Phasenanzeige ersetzt den Knopf, darunter das
Terminal. Abbrechen in Phase 1–3. Der Update-Knopf ist gesperrt — mit sichtbarer
Begründung, nicht nur ausgegraut.

**Nach einem Fehlschlag** sagt die Karte ausdrücklich, dass die bisherige Region
unverändert weiterläuft und nur Plattenplatz und Zeit verloren sind. Das ist die
zentrale Zusage dieses Entwurfs und muss dastehen, statt erschlossen zu werden.

**Randfälle:**

- *Reload während des Wechsels* — Zustand kommt aus `region_status.json`, nicht
  aus dem Komponentenzustand. Verhält sich wie die Update-Anzeige heute.
- *Installation ohne Updater-Container* — der Aktor fehlt, der Wechsel ist
  unmöglich. Die Karte zeigt dann die Region als reine Information plus Hinweis
  auf den Konfigurationsweg. Kein toter Knopf. **Zu verifizieren:** ob solche
  Installationen existieren; die Installer decken den Docker-Weg ab.

---

## 6. Ressourcenschätzung

Belastbare Datenpunkte aus `scripts/install.sh:375`:

| Region | Dokumentierter RAM | Dokumentierte Dauer |
|---|---|---|
| Bayern | ≥ 3 GB | 10–20 min |
| Deutschland | ≥ 6 GB | 45–90 min |
| DACH | ≥ 8 GB | 60–120 min |

Gegen die DACH-Extractgröße von ~5,5 GB gehalten passt eine Gerade der Form
`RAM ≈ 2 GB + 1,1 × Extract-Größe` auf alle drei Punkte.

**Diese Formel gilt als Arbeitshypothese, nicht als Ergebnis.** Belastbar ist
nur die DACH-Größe; die für Deutschland und Bayern sind geschätzt. Der
Implementierungsplan holt die drei realen Größen per HTTP-HEAD — was das Feature
ohnehin kann — und leitet die Koeffizienten daraus ab.

Wichtiger als die Genauigkeit sind drei Absicherungen:

1. Sicherheitsaufschlag von 20 % auf die Schätzung.
2. Einstufung `knapp` statt `ok`, sobald die Schätzung 80 % des Verfügbaren
   übersteigt.
3. **Ein Fehlschlag bleibt folgenlos** — der eigentliche Schutz.

Ergänzend schreibt der Updater nach jedem geglückten Import die tatsächliche
Spitzenlast und Dauer ins `AuditLog`-Detail. Der Eintrag wird ohnehin
geschrieben; jede weitere Schätzung auf dieser Maschine wird dadurch besser als
die Formel.

---

## 7. Fehlerfälle

| Fall | Phase | Folge |
|---|---|---|
| Geofabrik nicht erreichbar / 404 | 1 | Abbruch vor jedem Download, nichts angefasst |
| Prüfsumme stimmt nicht | 2 | Teil-Datei verworfen, Abbruch |
| Platte läuft beim Download voll | 2 | Abbruch und Aufräumen; Vorab-Check soll das verhindern |
| Import-OOM | 3 | Staging-Graph verworfen, **Live-Betrieb unberührt** |
| Neuer Container wird nicht gesund | 4 | **Rollback** auf den alten Graphen |
| Updater stirbt mitten im Wechsel | beliebig | Beim Neustart wird die laufende Anforderung erkannt und sauber beendet statt halb fortgesetzt |
| Update parallel ausgelöst | beliebig | `409` durch das gemeinsame Lock |

---

## 8. Teststrategie

**Backend-Unit**

- URL-Validierung gegen die Allowlist, inklusive Umgehungsversuchen: `http`,
  fremder Host, Redirect-Ziel, Pfad ohne `-latest.osm.pbf`.
- `409`-Verhalten beider Trigger gegeneinander.
- Preview-Rechnung an festen Eingaben.
- `AuditLog`-Eintrag je Ausgang.

**Updater-Skript**

Die Wechsel-Logik ist Bash. Ein `docker`-Stub im `PATH` protokolliert Aufrufe,
statt sie auszuführen. Damit sind Phasenreihenfolge, Rollback-Pfad und
Aufräumen prüfbar, ohne je einen Container zu starten.

**`entrypoint.sh`**

- `.region` hat Vorrang vor der Env.
- Fehlt `.region`, bleibt das bisherige Verhalten unverändert — der
  Regressionsschutz für alle Bestandsinstallationen.

**Integration in CI**

Der Berlin-Extract ist klein genug, um den vollständigen Weg von `preview` bis
zum Schwenk auf einem Runner durchzuspielen. Der einzige Test, der die fünf
Phasen gegeneinander prüft.

**Nicht automatisierbar**

Der Pfad mit großen Regionen sprengt Laufzeit und Speicher jedes Runners. Er
gehört als manueller Prüfschritt in den Plan, nicht als stillschweigende Lücke.

---

## 9. Offene Punkte für den Implementierungsplan

1. Läuft `graphhopper.jar import` in Version 9.1 ohne Server-Start? (Abschnitt 3)
2. Reale Extract-Größen für DACH, Deutschland, Bayern — Grundlage der
   Schätzformel. (Abschnitt 6)
3. Gibt es Installationen ohne Updater-Container? (Abschnitt 5)
4. Verhält sich der Health-Check des GraphHopper-Containers verlässlich genug,
   um den Rollback in Phase 4 daran zu hängen?
