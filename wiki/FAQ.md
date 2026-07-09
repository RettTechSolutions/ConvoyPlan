# Häufige Fragen (FAQ)

## Allgemein

**Muss ich etwas installieren?**
Nein. ConvoyPlan läuft vollständig im Browser. Eine Installation auf Endgeräten ist nicht erforderlich. ConvoyPlan kann optional als Progressive Web App (PWA) auf dem Homescreen des Smartphones installiert werden.

---

**Funktioniert ConvoyPlan offline?**
Kartenkacheln können für eine begrenzte Offline-Nutzung zwischengespeichert werden. Die Routen-Berechnung, Live-Tracking und Synchronisation erfordern jedoch eine aktive Internetverbindung.

---

**Auf welchen Geräten funktioniert ConvoyPlan?**
ConvoyPlan ist für Desktop-Browser (Chrome, Firefox, Edge, Safari) sowie mobile Browser optimiert. Für das GPS-Tracking empfiehlt sich ein Smartphone mit aktiviertem Standortdienst.

---

## Registrierung & Zugang

**Ich kann mich nicht einloggen – was tun?**
1. Stelle sicher, dass E-Mail-Adresse und Passwort korrekt eingegeben sind (Groß-/Kleinschreibung beachten)
2. Frage deinen Organisations-Admin, ob dein Konto bereits **aktiviert** wurde
3. Nutze ggf. die „Passwort vergessen"-Funktion

---

**Ich habe keine Einladung erhalten – wie bekomme ich Zugang?**
Bitte deinen Organisations-Administrator, dich über die Mitgliederverwaltung einzuladen. Du benötigst dazu die bei der Registrierung verwendete E-Mail-Adresse.

---

## Routenplanung

**Die Route wird nicht berechnet – woran liegt das?**
- Stelle sicher, dass Start- und Endpunkt gesetzt sind
- Prüfe die Internetverbindung
- Bei anhaltenden Problemen: Wende dich an den Administrator der Instanz (Routing-Dienst könnte nicht erreichbar sein)

---

**Kann ich eine vorhandene GPX-Route importieren?**
Ja. Klicke im Konvoi auf **Importieren** → **GPX-Datei auswählen**. Du kannst wählen, ob die importierten Punkte bestehende Wegpunkte ersetzen oder ergänzen sollen.

---

**Wie kann ich Wegpunkte umsortieren?**
Wegpunkte in der Liste können per **Drag & Drop** umsortiert werden. Die Route wird nach dem Verschieben automatisch neu berechnet.

---

## Fahrzeuge & Tracking

**Das GPS-Tracking funktioniert nicht – was tun?**
1. Stelle sicher, dass die Standortfreigabe im Browser aktiviert ist (Browsereinstellungen → Datenschutz → Standort)
2. HTTPS-Verbindung ist Voraussetzung für GPS-Zugriff
3. Im manuellen Modus kann die Position auch durch Tippen auf die Karte übermittelt werden

---

**Kann ich ein Fahrzeug mehreren Konvois zuweisen?**
Ja. Ein Fahrzeug kann in verschiedenen Konvois eingesetzt werden. Jede Zuweisung ist unabhängig und kann unterschiedliche Sonderfunktionen und Positionen haben.

---

**Warum sehe ich die Positionen anderer Fahrzeuge nicht?**
- Du benötigst mindestens die Rolle `beobachter` in der Organisation
- Stelle sicher, dass die Fahrer ihr Tracking aktiv gestartet haben
- Die WebSocket-Verbindung muss aufgebaut sein (Browser-Reload kann helfen)

---

## Marschbefehl & Export

**Im PDF fehlen Kanalwechsel-Angaben – warum?**
Kanalwechsel werden nur generiert, wenn der Administrator **Leitstellen** mit Gebietsgrenzen konfiguriert hat und die Route diese Grenzen kreuzt. Wende dich an deinen Systemadministrator.

---

**Kann ich den Marschbefehl nachträglich bearbeiten?**
Ja. Alle Felder des Marschbefehls (Lage, Auftrag, Marschform usw.) können jederzeit im Konvoi unter dem Tab **Marschbefehl** bearbeitet werden. Ein neues PDF wird beim nächsten Export automatisch mit den aktuellen Daten erstellt.

---

## Berechtigungen

**Ich kann einen Konvoi nicht bearbeiten – warum?**
Zum Bearbeiten von Konvois benötigst du die Rolle **Planer** oder **Admin** in der jeweiligen Organisation. Bitte deinen Organisations-Admin, deine Rolle anzupassen.

---

**Kann ich Inhalte anderer Organisationen sehen?**
Nein. Konvois und Fahrzeuge sind strikt auf die eigene Organisation beschränkt. Mitglieder können nur Inhalte ihrer eigenen Organisation einsehen und bearbeiten.

---

## Weiterer Support

Wurde deine Frage hier nicht beantwortet? Erstelle ein [Issue im Repository](https://github.com/RettTechSolutions/ConvoyPlan/issues) oder wende dich an deinen Organisationsadministrator.
