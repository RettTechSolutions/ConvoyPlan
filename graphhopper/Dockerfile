# GraphHopper – selbstständiger Build
# Lädt beim ersten Start automatisch OSM-Kartendaten herunter.
# Konfigurierbar über Umgebungsvariablen (siehe docker-compose.yml).

FROM eclipse-temurin:25-jre-alpine

# 10.2 statt 9.1: 9.1 bricht den Import mit turn_costs an gueltigen
# no_entry/no_exit-Relationen mit Via-Weg und mehreren from- oder to-Wegen ab
# ("fromEdges and toEdges cannot be size > 1 at the same time", GraphHopper
# #3086, behoben in #3100). Solche Relationen gibt es in DACH; seit beide
# Profile turn_costs haben, kam kein Import mehr durch.
ARG GH_VERSION=10.2

RUN apk upgrade --no-cache && apk add --no-cache curl

WORKDIR /graphhopper

# GraphHopper-JAR zur Build-Zeit herunterladen (gepinnte Version, kein Runtime-Download)
RUN curl -fsSL -o graphhopper.jar \
    "https://github.com/graphhopper/graphhopper/releases/download/${GH_VERSION}/graphhopper-web-${GH_VERSION}.jar"

# Der Entrypoint nimmt die Version in den Graph-Fingerprint: das Speicherformat
# wechselt zwischen den Versionen, ein Graph einer anderen Fassung wird nicht
# geladen und muss neu gebaut werden.
ENV GH_VERSION=${GH_VERSION}

COPY entrypoint.sh /entrypoint.sh
COPY region-source.sh /region-source.sh
RUN chmod +x /entrypoint.sh

# /data/osm   – OSM-PBF-Datei (wird beim ersten Start heruntergeladen)
# /data/graph – Kompilierter Routing-Graph (wird nach dem ersten PBF-Import gecacht)
VOLUME ["/data/osm", "/data/graph"]

EXPOSE 8989 8990

ENTRYPOINT ["/entrypoint.sh"]
