# MCP-Server (KI-Schnittstelle)

ConvoyPlan kann seine Fachdaten über einen **Model-Context-Protocol-Server** bereitstellen. KI-Programme wie Claude Desktop, Claude Code oder claude.ai tragen die Instanz als *Remote-MCP-Server* ein und arbeiten danach mit Konvois, Fahrzeugen, Wegpunkten, Routen und Marschstatus — im Rahmen dessen, was der zustimmende Benutzer selbst darf.

> **Standardmäßig ausgeschaltet.** Ohne `MCP_ENABLED=true` existiert weder `/mcp` noch ein Discovery-Dokument. Das Einschalten öffnet Einsatzdaten für einen externen Modellanbieter — diese Entscheidung gehört dem Betreiber, nicht dem Auslieferungszustand.

---

## Was der Server kann

**Lesen** (neun Werkzeuge): Konvois und Unterkonvois auflisten, Konvoi-Details samt aller sieben Abschnitte des Marschbefehls, Fahrzeugbestand und Einzelfahrzeug, Wegpunkte in Marschreihenfolge, die gespeicherte Route, zuletzt gemeldete Positionen, Marschstatus je Fahrzeug.

**Schreiben** (zwölf Werkzeuge, nur mit gültiger Lizenz): Konvoi und Fahrzeug anlegen und ändern, Fahrzeuge zuordnen und wieder lösen, Marschfolge setzen, Wegpunkte anlegen, ändern und umsortieren, Route berechnen, Fahrzeugstatus melden.

**Dokumente** (Resources): Marschbefehl als PDF, Route als GPX, Konvoi als JSON — dieselben Exporte wie im Portal.

## Was der Server nicht kann

| | |
|---|---|
| **Löschen** | Es gibt kein Werkzeug, das einen Konvoi, ein Fahrzeug, einen Wegpunkt, eine Route oder einen Benutzer löscht. Die einzige Ausnahme von der Anlegen-und-Ändern-Regel ist das **Lösen einer Fahrzeug-Zuordnung** — dabei bleiben Fahrzeug und Konvoi bestehen. |
| **Administration** | Keine Benutzerverwaltung, keine Lizenz, keine Systemkennzahlen, kein Regionswechsel, kein Branding, keine Leitstellen-Konfiguration. |
| **Mehrere Organisationen** | Ein Zugang gilt für genau **eine** Organisation, auch wenn der Benutzer in mehreren Mitglied ist. |

---

## Einschalten

In der `.env`:

```
MCP_ENABLED=true
```

Danach das Backend neu starten. Ein Reiter **MCP** im Admin-Portal zeigt anschließend den Zustand, die Verbindungsadresse und die erteilten Zugänge.

> Der Schalter ist bewusst **keine** Laufzeiteinstellung. Solange er aus ist, wird gar kein Endpunkt montiert — es gibt also nichts, was versehentlich offenstehen könnte. Das wäre mit einem Knopf im Portal nicht mehr so.

Der Reverse Proxy braucht Routen für `/mcp` und die OAuth-Pfade an der Wurzel der Site. **Bestehende Installationen rüsten das beim nächsten Backend-Start automatisch nach**; bei Neuinstallationen ist es von vornherein enthalten.

---

## Verbinden

1. Im Admin-Portal unter **MCP** die **Adresse** kopieren (`https://<domain>/mcp`).
2. Im KI-Programm als *Remote-MCP-Server* eintragen.
3. Das Programm öffnet den Browser auf der ConvoyPlan-Anmeldung.
4. **Anmelden** — mit dem eigenen Konto, inklusive MFA, falls eingerichtet.
5. **Organisation wählen.** Der Zugang gilt nur für diese.
6. **Zustimmen.** Erst damit entsteht ein Zugang.

Auf dem Zustimmungsbildschirm stehen zwei Angaben nebeneinander, und der Unterschied ist wichtig:

| Angabe | Bedeutung |
|---|---|
| **Name des Programms** — als *ungeprüft* gekennzeichnet | Selbstauskunft. Jedes Programm, das die Instanz erreicht, kann sich registrieren und sich dabei nennen, wie es will — auch „ConvoyPlan Desktop". |
| **Zieladresse** — als *geprüft* gekennzeichnet | Wurde bei der Registrierung hinterlegt und wird überprüft. Dorthin geht der Zugang. |

**Zustimmen nur, wenn du dieses Programm gerade selbst verbunden hast und die Zieladresse dazu passt.**

---

## Berechtigungen

Die Rechte des Zugangs sind eine Projektion der Rolle in der gewählten Organisation — nicht mehr, als der Benutzer selbst darf:

| Berechtigung | ab Rolle | erlaubt |
|---|---|---|
| `convoy:read` | beobachter | Konvois, Fahrzeuge, Wegpunkte, Routen und Positionen lesen |
| `fleet:status` | fahrer | zusätzlich Fahrzeugstatus und Positionen melden |
| `convoy:write` | planer | zusätzlich anlegen, ändern und Routen berechnen |

Geprüft wird bei **jedem** Aufruf frisch gegen die Datenbank. Wird eine Mitgliedschaft entzogen oder eine Rolle herabgestuft, wirkt das sofort — nicht erst, wenn der Zugang abläuft.

---

## Nachvollziehbarkeit

Jeder **schreibende** Aufruf erzeugt einen Eintrag im Audit-Log mit Benutzer, Organisation, Werkzeugname, Parametern und dem Programm, das ihn ausgelöst hat. Die Quelle ist als `mcp` gekennzeichnet — im Log ist damit unterscheidbar, was ein Mensch im Portal getan hat und was ein Modell über die Schnittstelle.

Lesende Aufrufe werden bewusst **nicht** protokolliert. Ein Modell liest im Minutentakt; das Log wäre sonst nach einer Woche unbrauchbar.

---

## Zugang entziehen

Im Admin-Portal unter **MCP**:

- **Verbindung trennen** — entzieht einem Benutzer den Zugang für ein bestimmtes Programm.
- **Programm sperren** — trennt alle seine Verbindungen und verhindert eine neue Autorisierung.

Zusätzlich entzieht jede Maßnahme, die ohnehin alle Sitzungen beendet (Passwortwechsel, „überall abmelden", Deaktivieren des Kontos, Entzug der Mitgliedschaft), auch die MCP-Zugänge.

> ### Das Zeitfenster beim Widerruf
>
> Ein Widerruf wirkt auf die Verbindung **sofort**: das Programm kann sich keinen neuen Zugang mehr holen. Ein bereits ausgestelltes Zugriffstoken bleibt aber noch bis zu seinem Ablauf gültig — standardmäßig **15 Minuten** (`MCP_ACCESS_TOKEN_TTL_MINUTES`).
>
> Das ist der Preis zustandsloser Tokens, und es wird hier genannt statt verschwiegen. Wer das Fenster kleiner haben will, setzt den Wert herunter; das kostet häufigere Erneuerungen, sonst nichts. Wer den Zugang **augenblicklich** beenden muss, deaktiviert das Benutzerkonto oder entzieht die Mitgliedschaft — beides wirkt ohne Verzögerung, weil es bei jedem Aufruf frisch geprüft wird.

---

## Datenschutz

Der entscheidende Punkt zuerst: **Was ein Modell über diese Schnittstelle liest, verlässt die Instanz und geht an den Anbieter des KI-Programms.** Das ist keine Nebenwirkung, sondern der Zweck — nur deshalb kann das Modell damit arbeiten.

Für den Betrieb heißt das:

- **Verantwortlich bleibt der Betreiber der Instanz.** Der Modellanbieter ist Auftragsverarbeiter; ein entsprechender Vertrag ist Sache des Betreibers, nicht von ConvoyPlan.
- **Personenbezug ist realistisch.** Fahrzeugbesatzungen mit Mobilnummer, Positionen mit Zeitstempel, Funkrufnamen — das sind personenbeziehbare Daten, sobald sie einer Person zugeordnet werden können.
- **Welche Daten fließen, entscheidet die Rolle.** Ein Zugang mit `convoy:read` für eine Organisation sieht genau das, was ein *beobachter* dort sieht — nicht weniger, aber auch nicht mehr.
- **Die Einwilligung ist dokumentiert.** Jede Zustimmung landet im Audit-Log mit Benutzer, Organisation, Programm und erteilten Rechten.

Wer das nicht will, lässt `MCP_ENABLED` auf `false` — dann existiert die Schnittstelle nicht.

Siehe auch: [Sicherheit und Datenschutz](Sicherheit-und-Datenschutz), [Rollen & Berechtigungen](Rollen), [API-Dokumentation](API-Dokumentation).

---

## Einstellungen

| Variable | Standard | Bedeutung |
|---|---|---|
| `MCP_ENABLED` | `false` | Schaltet die Schnittstelle ein. Erfordert einen Neustart. |
| `MCP_PUBLIC_URL` | aus `APP_BASE_URL` | Die Adresse, unter der Clients den Server erreichen. Ohne abschließenden Schrägstrich. |
| `MCP_ACCESS_TOKEN_TTL_MINUTES` | `15` | Gültigkeit eines Zugriffstokens — siehe Zeitfenster oben. |
| `MCP_REFRESH_TOKEN_TTL_DAYS` | `30` | Wie lange eine Verbindung ohne erneute Zustimmung hält. |
| `MCP_ALLOW_DCR` | `true` | Ob sich Programme selbst registrieren dürfen. Aus bedeutet: Clients von Hand eintragen. |
| `MCP_TOOL_CALLS_PER_MINUTE` | `120` | Obergrenze je Verbindung. Ein Modell in einer Schleife ist ein realistisches Lastprofil. |

Routenberechnungen zählen zusätzlich gegen `QUOTA_ROUTING_PER_HOUR` — dieselbe Einstellung wie an der REST-API.

---

## Technischer Hintergrund

Die Instanz ist zugleich **Resource Server und Authorization Server**: eine selbst gehostete Installation hat keinen externen Identitätsanbieter, und Benutzer, MFA, Organisationen und Rollen liegen ohnehin in der eigenen Datenbank.

Umgesetzt nach der MCP-Revision **2026-07-28**: Protected Resource Metadata nach RFC 9728 an der Wurzel der Site, PKCE ausschließlich mit `S256`, Resource Indicators nach RFC 8707 (ein Zugang für Instanz A ist an Instanz B wertlos) und der `iss`-Parameter nach RFC 9207 in jeder Antwort — auch in einer Absage, damit ein Programm den Absender prüfen kann.

Zugänge erneuern sich rollierend. Taucht ein bereits erneuertes Token noch einmal auf, hat es jemand mitgelesen — dann wird die **gesamte** Verbindung entzogen, nicht nur das vorgelegte Token.
