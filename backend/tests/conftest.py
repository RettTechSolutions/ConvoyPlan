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


@pytest.fixture(autouse=True, scope="session")
def bypass_license_for_tests():
    _lgm._license_valid = True
    yield
    _lgm._license_valid = None
