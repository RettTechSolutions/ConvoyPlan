# ConvoyPlan in ChatGPT verbinden

Diese Seite beschreibt, wie eine ConvoyPlan-Instanz an ChatGPT angebunden wird,
sodass man im Gespräch nach Konvois fragen und sie auch ändern kann.

**Der Weg heißt Developer Mode.** Das ist keine Notlösung: ConvoyPlan wird selbst
betrieben, jede Organisation hat ihre eigene Adresse. Ein Eintrag im
öffentlichen App-Verzeichnis von ChatGPT könnte immer nur auf **eine** Adresse
zeigen und wäre für alle anderen Instanzen wertlos. Der Developer Mode verbindet
ChatGPT mit **deiner** Instanz.

> Für Claude Desktop, Claude Code und andere Programme siehe
> [MCP-Server](MCP-Server) — dort steht der allgemeine Weg.

---

## Voraussetzungen

**Auf der ChatGPT-Seite:**

- Ein Konto mit **Pro, Plus, Business, Enterprise oder Education**. Mit einem
  kostenlosen Konto lässt sich kein eigener Server verbinden.
- Die Einrichtung läuft **im Browser**, nicht in der App.

**Auf der ConvoyPlan-Seite:**

- Die Instanz ist aus dem Internet über **HTTPS** erreichbar. Eine Instanz, die
  nur im internen Netz läuft, erreicht ChatGPT nicht — es verbindet sich von
  seinen eigenen Servern aus, nicht vom Rechner des Benutzers.
- Die **KI-Schnittstelle ist eingeschaltet**: Adminportal → System →
  KI-Schnittstelle. Siehe [MCP-Server](MCP-Server#einschalten).
- Du bist Mitglied einer Organisation. Welche Rolle du dort hast, entscheidet,
  was die Verbindung darf — siehe [Rollen & Berechtigungen](Rollen).

---

## Schritt 1: Developer Mode einschalten

In ChatGPT: **Einstellungen → Sicherheit und Anmeldung → Developer mode**
einschalten.

Je nach Oberflächenstand liegt der Schalter auch unter *Apps & Connectors →
Erweitert*. Gesucht ist in beiden Fällen dasselbe: die Erlaubnis, eigene
Verbindungen zu Servern anzulegen, die nicht aus dem Verzeichnis stammen.

---

## Schritt 2: Die Verbindung anlegen

1. Im Adminportal von ConvoyPlan unter **MCP** die **Adresse kopieren**. Sie
   sieht so aus:

   ```
   https://<deine-domain>/mcp
   ```

   Die Adresse aus dem Portal zu kopieren statt sie zu tippen erspart den
   häufigsten Fehler: **das `/mcp` am Ende fehlt**. Ohne diesen Pfad findet
   ChatGPT nichts und meldet einen Verbindungsfehler.

2. In ChatGPT unter **Apps & Connectors** eine neue Verbindung anlegen (Plus-Knopf).

3. Ausfüllen:

   | Feld | Wert |
   |---|---|
   | Name | ConvoyPlan (oder der Name deiner Organisation) |
   | Beschreibung | frei — was du im Auswahlmenü lesen willst |
   | Server-URL | die kopierte Adresse mit `/mcp` |
   | Authentifizierung | **OAuth** |

4. Speichern. ChatGPT ruft die Schnittstelle ab und liest die verfügbaren
   Werkzeuge ein.

---

## Schritt 3: Zustimmen — hier entscheidet sich alles

ChatGPT schickt dich zur Anmeldung auf deiner ConvoyPlan-Instanz. Nach dem
Anmelden (inklusive MFA, falls eingerichtet) erscheint der
Zustimmungsbildschirm. **Drei Dinge dort sind wichtig:**

### Die Organisation

Der Zugang gilt für **genau eine** Organisation. Gehörst du mehreren an, wähle
die richtige — ein Wechsel später bedeutet, die Verbindung neu zu erteilen.

### Die Rechte — Haken setzen, sonst bleibt es beim Lesen

Vorausgewählt ist nur, was ChatGPT von sich aus angefragt hat, und das ist
**nur Lesen**. Wer im Chat auch etwas anlegen oder ändern will, setzt hier den
Haken bei **„Konvois und Fahrzeuge anlegen und ändern"**.

> **Das lässt sich später nicht nachholen.** Andere Programme fragen bei Bedarf
> nach; ChatGPT fragt einmal beim Verbinden und danach nie wieder. Ohne den
> Haken endet jeder Änderungsversuch mit einer Fehlermeldung, und der einzige
> Ausweg ist, die Verbindung zu trennen und neu zu erteilen.

Angeboten wird nur, was deine Rolle hergibt. Als *Beobachter* gibt es kein
Schreibrecht zum Ankreuzen — das ist kein Fehler der Anbindung.

### Die Zieladresse

Auf dem Bildschirm stehen der **Name des Programms** (als *ungeprüft*
gekennzeichnet — den hat es sich selbst gegeben) und die **Zieladresse** (als
*geprüft*). Verlässlich ist nur die Zieladresse. Sie muss zu ChatGPT passen,
und du musst die Verbindung gerade selbst gestartet haben.

---

## Schritt 4: Im Gespräch einschalten

**Die Verbindung ist nicht automatisch in jeder Unterhaltung aktiv.** Im
Eingabefeld über das Plus-Menü **Developer mode** wählen und ConvoyPlan
ankreuzen. Das gilt je Unterhaltung — wer das vergisst, bekommt eine Antwort
aus dem Allgemeinwissen des Modells statt aus seinen Konvoidaten.

Das ist die zweithäufigste Ursache für „es funktioniert nicht".

---

## Was du dann fragen kannst

**Lesend:**

- „Welche Konvois stehen nächste Woche an?"
- „Zeig mir den Konvoi nach München."
- „Welche Fahrzeuge sind dem Marschverband Nord zugeordnet?"
- „Wie ist der Stand? Wer ist noch nicht da?"
- „Wann ist Abmarsch und wo ist der Ablaufpunkt?"

**Schreibend** (nur mit gesetztem Haken aus Schritt 3):

- „Lege einen Konvoi ‚Übung Nord' für Samstag 06:30 an."
- „Füge das ELW 1 hinzu."
- „Setz Florian 4 auf technischen Halt, Reifenschaden."
- „Berechne die Route."

ChatGPT blendet zu manchen Antworten eine **eigene Ansicht** ein: die
Konvoi-Liste, die Konvoi-Übersicht mit Marschbefehl und Fahrzeugen in
Marschordnung, oder den Marschstatus mit den Ausfällen zuoberst.

---

## Schreibende Aktionen

ChatGPT fragt vor jeder schreibenden Aktion nach und zeigt, was es senden will.
**Diese Anzeige lohnt sich zu lesen** — ein Modell kann eine Anweisung
missverstehen, und was es dann anlegt oder ändert, steht genau dort.

Die Option, eine Zustimmung dauerhaft zu merken, sollte man sparsam benutzen.
Sie ist bequem für „Status setzen" und riskant für alles, was einen Marschbefehl
verändert.

**Was nicht passieren kann:** Kein Werkzeug der Schnittstelle löscht Daten. Es
gibt keines, das einen Konvoi, ein Fahrzeug, einen Wegpunkt oder eine Route
entfernt. „Fahrzeug aus Konvoi entfernen" löst nur die Zuordnung — Fahrzeug und
Konvoi bleiben bestehen, und der Schritt lässt sich rückgängig machen.

---

## Was das für die Daten bedeutet

**Was ein Modell liest, verlässt die Instanz und geht an OpenAI.** Das gilt für
jeden Konvoi, jedes Fahrzeug und jede Position, nach der im Gespräch gefragt
wird. Für eine BOS-Organisation ist das die Entscheidung, die vor der
technischen Einrichtung steht — nicht danach.

Wer sie trifft, sollte wissen:

- Der Zugang ist auf **eine** Organisation und auf die Rolle des zustimmenden
  Benutzers begrenzt.
- Jeder **schreibende** Aufruf steht im Audit-Log, mit Benutzer, Werkzeug und
  dem Programm, das ihn ausgelöst hat.
- Lesende Aufrufe werden nicht protokolliert — ein Modell liest im Minutentakt.
- Der Betreiber kann die Schnittstelle jederzeit abschalten oder einzelne
  Verbindungen trennen.

Einzelheiten unter [Sicherheit und Datenschutz](Sicherheit-und-Datenschutz) und
[MCP-Server → Datenschutz](MCP-Server#datenschutz).

---

## Wenn es nicht funktioniert

| Symptom | Ursache | Abhilfe |
|---|---|---|
| ChatGPT findet den Server nicht | `/mcp` fehlt in der Adresse | Adresse aus dem Adminportal kopieren |
| „Verbindung fehlgeschlagen", Instanz läuft aber | Instanz nicht aus dem Internet erreichbar | ChatGPT verbindet sich von eigenen Servern aus, nicht vom Browser |
| Seite meldet 404 beim Anmelden | KI-Schnittstelle ist abgeschaltet | Adminportal → System → KI-Schnittstelle |
| Antworten kommen ohne Konvoidaten | Verbindung in dieser Unterhaltung nicht eingeschaltet | Plus-Menü → Developer mode → ConvoyPlan ankreuzen |
| Jede Änderung scheitert an fehlenden Rechten | Haken beim Zustimmen nicht gesetzt | Verbindung trennen und neu erteilen, diesmal mit Haken |
| Kein Schreibrecht zum Ankreuzen | Rolle gibt es nicht her | Rolle in der Organisation prüfen ([Rollen](Rollen)) |
| Schreibende Werkzeuge fehlen ganz | Instanz ohne gültige Lizenz | [Lizenz und Demo-Modus](Lizenz-und-Demo-Modus) |
| „Zu viele Werkzeugaufrufe" | Modell in einer Schleife | kurz warten; die Grenze steht im Adminportal |
| „Client ID … not found" nach der Weiterleitung | Die Registrierung ist im Adminportal gesperrt oder als verwaist entfernt worden | Verbindung in ChatGPT **löschen und neu anlegen** |
| Fehler bleibt, obwohl die Verbindung bearbeitet wurde | ChatGPT behält beim Bearbeiten seine gespeicherte Kennung | Löschen und neu anlegen — nur dabei registriert es sich neu |

Hilft nichts davon, sagt die Instanz selbst, was sie kann: frag im Gespräch
„Mit welcher Organisation bist du verbunden und was darfst du?" — die Antwort
nennt Organisation, Rolle, erteilte Rechte und die verfügbaren Werkzeuge.

---

## Zugang wieder entziehen

- **In ChatGPT:** die Verbindung unter Apps & Connectors löschen.
- **In ConvoyPlan:** Adminportal → Reiter **MCP** → Verbindung trennen. Das
  entwertet die Zugriffstoken sofort und wirkt auch dann, wenn in ChatGPT noch
  etwas eingetragen ist.

Der zweite Weg ist der verlässliche: Er liegt in der Hand des Betreibers.

> **Der Papierkorb im Portal sperrt, er löscht nicht.** ChatGPT merkt sich seine
> Kennung aus der Registrierung und benutzt sie stur weiter — auf eine gesperrte
> oder inzwischen aufgeräumte Kennung antwortet die Instanz mit „Client ID …
> not found". Anders als andere Programme registriert ChatGPT sich dann **nicht**
> von selbst neu. Wer die Verbindung wiederhaben will, legt sie in ChatGPT neu
> an, statt die bestehende zu bearbeiten.

---

## Was (noch) nicht geht

- **ConvoyPlan im öffentlichen App-Verzeichnis von ChatGPT.** Ein
  Verzeichniseintrag nennt genau eine Serveradresse; bei einer selbst
  gehosteten Software nützt das niemandem außer dem Betreiber genau dieser
  Adresse. Der Developer Mode bleibt deshalb der Weg.
- **Fahrer oder Teilnehmer zuordnen.** ConvoyPlan kennt keine Personen, die
  einem Fahrzeug zugeordnet wären — „Fahrer" ist eine Rolle in der
  Organisation, keine Zuordnung. Solche Fragen kann die Schnittstelle nicht
  beantworten.
- **Etwas löschen.** Bewusst nicht vorgesehen, siehe oben.
