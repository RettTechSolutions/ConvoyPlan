from typing import Literal

from pydantic import BaseModel, EmailStr


class SetupStatusResponse(BaseModel):
    setup_required: bool


class SetupRequest(BaseModel):
    # Admin account
    email: EmailStr
    password: str

    # Server config
    domain: str
    tls_mode: Literal["letsencrypt", "custom", "internal"]
    acme_email: EmailStr = "admin@example.com"

    # Custom cert (PEM content as strings, only when tls_mode == "custom")
    cert_pem: str = ""
    key_pem: str = ""

    # Optional: erste Organisation beim Setup anlegen
    org_name: str | None = None
    org_slug: str | None = None
