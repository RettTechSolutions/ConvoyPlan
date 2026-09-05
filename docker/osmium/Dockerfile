# osmium-tool fuer den Regionswechsel — verwendet von
# docker/updater/merge-extracts.sh, um mehrere Geofabrik-Extracts zu EINER
# Karte zu verschmelzen.
#
# Warum ein eigenes Image statt eines fertigen vom Hub:
# `stefda/osmium-tool:latest`, der naheliegende Kandidat, stammt vom
# 19.12.2017, ist 492 MB gross, laeuft als root, enthaelt die komplette
# Build-Toolchain und existiert nur als `latest` — es gibt also keinen Tag,
# auf den sich pinnen liesse. Fuer einen Container mit Schreibzugriff auf das
# OSM-Volume ist das die falsche Grundlage.
#
# Warum ein Wegwerf-Container und nicht osmium im Updater-Image:
# Das Updater-Image basiert auf `docker:cli` (Alpine), und osmium-tool ist in
# keinem Alpine-Zweig paketiert (v3.19, v3.20, v3.21, v3.22 und edge geprueft —
# in keinem enthalten). Debian hat es, also ein eigenes schlankes Debian-Image,
# das fuer die Dauer eines Merge lebt und danach verschwindet.
FROM debian:trixie-slim

# osmium-tool 1.18 aus trixie (statt der 2017er-Version im Fremdimage).
#
# `upgrade` vor `install`, analog zum `apk upgrade` im Updater-Image: Das
# Basisimage hinkt den Sicherheitsaktualisierungen regelmaessig hinterher —
# beim ersten Bau waren es zwei behebbare HIGH-Befunde in openssl, die der
# Trivy-Scan zu Recht abgewiesen hat.
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends osmium-tool \
 && rm -rf /var/lib/apt/lists/*

# Kein USER-Wechsel: Der Container schreibt in das osm_data-Volume, das die
# uebrigen Dienste als root anlegen. Er bekommt weder Docker-Socket noch
# Netzwerk (merge-extracts.sh startet ihn mit --network none).
CMD ["osmium", "--help"]
