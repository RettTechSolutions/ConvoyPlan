"""Passkeys: einrichten, anmelden, löschen — und was dabei abgewiesen wird.

Zuerst die Regeln aus ``services/passkey.py`` ohne Datenbank (Challenge gilt
einmal, Zähler, Relying Party). Danach der ganze Weg durch die App mit einem
Software-Authenticator: echte P-256-Schlüssel, echte Signaturen, dieselben
Bytes, die ein Browser schickt. Die Kryptografie wird nicht gemockt — ein
Test, der ``verify_*`` ersetzt, prüft nur, dass er sie ersetzt hat.
"""
import base64
import hashlib
import json
import secrets
import struct
import uuid

import bcrypt
import cbor2
import jwt as _jwt
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api.routes.auth import create_token
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models.organization import Organization, UserOrganization
from app.models.passkey import Passkey
from app.models.user import User
from app.services import passkey as pk

PASSWORT = "Richtig-Passwort-2026"


# ── Regeln ohne Datenbank ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def offene_challenges_leeren():
    pk.reset()
    yield
    pk.reset()


def test_challenge_gilt_genau_einmal():
    kennung, challenge = pk.ausstellen(pk.LOGIN, jetzt=100.0)
    assert pk.einloesen(kennung, pk.LOGIN, jetzt=101.0) == challenge
    assert pk.einloesen(kennung, pk.LOGIN, jetzt=101.0) is None


def test_challenge_laeuft_ab():
    kennung, _ = pk.ausstellen(pk.LOGIN, jetzt=100.0)
    assert pk.einloesen(kennung, pk.LOGIN, jetzt=100.0 + pk.CHALLENGE_TTL_SECONDS) is None


def test_falscher_zweck_verbraucht_die_challenge():
    """Eine Registrierungs-Challenge taugt nicht zum Anmelden — und wer es
    versucht, hat sie danach auch für die Registrierung verbrannt."""
    kennung, _ = pk.ausstellen(pk.REGISTRIERUNG, "benutzer-a", jetzt=0.0)
    assert pk.einloesen(kennung, pk.LOGIN, jetzt=1.0) is None
    assert pk.einloesen(kennung, pk.REGISTRIERUNG, "benutzer-a", jetzt=1.0) is None


def test_registrierung_gehoert_dem_der_sie_begonnen_hat():
    kennung, _ = pk.ausstellen(pk.REGISTRIERUNG, "benutzer-a", jetzt=0.0)
    assert pk.einloesen(kennung, pk.REGISTRIERUNG, "benutzer-b", jetzt=1.0) is None


def test_offene_challenges_sind_gedeckelt(monkeypatch):
    monkeypatch.setattr(pk, "MAX_OFFENE", 3)
    erste, _ = pk.ausstellen(pk.LOGIN, jetzt=0.0)
    for _ in range(3):
        pk.ausstellen(pk.LOGIN, jetzt=0.0)
    assert len(pk._offen) == 3
    assert pk.einloesen(erste, pk.LOGIN, jetzt=0.0) is None


@pytest.mark.parametrize(
    ("gespeichert", "neu", "ok"),
    [
        (0, 0, True),    # synchronisierter Passkey, zählt nicht
        (0, 1, True),    # erste gezählte Anmeldung
        (5, 6, True),
        (5, 5, False),   # gleicher Stand: zweites Exemplar
        (5, 3, False),   # Rückschritt
        (5, 0, False),   # zählte, zählt plötzlich nicht mehr
    ],
)
def test_signaturzaehler(gespeichert, neu, ok):
    assert pk.zaehler_ok(gespeichert, neu) is ok


def test_relying_party_kommt_aus_app_base_url(monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://Plan.Example.org:8443/")
    assert pk.rp_id() == "plan.example.org"
    assert pk.origin() == "https://plan.example.org:8443"


# ── Software-Authenticator ───────────────────────────────────────────────────


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


UP, UV, BE, BS, AT = 0x01, 0x04, 0x08, 0x10, 0x40


class Geraet:
    """Ein Authenticator mit genau einem Passkey, wie ihn ein Browser
    zurückgibt — nur ohne Browser."""

    def __init__(self, *, origin: str | None = None, zaehlt: bool = False):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(16)
        self.origin = origin or pk.origin()
        self.zaehlt = zaehlt
        self.zaehler = 0
        self.user_handle: bytes | None = None

    def _cose(self) -> bytes:
        n = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def _auth_data(self, flags: int, mit_schluessel: bool) -> bytes:
        if self.zaehlt:
            self.zaehler += 1
        daten = hashlib.sha256(pk.rp_id().encode()).digest() + bytes([flags]) + struct.pack(">I", self.zaehler)
        if mit_schluessel:
            daten += bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose()
        return daten

    def _client_data(self, typ: str, challenge: str) -> bytes:
        return json.dumps({"type": typ, "challenge": challenge, "origin": self.origin}).encode()

    def erstellen(self, options: dict, *, flags: int = UP | UV | BE | BS) -> dict:
        self.user_handle = _unb64(options["user"]["id"])
        client_data = self._client_data("webauthn.create", options["challenge"])
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": self._auth_data(flags | AT, True)})
        return {
            "id": _b64(self.credential_id),
            "rawId": _b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64(client_data),
                "attestationObject": _b64(att),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
        }

    def anmelden(self, options: dict, *, flags: int = UP | UV | BE | BS) -> dict:
        client_data = self._client_data("webauthn.get", options["challenge"])
        auth_data = self._auth_data(flags, False)
        signatur = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": _b64(self.credential_id),
            "rawId": _b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": _b64(client_data),
                "authenticatorData": _b64(auth_data),
                "signature": _b64(signatur),
                "userHandle": _b64(self.user_handle or b""),
            },
            "clientExtensionResults": {},
        }


# ── Durch die App ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def reset_db_engine():
    yield
    await engine.dispose()


@pytest.fixture
async def konto():
    """Ein Benutzer, Mitglied einer Organisation; ein zweiter ohne sie."""
    marker = uuid.uuid4().hex[:8]
    hashed = bcrypt.hashpw(PASSWORT.encode(), bcrypt.gensalt(4)).decode()
    async with AsyncSessionLocal() as db:
        user = User(email=f"passkey-{marker}@test.invalid", hashed_password=hashed, first_name="Pia")
        fremd = User(email=f"passkey-fremd-{marker}@test.invalid", hashed_password=hashed)
        db.add_all([user, fremd])
        await db.flush()
        org = Organization(name="Passkey-Test", slug=f"passkey-{marker}", owner_id=user.id)
        andere = Organization(name="Andere", slug=f"passkey-andere-{marker}", owner_id=fremd.id)
        db.add_all([org, andere])
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="planer"))
        db.add(UserOrganization(user_id=fremd.id, organization_id=andere.id, role="planer"))
        await db.commit()
        await db.refresh(user)
        await db.refresh(fremd)
    yield {"user": user, "fremd": fremd, "org": org, "andere": andere}
    async with AsyncSessionLocal() as db:
        ids = [user.id, fremd.id]
        await db.execute(delete(UserOrganization).where(UserOrganization.user_id.in_(ids)))
        await db.execute(delete(Organization).where(Organization.id.in_([org.id, andere.id])))
        await db.execute(delete(User).where(User.id.in_(ids)))
        await db.commit()


def _client() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _bearer(user: User, org: Organization) -> dict:
    token = create_token(str(user.id), False, str(org.id), org.slug, "planer", user.token_version)
    return {"Authorization": f"Bearer {token}"}


async def _einrichten(user: User, org: Organization, geraet: Geraet, **kw) -> dict:
    async with _client() as c:
        r = await c.post(
            "/api/auth/passkeys/register/options", json={"password": PASSWORT}, headers=_bearer(user, org)
        )
        assert r.status_code == 200, r.text
        data = r.json()
        r = await c.post(
            "/api/auth/passkeys/register",
            json={"challenge_id": data["challenge_id"], "credential": geraet.erstellen(data["options"], **kw)},
            headers=_bearer(user, org),
        )
    return {"status": r.status_code, "body": r.json()}


async def _anmelden(geraet: Geraet, org_slug: str | None, **kw):
    async with _client() as c:
        r = await c.post("/api/auth/login/passkey/options")
        assert r.status_code == 200, r.text
        data = r.json()
        credential = geraet.anmelden(data["options"], **kw)
        antwort = await c.post(
            "/api/auth/login/passkey",
            json={"challenge_id": data["challenge_id"], "credential": credential, "org_slug": org_slug},
        )
    return antwort, data, credential


async def test_einrichten_und_anmelden(konto):
    user, org = konto["user"], konto["org"]
    geraet = Geraet()
    ergebnis = await _einrichten(user, org, geraet)
    assert ergebnis["status"] == 201, ergebnis
    assert ergebnis["body"]["name"] == "Synchronisierter Passkey"
    assert ergebnis["body"]["backed_up"] is True
    # Die Benutzerkennung auf dem Gerät ist die UUID, nicht die Adresse.
    assert geraet.user_handle == user.id.bytes

    r, _, _ = await _anmelden(geraet, org.slug)
    assert r.status_code == 200, r.text
    payload = _jwt.decode(r.json()["access_token"], settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert payload["sub"] == str(user.id)
    assert payload["org_slug"] == org.slug
    assert payload["role"] == "planer"
    assert any(k.startswith("cp_session__") for k in r.cookies.keys())

    async with AsyncSessionLocal() as db:
        eintrag = (await db.execute(select(Passkey).where(Passkey.user_id == user.id))).scalar_one()
        assert eintrag.last_used_at is not None


async def test_passkey_ersetzt_den_zweiten_faktor(konto):
    """Mit MFA eingeschaltet gibt das Passwort nur einen MFA-Schritt her;
    der Passkey eine Sitzung."""
    user, org = konto["user"], konto["org"]
    geraet = Geraet()
    assert (await _einrichten(user, org, geraet))["status"] == 201
    async with AsyncSessionLocal() as db:
        u = await db.get(User, user.id)
        u.mfa_enabled = True
        u.mfa_secret = "irgendwas"
        await db.commit()

    r, _, _ = await _anmelden(geraet, org.slug)
    assert r.status_code == 200
    assert r.json()["mfa_required"] is False
    assert r.json()["access_token"]


async def test_challenge_laesst_sich_nicht_zweimal_einloesen(konto):
    user, org = konto["user"], konto["org"]
    geraet = Geraet()
    await _einrichten(user, org, geraet)
    r, data, credential = await _anmelden(geraet, org.slug)
    assert r.status_code == 200
    async with _client() as c:
        noch_mal = await c.post(
            "/api/auth/login/passkey",
            json={"challenge_id": data["challenge_id"], "credential": credential, "org_slug": org.slug},
        )
    assert noch_mal.status_code == 401


async def test_fremde_organisation_ist_dieselbe_absage(konto):
    user, org = konto["user"], konto["org"]
    geraet = Geraet()
    await _einrichten(user, org, geraet)
    r, _, _ = await _anmelden(geraet, konto["andere"].slug)
    assert r.status_code == 401
    unbekannt, _, _ = await _anmelden(geraet, "gibt-es-nicht")
    assert unbekannt.status_code == 401
    assert unbekannt.json() == r.json()


async def test_ohne_organisation_nur_superadmin(konto):
    user, org = konto["user"], konto["org"]
    geraet = Geraet()
    await _einrichten(user, org, geraet)
    r, _, _ = await _anmelden(geraet, None)
    assert r.status_code == 403

    async with AsyncSessionLocal() as db:
        (await db.get(User, user.id)).is_superadmin = True
        await db.commit()
    r, _, _ = await _anmelden(geraet, None)
    assert r.status_code == 200
    payload = _jwt.decode(r.json()["access_token"], settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert payload["is_superadmin"] is True
    assert payload["org_slug"] is None


async def test_deaktiviertes_konto_kommt_nicht_herein(konto):
    user, org = konto["user"], konto["org"]
    geraet = Geraet()
    await _einrichten(user, org, geraet)
    async with AsyncSessionLocal() as db:
        (await db.get(User, user.id)).is_active = False
        await db.commit()
    r, _, _ = await _anmelden(geraet, org.slug)
    assert r.status_code == 403


async def test_ohne_benutzerverifikation_keine_anmeldung(konto):
    """Nur Besitz, keine PIN/Biometrie: das ist kein Ersatz für Passwort
    plus Zweitfaktor."""
    user, org = konto["user"], konto["org"]
    geraet = Geraet()
    await _einrichten(user, org, geraet)
    r, _, _ = await _anmelden(geraet, org.slug, flags=UP)
    assert r.status_code == 401


async def test_ohne_benutzerverifikation_kein_einrichten(konto):
    ergebnis = await _einrichten(konto["user"], konto["org"], Geraet(), flags=UP)
    assert ergebnis["status"] == 400


async def test_fremder_ursprung_wird_abgewiesen(konto):
    user, org = konto["user"], konto["org"]
    geraet = Geraet()
    await _einrichten(user, org, geraet)
    geraet.origin = "https://convoyplan.example.com.evil.test"
    r, _, _ = await _anmelden(geraet, org.slug)
    assert r.status_code == 401


async def test_falsche_signatur_wird_abgewiesen(konto):
    user, org = konto["user"], konto["org"]
    geraet = Geraet()
    await _einrichten(user, org, geraet)
    geraet.key = ec.generate_private_key(ec.SECP256R1())
    r, _, _ = await _anmelden(geraet, org.slug)
    assert r.status_code == 401


async def test_unbekannter_passkey_wird_abgewiesen(konto):
    geraet = Geraet()
    r, _, _ = await _anmelden(geraet, konto["org"].slug)
    assert r.status_code == 401


async def test_rueckläufiger_zaehler_verraet_den_klon(konto):
    user, org = konto["user"], konto["org"]
    geraet = Geraet(zaehlt=True)
    await _einrichten(user, org, geraet)
    assert (await _anmelden(geraet, org.slug))[0].status_code == 200
    geraet.zaehler = 0  # der Klon fängt beim alten Stand an
    r, _, _ = await _anmelden(geraet, org.slug)
    assert r.status_code == 401


async def test_einrichten_verlangt_das_passwort(konto):
    user, org = konto["user"], konto["org"]
    async with _client() as c:
        r = await c.post(
            "/api/auth/passkeys/register/options", json={"password": "falsch"}, headers=_bearer(user, org)
        )
    assert r.status_code == 400


async def test_registrierung_eines_anderen_laesst_sich_nicht_abschliessen(konto):
    user, fremd, org = konto["user"], konto["fremd"], konto["org"]
    async with _client() as c:
        r = await c.post(
            "/api/auth/passkeys/register/options", json={"password": PASSWORT}, headers=_bearer(user, org)
        )
        data = r.json()
        r = await c.post(
            "/api/auth/passkeys/register",
            json={"challenge_id": data["challenge_id"], "credential": Geraet().erstellen(data["options"])},
            headers=_bearer(fremd, konto["andere"]),
        )
    assert r.status_code == 400


async def test_vorhandene_passkeys_werden_ausgeschlossen(konto):
    user, org = konto["user"], konto["org"]
    geraet = Geraet()
    await _einrichten(user, org, geraet)
    async with _client() as c:
        r = await c.post(
            "/api/auth/passkeys/register/options", json={"password": PASSWORT}, headers=_bearer(user, org)
        )
    ausgeschlossen = [e["id"] for e in r.json()["options"]["excludeCredentials"]]
    assert ausgeschlossen == [_b64(geraet.credential_id)]
    assert r.json()["options"]["authenticatorSelection"]["userVerification"] == "required"
    assert r.json()["options"]["authenticatorSelection"]["residentKey"] == "required"


async def test_auflisten_und_loeschen_nur_eigene(konto):
    user, fremd, org = konto["user"], konto["fremd"], konto["org"]
    geraet = Geraet()
    angelegt = (await _einrichten(user, org, geraet))["body"]

    async with _client() as c:
        liste = await c.get("/api/auth/passkeys", headers=_bearer(user, org))
        assert [p["id"] for p in liste.json()] == [angelegt["id"]]
        # Keine Schlüsseldaten in der Liste.
        assert set(liste.json()[0]) == {"id", "name", "created_at", "last_used_at", "backed_up"}

        assert (await c.get("/api/auth/passkeys", headers=_bearer(fremd, konto["andere"]))).json() == []
        fremd_loeschen = await c.delete(f"/api/auth/passkeys/{angelegt['id']}", headers=_bearer(fremd, konto["andere"]))
        assert fremd_loeschen.status_code == 404

        assert (await c.delete(f"/api/auth/passkeys/{angelegt['id']}", headers=_bearer(user, org))).status_code == 204

    r, _, _ = await _anmelden(geraet, org.slug)
    assert r.status_code == 401


async def test_auskunft_nennt_passkeys_ohne_schluessel(konto):
    """Art. 15: welche Passkeys es gibt, steht in der Auskunft — Kennung und
    öffentlicher Schlüssel nicht."""
    user, fremd, org = konto["user"], konto["fremd"], konto["org"]
    await _einrichten(user, org, Geraet())
    async with AsyncSessionLocal() as db:
        (await db.get(User, fremd.id)).is_superadmin = True
        await db.commit()
    token = create_token(str(fremd.id), True, token_version=fremd.token_version)
    async with _client() as c:
        r = await c.get(f"/api/admin/users/{user.id}/export", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    eintraege = r.json()["passkeys"]
    assert len(eintraege) == 1
    assert set(eintraege[0]) == {"id", "name", "backed_up", "created_at", "last_used_at"}
