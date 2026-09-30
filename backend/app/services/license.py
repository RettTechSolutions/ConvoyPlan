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
from datetime import date, datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Embedded public key — generated once, matches the private key in the Lizenzmanager Keychain
_PUBLIC_KEY_B64 = "F1iudWdhIPUGHkM58WnFV7hIwzFK6/7UiidEKJ/8Sm0="


@dataclass
class LicenseInfo:
    valid: bool
    license_id: str = ""
    customer: str = ""
    email: str = ""
    issued: str = ""
    expires: str = ""
    max_users: int = 0
    instance_id: str = ""
    # Letzter Tag, an dem der LTS-Update-Kanal freigeschaltet ist (ISO-Datum).
    # Gehört zum Wartungsvertrag; leer = kein LTS.
    lts_until: str = ""
    error: str = ""
    # Ab Payload v2 (Lizenzmanager mit Vorlagen). Ältere Schlüssel tragen kein
    # "v" und behalten, was sie hatten: beliebig viele Organisationen — die
    # Zusage „bereits ausgestellte Schlüssel bleiben gültig" gilt auch für das,
    # was sie erlaubt haben. Was daraus fürs Anlegen folgt, entscheidet
    # ``services/org_kontingent.py``, nicht dieses Modul.
    version: int = 1
    contract: str = "legacy"
    # Obergrenze für Organisationen auf der Instanz; None = unbegrenzt.
    max_orgs: int | None = None
    # Ende des Wartungs-/Hostingvertrags (YYYY-MM-DD), leer = keins.
    contract_until: str = ""

    @property
    def lts_active(self) -> bool:
        """True, solange die Lizenz gültig ist und LTS bis heute (einschließlich) abdeckt."""
        if not self.valid or not self.lts_until:
            return False
        try:
            return date.fromisoformat(self.lts_until) >= datetime.now(timezone.utc).date()
        except ValueError:
            return False

    @property
    def expires_date(self) -> date | None:
        """Letzter gültiger Tag (UTC); None, wenn ``expires`` fehlt oder unlesbar ist."""
        if not self.expires:
            return None
        # ISO date string (YYYY-MM-DD) — preferred format
        try:
            return date.fromisoformat(self.expires)
        except ValueError:
            pass
        # Unix timestamp — "exp" field in JWT convention
        try:
            return datetime.fromtimestamp(int(self.expires), tz=timezone.utc).date()
        except (ValueError, OSError, OverflowError):
            return None

    @property
    def expired(self) -> bool:
        ablauf = self.expires_date
        if ablauf is None:
            return True  # missing or unknown format → treat as expired
        return ablauf < datetime.now(timezone.utc).date()


def _b64url_decode(s: str) -> bytes:
    padded = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(padded)


def validate_license(license_key: str, instance_id: str = "") -> LicenseInfo:
    """
    Validate a license key.

    instance_id – the installation's machine fingerprint (from system_settings).
                  If the license contains an instance_id field, it must match.
                  An empty instance_id skips the binding check (CI / first boot).
    """
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
        # Accept both "expires" (internal convention) and "exp" (JWT convention)
        expires_raw = payload.get("expires") or payload.get("exp") or ""
        info = LicenseInfo(
            valid=True,
            license_id=payload.get("id", ""),
            customer=payload.get("customer", ""),
            email=payload.get("email", ""),
            issued=payload.get("issued", ""),
            expires=str(expires_raw),
            max_users=int(payload.get("max_users", 0)),
            # "iid" ist das Feld der frühen Lizenzmanager-Fassung. Wurde es
            # nicht gelesen, galt die Bindung als leer und der Schlüssel auf
            # jeder Installation — Widerruf wirkt offline nicht, also blieben
            # auch die als widerrufen geführten Schlüssel überall gültig.
            instance_id=payload.get("instance_id") or payload.get("iid") or "",
            lts_until=str(payload.get("lts_until", "") or ""),
        )
        if int(payload.get("v", 1)) >= 2:
            info.version = int(payload["v"])
            info.contract = str(payload.get("contract", "")) or "individuell"
            # 0 heißt im Schlüssel „unbegrenzt" — so kann der Lizenzmanager es
            # ohne null ausdrücken, und ein fehlendes Feld fällt nicht auf 0.
            max_orgs = int(payload.get("max_orgs", 0))
            info.max_orgs = max_orgs if max_orgs > 0 else None
            info.contract_until = str(payload.get("contract_until", "") or "")

        if info.expired:
            info.valid = False
            info.error = f"License expired on {info.expires}"
            return info

        # Instance binding: enforced when both the license and the running
        # installation carry an instance_id.
        if info.instance_id and instance_id:
            if info.instance_id != instance_id:
                info.valid = False
                info.error = "License is not valid for this installation"

        return info

    except InvalidSignature:
        return LicenseInfo(valid=False, error="Invalid license signature")
    except Exception as e:
        return LicenseInfo(valid=False, error=f"License validation error: {e}")
