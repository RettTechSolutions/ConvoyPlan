import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ApiKeyRole = Literal["beobachter", "fahrer", "planer", "admin"]


class ApiKeyCreate(BaseModel):
    name: str
    role: ApiKeyRole = "beobachter"
    expires_at: datetime | None = None


class SystemApiKeyCreate(BaseModel):
    """A system key carries no organization and no role — only a name and an
    optional expiry. It grants read-only access to the system metrics."""

    name: str
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    # None for system-scoped keys — they belong to the instance, not a tenant.
    organization_id: uuid.UUID | None = None
    scope: str = "organization"
    name: str
    prefix: str
    role: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked: bool

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned once on creation — includes the plaintext key."""
    key: str
