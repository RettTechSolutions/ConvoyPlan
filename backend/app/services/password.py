"""Password helpers shared by self-service reset and admin user management."""

import secrets
import string


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
