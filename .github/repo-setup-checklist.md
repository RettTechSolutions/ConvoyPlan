# Repo-Härtung & Auto-Merge — Einrichtungs-Checkliste

Dieses Repo enthält die **automatisierbaren** Bausteine für Branch-Schutz und
Auto-Merge als Code:

- `.github/workflows/auto-merge.yml` — aktiviert Auto-Merge (Squash) für PRs mit Label `auto-merge`.
- `.github/rulesets/main.json` — importierbares Ruleset zum Schutz von `main`.

Ein paar Schritte lassen sich **nur in den Repo-Settings** (UI) erledigen und
müssen einmalig von einem Repo-Admin ausgeführt werden. Reihenfolge einhalten.

## 1. Ruleset importieren (schützt `main`)

1. **Settings → Rules → Rulesets → New ruleset → Import a ruleset**
2. Datei `.github/rulesets/main.json` aus diesem Repo hochladen.
3. Speichern. Das Ruleset erzwingt auf dem Default-Branch (`main`):
   - **Pull Request Pflicht** — keine direkten Pushes auf `main`.
   - **Required Status Checks** (müssen grün sein, bevor gemergt werden kann):
     - `Backend – Lint & Tests`
     - `Frontend – Type Check`
     - `Docker – Build check`
     - `Security – Dependency Audit`
   - **Strict** — Branch muss vor dem Merge auf dem aktuellen Stand von `main` sein.
   - **Nur Squash-Merge** erlaubt.
   - **Conversation Resolution** Pflicht (alle Review-Threads aufgelöst).
   - **Kein Force-Push**, **kein Löschen** von `main`.
   - **0 Approvals** nötig — passend für Solo-/Kleinteam-Betrieb; Schutz kommt
     über die grünen Checks. Wenn das Team wächst: `required_approving_review_count`
     im Ruleset auf `1` (oder höher) anheben.

> **Notfall-Bypass:** `bypass_actors` ist absichtlich leer (maximale Sicherheit).
> Wer sich für Notfälle einen Direkt-Push offenhalten will, fügt im Ruleset unter
> **Bypass list** die Rolle *Repository admin* (Bypass: *Always*) hinzu.

## 2. "Allow auto-merge" aktivieren

**Settings → General → Pull Requests** → Häkchen bei **Allow auto-merge**.

Ohne diese Einstellung schlägt der Auto-Merge-Workflow fehl (GitHub erlaubt das
Aktivieren von Auto-Merge nur, wenn die Repo-Option gesetzt ist).

Empfohlen, gleich mit anhaken:
- **Allow squash merging** (an) — die anderen Merge-Methoden können deaktiviert
  werden, das Ruleset erzwingt ohnehin Squash.
- **Automatically delete head branches** (an) — räumt gemergte Branches auf.

## 3. Label `auto-merge` anlegen

**Issues/PRs → Labels → New label**, Name exakt: `auto-merge`.

## Nutzung im Alltag

1. Branch erstellen, Änderungen pushen, **Pull Request** öffnen.
2. PR das Label **`auto-merge`** geben.
3. Fertig. Sobald alle vier Checks grün sind, mergt GitHub den PR automatisch
   per Squash und löscht den Branch. Schlägt ein Check fehl, bleibt der PR offen.

**Dependabot-PRs** bekommen das Label `auto-merge` **automatisch** vom Workflow
und werden nach grünen Checks ohne weiteres Zutun gemergt. Voraussetzung: Das
Label `auto-merge` (Schritt 3) existiert.

## Warum nicht alles per API automatisiert?

Branch-Protection/Rulesets und Repo-Settings (`Allow auto-merge`, Labels) sind
Administrations-Einstellungen, die ein Token mit `administration: write` bzw.
einen Admin-Klick erfordern. Sie sind hier als Code/Checkliste hinterlegt, damit
sie versioniert, reproduzierbar und nachvollziehbar sind.
