FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# setuptools 70.3.0 (CVE-2025-47273 — path traversal in PackageIndex) is
# flagged by the container scan not from site-packages, but from the wheel
# CPython bundles for its own bootstrapping at
# ensurepip/_bundled/setuptools-*.whl. That file sits inside the stdlib tree,
# is never touched by `pip install`/`pip uninstall`, and is never executed at
# container runtime (ensurepip is not invoked again after this build step) —
# so it's a stale, inert artifact rather than something the app depends on.
# Delete it so the scan has nothing stale to flag, then install the patched
# setuptools that the app/build actually uses.
RUN rm -f /usr/local/lib/python3.*/ensurepip/_bundled/setuptools-*.whl \
    && pip install --no-cache-dir --upgrade "setuptools>=78.1.1" \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Make the robust boot entrypoint executable (runs migrations, then uvicorn;
# fails closed with a clear diagnostic if the image is older than the DB schema).
RUN chmod +x /app/docker-entrypoint.sh

# Bake git SHA and release version at build time so the admin UI / footer can
# show the installed version even before the updater has written its status file.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
ARG APP_VERSION=0.0.0-dev
ENV APP_VERSION=${APP_VERSION}

# Run as a non-root user to reduce the container's attack surface.
# Pre-create the volume mount-points here (owned by appuser) so that Docker
# named volumes pick up the correct owner on their first mount.
RUN useradd --uid 1001 --no-create-home --shell /sbin/nologin appuser \
    && mkdir -p /uploads /certs /update_status \
    && chown -R appuser:appuser /app /uploads /certs /update_status
USER appuser
