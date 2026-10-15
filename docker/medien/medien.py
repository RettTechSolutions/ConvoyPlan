"""Medien-Container: ein Video hinein, ein sauberes Video und ein Standbild hinaus.

Angesprochen nur vom Backend im Compose-Netz (``app/services/aktionsseite_video.py``),
ohne veröffentlichten Port. Nur Python-Standardbibliothek und das ffmpeg
dieses Images — der Container hat nichts außer Rechenzeit.

``POST /video?max_sekunden=60`` mit den Bytes des Videos im Körper:

- **200** ``{"breite", "hoehe", "sekunden", "ton", "video", "poster"}`` —
  ``video`` ist ein MP4 (H.264/AAC, ``+faststart``), ``poster`` ein JPEG,
  beide base64.
- **422** ``{"grund": "…"}`` — kein Video, zu lang, zu groß. Der Grund geht
  an die Gruppe, er enthält deshalb nichts aus der Datei.

Neu kodiert, nicht umverpackt: Was das Handy in die Datei schreibt —
GPS-Position (``©xyz``, ``com.apple.quicktime.location.ISO6709``), Gerät,
Aufnahmezeit, XMP —, steht in Boxen, die beim Neuschreiben gar nicht erst
entstehen (``-map_metadata -1``, ``-map_chapters -1``, nur eine Bild- und eine
Tonspur, keine Untertitel- oder Datenspuren). Gedreht wird nach der
Drehangabe des Handys, die danach ebenfalls weg ist.

Eins nach dem anderen: Ein Video kostet je nach Rechner zehn bis sechzig
Sekunden CPU. Was kommt, während eins läuft, wartet.
"""
import base64
import json
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

PORT = int(os.environ.get("PORT", "8090"))
# Größer liefert Telegram einem Bot nicht (getFile).
MAX_BYTES = int(os.environ.get("MEDIEN_MAX_BYTES", str(20 * 1024 * 1024)))
MAX_SEKUNDEN_OBERGRENZE = 300
LANGE_KANTE = 1280
MAX_FPS = 30
# Zeitgrenze je ffmpeg-Lauf; danach wird abgebrochen statt den Container zu binden.
ZEITGRENZE = int(os.environ.get("MEDIEN_ZEITGRENZE", "240"))
THREADS = os.environ.get("MEDIEN_THREADS", "2")

_eins_nach_dem_anderen = threading.Lock()


class Abgelehnt(Exception):
    """Ein Video, das so nicht hinausgeht — der Text geht an die Gruppe."""


def _ffprobe(pfad: str) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", pfad],
        capture_output=True, timeout=60,
    )
    if r.returncode != 0:
        raise Abgelehnt("Das ist kein Video, das sich lesen lässt.")
    return json.loads(r.stdout or b"{}")


def _dauer(info: dict) -> float:
    try:
        return float(info.get("format", {}).get("duration") or 0)
    except ValueError:
        return 0.0


def _ffmpeg(*argumente: str) -> None:
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", *argumente],
        capture_output=True, timeout=ZEITGRENZE,
    )
    if r.returncode != 0:
        # Was ffmpeg sagt, steht im Log des Containers, nicht in der Gruppe.
        print("ffmpeg:", r.stderr.decode(errors="replace")[-2000:], flush=True)
        raise Abgelehnt("Das Video lässt sich nicht umwandeln.")


def umwandeln(daten: bytes, max_sekunden: float) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        ein, aus, bild = (os.path.join(tmp, n) for n in ("ein", "aus.mp4", "poster.jpg"))
        with open(ein, "wb") as f:
            f.write(daten)
        info = _ffprobe(ein)
        if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
            raise Abgelehnt("Das ist kein Video.")
        dauer = _dauer(info)
        if dauer <= 0:
            raise Abgelehnt("Das Video hat keine Länge.")
        if dauer > max_sekunden + 0.5:
            raise Abgelehnt(f"Das Video ist länger als {int(max_sekunden)} Sekunden.")
        # Lange Kante höchstens 1280 (720p bei 16:9), gerade Maße für H.264.
        # `iw`/`ih` sind schon gedreht: ffmpeg wendet die Drehangabe vorher an.
        skalieren = (
            f"scale=w='if(gte(iw,ih),min({LANGE_KANTE},iw),-2)'"
            f":h='if(gte(iw,ih),-2,min({LANGE_KANTE},ih))',setsar=1,format=yuv420p"
        )
        _ffmpeg(
            "-i", ein,
            "-map", "0:v:0", "-map", "0:a:0?",
            "-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn",
            "-t", str(max_sekunden),
            "-vf", skalieren, "-fpsmax", str(MAX_FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-maxrate", "1500k", "-bufsize", "3000k",
            "-profile:v", "high", "-level:v", "4.0",
            "-c:a", "aac", "-b:a", "96k", "-ac", "2",
            "-threads", THREADS,
            # Keine Encoderkennung, keine Zeitstempel in den Boxen.
            "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
            "-metadata:s:v", "encoder=", "-metadata:s:a", "encoder=",
            "-movflags", "+faststart",
            "-f", "mp4", aus,
        )
        ergebnis = _ffprobe(aus)
        video = next(s for s in ergebnis["streams"] if s.get("codec_type") == "video")
        ton = any(s.get("codec_type") == "audio" for s in ergebnis["streams"])
        sekunden = _dauer(ergebnis)
        # Das Standbild nicht aus dem ersten Bild — das ist bei Handyvideos
        # oft schwarz oder verwackelt.
        _ffmpeg("-ss", str(min(0.5, sekunden / 2)), "-i", aus, "-frames:v", "1", "-q:v", "3",
                "-f", "image2", "-c:v", "mjpeg", bild)
        with open(aus, "rb") as f:
            mp4 = f.read()
        with open(bild, "rb") as f:
            jpeg = f.read()
    return {
        "breite": int(video["width"]),
        "hoehe": int(video["height"]),
        "sekunden": round(sekunden, 2),
        "ton": ton,
        "video": base64.b64encode(mp4).decode(),
        "poster": base64.b64encode(jpeg).decode(),
    }


class Anfrage(BaseHTTPRequestHandler):
    server_version = "medien"
    sys_version = ""

    def _antwort(self, code: int, inhalt: dict) -> None:
        roh = json.dumps(inhalt, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_GET(self) -> None:  # noqa: N802 — Name von http.server
        if self.path == "/health":
            return self._antwort(200, {"ok": True})
        self._antwort(404, {"grund": "Nicht gefunden"})

    def do_POST(self) -> None:  # noqa: N802
        teile = urlsplit(self.path)
        if teile.path != "/video":
            return self._antwort(404, {"grund": "Nicht gefunden"})
        try:
            laenge = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._antwort(411, {"grund": "Länge fehlt"})
        if laenge <= 0 or laenge > MAX_BYTES:
            return self._antwort(422, {"grund": "Das Video ist zu groß."})
        try:
            max_sekunden = float(parse_qs(teile.query).get("max_sekunden", ["60"])[0])
        except ValueError:
            max_sekunden = 60.0
        max_sekunden = max(1.0, min(max_sekunden, MAX_SEKUNDEN_OBERGRENZE))
        daten = self.rfile.read(laenge)
        try:
            with _eins_nach_dem_anderen:
                ergebnis = umwandeln(daten, max_sekunden)
        except Abgelehnt as e:
            return self._antwort(422, {"grund": str(e)})
        except subprocess.TimeoutExpired:
            return self._antwort(422, {"grund": "Das Umwandeln dauert zu lange."})
        self._antwort(200, ergebnis)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Ein Satz je Anfrage, ohne Inhalte.
        print(f"{self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}", flush=True)


if __name__ == "__main__":
    print(f"medien: lausche auf {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Anfrage).serve_forever()
