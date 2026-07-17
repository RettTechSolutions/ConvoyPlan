"""Vor-/Nachname: Schema-Normalisierung und Anzeigename."""
import pytest
from pydantic import ValidationError

from app.models.user import User
from app.schemas.user import AdminUserCreate, AdminUserUpdate, InviteUserRequest


def test_admin_create_names_are_trimmed():
    data = AdminUserCreate(email="a@b.de", password="x", first_name="  Max ", last_name=" Mustermann  ")
    assert data.first_name == "Max"
    assert data.last_name == "Mustermann"


def test_admin_create_empty_names_become_none():
    data = AdminUserCreate(email="a@b.de", password="x", first_name="   ", last_name="")
    assert data.first_name is None
    assert data.last_name is None


def test_admin_create_names_default_to_none():
    data = AdminUserCreate(email="a@b.de", password="x")
    assert data.first_name is None
    assert data.last_name is None


def test_name_too_long_rejected():
    with pytest.raises(ValidationError):
        AdminUserCreate(email="a@b.de", password="x", first_name="x" * 101)


def test_admin_create_password_optional():
    # Password is optional now — the backend generates one when omitted.
    data = AdminUserCreate(email="a@b.de")
    assert data.password is None


def test_admin_create_org_fields():
    import uuid
    oid = uuid.uuid4()
    data = AdminUserCreate(email="a@b.de", org_id=oid, org_role="planer")
    assert data.org_id == oid
    assert data.org_role == "planer"
    # Default role when only an org is given.
    assert AdminUserCreate(email="a@b.de", org_id=oid).org_role == "beobachter"


def test_update_distinguishes_omitted_from_cleared():
    # Omitted → not in fields_set → PATCH keeps the stored value.
    patch = AdminUserUpdate(is_active=True)
    assert "first_name" not in patch.model_fields_set
    # Empty string → normalized to None but explicitly set → PATCH clears it.
    patch = AdminUserUpdate(first_name="")
    assert "first_name" in patch.model_fields_set
    assert patch.first_name is None


def test_invite_request_accepts_names():
    data = InviteUserRequest(email="a@b.de", password="x", first_name="Erika", last_name="Musterfrau")
    assert data.first_name == "Erika"
    assert data.last_name == "Musterfrau"


def test_full_name_combinations():
    assert User(first_name="Max", last_name="Mustermann").full_name == "Max Mustermann"
    assert User(first_name="Max", last_name=None).full_name == "Max"
    assert User(first_name=None, last_name="Mustermann").full_name == "Mustermann"
    assert User(first_name=None, last_name=None).full_name == ""
