# Repo-Härtung & Auto-Merge — Einrichtungs-Checkliste

Dieses Repo enthält die **automatisierbaren** Bausteine für Branch-Schutz,
Auto-Merge und Auto-Release als Code:

- `.github/workflows/auto-merge.yml` — aktiviert Auto-Merge für PRs mit Label `auto-merge`.
- `.github/workflows/auto-release.yml` — schneidet nach einer abgearbeiteten
  Dependabot-Welle automatisch ein Patch-Release.
- `.github/rulesets/main.json` — importierbares Ruleset zum Schutz von `main`
  (inkl. **Merge Queue**).

Ein paar Schritte lassen sich **nur in den Repo-Settings** (UI) erledigen und
müssen einmalig von einem Repo-Admin ausgeführt werden. Reihenfolge einhalten.

## 1. Ruleset importieren (schützt `main`, aktiviert die Merge Queue)

> **Bestandsrepos:** Wenn bereits ein älteres „Protect main"-Ruleset existiert,
> dieses löschen bzw. ersetzen und die aktuelle `main.json` neu importieren —
> sonst fehlt die Merge Queue und Dependabot-PRs stauen sich wieder.

1. **Settings → Rules → Rulesets → New ruleset → Import a ruleset**
2. Datei `.github/rulesets/main.json` aus diesem Repo hochladen.
3. Speichern. Das Ruleset erzwingt auf dem Default-Branch (`main`):
   - **Pull Request Pflicht** — keine direkten Pushes auf `main`.
   - **Required Status Checks** (müssen grün sein, bevor gemergt werden kann):
     - `Backend – Lint & Tests`
     - `Frontend – Type Check`
     - `Docker – Build check`
     - `Security – Dependency Audit`
   - **Merge Queue** — Merges laufen seriell durch eine Warteschlange: GitHub
     baut pro Eintrag einen temporären Merge-Branch (PR + aktueller `main`),
     lässt die Required Checks darauf laufen (`merge_group`-Trigger in
     `ci.yml`) und mergt erst bei Grün. Dadurch ist **kein manuelles „Update
     branch" mehr nötig**, auch wenn sich `main` laufend ändert — genau das
     Szenario vieler gleichzeitiger Dependabot-PRs.
   - **Strict up-to-date ist dafür deaktiviert** — die Queue testet ohnehin
     jeden PR gegen den aktuellen Stand von `main` (stärkere Garantie).
   - **Nur Squash-Merge** erlaubt (auch in der Queue).
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
3. Fertig. Sobald die eigenen Checks grün sind, stellt GitHub den PR in die
   **Merge Queue**; die Queue testet ihn gegen den aktuellen `main` und mergt
   per Squash. Schlägt ein Check fehl, fliegt der PR aus der Queue und bleibt
   offen.

**Dependabot-PRs** bekommen das Label `auto-merge` **automatisch** vom Workflow.
Patch-/Minor-Bumps wandern damit ohne weiteres Zutun durch die Queue — von
unten nach oben, ein PR nach dem anderen, ohne manuelles Branch-Update. Nur
**Major-Bumps** bleiben zur manuellen Review offen. Voraussetzung: Das Label
`auto-merge` (Schritt 3) existiert.

**Automatisches Release:** Sobald die letzte Dependabot-PR einer Welle gemergt
ist (Queue leer), erstellt `auto-release.yml` nach einer 3-Minuten-Karenz
automatisch den nächsten Patch-Tag (`vX.Y.Z+1`) und startet `release.yml` —
Images werden gebaut, das GitHub-Release veröffentlicht, und die
Kunden-Updater rollen es automatisch aus. Menschliche Merges lösen **kein**
automatisches Release aus (weiterhin Tag-getrieben, siehe `RELEASING.md`).
Achtung: Unreleaste menschliche Commits, die zu dem Zeitpunkt bereits auf
`main` liegen, werden dabei mit ausgeliefert.

## Warum nicht alles per API automatisiert?

Branch-Protection/Rulesets und Repo-Settings (`Allow auto-merge`, Labels) sind
Administrations-Einstellungen, die ein Token mit `administration: write` bzw.
einen Admin-Klick erfordern. Sie sind hier als Code/Checkliste hinterlegt, damit
sie versioniert, reproduzierbar und nachvollziehbar sind.
