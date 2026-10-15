# Medien-Container der Aktionsseite: kodiert Videos aus Telegram neu, bevor
# sie gespeichert werden (backend/app/services/aktionsseite_video.py).
#
# Warum ein eigener Container und nicht ffmpeg im Backend:
# Ein ffmpeg mit H.264-Encoder (x264) steht unter der GPL. ConvoyPlan gibt es
# unter AGPL **und** unter kommerzieller Lizenz; ffmpeg als Bibliothek im
# Backend-Prozess (PyAV) hieße, GPL-Code in die kommerzielle Fassung zu
# linken. Hier läuft ffmpeg als eigenes Programm in einem eigenen Container,
# angesprochen über HTTP im Compose-Netz — getrennte Werke, nebeneinander
# ausgeliefert. Der Quelltext dazu ist genau die Fassung unten.
#
# Warum selbst gebaut statt Debians `ffmpeg`:
# Das Paket zieht SDL, PulseAudio, X11 und gut hundert weitere Bibliotheken
# nach — jede davon Trivy-Angriffsfläche für etwas, das nur MP4 in MP4
# umrechnet. Gebaut wird genau, was gebraucht wird: Handyvideos lesen (MOV/MP4,
# Matroska/WebM; H.264, HEVC, VP8/9, MPEG-4; AAC, Opus, MP3, PCM), H.264/AAC in
# MP4 schreiben, ein Standbild als JPEG. Kein Netzwerkprotokoll, kein Gerät,
# keine Hardwarebeschleunigung.

# ── Bau ─────────────────────────────────────────────────────────────────────
FROM debian:trixie-slim AS bau

ARG FFMPEG_VERSION=9.0.2
# Prüfsumme der Quelle von ffmpeg.org; wer die Fassung hebt, zieht sie mit.
ARG FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl nasm pkg-config xz-utils libx264-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN curl -fsSL "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" -o ffmpeg.tar.xz \
 && echo "${FFMPEG_SHA256}  ffmpeg.tar.xz" | sha256sum -c - \
 && tar -xJf ffmpeg.tar.xz --strip-components=1 \
 && rm ffmpeg.tar.xz

# --disable-everything schaltet alle Komponenten ab; was danach freigeschaltet
# wird, ist die ganze Liste. Fehlt ein Filter, den ffmpeg selbst einfügt
# (Drehen nach dem Handy, Formatwandlung), scheitert der Test im CI-Job —
# nicht erst ein Video in der Gruppe.
RUN ./configure \
      --prefix=/opt/ffmpeg \
      --enable-gpl --enable-libx264 \
      --disable-everything --disable-autodetect --disable-network \
      --disable-doc --disable-debug --disable-ffplay \
      --disable-static --enable-shared \
      --enable-protocol=file,pipe \
      --enable-demuxer=mov,matroska,avi,mpegts,image2 \
      --enable-muxer=mp4,mov,image2,matroska \
      --enable-decoder=h264,hevc,mpeg4,vp8,vp9,aac,aac_latm,mp3,opus,vorbis,pcm_s16le,pcm_s16be,pcm_s24le,pcm_f32le,amrnb,amrwb,mjpeg \
      --enable-encoder=libx264,aac,mjpeg \
      --enable-parser=h264,hevc,mpeg4video,vp8,vp9,aac,aac_latm,mpegaudio,opus,vorbis,mjpeg \
      --enable-bsf=h264_mp4toannexb,hevc_mp4toannexb,aac_adtstoasc,vp9_superframe \
      --enable-filter=scale,format,aformat,aresample,transpose,hflip,vflip,rotate,fps,trim,atrim,setpts,asetpts,setsar,null,anull,select \
 && make -j"$(nproc)" \
 && make install

# ── Laufzeit ────────────────────────────────────────────────────────────────
FROM debian:trixie-slim

# `upgrade` vor `install`, wie in den anderen Images: das Basisimage hinkt den
# Sicherheitsaktualisierungen hinterher.
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends libx264-164 python3 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=bau /opt/ffmpeg/bin/ffmpeg /opt/ffmpeg/bin/ffprobe /usr/local/bin/
COPY --from=bau /opt/ffmpeg/lib/ /usr/local/lib/
RUN ldconfig && ffmpeg -hide_banner -version | head -1

COPY medien.py /app/medien.py

# Nur Rechnen: kein Volume, kein Schreibzugriff außer /tmp (compose setzt
# read_only und ein tmpfs), kein Ausgang nach draußen nötig.
RUN useradd --uid 1001 --no-create-home --shell /usr/sbin/nologin medien
USER medien

EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=4)"
CMD ["python3", "/app/medien.py"]
