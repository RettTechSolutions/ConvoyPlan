FROM python:3.14-slim

WORKDIR /app

# Nur die Sicherheitsaktualisierungen des Basisimages, sonst (fast) keine Pakete:
# Alle Python-Abhaengigkeiten kommen als fertige Wheels (cp314, amd64 und
# arm64), Shapely bringt sein GEOS selbst mit. Das frueher installierte
# libgdal-dev hat nie ein Import gebraucht — es zog nur die komplette
# GDAL/PROJ/HDF5/NetCDF-Kette samt Header in das Laufzeitimage, ein
# Vielfaches der eigentlichen Anwendung, jedes Byte davon Trivy-Angriffsflaeche.
#
# Einzige Ausnahme: fonts-dejavu-core. Marschbefehl, Roadbook und Systembericht
# (fpdf2) laden DejaVu aus /usr/share/fonts — das Slim-Image hat keine Schriften.
# Bis #521 kamen sie unbemerkt über libgdal-dev → fontconfig mit. Der `test`
# lässt den Bau scheitern, statt dass erst der erste PDF-Export mit 500 endet.
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && test -f /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf \
    && test -f /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf

COPY requirements.txt .
# Upgrade the base image's baked-in setuptools (70.3.0, CVE-2025-47273 —
# path traversal in PackageIndex; also closes CVE-2026-59890, an sdist
# MANIFEST.in exclusion bypass fixed in 83.0.0) to a patched release. This
# is the copy actually importable/usable by anything in the image. See
# .trivyignore for why the scan still flags a residual finding after this.
# --only-binary=:all: macht die Wheel-Zusage oben pruefbar: Faellt ein Paket
# beim naechsten Hebung auf ein Quellpaket zurueck, bricht der Bau hier mit
# einer klaren Meldung ab, statt still nach einem Compiler und Headern zu
# suchen, die es in diesem Image absichtlich nicht gibt.
RUN pip install --no-cache-dir --upgrade "setuptools>=83.0.0" \
    && pip install --no-cache-dir --only-binary=:all: -r requirements.txt

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
