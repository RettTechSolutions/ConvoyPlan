"""build_login_url: credential-email login links resolve to real routes."""
from app.services.email import build_login_url


def test_org_member_link():
    assert build_login_url("https://web.convoyplan.de", org_slug="rdmu") == \
        "https://web.convoyplan.de/o/rdmu/login"


def test_trailing_slash_normalised():
    assert build_login_url("https://web.convoyplan.de/", org_slug="rdmu") == \
        "https://web.convoyplan.de/o/rdmu/login"


def test_superadmin_without_org_goes_to_admin():
    assert build_login_url("https://web.convoyplan.de", is_superadmin=True) == \
        "https://web.convoyplan.de/admin"


def test_no_org_no_superadmin_falls_back_to_root():
    # Must NOT produce the dead "/login" route.
    assert build_login_url("https://web.convoyplan.de") == "https://web.convoyplan.de/"


def test_org_slug_wins_over_superadmin():
    assert build_login_url("https://x.de", org_slug="rdmu", is_superadmin=True) == \
        "https://x.de/o/rdmu/login"
