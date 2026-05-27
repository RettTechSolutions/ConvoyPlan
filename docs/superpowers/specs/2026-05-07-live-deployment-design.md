# Live Deployment: User Management & SSL

## Overview

Three-tier user management (Superadmin → Org Admin → User) plus Caddy-based SSL termination with automatic Let's Encrypt or custom certificate support.

---

## Section 1: User Management — Data Model & Backend

### Database Changes

- `users` table gains two new columns:
  - `is_superadmin: bool, default false, not null`
  - `is_active: bool, default true, not null`
- Org-Admin role reuses the existing `UserOrganization.role = 'admin'` — no new table needed
- New Alembic migration: `0007_user_roles.py`

### Superadmin Seed

On startup (`main.py` lifespan), if no superadmin exists and env vars `SUPERADMIN_EMAIL` + `SUPERADMIN_PASSWORD` are set, one is created automatically. Runs only once; skipped if a superadmin already exists.

### New API Routes

**`/api/admin/users`** — requires `is_superadmin = true`:
- `GET /` — list all users (email, org memberships, is_active, is_superadmin, created_at)
- `POST /` — create a user directly (email + password, optionally assign to an org)
- `PATCH /{id}` — update `is_active` or `is_superadmin`
- `DELETE /{id}` — delete user and all their data

**`/api/organizations/{id}/members/invite`** — requires caller to be Org Admin of that org:
- `POST` — create a new user (email + password) and add them to the org in one step

### Registration Guard

The existing `/api/auth/register` endpoint is restricted: only callable by an authenticated Org Admin (for their own org). Anonymous self-registration is disabled.

### JWT

`is_superadmin` is included in the JWT payload so the frontend can gate the Admin UI without an extra request.

---

## Section 2: Frontend Admin UI

### Route `/admin`

Accessible only when `is_superadmin = true` (checked on page load, redirect to `/plan` otherwise). Uses the same sidebar layout as the Plan page.

**Tab: Benutzer**
- Table: Email | Organisations | Active | Superadmin | Actions
- Actions per row: toggle active/inactive, toggle superadmin role, delete (with confirm dialog)
- "+ Neuer User" button → inline form: Email + Password + optional Org assignment

**Tab: Organisationen**
- List all orgs with their current admins
- Assign or revoke Org Admin role: user picker dropdown per org

### Org Admin View (existing Plan page)

The existing "Organisation" tab in the Plan sidebar gains:
- "+ User einladen" button (visible only to Org Admins of that org)
- Inline form: Email + Password → calls `/api/organizations/{id}/members/invite`
- Existing member list + remove button remains unchanged

### Navigation

Admin link in sidebar header (next to logout button), visible only when `is_superadmin = true`. Renders as a small "⚙ Admin" text link.

---

## Section 3: SSL & Port Binding with Caddy

### New `caddy` Service

Added to both `docker-compose.yml` (dev, optional) and `portainer-stack.yml` (production).

Uses the official `caddy:2-alpine` image with a mounted `Caddyfile`.

### Caddyfile Logic

Two modes controlled by env vars:

**Mode 1 — Let's Encrypt (automatic):** Set `DOMAIN=convoy.example.com`. Caddy handles cert issuance and renewal automatically.

**Mode 2 — Custom certificate:** Set `DOMAIN`, `CADDY_TLS_CERT=/certs/cert.pem`, `CADDY_TLS_KEY=/certs/key.pem`. Mount cert files via a Docker volume.

In both modes, Caddy routes:
- `/api/*` and `/ws/*` → `backend:8000`
- `/*` → `frontend:3000`

### New Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DOMAIN` | — | Hostname for TLS (required for HTTPS) |
| `HTTP_PORT` | `80` | External HTTP port |
| `HTTPS_PORT` | `443` | External HTTPS port |
| `CADDY_TLS_CERT` | — | Path to custom cert (optional) |
| `CADDY_TLS_KEY` | — | Path to custom key (optional) |
| `SUPERADMIN_EMAIL` | — | Email for auto-created superadmin |
| `SUPERADMIN_PASSWORD` | — | Password for auto-created superadmin |

### Port Isolation

In production (`portainer-stack.yml`), frontend and backend **no longer expose ports directly**. Only Caddy is exposed on `HTTP_PORT` and `HTTPS_PORT`. This prevents bypassing SSL.

`docker-compose.override.yml` (local dev) remains unchanged — no Caddy, direct port access on 3000/8000.

### Volumes

- `caddy_data` — Caddy's internal cert cache (persisted across restarts)
- `caddy_config` — Caddy config state
- Optional bind mount for custom certs: `${CERT_DIR:-/certs}:/certs:ro`
