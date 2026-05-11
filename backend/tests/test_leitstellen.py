def test_leitstelle_model_importable():
    from app.models.leitstelle import Leitstelle
    ls = Leitstelle(name="ILS München", anrufgruppe="468")
    assert ls.name == "ILS München"
    assert ls.anrufgruppe == "468"
    assert ls.zusatz_kanaele is None
    assert ls.geometry is None
