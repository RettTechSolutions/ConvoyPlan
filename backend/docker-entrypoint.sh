#!/bin/sh
# Robust boot for the ConvoyPlan backend.
#
# Runs database migrations, then starts the API. The resilience property that
# matters: if the database schema is NEWER than this image — i.e. Alembic can't
# locate the DB's current revision, the classic symptom of running an image
# OLDER than the one that last migrated the database (a downgrade) — we do NOT
# crash silently into a 502 blackout. Instead we:
#   1. log a loud, actionable diagnostic,
#   2. drop an alert marker on the shared volume so the (eventually healthy)
#      backend emails the superadmins about it,
#   3. exit non-zero, so the container healthcheck reports unhealthy and the
#      updater's auto-rollback restores the previous, working image.
#
# Kept POSIX-sh (the base image is python:slim → /bin/sh is dash): no bashisms.
set -eu

BACKEND_PORT="${BACKEND_PORT:-8000}"
ALERT_FILE="/update_status/deploy_alert.json"

log() { echo "[entrypoint] $*"; }

# Best-effort alert marker for the backend's deploy-alert watcher to pick up and
# email. Never fails the boot if the shared volume isn't writable.
write_alert() {
    _event="$1"
    _detail="$2"
    _id="$(date -u '+%Y%m%dT%H%M%SZ')-$$"
    _img="${GIT_SHA:-unknown}"
    printf '{"id":"%s","event":"%s","at":"%s","failed_image":"%s","detail":"%s"}\n' \
        "${_id}" "${_event}" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${_img}" "${_detail}" \
        > "${ALERT_FILE}" 2>/dev/null || true
}

log "Running database migrations (alembic upgrade head)…"
if mig_out="$(alembic upgrade head 2>&1)"; then
    printf '%s\n' "${mig_out}"
    log "Migrations OK — starting uvicorn on 0.0.0.0:${BACKEND_PORT}"
    exec uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}"
fi

# ── Migration failed — classify and fail closed ─────────────────────────────
printf '%s\n' "${mig_out}"

if printf '%s' "${mig_out}" | grep -q "Can't locate revision"; then
    # The DB's current revision does not exist in THIS image's migration
    # scripts → this build predates the schema. Refuse to serve against a
    # schema we don't understand.
    rev="$(printf '%s' "${mig_out}" \
        | grep -oE "Can't locate revision identified by '[^']+'" \
        | head -1 | grep -oE "'[^']+'" | tr -d "'" || true)"
    log "=================================================================="
    log "FATAL: this backend image is OLDER than the database schema."
    log "The database is at migration revision '${rev:-unknown}', which this"
    log "image does not contain (alembic: \"Can't locate revision\")."
    log ""
    log "Most likely a DOWNGRADE was deployed — the image tag (:beta/:latest/"
    log ":nightly) resolved to a build predating the migration that last"
    log "upgraded this database. The API will NOT start against a schema it"
    log "does not understand (fail-closed to avoid data corruption)."
    log ""
    log "Fix: deploy a backend image that includes revision '${rev:-<DB revision>}'"
    log "(normally the newer / previous known-good tag). The updater will try an"
    log "automatic rollback to the previously running image."
    log "=================================================================="
    write_alert "boot_image_older_than_db" \
        "Backend-Image ist aelter als das DB-Schema (DB-Revision ${rev:-unbekannt}); Start abgebrochen (fail-closed). Bitte ein neueres/passendes Image deployen."
else
    log "FATAL: database migration failed (see alembic output above)."
    write_alert "boot_migration_failed" \
        "Datenbank-Migration beim Backend-Start fehlgeschlagen; Start abgebrochen. Details im Container-Log."
fi

exit 1
