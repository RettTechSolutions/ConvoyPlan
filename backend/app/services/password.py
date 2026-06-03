"""Password helpers shared by self-service reset and admin user management."""

import hashlib
import logging
import secrets
import string

import httpx
from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

# Central password policy (ISO 27001 A.5.17).
MIN_PASSWORD_LENGTH = 10

_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"


def validate_password(password: str) -> None:
    """Raise HTTP 400 if the password does not meet the policy.

    Requires at least MIN_PASSWORD_LENGTH characters and a mix of letters and
    digits. Call this for every user-supplied password (register / change /
    admin-set)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein",
        )
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwort muss Buchstaben und Ziffern enthalten",
        )


async def assert_password_not_breached(password: str) -> None:
    """Reject passwords found in the Have I Been Pwned breach corpus.

    Uses the k-anonymity range API: only the first 5 chars of the SHA-1 hash
    leave the server, never the password itself. Fails open — if the service
    is unreachable (offline/air-gapped deployment) the password is allowed and
    a warning is logged, so this never blocks legitimate password changes.
    """
    if not settings.password_breach_check_enabled:
        return
    # SHA-1 is mandated by the HIBP range API (k-anonymity), not used to store
    # or protect the password. usedforsecurity=False marks it as a non-security
    # digest for the runtime and static analysers (CodeQL/bandit S324).
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(_HIBP_RANGE_URL.format(prefix=prefix))
        if not resp.is_success:
            logger.warning("HIBP breach check unavailable (HTTP %s) — failing open", resp.status_code)
            return
        for line in resp.text.splitlines():
            hash_suffix, _, _count = line.partition(":")
            if hash_suffix.strip().upper() == suffix:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Dieses Passwort ist in bekannten Datenlecks aufgetaucht. Bitte ein anderes wählen.",
                )
    except HTTPException:
        raise
    except Exception:
        logger.warning("HIBP breach check failed — failing open", exc_info=True)


def generate_password(length: int = 14) -> str:
    """Generate a strong random password containing at least one of each character class."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pwd)
                and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd)
                and any(c in "!@#$%^&*" for c in pwd)):
            return pwd
