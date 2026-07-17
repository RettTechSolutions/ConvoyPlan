FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
