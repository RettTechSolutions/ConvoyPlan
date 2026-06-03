"""Password helpers shared by self-service reset and admin user management."""

import secrets
import string

from fastapi import HTTPException, status

# Central password policy (ISO 27001 A.5.17). Kept deliberately simple and
# offline; a breach-list (HIBP k-anonymity) check is tracked as a follow-up.
MIN_PASSWORD_LENGTH = 10


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
