"""Symmetric encryption for secrets at rest (currently MFA secrets, T7).

Uses Fernet (AES-128-CBC + HMAC). The key comes from `MFA_ENCRYPTION_KEY` when
set, otherwise it is derived deterministically from `JWT_SECRET` so existing
deployments keep working without a new mandatory variable.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    key = settings.mfa_encryption_key.strip()
    if key:
        return Fernet(key.encode())
    digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a stored secret.

    Backward-compatible: a value that is not a valid Fernet token is assumed to
    be a legacy plaintext secret (stored before encryption was introduced) and
    returned as-is. It will be re-encrypted the next time MFA is set up.
    """
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return token
