"""
License validation for ConvoyPlan.

License format:  <base64url_payload>.<base64url_signature>
  payload  – UTF-8 JSON with license fields
  signature – Ed25519 signature over the raw payload bytes

The public key is embedded here and must never be loaded from env or config,
otherwise an attacker could substitute their own key.
"""
import base64
import json
from dataclasses import dataclass
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Embedded public key — generated once, matches the private key in scripts/convoyplan_license.key
_PUBLIC_KEY_B64 = "ANM+Olsscy4ao+gss6wUyK8ybrZddS6B/BaICUhUEZU="


@dataclass
class LicenseInfo:
    valid: bool
    license_id: str = ""
    customer: str = ""
    email: str = ""
    issued: str = ""
    expires: str = ""
    max_users: int = 0
    domain: str = ""
    error: str = ""

    @property
    def expired(self) -> bool:
        if not self.expires:
            return True
        try:
            return date.fromisoformat(self.expires) < date.today()
        except ValueError:
            return True


def _b64url_decode(s: str) -> bytes:
    padded = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(padded)


def _normalize_domain(d: str) -> str:
    return d.lower().strip().removeprefix("www.")


# Domains that are never checked against the license (local/dev/CI installs).
_LOCAL_DOMAINS = {"localhost", "127.0.0.1", "::1", ""}


def validate_license(license_key: str, current_domain: str = "") -> LicenseInfo:
    if not license_key or not license_key.strip():
        return LicenseInfo(valid=False, error="No license key configured")

    try:
        parts = license_key.strip().split(".")
        if len(parts) != 2:
            return LicenseInfo(valid=False, error="Malformed license key")

        payload_b64, sig_b64 = parts
        payload_bytes = _b64url_decode(payload_b64)
        sig_bytes = _b64url_decode(sig_b64)

        pub_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(_PUBLIC_KEY_B64))
        pub_key.verify(sig_bytes, payload_bytes)

        payload = json.loads(payload_bytes.decode())
        info = LicenseInfo(
            valid=True,
            license_id=payload.get("id", ""),
            customer=payload.get("customer", ""),
            email=payload.get("email", ""),
            issued=payload.get("issued", ""),
            expires=payload.get("expires", ""),
            max_users=int(payload.get("max_users", 0)),
            domain=payload.get("domain", ""),
        )

        if info.expired:
            info.valid = False
            info.error = f"License expired on {info.expires}"
            return info

        # Domain binding: only enforced when the license specifies a domain
        # and the installation is not running on localhost.
        license_domain = _normalize_domain(info.domain)
        inst_domain = _normalize_domain(current_domain)
        if license_domain and inst_domain not in _LOCAL_DOMAINS:
            if inst_domain != license_domain:
                info.valid = False
                info.error = (
                    f"License issued for '{info.domain}', "
                    f"but this instance runs on '{current_domain}'"
                )

        return info

    except InvalidSignature:
        return LicenseInfo(valid=False, error="Invalid license signature")
    except Exception as e:
        return LicenseInfo(valid=False, error=f"License validation error: {e}")
