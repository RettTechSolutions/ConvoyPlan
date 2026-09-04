# GraphHopper – selbstständiger Build
# Lädt beim ersten Start automatisch OSM-Kartendaten herunter.
# Konfigurierbar über Umgebungsvariablen (siehe docker-compose.yml).

FROM eclipse-temurin:25-jre-alpine

ARG GH_VERSION=9.1

RUN apk upgrade --no-cache && apk add --no-cache curl

WORKDIR /graphhopper

# GraphHopper-JAR zur Build-Zeit herunterladen (gepinnte Version, kein Runtime-Download)
RUN curl -fsSL -o graphhopper.jar \
    "https://github.com/graphhopper/graphhopper/releases/download/${GH_VERSION}/graphhopper-web-${GH_VERSION}.jar"

COPY entrypoint.sh /entrypoint.sh
COPY region-source.sh /region-source.sh
RUN chmod +x /entrypoint.sh

# /data/osm   – OSM-PBF-Datei (wird beim ersten Start heruntergeladen)
# /data/graph – Kompilierter Routing-Graph (wird nach dem ersten PBF-Import gecacht)
VOLUME ["/data/osm", "/data/graph"]

EXPOSE 8989 8990

ENTRYPOINT ["/entrypoint.sh"]
