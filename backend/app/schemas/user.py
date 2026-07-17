import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, field_validator

MAX_NAME_LENGTH = 100


def normalize_email(value: str) -> str:
    """Trim and lower-case an address so storage and look-ups are
    case-insensitive.

    Mailbox providers treat addresses case-insensitively, but the app used to
    store and compare them verbatim. That made login fail when the case didn't
    match what was typed at sign-up, and let ``Max@x.de`` and ``max@x.de`` be
    registered as two separate accounts (bypassing the unique-email check).
    Normalising on the way in — combined with the lower-cased data migration
    and the ``lower(email)`` unique index — closes both holes."""
    return value.strip().lower()


# Full validation (format) + normalisation. Use for account-creation paths.
NormalizedEmailStr = Annotated[EmailStr, AfterValidator(normalize_email)]
# Normalisation only (no format enforcement). Use where a plain string is
# accepted on purpose — e.g. login, so malformed input still yields a clean
# 401 rather than a 422 that would reveal the field was even reached.
NormalizedEmail = Annotated[str, AfterValidator(normalize_email)]


def _clean_name(value: str | None) -> str | None:
    """Trim whitespace and collapse empty strings to None (column limit: 100)."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_NAME_LENGTH:
        raise ValueError(f"Name darf höchstens {MAX_NAME_LENGTH} Zeichen lang sein")
    return value


class _NameFieldsMixin(BaseModel):
    first_name: str | None = None
    last_name: str | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def _normalize_names(cls, v: str | None) -> str | None:
        return _clean_name(v)


class UserCreate(BaseModel):
    email: NormalizedEmailStr
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool
    is_superadmin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AdminUserCreate(_NameFieldsMixin):
    email: NormalizedEmailStr
    password: str
    is_superadmin: bool = False


class AdminUserUpdate(_NameFieldsMixin):
    is_active: bool | None = None
    is_superadmin: bool | None = None
    email: NormalizedEmailStr | None = None
    password: str | None = None


class AdminUserOrgInfo(BaseModel):
    id: uuid.UUID
    name: str
    role: str


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool
    is_superadmin: bool
    is_demo: bool = False
    mfa_enabled: bool = False
    created_at: datetime
    orgs: list[AdminUserOrgInfo] = []

    model_config = {"from_attributes": True}


class InviteUserRequest(_NameFieldsMixin):
    email: NormalizedEmailStr
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordResetRequest(BaseModel):
    email: NormalizedEmailStr
    org_slug: str | None = None
