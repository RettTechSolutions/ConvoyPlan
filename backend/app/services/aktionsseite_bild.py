"""Bilder für Beiträge der Aktionsseite: einmal neu kodiert, ohne Metadaten.

Ein Foto aus Telegram kann alles tragen, was das Handy hineinschreibt — als
``document`` geschickt auch die GPS-Position auf den Meter. Hinaus geht deshalb
nie das Original, sondern ein neu gezeichnetes Bild: gedreht nach EXIF, in
sRGB, verkleinert, als WebP und **ohne** EXIF, XMP oder ICC-Profil. Was in den
Metadaten stand, gibt es danach nicht mehr.

Gegen den Bildinhalt hilft das nicht — ein Ortsschild bleibt ein Ortsschild.
Dafür sind Verzögerung, Platzierung und Freigabe da
(``services/aktionsseite.py``, Plan § 4).

Verarbeitet wird beim Eingang, einmal; das Original wird nicht aufbewahrt.
Plan: docs/superpowers/plans/2026-10-13-fotos-auf-der-aktionsseite.md, § 5.
"""
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageCms, ImageOps

# Größer liefert ``getFile`` von Telegram ohnehin nicht.
MAX_BYTES = 20 * 1024 * 1024
# Gegen Dekompressionsbomben: Die Größe steht im Kopf der Datei, geprüft wird
# vor dem Dekodieren. 40 Megapixel reichen für jede Handykamera.
MAX_PIXEL = 40_000_000
# Lange Kante der Ansicht (Lightbox) und des Polaroids auf der Karte.
GROSS_PX = 1600
KLEIN_PX = 400
QUALITAET = 80
# Nur, was Telegram als Foto oder Dokument von einem Handy realistisch liefert.
# GIF ist meist Animation, SVG trägt Skript, HEIC kann Pillow ohne Zusatz nicht.
FORMATE = ("JPEG", "PNG", "WEBP")

_SRGB = ImageCms.createProfile("sRGB")


class BildFehler(ValueError):
    """Kein brauchbares Bild — der Bot sagt das in der Gruppe, sonst nichts."""


@dataclass(frozen=True)
class Bild:
    gross: bytes
    klein: bytes
    breite: int  # der großen Fassung
    hoehe: int


def _oeffnen(daten: bytes) -> Image.Image:
    if len(daten) > MAX_BYTES:
        raise BildFehler("Bild zu groß")
    try:
        bild = Image.open(io.BytesIO(daten), formats=FORMATE)
    except (Image.UnidentifiedImageError, OSError) as e:
        raise BildFehler("Kein Bild im Format JPEG, PNG oder WebP") from e
    if bild.width * bild.height > MAX_PIXEL:
        raise BildFehler("Bild hat zu viele Pixel")
    try:
        # Animierte PNG und WebP: das erste Bild, mehr wird nicht gezeigt.
        bild.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            bild.load()
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as e:
        raise BildFehler("Bild lässt sich nicht lesen") from e
    return bild


def _srgb(bild: Image.Image) -> Image.Image:
    """In sRGB, mit weißem Grund statt Transparenz."""
    profil = bild.info.get("icc_profile")
    if profil and bild.mode in ("RGB", "RGBA"):
        try:
            quelle = ImageCms.ImageCmsProfile(io.BytesIO(profil))
            bild = ImageCms.profileToProfile(bild, quelle, _SRGB, outputMode=bild.mode)
        except (ImageCms.PyCMSError, OSError):
            # Kaputtes Profil: dann eben ohne Umrechnung. Weggelassen wird es so
            # oder so.
            pass
    if bild.mode in ("RGBA", "LA") or (bild.mode == "P" and "transparency" in bild.info):
        bild = bild.convert("RGBA")
        grund = Image.new("RGB", bild.size, (255, 255, 255))
        grund.paste(bild, mask=bild.getchannel("A"))
        return grund
    return bild.convert("RGB")


def _webp(bild: Image.Image, kante: int) -> tuple[bytes, int, int]:
    kopie = bild.copy()
    kopie.thumbnail((kante, kante), Image.Resampling.LANCZOS)
    # Ein frisches Bild ohne ``info``: nichts aus dem Original wandert mit,
    # egal was ein künftiges Pillow beim Speichern von selbst übernähme.
    sauber = Image.new("RGB", kopie.size)
    sauber.paste(kopie)
    puffer = io.BytesIO()
    sauber.save(puffer, format="WEBP", quality=QUALITAET, method=4)
    return puffer.getvalue(), sauber.width, sauber.height


def verarbeiten(daten: bytes) -> Bild:
    """Aus den Bytes von Telegram die beiden Fassungen, die gespeichert werden."""
    bild = _oeffnen(daten)
    bild = ImageOps.exif_transpose(bild)
    bild = _srgb(bild)
    gross, breite, hoehe = _webp(bild, GROSS_PX)
    klein, _, _ = _webp(bild, KLEIN_PX)
    return Bild(gross=gross, klein=klein, breite=breite, hoehe=hoehe)
