# Beiträge auf der Aktionsseite — Fotos aus Telegram, in der Gruppe freigegeben

Anlass: Zuschauer der Aktionsseite wollen Bilder sehen, nicht nur einen Punkt,
der über die Karte kriecht. Fahrer und Begleiter laden unterwegs Fotos in eine
Telegram-Gruppe und schreiben ein paar Worte dazu. In derselben Gruppe sitzen
Leute der Pressestelle. Sie geben Beiträge frei und bearbeiten den Text. Erst
danach kommt ein Beitrag in die Warteschlange und erscheint nach festen Regeln
auf der Karte, dort, wo der Konvoi war. Auf der Seite sieht er aus wie ein
Polaroid.

Dieses Dokument hält fest, was die Funktion darf, was sie nicht darf, was dafür
gebaut werden muss und in welcher Reihenfolge. Es baut auf
`2026-10-02-oeffentliche-aktionsseite.md` auf und ändert keine der drei Regeln
dort, sondern wendet sie auf Beiträge an.

---

## 1. Warum „live" ausgeschlossen ist

Die Aktionsseite steht auf einem Satz: **Draußen liegt nie eine
Echtzeitposition.** Ein Foto, das um 14:03 in der Gruppe landet und um 14:03
auf der Seite erscheint, ist eine Echtzeitposition, auch ohne Koordinate:

| Was verrät | Wodurch | Hilft dagegen |
|---|---|---|
| exakte Position | EXIF-GPS | neu kodieren, Metadaten verwerfen |
| Ort | Bildinhalt: Ortsschild, Autobahnkilometer, Rastplatzname, Kirchturm | **nur** Verzögerung, nichts sonst |
| Ort | Text: „Wir stehen an der A3 bei Würzburg" | Freigabe durch die Presse, Verzögerung |
| Fortschritt | der Zeitpunkt („gerade eben") neben einer Linie, die vor zwei Stunden endet | Verzögerung |
| Standort über Nacht | Foto vom Autohof um 20 Uhr, ab 22 Uhr auf der Seite, der Konvoi steht noch dort | Zurückhalten, solange er dort steht (§ 4.2) |

Gegen Bildinhalt hilft kein Filter. Ein Beitrag darf deshalb erst sichtbar
werden, wenn auch die Position zu seinem Zeitpunkt sichtbar ist, und er darf
nie mehr verraten als die Karte zu diesem Zeitpunkt.

Daraus folgt dieselbe Aufteilung wie bei den Positionen: **Verzögerung,
Platzierung und Zurückhalten macht ConvoyPlan.** Die Freigabe durch die Presse
kommt dazu, sie ersetzt keine dieser Regeln. Der EventTracker bekommt nur
Beiträge, die er zeigen darf, und hat keine Regel, die man bei einer Übernahme
umgehen könnte.

## 2. Gruppen und Rollen

### 2.1 Eine Gruppe je Konvoi, oder eine Gruppe mit Themen

Ein Beitrag muss eindeutig zu einem Konvoi gehören, sonst lässt er sich nicht
platzieren. Beides wird unterstützt, weil es dasselbe kostet:

- **Eine Gruppe je Konvoi.** Am einfachsten zu verstehen. Die Presseleute
  müssen in jeder Gruppe sein.
- **Eine Supergruppe mit Themen (Topics), ein Thema je Konvoi.** Die Presse
  sitzt an einer Stelle, und die Fahrer posten in „ihr" Thema.
  `message_thread_id` unterscheidet die Konvois.

Gebunden wird deshalb an `(chat_id, message_thread_id)`, wobei Letzteres leer
sein darf. **Empfehlung: Themen**, sobald es mehr als zwei Konvois sind. Fünf
Gruppen, in denen dieselben drei Presseleute mitlesen müssen, pflegt nach drei
Tagen niemand mehr.

Verbunden wird über einen Code, nicht über eine eingetippte Chat-ID:

1. Der Org-Admin klickt in ConvoyPlan beim Konvoi auf *Telegram verbinden* und
   bekommt einen Einmalcode (`/verbinden 7KQ-2MX`, 15 min gültig).
2. Jemand schreibt den Befehl in die Gruppe bzw. in das Thema. Der Bot bindet
   und antwortet dort mit einem festen Satz: „Fotos hier können nach Freigabe
   durch die Presse öffentlich erscheinen, mindestens N Minuten verzögert."
   Damit weiß jedes Mitglied, worauf es sich einlässt.
3. Nachrichten aus Chats oder Themen ohne Bindung verwirft der Bot, ohne zu
   antworten.

### 2.2 Wer Presse ist

Freigeben und Texte ändern darf nur, wer **ausdrücklich als Presse
eingetragen** ist, je Aktionsseite und damit für alle ihre Gruppen.

- Nicht „wer in Telegram Gruppenadmin ist". Das sind oft die Fahrer selbst, oder
  wer die Gruppe zufällig angelegt hat. Admin-Status in Telegram ist
  Gruppenverwaltung, keine Presseverantwortung.
- Eingetragen wird wie verbunden, mit einem Code: Der Org-Admin erzeugt einen
  Presse-Code (24 h gültig, mehrfach verwendbar), die Person schickt dem Bot
  **privat** `/presse 4TR-8LK`. Gespeichert werden Telegram-User-ID und
  Anzeigename. Der Org-Admin sieht die Liste in ConvoyPlan und kann Einträge
  entfernen.
- Über die Telegram-User-ID: Die kommt bei Long Polling direkt von Telegram
  (`callback_query.from.id`, `message.from.id`) und ist nicht zu fälschen.
  Anders als der Anzeigename, der gilt nichts.
- Org-Admins können in ConvoyPlan dasselbe wie die Presse. Das ist der
  Notnagel, wenn unterwegs niemand Netz hat.

## 3. Ablauf in der Gruppe

### 3.1 Ein Beitrag entsteht

Ein Beitrag ist eine Nachricht mit Foto **oder ein Album** (`media_group_id`,
bis zu 10 Bilder) samt Bildunterschrift. Telegram schickt ein Album als
einzelne Updates, nur eines trägt die Unterschrift. Der Abholer sammelt Updates
mit derselben `media_group_id` zwei Sekunden lang und macht daraus einen
Beitrag.

Angenommen werden:

- `message.photo` (von Telegram schon verkleinert, ohne EXIF) und
  `message.document` mit Bild-MIME-Typ (Original **mit** EXIF, wird trotzdem
  angenommen, weil § 5 ohnehin neu kodiert).
- **Keine weitergeleiteten Nachrichten** (`forward_origin` gesetzt). Sie
  können alt sein oder von woanders stammen.
- Text ohne Bild ist kein Beitrag. Das ist die Unterhaltung in der Gruppe.
- **Zeitpunkt = `message.date`**, nicht EXIF `DateTimeOriginal`. EXIF stellt
  jedes Handy anders ein und lässt sich frei setzen. Ein Foto aus dem Funkloch
  hat ein späteres `message.date` als seine Aufnahme. Das verschiebt es nach
  hinten, also zur sicheren Seite.
- Höchstens 20 MB je Bild (Grenze von `getFile`), höchstens 300 Bilder je
  Gruppe und Tag.

### 3.2 Die Karte des Bots, eine je Beitrag

Der Bot antwortet auf jeden Beitrag mit **genau einer** Nachricht und
**bearbeitet sie** bei jedem Statuswechsel (`editMessageText`), statt neue zu
schreiben. Sonst ertrinkt die Gruppe in Bot-Meldungen.

```
📷 Beitrag #12 · Konvoi Bosnien · 3 Bilder · von Jonas
„Grenze geschafft, alle wohlauf! Danke an die Kollegen in Zagreb."

⏳ Wartet auf Presse
[✅ Freigeben]  [✏️ Text ändern]  [❌ Ablehnen]
```

Nach der Freigabe:

```
✅ Freigegeben von Anna · in der Warteschlange
   erscheint frühestens 16:05 (Verzögerung 120 min)
[✏️ Text ändern]  [↩️ Zurückziehen]
```

Später, wenn er draußen ist: `🌍 Öffentlich seit 16:07`. Wird er nach § 4.2
zurückgehalten: `⏸ Zurückgehalten, der Konvoi steht noch dort`. Ein Absatz
genügt, die Gruppe soll verstehen, warum ein freigegebenes Bild noch fehlt.

Der Name „von Jonas" steht nur in der Gruppe, nie auf der Seite (§ 4.3).

### 3.3 Knöpfe

- Drückt jemand ohne Presse-Eintrag einen Knopf: `answerCallbackQuery` mit
  `show_alert` („Freigeben darf nur die Presse") und sonst nichts.
- `callback_data` (höchstens 64 Byte): `b:<kurze-id>:<aktion>`. Der Server
  prüft bei jedem Druck neu: Presse-Eintrag für **diese** Aktionsseite,
  Beitrag gehört zu dem Chat, aus dem der Druck kommt, Status erlaubt die
  Aktion. Dem Inhalt von `callback_data` wird nichts geglaubt.
- **Text ändern:** Der Bot schickt `✏️ Neuer Text für #12 — antworte auf diese
  Nachricht` als `ForceReply` (`selective`, also nur für die Person, die
  gedrückt hat). Die Antwort dieser Person wird der öffentliche Text, höchstens
  500 Zeichen, und die Karte zeigt ihn. Leere Antwort oder `-` heißt: ohne
  Text. Antworten anderer auf diese Nachricht werden ignoriert.
- **Ablehnen** entfernt nur den Beitrag aus ConvoyPlan. Die Nachricht in der
  Gruppe bleibt, löschen kann der Bot sie aus gutem Grund nicht.
- **Zurückziehen** geht jederzeit, auch wenn der Beitrag schon draußen ist.
  Er fällt mit dem nächsten Abruf aus der Antwort, und der EventTracker löscht
  seine Kopie.

### 3.4 Was mit dem Text der Fahrer passiert

Die Bildunterschrift ist der **Vorschlag** für den öffentlichen Text und steht
auf der Karte des Bots. Mit *Freigeben* gibt die Presse **genau den Text frei,
der auf der Karte steht**, geändert oder nicht. Hinaus geht immer der Text auf
der Karte, nie der rohe aus der Nachricht.

Eine Falle: Telegram erlaubt das **Bearbeiten** einer Nachricht nachträglich
(`edited_message`). Bearbeitet der Fahrer seine Unterschrift,

- solange der Beitrag wartet: wird der Vorschlag auf der Karte ersetzt,
  sofern die Presse ihn noch nicht geändert hat;
- **nach der Freigabe: ignoriert.** Sonst ließe sich ein freigegebener Text
  hinterher still austauschen. Die Karte zeigt dann einen Hinweis („Jonas hat
  den Text in Telegram geändert, öffentlich bleibt der freigegebene"), und die
  Presse kann ihn mit *Text ändern* übernehmen.

Dasselbe gilt für Bilder: Wird in Telegram ein Bild ausgetauscht, bleibt das
freigegebene.

### 3.5 „Terminiert": die Warteschlange

Freigegeben heißt **in der Warteschlange**, nicht öffentlich. Öffentlich wird
ein Beitrag, sobald § 4.2 es erlaubt. Das prüft niemand von Hand, das ergibt
sich bei jedem Abruf des EventTrackers.

Die Presse kann einen Beitrag zusätzlich **später** terminieren, nie früher:
`/ab 18:00` als Antwort auf die Karte setzt eine Untergrenze („erst zur
Pressekonferenz"). Sichtbar wird er dann bei `max(Regelzeit, ab)`. Eine Zeit
vor der Regelzeit beantwortet der Bot mit der Regelzeit, ohne Fehler.

Umgesetzt in Schritt 7 (`_ab`, `termin_lesen` in `services/aktionsseite_telegram.py`):

- Als Antwort auf die Karte **oder** auf das Foto selbst; ohne Bezug erklärt
  der Bot, wie es geht. Nur die Presse dieser Seite, wie bei den Knöpfen.
- `18:00` ist das **nächste** 18:00 in deutscher Ortszeit (um 23 Uhr also
  morgen früh), `27.12. 18:00` oder `27.12.2026 18:00` ein bestimmter Tag,
  `/ab -` nimmt den Termin weg. Höchstens sieben Tage voraus.
- Geht auch an wartenden Beiträgen; der Termin gilt dann ab der Freigabe.
  An einem schon öffentlichen nicht — dafür gibt es *Zurückziehen*.
- Die Karte sagt „erscheint frühestens … (Termin der Presse)“, der
  Zwischenspeicher der Seite wird geleert. Audit
  `org.aktionsseite.beitrag_terminiert`. Im Org-Admin dasselbe über
  *Erst ab …* (`not_before` in `PUT …/beitraege/{id}`).

Damit die Karte „🌍 Öffentlich seit" zeigen kann, läuft eine zweite Schleife
im Backend (einmal pro Minute), die für freigegebene Beiträge die
Sichtbarkeit nach § 4.2 berechnet und Statuswechsel an Telegram meldet. Es ist
dieselbe Funktion, die auch `nutzlast` benutzt.

## 4. Die Regeln

Reine Funktionen in `services/aktionsseite.py`, ohne Datenbank und Uhr:
`beitrag_position` und `beitrag_sichtbar`, geprüft von
`tests/test_aktionsseite_beitraege.py`. Beide rechnen mit **derselben** `lage()`
wie `konvoi()` (Vertreter, Halte mit Schutzbereich, Parkplatz, Ende der Linie).
Ein Foto zeigt damit nie mehr als die Karte daneben, und wer an den Halteregeln
dreht, ändert die Beiträge mit.

### 4.1 Platzierung aus dem Verlauf, nie aus dem Foto

Ein Beitrag liegt dort, wo der **Vertreter** des Konvois zum Zeitpunkt
`message.date` war, interpoliert zwischen den Verlaufspunkten davor und danach.

- Fällt der Zeitpunkt in den **Schutzbereich eines Halts** (`halt_bei`, also
  auch schon auf der Anfahrt und noch nach der Abfahrt, und ebenso in einem
  Funkloch ab 20 min), liegt der Beitrag auf dem **Parkplatz dieses Halts**:
  derselben Stelle, an der der Konvoi in dieser Zeit auf der Seite stand,
  `coarse: true`. Kein zweiter Versatz, sonst ließen sich beide gegeneinander
  rechnen.
- Liegt der Halt am Ziel (`ANKUNFT_RADIUS_M`), wird wie bei der Ankunft nur
  vergröbert.
- Ohne Verlaufspunkt in ±15 min (`BEITRAG_NAEHE`) und außerhalb jedes Halts
  hat der Beitrag **keine Position**. Er erscheint dann nur in der Leiste des
  Konvois. Typischer Fall ist ein Foto von vor der Abfahrt.

### 4.2 Sichtbar ab der Stichzeit, zurückgehalten während eines Halts

Ein freigegebener Beitrag geht hinaus, wenn **alle** Bedingungen gelten:

1. `beitrag.at <= stichzeit` (dieselbe Stichzeit wie für die Positionen),
2. `ab` ist leer oder vorbei (§ 3.5),
3. liegt der Beitrag im Schutzbereich eines Halts, hat der Konvoi diesen
   Bereich zur Stichzeit **verlassen**. Ausnahme: der Halt am Ziel, sobald der
   Konvoi angekommen ist. Sonst käme das Übergabefoto nie, und der Ort steht
   vergröbert ohnehin da.
4. Hält der Konvoi zur Stichzeit irgendwo, nur Beiträge, die die Linie schon
   zeigt (`beitrag.at` nicht nach dem letzten Punkt der Linie).

Bedingung 3 schließt die Lücke aus § 1, letzte Zeile: Das Foto vom Autohof
erscheint erst, wenn der Konvoi auf der Seite wieder fährt. Bedingung 4 hält
Fotos zurück, die zwischen dem Ende der Linie und dem Halt entstanden sind; sie
verrieten sonst, wie weit er schon ist. Ein schon sichtbarer Beitrag kann
dadurch kurz wieder verschwinden, wenn der Konvoi kurz danach hält. Das ist
gewollt: Er geht nur aus der Antwort, und der EventTracker holt ihn danach
erneut.

Damit ist ein Beitrag nie früher sichtbar als die Linie, die zu seinem Ort
führt.

### 4.3 Nur, was die Presse freigegeben hat, und nichts über die Absender

- Ohne Freigabe geht nichts hinaus, egal wie alt.
- Der **Absender wird nie veröffentlicht**, weder Name noch Kennung. Auf der
  Seite steht „Konvoi Bosnien, 12:40 Uhr", nicht „Jonas". Gespeichert werden
  Telegram-ID und Anzeigename für die Karte in der Gruppe und fürs
  Audit-Log, gelöscht mit dem Beitrag.
- Jede Freigabe, Textänderung, Ablehnung und jedes Zurückziehen steht im
  Audit-Log (`org.aktionsseite.beitrag_*`). Die Presse hat kein
  ConvoyPlan-Konto, deshalb ohne `actor_id`, mit Telegram-ID und Anzeigename
  in `detail`. `audit.record` erlaubt das schon.

## 5. Bildverarbeitung

Beim Eingang, einmal, in `services/aktionsseite_bild.py` (`verarbeiten`,
geprüft von `tests/test_aktionsseite_bild.py`):

- Pillow (schon in `requirements.txt`). Höchstens 20 MB und 40 Megapixel; die
  Pixelzahl wird aus dem Kopf der Datei geprüft, **bevor** dekodiert wird
  (Dekompressionsbombe). Nur JPEG, PNG und WebP. GIF, BMP, TIFF, SVG und HEIC
  werden abgelehnt (`BildFehler`). Als `photo` liefert Telegram ohnehin JPEG.
  Bei animierten Dateien zählt das erste Bild.
- `ImageOps.exif_transpose`, ICC-Profil nach sRGB umgerechnet, Transparenz
  auf weißen Grund, dann in ein **frisches** Bild ohne `info` kopiert und neu
  kodiert. Was in den Metadaten stand, existiert danach nicht mehr; der Test
  schreibt ein JPEG mit GPS hinein und sucht danach auch in den rohen Bytes.
- **Quadratisch zugeschnitten** für die Polaroid-Ansicht (§ 10) wird **nicht**
  hier, sondern im Browser per `object-fit: cover`. Gespeichert wird das
  ganze Bild, damit die Lightbox es ungeschnitten zeigen kann.
- Zwei Größen: 1600 px lange Kante (Ansicht) und 400 px (Polaroid auf der
  Karte), WebP, Qualität ~80.
- Gespeichert als `bytea` in einer eigenen Tabelle, nicht im Dateisystem: Bei
  einigen hundert Bildern je Aktion sind das um 150 MB, sie liegen im
  vorhandenen Backup, und es braucht weder ein neues Volume noch eine Zeile im
  Installer. Wird das zu groß, lohnt sich ein Volume. Das ist eine bewusste
  Grenze.
- Das Original von Telegram wird nicht aufbewahrt. Verarbeitet wird **beim
  Eingang**, nicht erst bei der Freigabe. Die Karte des Bots braucht die
  Vorschau nicht, aber ConvoyPlans Admin-Ansicht schon, und die `file_id` von
  Telegram ist nur begrenzt abrufbar.

## 6. Telegram-Anbindung

- **Long Polling (`getUpdates`), kein Webhook.** Viele Instanzen stehen hinter
  NAT oder ohne öffentliche Adresse für das Backend. Ein Webhook bräuchte eine
  eingehende Route von Telegram ins Backend, Polling nur ausgehend HTTPS zu
  `api.telegram.org`. Eine Schleife im `_lifespan` wie `anwesenheit_loop`,
  `allowed_updates = ["message", "edited_message", "callback_query"]`.
- **Ein Bot je Organisation**, Token verschlüsselt mit `services/crypto.py`
  (`encrypt_secret`). Eingetragen wird es im Org-Admin bei den Aktionsseiten,
  angezeigt wird es nie wieder (wie das Abruf-Token).
- **Nur ein Abholer je Token**: Telegram antwortet zwei gleichzeitigen
  `getUpdates` mit 409. Heute läuft ein uvicorn-Prozess. Trotzdem gehört ein
  `pg_try_advisory_lock` je Bot davor, sonst bricht es beim ersten
  `--workers 2` still.
- **Privacy Mode**: Ein Bot in einer Gruppe sieht im Standard nur Befehle und
  Antworten an ihn, **keine Fotos**. Der Org-Admin muss bei BotFather
  `/setprivacy` → *Disable* setzen oder den Bot zum Gruppenadmin machen. Das
  gehört in die Einrichtungsanleitung im Admin-Dialog und in die Prüfung
  (`getMe` → `can_read_all_group_messages`). Die meisten Supportfälle
  „Bot sieht nichts" kommen genau daher.
- **Ratenlimit von Telegram** (etwa 20 Nachrichten pro Minute je Gruppe):
  Kartenbearbeitungen laufen über eine kleine Warteschlange je Chat. Bei 429
  wird `retry_after` abgewartet. Ein Statuswechsel, der sich verspätet, ist
  harmlos.
- Abgelaufene Seite (`valid_until`) oder abgeschaltetes Modul: Der Bot nimmt
  keine Beiträge mehr an und sagt das einmal in der Gruppe.

### 6.1 Umgesetzt (Schritt 3) und was davon abweicht

Draht in `services/telegram.py` (`TelegramApi`), Verarbeitung und Abholen in
`services/aktionsseite_telegram.py`, Org-Admin in
`api/routes/aktionsseite_telegram.py`, Tests in
`tests/test_aktionsseite_telegram.py` gegen eine gestellte Bot-API.

- **Abholen**: `telegram_schleife` im `_lifespan` startet je Bot eine Aufgabe
  (`_bot_laufen`), die per `pg_try_advisory_lock` auf einer eigenen Verbindung
  sicherstellt, dass im Cluster nur eine abholt. Je Durchgang `getMe` und
  `getUpdates` (25 s Long Polling); der Offset wird nach **jedem** Update
  geschrieben. Ein Update, das scheitert, wird geloggt und übersprungen — sonst
  hinge die Gruppe an ihm fest. 401/404 setzt `ungueltig` und beendet die
  Aufgabe, bis ein neuer Token eingetragen ist; 409 `konflikt`; 429 wartet
  `retry_after`. Abschaltbar mit `TELEGRAM_ENABLED=false`, Adresse der Bot-API
  `TELEGRAM_API_URL` (nur für Tests oder einen eigenen Bot-API-Server).
- **Token**: steht in jeder Adresse der Bot-API. `TelegramFehler` trägt deshalb
  nur Telegrams Beschreibung, httpx-Ausnahmen nur ihren Typ — nie die URL.
- **Alben** werden nicht zwei Sekunden gesammelt (§ 3.1), sondern sofort: Das
  erste Bild legt den Beitrag samt Karte an, jedes weitere hängt sich über
  `(chat_id, media_group_id)` an und bearbeitet die Karte. Kein Zeitgeber, und
  ein Neustart mitten im Album verliert nichts.
- **„Text ändern“**: Die Aufforderung merkt sich der Prozess im Speicher (eine
  Stunde), wie Belegungen und Passkey-Challenges. Nach einem Neustart drückt die
  Presse eben noch einmal. Wer inzwischen aus der Presse entfernt wurde, ändert
  auch über eine offene Aufforderung nichts mehr.
- **Nachgetragen** (nach Schritt 7): „Öffentlich seit“ (Schritt 4), `/ab`
  (Schritt 7) und:
  - **Ansage** bei nicht aktiver Seite (abgelaufen, abgeschaltet, Modul
    gesperrt) und bei erreichter Tagesgrenze für Fotos oder Links: als Antwort
    auf die Nachricht, einmal je Grund und 24 Stunden je Gruppe
    (`public_tracker_chats.ansage_grund`/`ansage_at`), nicht auf jedes Bild
    eines Albums. Eine nicht verbundene Gruppe bekommt weiter keine Antwort.
  - **Warteschlange bei 429**: Kann der Bot eine Karte nicht senden oder
    bearbeiten (429, Netzfehler, 5xx), steht der Beitrag mit
    `karte_faellig_ab` (`retry_after`, sonst 30 s) in der Datenbank und
    überlebt so einen Neustart. Jeder Durchgang des Long Pollings holt bis zu
    20 fällige Karten nach, die ältesten zuerst, und hört beim nächsten 429
    auf. Gebaut wird die Karte aus dem Stand **beim Nachholen**. Ein 403 (Bot
    aus der Gruppe geworfen) wird nicht besser und kommt nicht in die
    Warteschlange.
- **Audit**: `org.aktionsseite.telegram_bot_gesetzt`/`_entfernt`,
  `telegram_code`, `telegram_verbunden`, `telegram_getrennt`,
  `presse_eingetragen`/`_entfernt`, `beitrag_freigegeben`/`_abgelehnt`/
  `_zurueckgezogen`, `beitrag_text_geaendert` — aus Telegram ohne `actor_id`,
  mit Telegram-ID und Name in `detail`.

## 7. Datenmodell

```
public_tracker_telegram            (ein Bot je Organisation)
  organization_id (PK)
  bot_token_enc                     Fernet, services/crypto.py
  bot_username
  update_offset                     letzte verarbeitete update_id + 1
  status, last_error, checked_at

public_tracker_chats               (Gruppe bzw. Thema ↔ Konvoi einer Aktionsseite)
  tracker_id, convoy_id   → public_tracker_convoys
  chat_id, thread_id (nullable)     zusammen unique
  chat_title                        nur intern
  created_at

public_tracker_presse              (wer freigeben darf, je Aktionsseite)
  tracker_id, telegram_user_id (PK)
  display_name
  added_at

public_tracker_codes               (Einmal-/Presse-Codes, gehasht)
  code_hash, tracker_id, convoy_id (nullable), art ('verbinden'|'presse')
  expires_at

public_tracker_posts               (ein Beitrag = Nachricht oder Album)
  id                                uuid, intern
  public_id                         zufällig, ≥ 16 Zeichen, geht hinaus
  tracker_id, convoy_id
  quelle                            'telegram' (eine App-Quelle ist verworfen, § 13)
  chat_id, message_id, media_group_id, card_message_id
  taken_at                          message.date
  not_before                        `/ab`, nullable
  status                            'wartet' | 'freigegeben' | 'abgelehnt' | 'zurueckgezogen'
  text_raw                          Bildunterschrift, intern
  text_public                       Text auf der Karte, geht nach Freigabe hinaus
  text_edited_by_presse             bool
  sender_telegram_id, sender_name   intern
  reviewed_by_telegram_id, reviewed_at
  public_since                      fürs „Öffentlich seit" der Karte
  created_at

public_tracker_photos
  id, post_id, position (0–9)
  public_id
  width, height

public_tracker_photo_data          (getrennt, damit Listen nie Bytes laden)
  photo_id (PK), gross bytea, klein bytea
```

`public_id` statt der Datenbank-Kennung: dieselbe Begründung wie bei `key` je
Konvoi.

Migration `0070_aktionsseite_beitraege.py` (0069 ist der Zielpunkt je Konvoi),
Modelle in `models/public_tracker.py`. Gegenüber dem Entwurf oben:

- `public_tracker_chats`, `_codes` und `_posts` hängen per zusammengesetztem
  Fremdschlüssel an `public_tracker_convoys (tracker_id, convoy_id)`, nicht
  einzeln an Seite und Konvoi: Ein Beitrag kann nur zu einem Konvoi gehören,
  der auf der Seite steht.
- Ein Chat je Konvoi einer Seite (`uq_public_tracker_chats_konvoi`), und eine
  Gruppe oder ein Thema nur einmal überhaupt — zwei Teilindizes, weil `NULL`
  in einem `UNIQUE` nicht gleich `NULL` ist.
- Eine Nachricht und ein Album ergeben je einen Beitrag
  (`uq_public_tracker_posts_nachricht`, `_album`).
- Status und Textlänge (500) prüft auch die Datenbank, ebenso, dass ein Code
  `verbinden` einen Konvoi nennt und `presse` keinen.
- `reviewed_by_user_id` neben `reviewed_by_telegram_id`, für Freigaben aus
  ConvoyPlan (§ 8.3).

## 8. Schnittstelle

### 8.1 Erweiterung der Positivliste

`OeffentlicherKonvoi` bekommt `posts: list[OeffentlicherBeitrag]`:

```python
class OeffentlichesBild(_Streng):
    id: str                       # public_id des Bildes
    width: int
    height: int


class OeffentlicherBeitrag(_Streng):
    id: str                       # public_id des Beitrags
    at: datetime                  # taken_at, immer <= as_of
    position: OeffentlicherPunkt | None
    coarse: bool
    text: str | None              # text_public
    photos: list[OeffentlichesBild]
```

Höchstens die letzten 100 je Konvoi, neueste zuerst. `POSITIVLISTE` in
`tests/test_aktionsseite_felder.py` wird um beide Modelle und `posts`
erweitert. Das ist die eine Stelle, an der die Erweiterung bewusst passiert.

Ohne Beiträge ist `posts` eine leere Liste. Der EventTracker übernimmt das Feld
erst, wenn er es kennt (sein `vertrag.ts` verwirft Unbekanntes). Deshalb kann
ConvoyPlan zuerst ausrollen.

„Beitrag" statt „Foto" auch deshalb, weil ein späterer Link-Beitrag (§ 11)
dasselbe Modell mit leerem `photos` und einem `link` wird, statt eines dritten
Modells.

### 8.2 Die Bilder selbst

```
GET /api/public/aktion/{slug}/bild/{public_id}/{gross|klein}.webp
Authorization: Bearer <Abruf-Token>
```

- Dieselbe 404 für alles: unbekannter Slug, falsches Token, unbekanntes Bild,
  Beitrag nicht freigegeben oder **noch nicht sichtbar nach § 4.2**. Die
  Sichtbarkeit wird hier mit derselben Funktion geprüft wie in `nutzlast`.
  Sonst ließe sich ein Bild vor seiner Zeit über die Kennung abholen, sobald
  sie einmal bekannt ist.
- `Cache-Control: private, max-age=86400`. Ein freigegebenes Bild ändert sich
  nicht. Wird es zurückgezogen, fällt es aus der Liste, und der EventTracker
  löscht es.

### 8.3 Org-Admin

```
PUT    /org/aktionsseiten/telegram                       Bot-Token setzen, prüfen (getMe)
DELETE /org/aktionsseiten/telegram
POST   /org/aktionsseiten/{id}/konvois/{convoy_id}/telegram-code
DELETE /org/aktionsseiten/{id}/konvois/{convoy_id}/telegram
POST   /org/aktionsseiten/{id}/presse-code
GET    /org/aktionsseiten/{id}/presse
DELETE /org/aktionsseiten/{id}/presse/{telegram_user_id}
GET    /org/aktionsseiten/{id}/beitraege?status=wartet
GET    /org/aktionsseiten/{id}/bilder/{photo_id}/{gross|klein}.webp
PUT    /org/aktionsseiten/{id}/beitraege/{post_id}       {status, text_public, not_before}
```

Alle hinter `require_modul(AKTIONSSEITEN)` und `_require_admin`. Die
Admin-Ansicht ist Übersicht und Notnagel, gearbeitet wird in Telegram. Eine
Änderung hier bearbeitet die Karte in der Gruppe mit („✅ Freigegeben von
Christoph (ConvoyPlan)"). Die vorhandene `vorschau` zeigt Beiträge genau so,
wie der EventTracker sie bekäme.

### 8.4 Oberfläche im Org-Admin

Alles liegt im vorhandenen Reiter **Aktionsseiten**
(`AktionsseitenVerwaltung.svelte`), nicht in einem eigenen Reiter und nicht in
den allgemeinen Einstellungen. Gruppen und Presse hängen an einer Aktionsseite,
ohne Seite gibt es nichts zu verbinden. Der Reiter sitzt schon am Modul
`aktionsseiten` und ist nur für Org-Admins da. Ein eigenes Modul „Telegram“
wäre eine zweite Freischaltung, die man vergessen kann.

**Karte „Telegram-Bot“, einmal je Organisation, oben im Reiter**

- Bot-Token eintragen. Danach steht er nie wieder im Klartext da, sondern nur
  `@BotName` mit Status. Daneben „Token ersetzen“ und „Bot trennen“.
- Die Prüfung über `getMe` zeigt eine Ampel. Gelb, wenn
  `can_read_all_group_messages` falsch ist: „Der Bot sieht in Gruppen keine
  Fotos“, mit den drei Schritten bei BotFather (`/setprivacy` → Bot →
  *Disable*) oder dem Hinweis, ihn zum Gruppenadmin zu machen. Rot bei
  ungültigem Token oder wenn der Abholer seit mehr als fünf Minuten nicht
  durchkommt (`last_error`, `checked_at`).
- Ohne Bot sind die Abschnitte in den Aktionsseiten zu sehen, aber gesperrt,
  mit Verweis auf diese Karte.

**Abschnitt „Fotos von unterwegs“, in jeder Aktionsseiten-Karte**

Zugeklappt (`use:klappbar`) steht nur der Zähler im Kopf: „3 warten · 12 in
der Warteschlange · 41 öffentlich“. Wartende Beiträge machen den Zähler
auffällig, damit der Notnagel nicht übersehen wird. Aufgeklappt gibt es drei
Bereiche:

| Bereich | Inhalt |
|---|---|
| **Gruppen** | Eine Zeile je Konvoi der Seite. Nicht verbunden: [Code erzeugen]. Der Code steht 15 Minuten mit Kopierknopf und Ablaufzeit da, mit dem Satz, wohin er gehört („in die Gruppe oder das Thema des Konvois schreiben“). Verbunden: „*Konvoi Bosnien* → Thema *Bosnien* in *Weihnachtskonvoi 2026*“ und [trennen]. Trennen nimmt nur keine neuen Beiträge mehr an; vorhandene bleiben (§ 9). |
| **Presse** | Liste mit Telegram-Anzeigename, `@benutzername` falls vorhanden und Datum, je Eintrag [entfernen]. Dazu [Presse-Code erzeugen], 24 h gültig und mehrfach verwendbar, mit dem Satz „dem Bot **privat** schicken: `/presse 4TR-8LK`“. Entfernen wirkt sofort: Ein Knopfdruck danach bekommt den Alert „nur Presse“. |
| **Beiträge** | Liste, neueste zuerst, gefiltert nach Status. Je Beitrag Vorschaubild (bei Alben das erste mit Zahl), Konvoi, Zeit, öffentlicher Text und Status samt „erscheint frühestens …“ bzw. „öffentlich seit …“. Dieselben Aktionen wie die Knöpfe in Telegram: freigeben, Text ändern, ablehnen, zurückziehen, später terminieren. |

Was hier passiert, steht wie jede Aktion aus Telegram im Audit-Log, und die
Bot-Karte in der Gruppe zieht mit (§ 8.3).

**Wer was darf**

| Rolle | Wo | Darf |
|---|---|---|
| **Org-Admin** | ConvoyPlan | Bot einrichten, Gruppen verbinden und trennen, Presse eintragen und entfernen, Beiträge moderieren |
| **Presse** | Telegram | Beiträge der Aktionsseite freigeben, Text ändern, ablehnen, zurückziehen, mit `/ab` terminieren |
| **Fahrer, Begleiter** | Telegram | Fotos mit Text posten, sonst nichts. Wer in der Gruppe ist, darf posten. |
| **Planer** | ConvoyPlan | nichts, wie heute bei Aktionsseiten |

Zwei Entscheidungen dazu, festgehalten am 2026-10-14:

- **Planer moderieren nicht.** Auch der Bereich „Beiträge“ bekommt keine
  Ausnahme vom `_require_admin` der Aktionsseiten. Die Pressestelle arbeitet
  in Telegram. Wer sie zusätzlich in ConvoyPlan moderieren lassen will, macht
  sie zum Org-Admin.
- **Freigeben in Telegram braucht immer einen Presse-Eintrag**, auch für
  Org-Admins. Konten von ConvoyPlan und Telegram werden nicht verknüpft. Das
  spart einen Kopplungsschritt, und in Telegram gilt genau eine Regel:
  freigeben darf, wer auf der Presseliste steht.

**Zusagen, die ein E2E-Test festhält** (`frontend/e2e/aktionsseite-fotos.spec.ts`):

- Der Bot-Token steht nach dem Speichern nirgends mehr auf der Seite, auch
  nicht im DOM eines versteckten Felds.
- Ein Code steht nur bis zu seinem Ablauf da und verschwindet danach ohne
  Neuladen.
- Ein Planer sieht den Reiter nicht (wie heute) und bekommt auch über die
  Beitrags-API eine 403.
- Die Aktionen in der Beitragsliste schicken dieselben Aufrufe wie in § 8.3,
  geprüft am Körper der abgefangenen Anfrage. Dasselbe Muster wie
  `kontextmenue-planung-und-admin.spec.ts`.

### 8.5 Umgesetzt (Schritt 4)

- `nutzlast` hängt je Konvoi `posts` an: freigegebene Beiträge bis zur
  Stichzeit, gefiltert mit `beitrag_sichtbar`, platziert mit
  `beitrag_position`, beide mit **einer** `lage()` je Konvoi. Höchstens 100,
  neueste zuerst. Ein Beitrag ohne Bild geht nicht hinaus.
- Der Bildendpunkt prüft an **genau** der Antwort, die `abrufen` liefert
  (gemeinsamer Zwischenspeicher, `_oeffentlich`). Steht das Bild dort nicht,
  ist es dieselbe 404 wie für einen unbekannten Slug.
- „Öffentlich seit": `oeffentlich_markieren` läuft in der Telegram-Schleife
  alle 30 s, entscheidet ebenfalls mit `nutzlast` und bearbeitet die Karte.
  Es läuft auch mit `TELEGRAM_ENABLED=false` (nur ohne Karte).
- Freigeben und Zurückziehen — in Telegram wie im Org-Admin — leeren den
  Zwischenspeicher der Seite: Zurückgezogen ist sofort weg, nicht erst nach
  einer Minute.
- Org-Admin: `GET …/beitraege`, `GET …/bilder/{id}/{groesse}.webp` (auch
  wartende), `PUT …/beitraege/{id}` mit `aktion` und/oder `text_public`.
  Prüfer aus ConvoyPlan erscheinen auf der Karte mit Vornamen und
  „(ConvoyPlan)", nie mit Adresse. `not_before` (`/ab`) bleibt für Schritt 7.
- Export: Die Tabellen bleiben vorerst draußen (§ 9). Beiträge ohne Absender
  in den Export aufzunehmen ist möglich, wenn eine Organisation danach fragt.

## 9. Löschen

- `retention.py` (`purge_old_beitraege`) löscht Beiträge, deren Zeitpunkt
  älter ist als der Positionsverlauf (`RETENTION_POSITION_TRAIL_DAYS`, 45
  Tage): Ohne Verlauf wüsste niemand mehr, wo sie hingehören. Bilder und ihre
  Bytes fallen per Fremdschlüssel mit.
- Abgelehnte und zurückgezogene Beiträge nach 7 Tagen, nie bearbeitete nach
  30 Tagen. Abgelaufene Codes beim nächsten Lauf (`purge_expired_beitrag_codes`).
- Löschen der Aktionsseite → alles. Fällt ein Konvoi aus der Seite, fallen
  seine Gruppe, seine Codes und seine Beiträge mit; die Presse gehört der Seite
  und bleibt. **Bearbeiten** der Seite löscht nichts: `_konvois_setzen` ändert
  bleibende Konvoi-Zeilen, statt sie zu ersetzen (vorher wurden sie bei jedem
  Speichern neu angelegt, mit Beiträgen daran hätte schon ein neuer Titel sie
  gelöscht).
- **Trennen** einer Gruppe nimmt nur keine neuen Beiträge mehr an; vorhandene
  bleiben, freigegebene auch öffentlich. Wer sie loswerden will, zieht sie
  zurück.
- Im Organisations-Export (entschieden am 15. Oktober) stehen Beiträge und
  Bildzeilen (`beitraege`, `beitrag_bilder`), ohne Absender und ohne
  Telegram-Kennungen; die Bilder liegen als WebP unter `beitraege/` im ZIP. Bot,
  Codes, Presse und Gruppen bleiben draußen.
- In der Gruppe gelöschte Nachrichten bekommt ein Bot nicht mit. Das steht in
  der Einrichtungsanleitung und im Bot-Satz beim Verbinden: Zurückziehen geht
  über den Knopf, nicht übers Löschen in Telegram.

## 10. Polaroid-Ansicht (EventTracker)

Der Look gehört dem EventTracker, ConvoyPlan liefert nur Daten. Hier steht er,
damit das Format der Bilder (§ 5) dazu passt.

Ein klickbares Mockup gibt es (Stand 14. Oktober, privat, bei Bedarf über
„Teilen" freigeben): https://claude.ai/artifact/Km2CpiWjAkWyDQLuwgrfvG. Es
zeigt den festlichen Look „Winternacht" mit Beispielbildern und einer
schematischen Karte statt OSM-Kacheln. Was dort zu sehen ist, beschreibt
dieser Abschnitt. Wo das Mockup und dieser Text auseinandergehen, gilt der
Text.

- **Rahmen:** weiß (`#fbfaf6`, nicht reinweiß), Bild quadratisch
  (`aspect-ratio: 1; object-fit: cover`), Rand ringsum ~6 %, unten ~22 % für
  Text. Schatten weich und leicht versetzt. Bleibt auch im Dunkelmodus hell,
  genau das macht ein Polaroid aus.
- **Schräglage:** −4° bis +4°, **aus der `id` abgeleitet**, nicht zufällig. So
  liegt ein Bild nach jedem Abruf gleich und springt nicht.
- **Text unten:** handschriftlich wirkende Schrift, **selbst ausgeliefert**
  (z. B. *Caveat* oder *Kalam*, OFL, Lizenz daneben wie bei `schriften/`). Die
  CSP erlaubt nichts von Google Fonts, und genau so soll es bleiben. Darunter
  klein und in normaler Schrift: „Konvoi Bosnien · 12:40 Uhr".
- **Auf der Karte:** kleine Polaroids (~60–70 px) als Marker an `position`,
  mit einem Stiel in der Konvoifarbe zum Punkt. Beim Überfahren oder
  Fokussieren richtet sich das Polaroid gerade und wird etwas größer.
- **Grobe Beiträge (`coarse`):** Der Punkt liegt in einer gestrichelten,
  halbtransparenten Fläche, wie der stehende Konvoi selbst. Der Stiel ist
  länger, sodass das Polaroid über der Fläche hängt und nicht auf einen Punkt
  zeigt. Ein Beitrag mit `position: null` erscheint nur in der Leiste.
- **Häufungen:** Liegen Beiträge auf dem Bildschirm dichter als etwa ein
  Polaroid nebeneinander, werden sie zu einem **Stapel** aus bis zu drei
  versetzten Polaroids mit Zahl. Typischer Fall ist der gemeinsame
  Abfahrtsort mehrerer Konvois. Ein Klick öffnet die Lightbox mit allen
  Beiträgen des Stapels. Gerechnet wird je Zoomstufe neu, nicht auf festen
  Koordinaten.
- **Album:** als leicht gefächerter Stapel mit Zahl der Bilder.
- **Leiste je Konvoi:** in der Konvoiliste unter Name, Status und Kilometern,
  waagerecht durchscrollbar, neueste zuerst, mit derselben Schräglage. Ohne
  Beiträge steht dort ein Satz statt einer leeren Fläche: „Noch keine Fotos.
  Sie erscheinen hier, sobald die Presse sie freigegeben hat."
- **Lightbox:** großes Polaroid mit dem ganzen, ungeschnittenen Bild (4:3,
  `object-fit: contain`), Text in Handschrift und darunter „Konvoi Rumänien ·
  Foto von 15:40 Uhr · Seite zeigt den Stand von 17:00 Uhr". Das erklärt
  nebenbei die Verzögerung. Bei groben Beiträgen kommt „Ort vergröbert, der
  Konvoi stand" dazu. Geblättert wird mit Knöpfen und Pfeiltasten durch alle
  Bilder aller Beiträge, aus denen die Lightbox geöffnet wurde: aus der Leiste
  durch den Konvoi, aus einem Stapel durch den Stapel. Punkte zeigen die
  Stelle.
- **Bewegung:** Hineinflattern neuer Polaroids nur ohne
  `prefers-reduced-motion`, sonst erscheinen sie einfach. Das gleiche
  Versprechen wie „kein Schnee bei reduzierter Bewegung", mit eigenem E2E-Test.
- **Neuer Beitrag:** fliegt einmal von oben ein und legt sich in seine
  Schräglage. Ist die Konvoiliste auf dem Handy eingeklappt, steht im Balken
  „neu · 10 Fotos" in der Akzentfarbe, und die Farbpunkte pulsieren zweimal.
- **Thema `weihnachten`:** ein Streifen rot gestreiftes Washi-Tape oben an den
  Polaroids in Leiste und Lightbox, zusätzlich zum Schatten. Auf der Karte kein
  Tape, dort wäre es bei 60 px nur ein roter Fleck. Mehr Dekoration nicht, sonst
  wird es kitschig. Im Thema `neutral` fällt das Tape weg.
- **Barrierefreiheit:** `alt` = Text des Beitrags, sonst „Foto von Konvoi
  Bosnien, 12:40 Uhr". Marker sind fokussierbar und öffnen mit Enter oder
  Leertaste. Lightbox per Tastatur bedienbar, Escape schließt.

### 10.1 Auf dem Handy

Bis 640 px Breite liegen Kopftafel und Konvoiliste über der Karte und
verdecken sonst den größten Teil davon. Zwei Regeln halten sie klein:

- **Konvoiliste einklappbar, eingeklappt beim Öffnen.** Übrig bleibt ein
  Balken am unteren Rand mit den Farbpunkten der Konvois, „Konvois und Fotos",
  der Zahl der Fotos und einem Pfeil. Ausgeklappt nimmt die Liste höchstens
  55 % der Höhe ein, der Balken bleibt beim Scrollen oben in der Liste stehen
  und klappt sie wieder zu (`aria-expanded`, `aria-controls`).
- **Kopftafel wird kompakt, sobald jemand die Karte bewegt oder die Liste
  scrollt.** Untertitel und Kennzahlen gleiten weg, Titel und **Stand-Zeile
  bleiben immer**. Die Stand-Zeile ist die Zusage, offen zu sagen, wie
  verzögert die Seite ist, und darf nie verschwinden. Neben dem Titel erscheint
  „mehr ▾" und holt den Rest zurück. Ausgelöst wird über MapLibres
  `movestart` (nur bei Bewegung durch den Nutzer, nicht beim ersten
  `fitBounds`) und das `scroll`-Ereignis der Liste. Bei reduzierter Bewegung
  ohne Gleiten.
- Breiter als 640 px klappt nichts davon ein, die Liste bleibt offen und der
  Balken ist ausgeblendet. Wird das Fenster breiter, geht die Kopftafel wieder
  ganz auf.

## 11. Instagram: nur als Link

Einbetten (`embed.js`) lädt Skripte und Tracking von Meta in die Seite und
verstößt gegen die CSP des EventTrackers („nichts von außen"). Abholen und
selbst ausliefern geht über die API für fremde Accounts praktisch nicht und
wäre urheberrechtlich heikel.

Was geht: Die Presse schickt einen Instagram-Link in die Gruppe, als Antwort
auf einen Beitrag oder für sich, und der wird ein Beitrag mit `link` und ohne
Bilder, mit derselben Freigabe und denselben Regeln (§ 4). Der EventTracker
zeigt ihn als schlichtes Polaroid mit Instagram-Symbol aus eigenen Dateien
(ohne Vorschaubild von Meta) und einem Link, der erst beim Klick nach außen
führt. „Auf der Route hinterlegen" ginge nur mit sichtbaren Wegpunkten, und die
sind aus gutem Grund standardmäßig aus (Plan vom 2. Oktober, § 3). Ein Beitrag
hängt am Zeitpunkt, nicht an einem Wegpunkt.

### 11.1 Umgesetzt (Schritt 6)

- **Dienste:** Instagram, YouTube (`youtu.be`), Facebook (`fb.watch`), TikTok —
  eine feste Liste in `services/aktionsseite_link.py` und im CHECK der Tabelle.
  Ein beliebiger Link auf einer öffentlichen Seite wäre ein Weg, Zuschauer
  irgendwohin zu schicken, auch an einer Presse vorbei, die nur überfliegt.
- **Bereinigt:** https, ohne Anmeldedaten, Port, Fragment und Abfrage (`igsh`,
  `si`, `utm_*` verraten, wer geteilt hat); YouTube behält `v` und `t`. Die
  Karte zeigt die Adresse so, wie sie hinausgeht.
- **Wer:** jede Person in der Gruppe, nicht nur die Presse — freigeben muss sie
  ohnehin. Nur Textnachrichten; ein Link in einer Bildunterschrift bleibt Text.
- **Wann:** als Antwort auf einen Beitrag (das Foto oder die Karte des Bots)
  dessen `taken_at`, sonst die Zeit der Nachricht. Damit gelten Verzögerung,
  Halte und Platzierung unverändert.
- **Fest nach dem Anlegen:** Eine Bearbeitung in Telegram ändert nur den Text,
  nie die Adresse — auch vor der Freigabe, damit niemand eine geprüfte Adresse
  austauscht, während die Presse schon hinsieht.
- Höchstens `LINKS_JE_TAG` (100) je Gruppe und Tag.
- Öffentlich: `link: {url, dienst}` am Beitrag, `photos` leer. Datenmodell:
  `link_url`/`link_dienst` in `0070` (noch nicht ausgerollt, deshalb keine
  eigene Migration).

### 11.2 Vorschaubilder (entschieden am 15. Oktober)

§ 11 hatte das Abholen verworfen. Für das **Vorschaubild** — nicht den Inhalt —
gilt das nicht mehr: Ein Polaroid mit Bild trägt auf der Karte mehr als eines
mit Symbol. Geändert hat sich nur, woher das Bild kommt; der Weg in den
Browser bleibt derselbe.

- **Wann und wie oft:** einmal, beim Eingang des Links in der Gruppe — vor der
  Karte, damit die Presse sieht, ob ein Bild mit hinausgeht („🖼 mit
  Vorschaubild des Dienstes"). Der Dienst sieht einen Abruf je Link, keinen je
  Zuschauer; der EventTracker lädt weiter nichts von außen.
- **Welche Dienste:** YouTube (`i.ytimg.com/vi/<kennung>/maxresdefault.jpg`,
  sonst `hqdefault.jpg`, ohne API) und TikTok (`thumbnail_url` aus dem
  öffentlichen oEmbed). Instagram und Facebook nicht: Meta hat `thumbnail_url`
  zum 3. November 2025 aus seinem oEmbed genommen und empfiehlt, die Seite
  selbst auszulesen — hinter einer Anmeldesperre, also scrapen. Dort bleibt es
  beim Symbol.
- **Sicher abholen:** nur feste Hosts je Dienst, https, kein Port, keine
  Weiterleitung, Größe begrenzt (5 MB), kurze Zeitgrenzen. Die Bildadresse aus
  oEmbed bestimmt TikTok, nicht wir.
- **Verarbeitet wie ein Foto** (§ 5): neu kodiert, ohne Metadaten, als
  einziges Bild des Link-Beitrags gespeichert; es zählt bei `LINKS_JE_TAG`,
  nicht bei `BILDER_JE_TAG`.
- **Öffentlich:** `link: {url, dienst, vorschau: {id, width, height} | null}`,
  `photos` bleibt leer. Das Bild gehört zum Link: Verwirft der EventTracker den
  Link, verschwindet es mit, statt als fremdes Foto „von unterwegs" stehen zu
  bleiben. Ausgeliefert über denselben Bildendpunkt (§ 8.2).
- **Urheberrecht:** Das Vorschaubild ist ein fremdes Bild, aber genau das, was
  der Dienst selbst zum Teilen des Links anbietet, und es führt dorthin. Es
  geht nur nach Freigabe durch die Presse hinaus, wie jeder Beitrag.
- **Aus:** `LINK_VORSCHAU_ENABLED=false` für Instanzen ohne Ausgang oder wer es
  nicht will; Links bleiben dann wie in § 11.1.

## 12. Tests

Reine Funktionen (ohne Datenbank):

- `beitrag_position`: interpoliert zwischen zwei Punkten. Steht der Konvoi zum
  Zeitpunkt, wird vergröbert. Ohne Punkt in ±15 min gibt es keine Position.
- `beitrag_sichtbar`: nicht vor der Stichzeit, nicht vor `not_before`, nicht
  solange der Konvoi zur Stichzeit im Umkreis steht, sichtbar, sobald er
  fährt. Der Autohof-Fall aus § 1 als eigener, benannter Test, er ist der
  wichtigste dieses Plans.
- Bildverarbeitung: GPS-EXIF hinein, keines heraus. Dekompressionsbombe wird
  abgelehnt. Die Orientierung bleibt richtig.
- Album-Sammler: drei Updates mit derselben `media_group_id`, Unterschrift am
  zweiten, ergeben einen Beitrag mit drei Bildern und dem Text.

Gegen eine gestellte Bot-API (`httpx.MockTransport`):

- Verbinden per Code, in Gruppe und in Thema. Unbekannter Chat und unbekanntes
  Thema werden verworfen, weitergeleitete Nachrichten auch.
- Knopf von jemandem ohne Presse-Eintrag ändert nichts und gibt einen Alert.
  Knopf eines Presse-Eintrags **einer anderen Aktionsseite** ändert auch
  nichts.
- Text ändern: Nur die Antwort der Person, die gedrückt hat, zählt.
- `edited_message` vor der Freigabe ersetzt den Vorschlag, nach der Freigabe
  nicht. Der Fall heißt im Test so, wie er gemeint ist: „Fahrer tauscht
  freigegebenen Text aus".
- Offset wird fortgeschrieben. 409 und 429 führen zum Abwarten statt zur
  Endlosschleife.

Mit Datenbank (`aktionsseite_fixtures.py` erweitern):

- Positivliste: `OeffentlicherBeitrag` und `OeffentlichesBild` mit
  `extra="forbid"`. `text_raw`, `sender_*`, `reviewed_by_*` und interne
  Kennungen stehen nie in der Antwort (wie `GEHEIMER_KONVOINAME`).
- Bildendpunkt: 404 für wartend, abgelehnt, zurückgezogen, noch nicht sichtbar,
  falsches Token und fremden Slug. 200 erst ab Sichtbarkeit.
- Retention: Beiträge fallen mit dem Verlauf.

## 13. Reihenfolge

| # | Schritt | Wo |
|---|---|---|
| 1 | Regeln (`beitrag_position`, `beitrag_sichtbar`) + Tests (umgesetzt) | ConvoyPlan |
| 2 | Modell, Migration, Bildverarbeitung, Retention (umgesetzt) | ConvoyPlan |
| 3 | Telegram-Abholer: Verbinden, Presse-Codes, Beiträge, Alben, Karte mit Knöpfen, Text ändern; Bot-Karte, Gruppen und Presse im Org-Admin (§ 8.4) (umgesetzt, § 6.1) | ConvoyPlan |
| 4 | `posts` in der Positivliste, Bildendpunkt, Sichtbarkeitsschleife („Öffentlich seit"), Beitragsliste im Org-Admin (§ 8.4) (umgesetzt, § 8.5) | ConvoyPlan |
| 5 | Vertrag, Abholen der Bilder, Polaroid-Ansicht (s. u.) (umgesetzt, Convoyplan-EventTracker#23) | EventTracker |
| 6 | Link-Beiträge (Instagram & Co.) (umgesetzt, § 11.1) | beide |
| 7 | `/ab` zum späteren Terminieren (umgesetzt, § 3.5); Companion-App als Quelle **verworfen** (s. u.) | ConvoyPlan |

Schritte 1–4, der ConvoyPlan-Teil von 6 und `/ab` gehen als ein Release hinaus.
`posts` bleibt leer, bis jemand einen Bot einrichtet, und ein EventTracker
älterer Fassung verwirft das Feld.

**Keine Beiträge aus der Begleit-App** (entschieden am 14. Oktober). Die App
ist das Werkzeug für den Einsatz, die Aktionsseite gibt es nur zu einzelnen
Veranstaltungen. Beides bleibt getrennt: Fotos kommen ausschließlich aus den
Telegram-Gruppen. `quelle` bleibt als Spalte stehen, sie kostet nichts und
hält die Herkunft fest.

### Was im EventTracker dazukommt (Schritt 5)

- `src/lib/vertrag.ts`: `posts` prüfen und übernehmen.
  `testdaten/aktion.json` bekommt Beiträge (gegen `OeffentlicheAktion`
  geprüft).
- `src/lib/server/abholer.ts`: Bilder neuer `id`s mit dem Abruf-Token holen,
  unter `DATA_DIR/bilder/` ablegen, nicht mehr gelistete löschen. Bei einer 404
  der Seite verschwinden alle Bilder. Größenlimit beim Abholen.
- Ausgeliefert unter `/<pfad>/bilder/{id}-{gross|klein}.webp`, eigene
  Herkunft, die CSP bleibt unverändert.
- Polaroid-Ansicht nach § 10, Schrift unter `schriften/`.
- E2E: Bilder und Schrift kommen nur von der eigenen Herkunft. Weder Slug noch
  Token stehen in einer Bild-URL. Kein Hineinflattern bei reduzierter
  Bewegung. Auf Handybreite: Liste beim Öffnen eingeklappt, und nach einem
  Verschieben der Karte ist der Untertitel weg, die Stand-Zeile aber sichtbar.
- Das Vorschaubild (`vorschaubild.ts`) bleibt ohne Fotos: Es soll schnell und
  ohne Abhängigkeit bleiben.

## 14. Offene Fragen an die Organisation

1. **Themen oder Gruppen?** Der Plan kann beides. Empfohlen ist eine
   Supergruppe mit einem Thema je Konvoi (§ 2.1).
2. **Wer ist Presse, und wie viele?** Zwei bis drei Leute mit Netz, auch
   nachts. Ein Beitrag, der sechs Stunden auf Freigabe wartet, erscheint eben
   sechs Stunden später, das ist kein Fehler, sollte aber allen klar sein.
3. **Einwilligung der Abgebildeten:** Der Bot-Satz beim Verbinden reicht als
   Hinweis für die Fahrer in der Gruppe. Für Dritte auf den Fotos (Grenzbeamte,
   Empfänger, Kinder bei der Übergabe) reicht er nicht. Das entscheidet die
   Presse beim Freigeben, und sie sollte eine kurze Linie dafür haben.
4. **Absendernamen in der Gruppe:** „von Jonas" auf der Karte des Bots hilft
   der Presse beim Nachfragen. Wer das nicht will, bekommt eine Einstellung,
   die es weglässt. (Umgesetzt: Haken *Absender auf den Beiträgen nennen* je
   Seite, `show_sender`, Migration `0071`; aus löscht auch vorhandene Namen.)

## 15. Videos (entschieden am 15. Oktober)

Videos aus der Gruppe werden Beiträge wie Fotos — gleiche Freigabe, gleiche
Regeln (§ 4). Drei Entscheidungen der Organisation:

- **Ton bleibt**, abgespielt wird stumm, bis jemand ihn einschaltet. Ton
  verrät mehr als das Bild (Durchsagen, Gespräche, Ortsnamen); die Karte des
  Bots sagt deshalb „🔊 mit Ton — vor dem Freigeben anhören", und im Org-Admin
  öffnet das Standbild das Video.
- **60 Sekunden, 720p.** Längeres lehnt der Bot ab (Telegram nennt die Länge
  vorab, ohne Abruf), statt still zu kürzen. Rund 1,5 Mbit/s, also höchstens
  um 12 MB je Video — das trägt der EventTracker je Zuschauer, der abspielt.
- **Dateien im Volume**, nicht in der Datenbank: `/uploads/aktionsseite/videos/`
  auf dem vorhandenen Upload-Volume (im Backup als `uploads.tar.gz`). Das
  Standbild bleibt als `PublicTrackerPhoto` in der Datenbank.

**Neu kodieren in einem eigenen Container** (`docker/medien`, Dienst `medien`).
Umverpacken hieße, jeder Box im MP4 zu trauen, die wir nicht kennen; neu
schreiben lässt sie gar nicht erst entstehen. ffmpeg mit x264 steht unter der
GPL, ConvoyPlan gibt es auch kommerziell — als Bibliothek im Backend (PyAV)
wäre das gelinkt. Der Container ist ein eigenes Programm im Compose-Netz,
angesprochen über HTTP, ohne Volume und ohne Port nach außen. ffmpeg ist
selbst gebaut, nur mit dem, was Handyvideos brauchen (Debians Paket zieht SDL,
PulseAudio und X11 nach). Der Test (`docker/medien/tests/test_medien.sh`)
läuft gegen echte Proben mit GPS-Box, Apple-Ortsangabe, Drehung und Überlänge.

**Öffentlich:** `video: {id, width, height, seconds, sound, poster}` am
Beitrag, `photos` leer — wie die Link-Vorschau steht das Standbild am Video.
Das Video gibt `/api/public/aktion/{slug}/video/{id}.mp4` heraus, nur solange
es in der Antwort steht; das Standbild der Bildendpunkt.

**Löschen:** Die Retention läuft in einem Container ohne Upload-Volume, und
eine Zeile fällt auf vielen Wegen (Konvoi aus der Seite, Seite gelöscht,
Retention). Deshalb räumt `aufraeumen` in der Telegram-Schleife stündlich jede
Datei ohne Zeile weg, die älter als 30 Minuten ist; geschrieben wird die Datei
vor dem Commit.

**Export:** Videos unter `beitraege/videos/` im ZIP. Das ZIP entsteht deshalb
in einer temporären Datei und wird gestreamt; im Speicher wären es schnell
über ein Gigabyte.

**EventTracker:** holt das Video einmal mit dem Abruf-Token, legt es unter
`DATA_DIR` ab und liefert es mit Teilabrufen (Range, sonst spielt Safari
nicht) aus; CSP `media-src 'self'`; kein Autoplay, `preload="none"`, stumm.
