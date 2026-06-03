"""
Pre-populate the license cache so all tests see a valid license.

The CI LICENSE_KEY in ci.yml was issued before the Ed25519 keypair was
rotated (ef096d0). Rather than regenerate that key (requires the Lizenzmanager
macOS app), we short-circuit the middleware cache here so AsyncClient-based
tests are not affected by license validation.

This fixture does NOT affect any production code path.
"""
import pytest
import app.middleware.license_guard as _lgm
from app.config import settings
from app.services import rate_limit


@pytest.fixture(autouse=True, scope="session")
def bypass_license_for_tests():
    _lgm._license_valid = True
    yield
    _lgm._license_valid = None


@pytest.fixture(autouse=True)
def disable_rate_limiting():
    """Rate limiting is keyed by client IP and persists across requests; disable
    it by default so unrelated auth tests don't interfere with each other.
    Tests that exercise the limiter re-enable it explicitly."""
    previous = settings.rate_limit_enabled
    settings.rate_limit_enabled = False
    rate_limit.reset()
    yield
    settings.rate_limit_enabled = previous
    rate_limit.reset()


@pytest.fixture(autouse=True)
def disable_breach_check():
    """Disable the HIBP breach check by default so tests never hit the network.
    Tests for the check itself re-enable it and mock httpx."""
    previous = settings.password_breach_check_enabled
    settings.password_breach_check_enabled = False
    yield
    settings.password_breach_check_enabled = previous
