#!/usr/bin/env python3
"""
ConvoyPlan License Issuer
=========================
Issues signed license keys for ConvoyPlan installations.

Requirements:
    pip install cryptography

Private key file:
    scripts/convoyplan_license.key  (keep secret, never commit)

Usage:
    python scripts/issue_license.py \\
        --customer "Feuerwehr Musterstadt" \\
        --email "admin@fw-musterstadt.de" \\
        --days 365 \\
        --max-users 50

Output:
    A LICENSE_KEY string the customer puts in their .env file.
"""
import argparse
import base64
import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

KEY_FILE = Path(__file__).parent / "convoyplan_license.key"


def _load_private_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not KEY_FILE.exists():
        print(f"ERROR: Private key not found at {KEY_FILE}", file=sys.stderr)
        print("Run with --generate-key to create a new keypair.", file=sys.stderr)
        sys.exit(1)

    raw = base64.b64decode(KEY_FILE.read_text().strip())
    return Ed25519PrivateKey.from_private_bytes(raw)


def _generate_keypair():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    priv_b64 = base64.b64encode(priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()
    pub_b64 = base64.b64encode(pub.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()

    KEY_FILE.write_text(priv_b64 + "\n")
    KEY_FILE.chmod(0o600)

    print(f"Private key saved to: {KEY_FILE}")
    print()
    print("IMPORTANT: Update backend/app/services/license.py with this public key:")
    print(f"  _PUBLIC_KEY_B64 = \"{pub_b64}\"")
    print()
    print("Keep the private key file secret and NEVER commit it.")


def issue_license(customer: str, email: str, days: int, max_users: int, license_id: str | None = None) -> str:
    priv = _load_private_key()

    payload = {
        "id": license_id or str(uuid.uuid4()),
        "customer": customer,
        "email": email,
        "issued": date.today().isoformat(),
        "expires": (date.today() + timedelta(days=days)).isoformat(),
        "max_users": max_users,
    }

    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig_bytes = priv.sign(payload_bytes)

    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
    sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")

    return f"{payload_b64}.{sig_b64}"


def main():
    parser = argparse.ArgumentParser(description="Issue a ConvoyPlan license key")
    parser.add_argument("--generate-key", action="store_true", help="Generate a new Ed25519 keypair")
    parser.add_argument("--customer", help="Customer / organisation name")
    parser.add_argument("--email", help="Contact e-mail address")
    parser.add_argument("--days", type=int, default=365, help="Validity period in days (default: 365)")
    parser.add_argument("--max-users", type=int, default=50, help="Maximum number of users (default: 50)")
    parser.add_argument("--id", dest="license_id", help="Optional fixed license UUID")

    args = parser.parse_args()

    if args.generate_key:
        _generate_keypair()
        return

    if not args.customer or not args.email:
        parser.error("--customer and --email are required")

    key = issue_license(
        customer=args.customer,
        email=args.email,
        days=args.days,
        max_users=args.max_users,
        license_id=args.license_id,
    )

    expires = (date.today() + timedelta(days=args.days)).isoformat()
    print(f"Customer  : {args.customer}")
    print(f"E-Mail    : {args.email}")
    print(f"Expires   : {expires}")
    print(f"Max users : {args.max_users}")
    print()
    print("Add this line to the customer's .env file:")
    print()
    print(f"LICENSE_KEY={key}")


if __name__ == "__main__":
    main()
