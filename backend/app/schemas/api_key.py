import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ApiKeyRole = Literal["beobachter", "fahrer", "planer", "admin"]


class ApiKeyCreate(BaseModel):
    name: str
    role: ApiKeyRole = "beobachter"
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
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
