FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake git SHA at build time so the admin UI can show the installed version
# even before the updater has written its status file.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
