import pytest
from app.services.region_estimate import (
    estimate_ram_bytes, estimate_graph_bytes, estimate_duration_minutes, verdict,
)

GB = 1024 ** 3

@pytest.mark.parametrize("pbf_gb,documented_ram_gb", [(0.7, 3), (4.0, 6), (5.5, 8)])
def test_estimate_matches_documented_installer_values(pbf_gb, documented_ram_gb):
    """Die Schätzung darf die Installer-Angaben nicht unterschreiten."""
    got = estimate_ram_bytes(int(pbf_gb * GB))
    assert got >= documented_ram_gb * GB

def test_estimate_includes_safety_margin():
    """20 % Aufschlag: die rohe Gerade allein reicht nicht."""
    raw = 2 * GB + int(1.1 * 5.5 * GB)
    assert estimate_ram_bytes(int(5.5 * GB)) >= int(raw * 1.2)

def test_verdict_tight_above_80_percent():
    assert verdict(needed=9 * GB, available=10 * GB) == "knapp"

def test_verdict_insufficient_when_over():
    assert verdict(needed=11 * GB, available=10 * GB) == "reicht nicht"

def test_verdict_ok_with_headroom():
    assert verdict(needed=4 * GB, available=10 * GB) == "ok"
