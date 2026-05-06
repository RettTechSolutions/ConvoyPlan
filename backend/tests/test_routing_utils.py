from math import isclose


def _haversine_m(lon1, lat1, lon2, lat2) -> float:
    from math import radians, cos, sin, asin, sqrt
    R = 6_371_000
    dlon, dlat = radians(lon2 - lon1), radians(lat2 - lat1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def test_haversine_known_distance():
    # Berlin Mitte → Hamburg Mitte ≈ 255 km (rough)
    d = _haversine_m(13.405, 52.52, 9.993, 53.551)
    assert 250_000 < d < 260_000


def test_haversine_zero():
    d = _haversine_m(10.0, 48.0, 10.0, 48.0)
    assert isclose(d, 0.0, abs_tol=0.01)


def test_segment_dist_two_points():
    # zwei Punkte 1 Grad Breitenunterschied ≈ 111 km
    coords = [[10.0, 48.0], [10.0, 49.0]]
    from app.services.routing import _segment_dist_m
    d = _segment_dist_m(coords, 0, 1)
    assert 110_000 < d < 112_000


def test_segment_dist_empty():
    from app.services.routing import _segment_dist_m
    d = _segment_dist_m([[10.0, 48.0], [10.0, 49.0]], 0, 0)
    assert d == 0.0


def test_convoy_duration_with_details():
    from app.api.routes.routing import _convoy_duration_s
    # 10 km komplett urban → 10/40 h = 0.25 h = 900 s
    coords = [[10.0, 48.0], [10.0, 48.09]]  # ~10 km
    details = [[0, 1, "residential"]]
    # Actual haversine distance for this segment ≈ 10.008 km
    d = _convoy_duration_s(10_000, coords, details, speed_urban_kmh=40, speed_rural_kmh=65)
    # 10 km / 40 km/h = 900 s, allow ±60 s for floating point
    assert 840 < d < 960


def test_convoy_duration_fallback():
    from app.api.routes.routing import _convoy_duration_s
    # no details → fallback formula
    d = _convoy_duration_s(65_000, [], [], speed_urban_kmh=40, speed_rural_kmh=65)
    # avg = 0.7*65 + 0.3*40 = 57.5 km/h → 65/57.5 h ≈ 4061 s
    assert 4000 < d < 4120
