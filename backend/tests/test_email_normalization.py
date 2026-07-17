"""E-Mail-Normalisierung: Adressen werden case-insensitiv gespeichert & gesucht.

Regression für den case-sensitiven Login (``Max@x.de`` konnte sich nicht als
``max@x.de`` anmelden) und doppelte Accounts, die sich nur in der Groß-/
Kleinschreibung unterschieden."""
import pytest
from pydantic import ValidationError

from app.api.routes.auth import LoginRequest
from app.api.routes.organizations import OrgMemberAdd
from app.schemas.setup import SetupRequest
from app.schemas.user import (
    AdminUserCreate,
    AdminUserUpdate,
    InviteUserRequest,
    PasswordResetRequest,
    UserCreate,
    normalize_email,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Max@Example.DE", "max@example.de"),
        ("  user@host.com ", "user@host.com"),
        ("ALL@CAPS.COM", "all@caps.com"),
        ("already@lower.de", "already@lower.de"),
    ],
)
def test_normalize_email_helper(raw, expected):
    assert normalize_email(raw) == expected


def test_login_request_normalizes_email():
    # Plain string: normalised but not format-validated.
    assert LoginRequest(email="  Max@Example.DE ", password="x").email == "max@example.de"


def test_user_create_normalizes_email():
    assert UserCreate(email="Max@Example.DE", password="x").email == "max@example.de"


def test_admin_create_normalizes_email():
    assert AdminUserCreate(email="Admin@Firma.DE", password="x").email == "admin@firma.de"


def test_admin_update_normalizes_email():
    assert AdminUserUpdate(email="New@Mail.DE").email == "new@mail.de"
    # Omitted stays None (PATCH semantics unaffected).
    assert AdminUserUpdate(is_active=True).email is None


def test_invite_request_normalizes_email():
    assert InviteUserRequest(email="Invite@X.DE", password="x").email == "invite@x.de"


def test_password_reset_normalizes_email():
    assert PasswordResetRequest(email="Forgot@X.DE").email == "forgot@x.de"


def test_org_member_add_normalizes_email():
    assert OrgMemberAdd(email="Member@X.DE").email == "member@x.de"


def test_setup_request_normalizes_admin_email():
    data = SetupRequest(
        email="Setup@X.DE",
        password="x",
        domain="example.com",
        tls_mode="internal",
    )
    assert data.email == "setup@x.de"


def test_account_creation_still_rejects_malformed_email():
    # NormalizedEmailStr keeps EmailStr's format validation.
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password="x")
