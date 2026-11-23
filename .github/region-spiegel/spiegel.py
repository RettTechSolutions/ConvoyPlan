"""Geofabrik-Spiegel fuer den Job `region-switch` in ci.yml.

Der Regionswechsel laedt sein Extract von https://download.geofabrik.de/ —
und nur von dort, das ist im Updater eine Allowlist (switch-region.sh) und im
Backend eine Sicherheitsgrenze (geofabrik.validate_region_url). Am 2026-11-23
war Geofabrik von den Runnern aus stundenlang nur zeitweise erreichbar, und
jeder Merge hing davon ab, ob der Region-Job gerade Glueck hatte.

Deshalb antwortet im Job dieser Server unter genau diesem Namen: ein
Netzwerk-Alias im Compose-Netz (compose.yml daneben) und ein Zertifikat einer
Test-CA, der nur der Updater des Jobs vertraut (CURL_CA_BUNDLE). Der Updater
laeuft unveraendert — HEAD fuer die Groesse, .md5, Download, Pruefung. Ob
Geofabrik selbst noch so ausliefert, prueft der taegliche Job `caches`, der
die Extracts von dort holt.

Aufruf: spiegel.py <wurzel> <zertifikat> <schluessel> [port]
"""

import functools
import http.server
import ssl
import sys


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 — Signatur der Basisklasse
        # Auf stdout und sofort: `docker compose logs` ist der Beleg im Job,
        # dass Berlin von hier kam und nicht von Geofabrik.
        print("%s %s" % (self.address_string(), format % args), flush=True)


def main() -> None:
    wurzel, zertifikat, schluessel = sys.argv[1:4]
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 443
    handler = functools.partial(_Handler, directory=wurzel)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
    kontext = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # Nur in der CI, aber trotzdem: kein TLS 1.0/1.1 (CodeQL
    # py/insecure-protocol). curl im Updater spricht ohnehin 1.2+.
    kontext.minimum_version = ssl.TLSVersion.TLSv1_2
    kontext.load_cert_chain(zertifikat, schluessel)
    server.socket = kontext.wrap_socket(server.socket, server_side=True)
    print(f"Geofabrik-Spiegel auf Port {port}, Wurzel {wurzel}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
