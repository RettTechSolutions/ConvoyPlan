"""Aktionsseite: Bilder gehen ohne Metadaten hinaus.

Ein Foto, als Dokument in Telegram geschickt, trägt die GPS-Position auf den
Meter. Das Wichtigste hier ist deshalb der erste Test: GPS hinein, nichts
heraus. Ohne Datenbank.
"""
import io

import pytest
from PIL import Image

from app.services import aktionsseite_bild as b

GPS_IFD = 0x8825
ORIENTIERUNG = 0x0112


def _jpeg(breite=640, hoehe=480, exif: Image.Exif | None = None, farbe=(200, 30, 30)) -> bytes:
    bild = Image.new("RGB", (breite, hoehe), farbe)
    puffer = io.BytesIO()
    bild.save(puffer, format="JPEG", exif=exif or Image.Exif())
    return puffer.getvalue()


def _mit_gps() -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "Handyhersteller"  # Make
    gps = exif.get_ifd(GPS_IFD)
    gps[1] = "N"
    gps[2] = (48.0, 8.0, 30.0)
    gps[3] = "E"
    gps[4] = (11.0, 34.0, 10.0)
    return exif


def _oeffne(daten: bytes) -> Image.Image:
    bild = Image.open(io.BytesIO(daten))
    bild.load()
    return bild


def test_gps_hinein_nichts_heraus():
    original = _jpeg(exif=_mit_gps())
    # Vorbedingung: das Testbild trägt wirklich eine Position.
    assert _oeffne(original).getexif().get_ifd(GPS_IFD)

    ergebnis = b.verarbeiten(original)
    for fassung in (ergebnis.gross, ergebnis.klein):
        bild = _oeffne(fassung)
        assert bild.format == "WEBP"
        assert not bild.getexif()
        assert not bild.getexif().get_ifd(GPS_IFD)
        for schluessel in ("exif", "xmp", "icc_profile"):
            assert not bild.info.get(schluessel), schluessel
        # Auch nicht irgendwo in den Bytes.
        assert b"Exif" not in fassung
        assert b"Handyhersteller" not in fassung


def test_gedreht_wie_aufgenommen():
    """Hochkant fotografiert heißt beim Handy oft: quer gespeichert, mit
    Orientierung im EXIF. Ohne Drehen läge das Bild nach dem Entfernen der
    Metadaten auf der Seite."""
    exif = Image.Exif()
    exif[ORIENTIERUNG] = 6  # 90° im Uhrzeigersinn drehen
    ergebnis = b.verarbeiten(_jpeg(800, 400, exif=exif))
    assert (ergebnis.breite, ergebnis.hoehe) == (400, 800)
    assert _oeffne(ergebnis.gross).size == (400, 800)


def test_zwei_groessen_nie_vergroessert():
    ergebnis = b.verarbeiten(_jpeg(4000, 3000))
    assert _oeffne(ergebnis.gross).size == (b.GROSS_PX, 1200)
    assert max(_oeffne(ergebnis.klein).size) == b.KLEIN_PX

    klein = b.verarbeiten(_jpeg(300, 200))
    assert _oeffne(klein.gross).size == (300, 200)
    assert _oeffne(klein.klein).size == (300, 200)


def test_png_mit_transparenz_bekommt_weissen_grund():
    bild = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    puffer = io.BytesIO()
    bild.save(puffer, format="PNG")
    ergebnis = _oeffne(b.verarbeiten(puffer.getvalue()).gross)
    assert ergebnis.mode == "RGB"
    r, g, bl = ergebnis.getpixel((50, 50))
    assert min(r, g, bl) > 240


def test_dekompressionsbombe_wird_abgelehnt():
    """Ein paar Kilobyte, die beim Dekodieren Hunderte Megabyte belegten.
    Geprüft wird die Größe aus dem Kopf, bevor dekodiert wird."""
    bild = Image.new("1", (10_000, 5_000))
    puffer = io.BytesIO()
    bild.save(puffer, format="PNG")
    assert len(puffer.getvalue()) < 1_000_000
    with pytest.raises(b.BildFehler):
        b.verarbeiten(puffer.getvalue())


def test_zu_grosse_datei_wird_nicht_einmal_geoeffnet():
    with pytest.raises(b.BildFehler):
        b.verarbeiten(b"\xff\xd8" + b"0" * b.MAX_BYTES)


@pytest.mark.parametrize("format_", ["GIF", "BMP", "TIFF"])
def test_andere_formate_werden_abgelehnt(format_):
    puffer = io.BytesIO()
    Image.new("RGB", (50, 50)).save(puffer, format=format_)
    with pytest.raises(b.BildFehler):
        b.verarbeiten(puffer.getvalue())


def test_svg_und_unsinn_werden_abgelehnt():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    for daten in (svg, b"", b"kein Bild", _jpeg()[:200]):
        with pytest.raises(b.BildFehler):
            b.verarbeiten(daten)
