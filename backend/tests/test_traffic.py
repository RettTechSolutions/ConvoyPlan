"""Tests für den Traffic-Merge-Layer (Overpass + Autobahn in einen Topf)."""
import pytest

from app.services import traffic as traffic_svc
from app.services.traffic import AllSourcesFailedError


def _fc(*titles):
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [11.0, 48.0]},
             "properties": {"name": t}}
            for t in titles
        ],
    }


def _ab_feature(title):
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [11.1, 48.1]},
            "properties": {"source": "autobahn", "service": "warning", "title": title}}


async def test_merge_combines_both_sources(monkeypatch):
    async def fake_overpass(*a, **k):
        return _fc("osm-baustelle")

    async def fake_autobahn(*a, **k):
        return [_ab_feature("autobahn-warnung")]

    monkeypatch.setattr(traffic_svc.overpass_svc, "get_closures", fake_overpass)
    monkeypatch.setattr(traffic_svc.autobahn_svc, "features_around", fake_autobahn)

    result = await traffic_svc.get_closures(48.0, 11.0, 15000)
    titles = {f["properties"].get("title") or f["properties"].get("name") for f in result["features"]}
    assert titles == {"osm-baustelle", "autobahn-warnung"}
    # Overpass-Features werden mit source-Tag versehen.
    sources = {f["properties"]["source"] for f in result["features"]}
    assert sources == {"overpass", "autobahn"}


async def test_overpass_failure_still_returns_autobahn(monkeypatch):
    async def fail(*a, **k):
        raise RuntimeError("overpass down")

    async def fake_autobahn(*a, **k):
        return [_ab_feature("nur-autobahn")]

    monkeypatch.setattr(traffic_svc.overpass_svc, "get_closures", fail)
    monkeypatch.setattr(traffic_svc.autobahn_svc, "features_around", fake_autobahn)

    result = await traffic_svc.get_closures(48.0, 11.0, 15000)
    assert [f["properties"]["title"] for f in result["features"]] == ["nur-autobahn"]


async def test_autobahn_failure_still_returns_overpass(monkeypatch):
    async def fake_overpass(*a, **k):
        return _fc("nur-osm")

    async def fail(*a, **k):
        raise RuntimeError("autobahn down")

    monkeypatch.setattr(traffic_svc.overpass_svc, "get_closures_along_route", fake_overpass)
    monkeypatch.setattr(traffic_svc.autobahn_svc, "features_along_route", fail)

    result = await traffic_svc.get_closures_along_route([(11.0, 48.0), (11.1, 48.1)])
    assert [f["properties"]["name"] for f in result["features"]] == ["nur-osm"]
    assert result["features"][0]["properties"]["source"] == "overpass"


async def test_both_sources_failing_raises(monkeypatch):
    async def fail(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(traffic_svc.overpass_svc, "get_closures", fail)
    monkeypatch.setattr(traffic_svc.autobahn_svc, "features_around", fail)

    with pytest.raises(AllSourcesFailedError):
        await traffic_svc.get_closures(48.0, 11.0, 15000)
