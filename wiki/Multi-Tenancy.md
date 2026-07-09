# Multi-Tenancy

ConvoyPlan ist mandantenfähig: Mehrere Organisationen teilen sich eine Instanz, arbeiten aber vollständig voneinander isoliert.

---

## Org-Code-Slug

Jede Organisation erhält einen kurzen **Org-Code** (4–8 Zeichen) als URL-Slug. Er wird beim Anlegen der Organisation vergeben (Setup-Wizard, Schritt 2, oder später im Admin-Bereich) und ist Teil aller org-spezifischen URLs unter dem Scope `/o/[slug]/`:

| Bereich | URL |
|---|---|
| Login | `https://<DOMAIN>/o/[slug]/login` |
| Planung | `https://<DOMAIN>/o/[slug]/plan/` |
| Live-Tracking | `https://<DOMAIN>/o/[slug]/tracking/` |
| Org-Admin | `https://<DOMAIN>/o/[slug]/admin/` |

---

## Org-spezifische Login-Seite und Branding

Die Login-Seite unter `/o/[slug]/login` zeigt das **eigene Branding** der Organisation (Logo, Farben, App-Name). Das Branding wird im Org-Admin-Bereich gepflegt und ist unabhängig vom globalen Branding der Instanz.

---

## Datenisolation

Alle fachlichen Objekte (Konvois, Fahrzeuge, Leitstellen-Vorschläge, Positionen) sind über die `organization_id` an eine Organisation gebunden. Benutzer sehen ausschließlich Daten der Organisationen, denen sie zugeordnet sind. Die Zuordnung erfolgt über `UserOrganizations`.

---

## Rollen im Org-Kontext

Innerhalb einer Organisation gelten die üblichen Rollen (**Admin, Planer, Fahrer, Beobachter**). Details siehe [Rollen & Berechtigungen](Rollen).

- **Superadmin** ist instanzweit und verwaltet Organisationen, globale Leitstellen, Updates und System-Einstellungen.
- **Org-Admin** verwaltet Mitglieder, org-eigene Leitstellen, Branding und System-Einstellungen der eigenen Organisation.

---

## Anlegen und Zuweisen

| Aktion | Wo |
|---|---|
| Organisation anlegen | Setup-Wizard (erste Org) oder Superadmin → Organisationen |
| Benutzer einer Org zuweisen | Superadmin → Benutzer, oder Org-Admin → Mitglieder |
| Org-Code / Branding ändern | Org-Admin → System / Branding |

Relevante Endpunkte: siehe [API-Dokumentation → Organisationen](API-Dokumentation#organisationen).
