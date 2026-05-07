import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    is_superadmin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str
    is_superadmin: bool = False


class AdminUserUpdate(BaseModel):
    is_active: bool | None = None
    is_superadmin: bool | None = None


class AdminUserOrgInfo(BaseModel):
    id: uuid.UUID
    name: str
    role: str


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    is_superadmin: bool
    created_at: datetime
    orgs: list[AdminUserOrgInfo] = []

    model_config = {"from_attributes": True}


class InviteUserRequest(BaseModel):
    email: EmailStr
    password: str
