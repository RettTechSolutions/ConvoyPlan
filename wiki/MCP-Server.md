# MCP-Server (KI-Schnittstelle)

ConvoyPlan kann seine Fachdaten über einen **Model-Context-Protocol-Server** bereitstellen. KI-Programme wie Claude Desktop, Claude Code oder claude.ai tragen die Instanz als *Remote-MCP-Server* ein und arbeiten danach mit Konvois, Fahrzeugen, Wegpunkten, Routen und Marschstatus — im Rahmen dessen, was der zustimmende Benutzer selbst darf.

> **Standardmäßig ausgeschaltet.** Ohne `MCP_ENABLED=true` existiert weder `/mcp` noch ein Discovery-Dokument. Das Einschalten öffnet Einsatzdaten für einen externen Modellanbieter — diese Entscheidung gehört dem Betreiber, nicht dem Auslieferungszustand.

---

## Was der Server kann

**Lesen** (neun Werkzeuge): Konvois und Unterkonvois auflisten, Konvoi-Details samt aller sieben Abschnitte des Marschbefehls, Fahrzeugbestand und Einzelfahrzeug, Wegpunkte in Marschreihenfolge, die gespeicherte Route, zuletzt gemeldete Positionen, Marschstatus, Mannschaftsstärke und Betriebsstofflage je Fahrzeug.

**Schreiben** (vierzehn Werkzeuge, nur mit gültiger Lizenz): Konvoi und Fahrzeug anlegen und ändern, Fahrzeuge zuordnen und wieder lösen, Marschfolge setzen, Wegpunkte anlegen, ändern und umsortieren, Route berechnen, Fahrzeugstatus, Mannschaftsstärke und Betriebsstoff melden.

Die Stärke meldet `fahrzeugstaerke_melden` in der Notation Führer/Unterführer/Mannschaften; die Gesamtzahl rechnet der Server und nimmt sie nicht entgegen. `konvoi_status` gibt sie je Fahrzeug und als Verbandsstärke zurück. Ein Fahrzeug **ohne** Meldung steht dort als `null` — nicht als `0/0/0`, das eine Meldung wäre und „unbesetzt" hieße. Melden braucht den Scope `fleet:status`, Lesen `convoy:read`; beides zusätzlich den freigegebenen Bereich *Live-Positionen, Marschstatus, Mannschaftsstärke und Betriebsstoff*.

Den Betriebsstoff meldet `fahrzeug_betriebsstoff_melden` — meist genügt `fuellstand_prozent`, denn Tankvolumen und Verbrauch kennt ConvoyPlan aus den Stammdaten des Fahrzeugs. Die Meldung ersetzt die vorige ganz und ändert die Stammdaten nicht. `konvoi_status` gibt je Fahrzeug Füllstand, Liter im Tank und Reichweite zurück (mit dem Hinweis, wo die Stammdaten eingesprungen sind) und für den Verband, wer knapp ist (ab 25 %) und wer noch nichts gemeldet hat. Bei E-Fahrzeugen liefert `konvoi_status` dieselben Angaben unter eigenen kWh-Schlüsseln (`akku_kapazitaet_kwh`, `verbrauch_kwh_100km`, `kwh_im_akku`, `reichweite_km`) statt `tank_l` und `liter_im_tank` — auch sie zählen in der Liste der knappen Fahrzeuge. Auch hier heißt `null` „nicht gemeldet", ein Füllstand `0` dagegen „leer". Scope und Bereich wie bei der Stärke.

**Dokumente** (Resources): Marschbefehl als PDF, Route als GPX, Konvoi als JSON — dieselben Exporte wie im Portal.

**Live mitlaufen** (Abonnement): Ein Programm kann einen Konvoi *abonnieren* und wird benachrichtigt, sobald sich dort etwas bewegt, statt im Sekundentakt nachzufragen. Übertragen wird dabei nur der Anstoß „hier gibt es Neues" — die Daten holt das Programm anschließend selbst, und dabei greift dieselbe Prüfung wie bei jedem anderen Zugriff. Voraussetzung ist ein Programm, das die MCP-Revision 2026-07-28 spricht.

## Was der Server nicht kann

| | |
|---|---|
| **Löschen** | Es gibt kein Werkzeug, das einen Konvoi, ein Fahrzeug, einen Wegpunkt, eine Route oder einen Benutzer löscht. Die einzige Ausnahme von der Anlegen-und-Ändern-Regel ist das **Lösen einer Fahrzeug-Zuordnung** — dabei bleiben Fahrzeug und Konvoi bestehen. |
| **Administration** | Keine Benutzerverwaltung, keine Lizenz, keine Systemkennzahlen, kein Regionswechsel, kein Branding, keine Leitstellen-Konfiguration. |
| **Mehrere Organisationen** | Ein Zugang gilt für genau **eine** Organisation, auch wenn der Benutzer in mehreren Mitglied ist. |

---

## Einschalten

Im Admin-Portal unter **System → KI-Schnittstelle**: ein Klick auf *Schnittstelle aktivieren*. Das wirkt sofort, ein Neustart ist nicht nötig.

Alternativ als Ausgangswert in der `.env`:

```
MCP_ENABLED=true
```

Die Einstellung aus dem Portal hat Vorrang; die Umgebungsvariable gilt, solange im Portal nichts eingestellt wurde. Der Reiter **MCP** zeigt anschließend den Zustand, die Verbindungsadresse und die erteilten Zugänge.

### Und dann noch je Organisation

Der Schalter oben sagt, ob es die Schnittstelle auf dieser Instanz **gibt**. Ob
eine einzelne Organisation daran teilnimmt, entscheidet deren eigener Admin —
im **Org-Adminbereich unter „KI-Zugriff"**, und **standardmäßig ist er aus**.

Das ist keine doppelte Absicherung aus Vorsicht, sondern eine Trennung: wer
eine Instanz für mehrere BOS-Organisationen betreibt, entscheidet nicht über
deren Einsatzdaten. Eine frisch angelegte Organisation nimmt deshalb nicht
teil, auch auf einer Instanz, auf der die Schnittstelle längst läuft.

Der Org-Admin stellt dort drei Dinge ein:

| Einstellung | Bedeutung |
|---|---|
| **KI-Zugriff erlauben** | Der Schalter der Organisation. Aus heißt: kein Werkzeug, keine Resource, kein Abo — auch für bestehende Verbindungen, ab dem nächsten Aufruf. |
| **Bereiche** | *Worauf.* Konvois und Marschbefehle, Fahrzeuge, Wegpunkte, Routen, Live-Positionen, Marschstatus und Mannschaftsstärke — einzeln an- und abwählbar. Was nicht angekreuzt ist, ist über die Schnittstelle nicht zu bekommen, auch nicht über ein anderes Werkzeug. |
| **Lesen / Status / Schreiben** | *Wie weit.* Lesen ist die Grundlage und lässt sich nicht abwählen — ohne sie käme keine Verbindung zustande. Statusmeldungen und Schreiben kommen nur dazu, wenn sie freigegeben sind. Gelöscht wird in keinem Fall. |

Die beiden Achsen wirken als **Und**: ein Werkzeug steht zur Verfügung, wenn
sein Bereich freigegeben *und* sein Zugriff erlaubt ist. Die Rolle des
Mitglieds bleibt die zweite Grenze darüber — ein Beobachter kann auch bei
voller Freigabe nichts Schreibendes erteilen.

Ein Assistent sieht dabei nur, was übrig bleibt: was die Organisation nicht
freigibt, steht gar nicht erst in seiner Werkzeugliste. Das ist Absicht — ein
Modell, das ein Werkzeug sieht, probiert es aus, und eine Absage nach dem
Versuch ist eine schlechtere Auskunft als ein Werkzeug, das es nicht gibt.

> **Beim Update auf diese Version** bleiben Organisationen eingeschaltet, an
> denen bereits eine aktive Verbindung hängt — mit genau den Rechten, die dort
> in Gebrauch sind. Eine laufende Anbindung soll nicht wortlos abreißen. Alle
> übrigen Organisationen stehen auf aus.

Im selben Tab steht die Liste der **bestehenden Verbindungen** dieser
Organisation. Den Zugriff abzuschalten trennt sie nicht — sie laufen dann ins
Leere. Wer sie wirklich los sein will, trennt sie dort einzeln.

### Was der Betreiber davon sieht

Im Admin-Portal unter **MCP** steht eine Übersicht aller Organisationen: ob sie
den KI-Zugriff freigegeben haben, welche Bereiche und Rechte, und wie viele
Verbindungen daran hängen. Abgeschaltete Organisationen sind eingeklappt und
über *Alle anzeigen* zu erreichen — dort steht dann auch die Antwort auf die
häufigste Rückfrage, warum eine Anbindung nicht zustande kommt.

Die Übersicht ist **nur zum Ansehen**. Der Betreiber der Instanz schaltet die
Schnittstelle als Ganzes ein oder aus; über die Einsatzdaten einer einzelnen
Organisation entscheidet deren Admin. Eine Zeile mit `0` Verbindungen und
„frei" heißt: es wäre möglich, es hat nur noch niemand verbunden.

### Wenn der Schalter auf „An" steht und trotzdem nichts geht

Zwei Dinge können es sein: der Reverse Proxy (unten) oder der
Zustimmungsbildschirm. Kommt der Client bis zur Anmeldung und scheitert dort,
liegt es nicht am Proxy.

#### Zustimmung: wer darf sie erteilen?

Jedes Mitglied einer Organisation, nicht nur Superadmins. Der Bildschirm
erkennt die **Person** und bietet danach alle Organisationen zur Auswahl an,
in denen sie Mitglied ist; die Rolle dort deckelt, welche Zugriffe erteilbar
sind.

Sind im selben Browser **verschiedene Personen** angemeldet, verweigert der
Bildschirm die Auskunft, statt sich eine auszusuchen. Dann in den anderen
Konten abmelden und im Client neu beginnen.

Wer nicht angemeldet ist, wird zur Anmeldung geschickt und danach auf den
Zustimmungsbildschirm zurückgebracht. Dauert das zu lange, verfällt die
Anfrage des Clients — dann im Client erneut starten.

Der Schalter mountet die Routen **im Backend**. Ob der Reverse Proxy sie von außen auch dorthin leitet, ist eine zweite Frage — und bei einer Installation, die von vor dieser Schnittstelle stammt, lautet die Antwort oft nein. Das Portal zeigte dann „An" samt Verbindungsadresse, und ein Aufruf von außen landete beim Frontend.

Der Reiter **System → KI-Schnittstelle** prüft das jetzt mit und sagt es: steht dort eine Zeile **Proxy** mit einem Hinweis, leitet der Proxy die Pfade nicht weiter. Der Knopf **Proxy reparieren** stellt sie her — er schreibt eine dauerhafte Proxy-Konfiguration und lädt sie sofort nach, ohne Neustart und ohne Zugriff auf den Server.

Geprüft wird dabei die **laufende** Konfiguration über Caddys Admin-API, nicht eine Datei auf der Platte. Das ist der Unterschied, der zählt: die Datei kann längst stimmen, während der Caddy-Container noch mit der alten Konfiguration läuft.

#### „Die Schnittstelle ist erreichbar, aber nicht dauerhaft hinterlegt"

Auf Installationen, die aus der Zeit stammen, als das Backend noch als `root`
lief, gehört das gemeinsame Verzeichnis `/certs` weiterhin `root` — Docker
überträgt die Besitzrechte aus dem Abbild nur beim allerersten Mount eines
leeren Volumes. Das Backend läuft seitdem als eigener Benutzer und darf dort
nicht mehr schreiben.

Der Knopf bringt die Routen in diesem Fall trotzdem in den laufenden Proxy —
das Nachladen braucht keine Datei — und sagt dazu, dass ein Neustart des
Proxy-Containers sie wieder verliert. Der Proxy zieht die Besitzrechte beim
nächsten Start selbst gerade, das passiert also spätestens mit dem nächsten
Update von allein. Danach genügt ein erneuter Klick, und die Konfiguration ist
dauerhaft hinterlegt. **Kein SSH-Zugriff nötig.**

Solange das aussteht, bleibt der Knopf sichtbar, obwohl die Schnittstelle
erreichbar ist — der Hinweis daneben sagt, warum.

Zwei Fälle kann der Knopf nicht lösen:

- **Die Setup-Werte fehlen** (Domain, TLS-Modus stehen nicht in der Datenbank). Daraus lässt sich keine Konfiguration erzeugen — dann hilft nur der Setup-Assistent. Das Portal bietet den Knopf in diesem Fall gar nicht erst an.
- **Caddys Admin-API antwortet nicht.** Dann ist der Zustand schlicht unbekannt; das Portal sagt das so, statt einen Fehler zu behaupten. Prüfen lässt es sich mit einem Aufruf von außen:

```
curl -i -X POST https://<domain>/mcp -H 'Content-Type: application/json' -d '{}'
```

| Antwort | Bedeutung |
|---|---|
| **401** mit `WWW-Authenticate` | Alles richtig — ein Client kann sich jetzt anmelden. |
| **404 als JSON** (`{"detail":"Not Found"}`) | Der Proxy leitet weiter, die Schnittstelle ist nur abgeschaltet. |
| **404 als HTML** | Der Proxy leitet **nicht** weiter — die Anfrage ist beim Frontend gelandet. |

---

> **Ausgeschaltet heißt wirklich ausgeschaltet.** Der Schalter entfernt die Routen, statt sie mit einer Fehlerseite zu bedecken: es gibt dann weder `/mcp` noch die Discovery-Dokumente — nicht als 404 eines Handlers, sondern weil keine Route passt. Genau das war der Grund, warum es lange nur eine Umgebungsvariable gab; die Zusage gilt mit dem Knopf unverändert weiter und wird von einem Test festgehalten.
>
> **Was das Ausschalten nicht tut:** bereits ausgestellte Zugriffstoken ungültig machen. Die laufen ins Leere, weil der Endpunkt fehlt, bleiben aber Tokens. Wer sie wirklich entziehen will, trennt die Verbindungen im Reiter **MCP**.

Der Reverse Proxy braucht Routen für `/mcp` und die OAuth-Pfade an der Wurzel der Site. **Bestehende Installationen rüsten das beim nächsten Backend-Start automatisch nach**; bei Neuinstallationen ist es von vornherein enthalten.

---

## Verbinden

1. Im Admin-Portal unter **MCP** die **Adresse** kopieren (`https://<domain>/mcp`).
2. Im KI-Programm als *Remote-MCP-Server* eintragen.
3. Das Programm öffnet den Browser auf der ConvoyPlan-Anmeldung.
4. **Anmelden** — mit dem eigenen Konto, inklusive MFA, falls eingerichtet.
5. **Organisation wählen.** Der Zugang gilt nur für diese.
6. **Rechte ankreuzen.** Vorausgewählt ist, was das Programm verlangt hat. Was
   die eigene Rolle darüber hinaus hergibt, steht darunter zum Ankreuzen —
   und was sie nicht hergibt, ist durchgestrichen und wird nicht erteilt.
7. **Zustimmen.** Erst damit entsteht ein Zugang.

Auf dem Zustimmungsbildschirm stehen zwei Angaben nebeneinander, und der Unterschied ist wichtig:

| Angabe | Bedeutung |
|---|---|
| **Name des Programms** — als *ungeprüft* gekennzeichnet | Selbstauskunft. Jedes Programm, das die Instanz erreicht, kann sich registrieren und sich dabei nennen, wie es will — auch „ConvoyPlan Desktop". |
| **Zieladresse** — als *geprüft* gekennzeichnet | Wurde bei der Registrierung hinterlegt und wird überprüft. Dorthin geht der Zugang. |

**Zustimmen nur, wenn du dieses Programm gerade selbst verbunden hast und die Zieladresse dazu passt.**

> **ChatGPT** braucht ein paar Schritte mehr — Developer Mode, Einschalten je Unterhaltung, und den Haken bei den Schreibrechten, den es später nicht nachholen kann. Dafür gibt es eine eigene Seite: [ConvoyPlan in ChatGPT verbinden](ChatGPT-verbinden).

---

## Berechtigungen

Die Rechte des Zugangs sind eine Projektion der Rolle in der gewählten Organisation — nicht mehr, als der Benutzer selbst darf:

| Berechtigung | ab Rolle | erlaubt |
|---|---|---|
| `convoy:read` | beobachter | Konvois, Fahrzeuge, Wegpunkte, Routen und Positionen lesen |
| `fleet:status` | fahrer | zusätzlich Fahrzeugstatus, Positionen und Mannschaftsstärke melden |
| `convoy:write` | planer | zusätzlich anlegen, ändern und Routen berechnen |

Darüber liegt die Freigabe der Organisation (siehe *Und dann noch je
Organisation*). Sie deckelt beides: die Bereiche und die Berechtigungen. Was
die Organisation nicht freigibt, bekommt auch ein Admin nicht erteilt — und
was sie später zurücknimmt, ist mit dem nächsten Aufruf zu.

Geprüft wird bei **jedem** Aufruf frisch gegen die Datenbank. Wird eine Mitgliedschaft entzogen, eine Rolle herabgestuft oder eine Freigabe zurückgenommen, wirkt das sofort — nicht erst, wenn der Zugang abläuft.

---

## Nachvollziehbarkeit

Jeder **schreibende** Aufruf erzeugt einen Eintrag im Audit-Log mit Benutzer, Organisation, Werkzeugname, Parametern und dem Programm, das ihn ausgelöst hat. Die Quelle ist als `mcp` gekennzeichnet — im Log ist damit unterscheidbar, was ein Mensch im Portal getan hat und was ein Modell über die Schnittstelle.

Lesende Aufrufe werden bewusst **nicht** protokolliert. Ein Modell liest im Minutentakt; das Log wäre sonst nach einer Woche unbrauchbar.

---

## Zugang entziehen

Im **Org-Adminbereich unter „KI-Zugriff"** (für die eigene Organisation):

- **KI-Zugriff abschalten** — wirkt sofort auf alle Verbindungen dieser Organisation. Sie bleiben stehen und laufen ins Leere; wieder einschalten stellt sie ohne Zutun her.
- **Einzelne Bereiche oder Berechtigungen zurücknehmen** — wirkt ebenso sofort, ohne die Verbindung zu beenden.
- **Verbindung trennen** — nimmt eine erteilte Zustimmung endgültig zurück.

Im Admin-Portal unter **MCP** (für die ganze Instanz):

- **Verbindung trennen** — entzieht einem Benutzer den Zugang für ein bestimmtes Programm.
- **Programm sperren** — trennt alle seine Verbindungen und verhindert eine neue Autorisierung.

Zusätzlich entzieht jede Maßnahme, die ohnehin alle Sitzungen beendet (Passwortwechsel, „überall abmelden", Deaktivieren des Kontos, Entzug der Mitgliedschaft), auch die MCP-Zugänge.

### Verwaiste Registrierungen aufräumen

Die Liste **Registrierte Programme** wächst schneller, als man erwartet: bei Selbstregistrierung legt **jeder** Verbindungsversuch eine Zeile an — auch der abgebrochene, und manche Programme registrieren sich bei jedem Anlauf neu. Nach ein paar Versuchen stehen dort ein Dutzend gleich aussehender Einträge, von denen einer etwas trägt.

Als **verwaist** gilt eine Zeile, an der nichts mehr hängt: keine Verbindung, kein laufender Verbindungsversuch, und älter als eine Stunde. Solche Zeilen sind gekennzeichnet, und der Knopf **„… verwaiste entfernen"** löscht genau sie.

Zwei Punkte dazu:

- **Das ist kein Zugangsentzug.** Eine Registrierung *ist* kein Zugang — der entsteht erst durch die Zustimmung eines Benutzers. Was eine Verbindung trägt, bleibt deshalb stehen, auch wenn es alt ist und auch wenn es gesperrt ist.
- **Es passiert ohnehin von selbst.** Der nächtliche Aufräumdurchgang macht dasselbe, nur mit größerer Frist (`RETENTION_OAUTH_CLIENTS_DAYS`, Standard 7 Tage). Der Knopf nimmt das vorweg, wenn man die Liste jetzt lesbar haben will.

Eine gelöschte Registrierung hält niemanden fern: das Programm registriert sich beim nächsten Versuch neu und bekommt eine neue Kennung. Mit einer Ausnahme, die man kennen sollte: **ChatGPT** registriert sich nicht von selbst neu, sondern bleibt bei seiner gespeicherten Kennung und meldet einen Fehler — dort muss die Verbindung neu angelegt werden (siehe [ChatGPT verbinden](ChatGPT-verbinden#wenn-es-nicht-funktioniert)). Wer ein Programm *fernhalten* will, sperrt es — oder schaltet die Selbstregistrierung ab (`MCP_ALLOW_DCR=false`).

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
| `MCP_ENABLED` | `false` | Ausgangswert für die Schnittstelle. Der Schalter im Portal (System → KI-Schnittstelle) hat Vorrang und wirkt ohne Neustart. |
| `MCP_PUBLIC_URL` | aus `APP_BASE_URL` | Die Adresse, unter der Clients den Server erreichen. Ohne abschließenden Schrägstrich. |
| `MCP_ACCESS_TOKEN_TTL_MINUTES` | `15` | Gültigkeit eines Zugriffstokens — siehe Zeitfenster oben. |
| `MCP_REFRESH_TOKEN_TTL_DAYS` | `30` | Wie lange eine Verbindung ohne erneute Zustimmung hält. |
| `MCP_ALLOW_DCR` | `true` | Ob sich Programme selbst registrieren dürfen. Aus bedeutet: Clients von Hand eintragen. |
| `MCP_ALLOW_CIMD` | `false` | Ob Programme sich über eine hinterlegte Steckbrief-URL ausweisen dürfen — siehe unten. |
| `MCP_CIMD_CACHE_MINUTES` | `60` | Wie lange ein abgeholter Steckbrief gilt. |
| `MCP_TOOL_CALLS_PER_MINUTE` | `120` | Obergrenze je Verbindung. Ein Modell in einer Schleife ist ein realistisches Lastprofil. |

Routenberechnungen zählen zusätzlich gegen `QUOTA_ROUTING_PER_HOUR` — dieselbe Einstellung wie an der REST-API.

---

## Programme ohne Selbstregistrierung (CIMD)

Die Selbstregistrierung (`MCP_ALLOW_DCR`) hat einen bekannten Haken: **jedes** Programm, das die Instanz erreicht, kann sich eintragen und sich dabei nennen, wie es will. Deshalb steht der Name auf dem Zustimmungsbildschirm als *ungeprüft*.

Der Nachfolger heißt **Client ID Metadata Documents**. Statt sich einzutragen, nennt ein Programm als Kennung eine HTTPS-Adresse, unter der sein Steckbrief liegt — der Server holt ihn dort ab. Die Kennung ist damit selbst überprüfbar: sie sagt, wem das Programm gehört.

**ChatGPT bevorzugt diesen Weg.** Ohne ihn fällt es auf die Selbstregistrierung zurück, die weiterhin funktioniert — die Anbindung scheitert daran also nicht, sie läuft nur über die schwächere Kennung.

Das ist standardmäßig **aus**, und zwar bewusst. Eingeschaltet ruft der Server eine Adresse ab, **die der Client bestimmt** — die klassische Zutat für einen Angriff auf das interne Netz. Abgesichert ist das: nur HTTPS, keine internen, privaten oder Link-Local-Adressen (jede aufgelöste, nicht nur die erste), keine Weiterleitungen, harte Zeit- und Größengrenzen. Trotzdem bleibt es eine Entscheidung des Betreibers.

Der Schalter sitzt im Admin-Portal unter **System → KI-Schnittstelle**, direkt unter dem Hauptschalter, und wirkt ohne Neustart. `MCP_ALLOW_CIMD` in der `.env` ist nur noch der Ausgangswert — was im Portal eingestellt ist, schlägt ihn.

Zwei Dinge dazu:

- **Zudrehen wirkt sofort.** Die Prüfung steht vor dem Zwischenspeicher; ein bereits abgeholter Steckbrief hilft danach niemandem mehr.
- **Aufdrehen sieht ein Client unter Umständen verzögert.** Das Discovery-Dokument, in dem die Instanz CIMD ankündigt, darf eine Stunde zwischengespeichert werden. Wer gerade verbindet und nichts davon merkt, versucht es nach einer Stunde erneut.

Bestehende Verbindungen sind von beidem nicht betroffen — sie hängen an ihren Tokens, nicht am Ausweisweg.

---

## Oberflächen in ChatGPT

Manche Programme können zu einer Antwort mehr zeigen als Text. ConvoyPlan liefert dafür drei Ansichten mit, die ChatGPT im Gespräch einblendet:

| Ansicht | erscheint bei |
|---|---|
| **Konvoi-Liste** — Abmarschzeit, Umfang, Status je Konvoi | „Welche Konvois habe ich?" |
| **Konvoi-Übersicht** — Marschbefehl und Fahrzeuge in Marschordnung | „Zeig mir den Konvoi nach München" |
| **Marschstatus** — Zusammenfassung, Status und Mannschaftsstärke je Fahrzeug, Ausfälle zuerst | „Wie ist der Stand?" |

Wie die Verbindung dorthin entsteht: [ConvoyPlan in ChatGPT verbinden](ChatGPT-verbinden).

Drei Dinge, die dazugehören:

- **Der Server funktioniert ohne sie vollständig.** Ein Programm, das keine Oberflächen kennt — Claude Desktop etwa —, bekommt unverändert dieselbe Antwort wie bisher. Es gibt nichts, was nur in einer Ansicht steht.
- **Die Ansichten laden nichts nach.** Kein Skript, kein Zeichensatz, kein Bild von einer fremden Adresse. Das Fenster spannt ChatGPT auf, die Daten darin gehören der Organisation; was dort nachgeladen würde, säße als dritte Partei in genau dieser Sichtlinie.
- **Sie tragen keine eigenen Rechte.** Eine Ansicht ist eine leere Vorlage; die Daten kommen aus dem Werkzeugaufruf, und der geht durch dieselbe Prüfung wie jeder andere.

---

## Wenn die Rechte nicht reichen

Versucht ein Programm etwas, wofür sein Zugang nicht genügt, bekommt es keine nichtssagende Fehlermeldung, sondern die Auskunft, **welches** Recht fehlt. Programme, die das beherrschen, fordern es daraufhin von sich aus nach — für den Benutzer heißt das: eine Nachfrage im Browser, kein Neu-Einrichten der Verbindung.

Nicht jedes Programm kann das. **ChatGPT etwa fragt einmalig beim Verbinden** und später nicht mehr. Deshalb lassen sich die Rechte schon auf dem Zustimmungsbildschirm ankreuzen: Wer weiß, dass er im Chat auch etwas anlegen oder ändern will, setzt dort gleich den Haken bei *Konvois und Fahrzeuge anlegen und ändern*. Ohne diesen Haken bleibt die Verbindung lesend, und der Versuch endet mit dem Hinweis, dass sie neu erteilt werden muss.

Was erteilt werden kann, deckelt in jedem Fall die Rolle. Ein *beobachter* bekommt `convoy:write` nicht — weder durch Ankreuzen noch durch Nachfordern, und auch dann nicht, wenn das Programm ausdrücklich danach fragt.

---

## Technischer Hintergrund

Die Instanz ist zugleich **Resource Server und Authorization Server**: eine selbst gehostete Installation hat keinen externen Identitätsanbieter, und Benutzer, MFA, Organisationen und Rollen liegen ohnehin in der eigenen Datenbank.

Umgesetzt nach der MCP-Revision **2026-07-28**: Protected Resource Metadata nach RFC 9728 an der Wurzel der Site, PKCE ausschließlich mit `S256`, Resource Indicators nach RFC 8707 (ein Zugang für Instanz A ist an Instanz B wertlos) und der `iss`-Parameter nach RFC 9207 in jeder Antwort — auch in einer Absage, damit ein Programm den Absender prüfen kann.

Zugänge erneuern sich rollierend. Taucht ein bereits erneuertes Token noch einmal auf, hat es jemand mitgelesen — dann wird die **gesamte** Verbindung entzogen, nicht nur das vorgelegte Token.

Die Live-Abonnements laufen über `subscriptions/listen`. Die Adresse einer abonnierbaren Resource trägt die Organisation in sich (`convoyplan://org/<org>/konvoi/<id>/live`) — daran entscheidet der Server, wer eine Benachrichtigung bekommt. Das ist nicht kosmetisch: das MCP-SDK nimmt jede angefragte Adresse ohne Rückfrage an, die Trennung nach Organisationen muss also aus der Form der Adresse selbst kommen. Ein Programm, das die Adresse eines fremden Konvois errät, erfährt davon nichts.
