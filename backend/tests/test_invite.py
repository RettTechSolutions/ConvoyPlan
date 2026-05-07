import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_invite_endpoint_exists():
    # Smoke test — verify endpoint is registered
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # A UUID that doesn't exist — should return 401 (not authenticated), not 404
        resp = await client.post(
            "/api/organizations/00000000-0000-0000-0000-000000000000/members/invite",
            json={"email": "test@example.com", "password": "test123"},
        )
    assert resp.status_code == 401
