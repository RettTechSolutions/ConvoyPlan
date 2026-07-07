import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator

MAX_NAME_LENGTH = 100


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
    email: EmailStr
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
    email: EmailStr
    password: str
    is_superadmin: bool = False


class AdminUserUpdate(_NameFieldsMixin):
    is_active: bool | None = None
    is_superadmin: bool | None = None
    email: EmailStr | None = None
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
    email: EmailStr
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordResetRequest(BaseModel):
    email: EmailStr
    org_slug: str | None = None
