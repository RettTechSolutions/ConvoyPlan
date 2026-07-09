import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import get_db


def _superadmin():
    user = MagicMock()
    user.is_superadmin = True
    return user


def _make_app_with_superadmin():
    from app.api.deps import require_superadmin
    app.dependency_overrides[require_superadmin] = lambda: _superadmin()
    return app


def _make_app_with_superadmin_and_db():
    from app.api.deps import require_superadmin
    app.dependency_overrides[require_superadmin] = lambda: _superadmin()
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    async def _db_override():
        yield db

    app.dependency_overrides[get_db] = _db_override
    return app


def _mock_github_client(*, latest_tag=None, latest_status=200, commit_sha=None, main_sha=None,
                        compare_status="behind", releases_list=None):
    """Mock httpx.AsyncClient for the update-status endpoint, dispatching by URL:
      - releases/latest                       -> {"tag_name": latest_tag} (status: latest_status) [stable]
      - releases?per_page=…                    -> releases_list (or [])                            [beta]
      - commits/<tag>                          -> {"sha": commit_sha}      (stable/beta tag→sha)
      - compare/<tag>...<sha>                  -> {"status": compare_status} (ancestry check)
      - actions/workflows/nightly-images.yml   -> last successful :nightly build                  [nightly]
    """
    async def _get(url, **kwargs):
        resp = MagicMock()
        if "releases/latest" in url:
            resp.status_code = latest_status
            resp.is_success = 200 <= latest_status < 300
            resp.json.return_value = {"tag_name": latest_tag}
        elif "/releases?" in url:
            # Beta channel: list of releases, newest first.
            resp.status_code = 200
            resp.is_success = True
            resp.json.return_value = releases_list or []
        elif "/compare/" in url:
            resp.status_code = 200
            resp.is_success = True
            resp.json.return_value = {"status": compare_status}
        elif "/commits/" in url:
            resp.status_code = 200
            resp.is_success = True
            resp.json.return_value = {"sha": commit_sha}
        else:  # actions/workflows/nightly-images.yml/runs?…status=success (nightly)
            resp.status_code = 200
            resp.is_success = True
            resp.json.return_value = {
                "workflow_runs": [{"head_sha": main_sha}] if main_sha else []
            }
        return resp

    inner = MagicMock()
    inner.get = AsyncMock(side_effect=_get)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=inner)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_get_update_status_no_status_file():
    # Default channel is "stable": compares against the latest release commit.
    _make_app_with_superadmin_and_db()
    with patch("builtins.open", side_effect=FileNotFoundError), \
         patch("os.makedirs"), \
         patch("app.services.update_check.httpx.AsyncClient",
               return_value=_mock_github_client(latest_tag="v1.0.0", commit_sha="abc1234567890")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["deployed_sha"] is None
    assert data["remote_sha"] == "abc1234"
    assert data["update_available"] is False
    assert data["github_reachable"] is True
    assert data["channel"] == "stable"
    assert data["latest_release"] == "v1.0.0"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_update_available():
    _make_app_with_superadmin_and_db()
    status_content = json.dumps({"deployed_sha": "aaa1111", "deployed_at": "2026-05-18T10:00:00Z"})
    with patch("builtins.open", mock_open(read_data=status_content)), \
         patch("os.makedirs"), \
         patch("app.services.update_check.httpx.AsyncClient",
               return_value=_mock_github_client(latest_tag="v1.1.0", commit_sha="bbb2222abcdef")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["deployed_sha"] == "aaa1111"
    assert data["remote_sha"] == "bbb2222"
    assert data["update_available"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_stable_deployed_ahead_of_release():
    # Instance previously ran on the nightly channel and is now AHEAD of the
    # latest release: no "update available" (that would be a downgrade).
    _make_app_with_superadmin_and_db()
    status_content = json.dumps({"deployed_sha": "fff9999", "deployed_at": "2026-07-07T11:33:49Z"})
    with patch("builtins.open", mock_open(read_data=status_content)), \
         patch("os.makedirs"), \
         patch("app.services.update_check.httpx.AsyncClient",
               return_value=_mock_github_client(latest_tag="v1.0.1", commit_sha="c7694f4abcdef",
                                                compare_status="ahead")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["deployed_sha"] == "fff9999"
    assert data["remote_sha"] == "c7694f4"
    assert data["ahead_of_release"] is True
    assert data["update_available"] is False
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_stable_no_release():
    # Stable channel + repo without any release: not "out of date", just no release.
    _make_app_with_superadmin_and_db()
    with patch("builtins.open", side_effect=FileNotFoundError), \
         patch("os.makedirs"), \
         patch("app.services.update_check.httpx.AsyncClient",
               return_value=_mock_github_client(latest_status=404)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["github_reachable"] is True
    assert data["no_release"] is True
    assert data["remote_sha"] is None
    assert data["update_available"] is False
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_nightly_channel_tracks_main():
    # Nightly channel compares against the commit of the last *successful*
    # :nightly image build — not the tip of main, which moves at merge time
    # while the images only exist once the nightly-images workflow finished.
    _make_app_with_superadmin_and_db()
    status_content = json.dumps({"deployed_sha": "aaa1111", "deployed_at": "2026-05-18T10:00:00Z"})
    with patch("builtins.open", mock_open(read_data=status_content)), \
         patch("os.makedirs"), \
         patch("app.services.update_check.settings.update_channel", "nightly"), \
         patch("app.services.update_check.httpx.AsyncClient",
               return_value=_mock_github_client(main_sha="ccc3333abcdef")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["channel"] == "nightly"
    assert data["remote_sha"] == "ccc3333"
    assert data["update_available"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_nightly_channel_no_successful_build():
    # Nightly channel, but no :nightly build has succeeded yet (e.g. workflow
    # still running right after a merge): no remote_sha, no false "update available".
    _make_app_with_superadmin_and_db()
    status_content = json.dumps({"deployed_sha": "aaa1111", "deployed_at": "2026-05-18T10:00:00Z"})
    with patch("builtins.open", mock_open(read_data=status_content)), \
         patch("os.makedirs"), \
         patch("app.services.update_check.settings.update_channel", "nightly"), \
         patch("app.services.update_check.httpx.AsyncClient",
               return_value=_mock_github_client(main_sha=None)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["channel"] == "nightly"
    assert data["remote_sha"] is None
    assert data["update_available"] is False
    assert data["github_reachable"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_beta_channel_tracks_latest_prerelease():
    # Beta channel tracks the newest GitHub *pre-release* (the first prerelease
    # entry in the /releases list), resolves its tag to a commit SHA and compares.
    _make_app_with_superadmin_and_db()
    status_content = json.dumps({"deployed_sha": "aaa1111", "deployed_at": "2026-05-18T10:00:00Z"})
    releases = [
        {"tag_name": "v2026.2.1-beta.2", "prerelease": True},
        {"tag_name": "v2026.1.1", "prerelease": False},
    ]
    with patch("builtins.open", mock_open(read_data=status_content)), \
         patch("os.makedirs"), \
         patch("app.services.update_check.settings.update_channel", "beta"), \
         patch("app.services.update_check.httpx.AsyncClient",
               return_value=_mock_github_client(releases_list=releases, commit_sha="ddd4444abcdef")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["channel"] == "beta"
    assert data["latest_release"] == "v2026.2.1-beta.2"
    assert data["remote_sha"] == "ddd4444"
    assert data["update_available"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_beta_channel_no_prerelease():
    # Beta channel but the repo has only stable releases (no prerelease yet):
    # reported as "no target", not a false "update available".
    _make_app_with_superadmin_and_db()
    status_content = json.dumps({"deployed_sha": "aaa1111", "deployed_at": "2026-05-18T10:00:00Z"})
    releases = [{"tag_name": "v2026.1.1", "prerelease": False}]
    with patch("builtins.open", mock_open(read_data=status_content)), \
         patch("os.makedirs"), \
         patch("app.services.update_check.settings.update_channel", "beta"), \
         patch("app.services.update_check.httpx.AsyncClient",
               return_value=_mock_github_client(releases_list=releases)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["channel"] == "beta"
    assert data["no_release"] is True
    assert data["remote_sha"] is None
    assert data["update_available"] is False
    assert data["github_reachable"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_github_unreachable():
    _make_app_with_superadmin_and_db()
    import httpx as _httpx
    inner = MagicMock()
    inner.get = AsyncMock(side_effect=_httpx.ConnectError("unreachable"))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=inner)
    ctx.__aexit__ = AsyncMock(return_value=False)
    with patch("builtins.open", side_effect=FileNotFoundError), \
         patch("os.makedirs"), \
         patch("app.services.update_check.httpx.AsyncClient", return_value=ctx):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["github_reachable"] is False
    assert data["remote_sha"] is None
    assert data["update_available"] is False
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_channel_default_env():
    _make_app_with_superadmin_and_db()
    with patch("os.makedirs"), patch("builtins.open", mock_open()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/settings/update-channel")
    assert r.status_code == 200
    data = r.json()
    assert data["channel"] in ("stable", "beta", "nightly")
    assert data["source"] == "env"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_set_update_channel_persists_and_writes_file():
    _make_app_with_superadmin_and_db()
    m = mock_open()
    with patch("os.makedirs"), patch("builtins.open", m), \
         patch("app.api.routes.admin.audit.record", new=AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put("/api/admin/settings/update-channel", json={"channel": "beta"})
    assert r.status_code == 204
    # The effective channel is mirrored to the shared volume for the updater.
    m().write.assert_any_call("beta")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_set_update_channel_accepts_nightly():
    _make_app_with_superadmin_and_db()
    m = mock_open()
    with patch("os.makedirs"), patch("builtins.open", m), \
         patch("app.api.routes.admin.audit.record", new=AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put("/api/admin/settings/update-channel", json={"channel": "nightly"})
    assert r.status_code == 204
    m().write.assert_any_call("nightly")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_set_update_channel_rejects_invalid():
    _make_app_with_superadmin_and_db()
    with patch("os.makedirs"), patch("builtins.open", mock_open()), \
         patch("app.api.routes.admin.audit.record", new=AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put("/api/admin/settings/update-channel", json={"channel": "canary"})
    assert r.status_code == 422
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_update_creates_file():
    _make_app_with_superadmin()
    m = mock_open()
    with patch("builtins.open", m), \
         patch("os.path.exists", return_value=False), \
         patch("os.makedirs"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/admin/trigger-update")
    assert r.status_code == 202
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_update_409_when_already_triggered():
    _make_app_with_superadmin()
    with patch("os.path.exists", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/admin/trigger-update")
    assert r.status_code == 409
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_update_503_when_volume_not_writable():
    # A non-writable /update_status volume (e.g. root-owned, predating the
    # non-root backend) must yield a clear 503 instead of a bare 500.
    _make_app_with_superadmin()
    with patch("os.path.exists", return_value=False), \
         patch("os.makedirs"), \
         patch("builtins.open", side_effect=PermissionError("read-only")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/admin/trigger-update")
    assert r.status_code == 503
    app.dependency_overrides.clear()


# ── Update-Modus (auto / notify) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_update_mode_default_env():
    _make_app_with_superadmin_and_db()
    with patch("os.makedirs"), patch("builtins.open", mock_open()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/settings/update-mode")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "auto"
    assert data["source"] == "env"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_set_update_mode_persists_and_writes_file():
    _make_app_with_superadmin_and_db()
    m = mock_open()
    with patch("os.makedirs"), patch("builtins.open", m), \
         patch("app.api.routes.admin.audit.record", new=AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put("/api/admin/settings/update-mode", json={"mode": "notify"})
    assert r.status_code == 204
    # The effective mode is mirrored to the shared volume for the updater.
    m().write.assert_any_call("notify")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_set_update_mode_rejects_invalid():
    _make_app_with_superadmin_and_db()
    with patch("os.makedirs"), patch("builtins.open", mock_open()), \
         patch("app.api.routes.admin.audit.record", new=AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put("/api/admin/settings/update-mode", json={"mode": "yolo"})
    assert r.status_code == 422
    app.dependency_overrides.clear()


# ── Update-Benachrichtigung (Modus "notify") ──────────────────────────────────


def _notify_db(last_notified=None, superadmin_emails=("admin@example.com",)):
    """Mock AsyncSession for check_and_notify_once: resolve_mode → last-notified
    lookup → superadmin query, in call order."""
    db = AsyncMock()

    mode_result = MagicMock()
    mode_setting = MagicMock()
    mode_setting.value = "notify"
    mode_result.scalar_one_or_none.return_value = mode_setting

    notified_result = MagicMock()
    if last_notified is None:
        notified_result.scalar_one_or_none.return_value = None
    else:
        setting = MagicMock()
        setting.value = last_notified
        notified_result.scalar_one_or_none.return_value = setting

    admins_result = MagicMock()
    users = []
    for mail in superadmin_emails:
        u = MagicMock()
        u.email = mail
        users.append(u)
    admins_result.scalars.return_value.all.return_value = users

    db.execute.side_effect = [mode_result, notified_result, admins_result]
    return db


@pytest.mark.asyncio
async def test_check_and_notify_sends_email_once_per_target():
    from app.services.update_notify import check_and_notify_once

    state = {
        "update_available": True,
        "remote_sha": "bbb2222",
        "channel": "stable",
        "latest_release": "v1.1.0",
        "deployed_sha": "aaa1111",
    }
    send = AsyncMock()
    db = _notify_db()
    with patch("app.services.update_notify.fetch_update_state", new=AsyncMock(return_value=state)), \
         patch("app.services.update_notify.send_update_notification", new=send):
        sent = await check_and_notify_once(db)
    assert sent is True
    send.assert_awaited_once()
    assert send.await_args.args[1] == "admin@example.com"
    # Merker für das Ziel wird gespeichert (genau eine Mail pro Ziel)
    added = db.add.call_args.args[0]
    assert added.key == "update.last_notified_target"
    assert added.value == "stable:bbb2222"


@pytest.mark.asyncio
async def test_check_and_notify_skips_already_notified_target():
    from app.services.update_notify import check_and_notify_once

    state = {
        "update_available": True,
        "remote_sha": "bbb2222",
        "channel": "stable",
        "latest_release": "v1.1.0",
        "deployed_sha": "aaa1111",
    }
    send = AsyncMock()
    db = _notify_db(last_notified="stable:bbb2222")
    with patch("app.services.update_notify.fetch_update_state", new=AsyncMock(return_value=state)), \
         patch("app.services.update_notify.send_update_notification", new=send):
        sent = await check_and_notify_once(db)
    assert sent is False
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_and_notify_noop_when_mode_auto():
    from app.services.update_notify import check_and_notify_once

    db = AsyncMock()
    mode_result = MagicMock()
    mode_result.scalar_one_or_none.return_value = None  # kein DB-Setting → env "auto"
    db.execute.return_value = mode_result
    fetch = AsyncMock()
    with patch("app.services.update_notify.fetch_update_state", new=fetch):
        sent = await check_and_notify_once(db)
    assert sent is False
    fetch.assert_not_awaited()


# ── Benachrichtigung nach automatischer Installation (notify_on_auto) ─────────


def _installed_db(last_installed=None, notify_on_auto="true", superadmin_emails=("admin@example.com",)):
    """Mock AsyncSession for the installed-notification flow, in call order:
    resolve_mode → resolve_notify_on_auto → last-installed lookup → superadmins."""
    db = AsyncMock()

    mode_result = MagicMock()
    mode_result.scalar_one_or_none.return_value = None  # env fallback → "auto"

    flag_result = MagicMock()
    flag_setting = MagicMock()
    flag_setting.value = notify_on_auto
    flag_result.scalar_one_or_none.return_value = flag_setting

    installed_result = MagicMock()
    if last_installed is None:
        installed_result.scalar_one_or_none.return_value = None
    else:
        setting = MagicMock()
        setting.value = last_installed
        installed_result.scalar_one_or_none.return_value = setting

    admins_result = MagicMock()
    users = []
    for mail in superadmin_emails:
        u = MagicMock()
        u.email = mail
        users.append(u)
    admins_result.scalars.return_value.all.return_value = users

    db.execute.side_effect = [mode_result, flag_result, installed_result, admins_result]
    return db


@pytest.mark.asyncio
async def test_notify_on_auto_first_run_records_baseline_without_mail():
    from app.services.update_notify import check_and_notify_once

    send = AsyncMock()
    db = _installed_db(last_installed=None)
    with patch("app.services.update_notify.read_deployed", return_value=("aaa1111", "2026-07-07T11:33:49Z")), \
         patch("app.services.update_notify.send_update_notification", new=send):
        sent = await check_and_notify_once(db)
    assert sent is False
    send.assert_not_awaited()
    # Basislinie wird still vermerkt, damit Altbestand keine Mail auslöst
    added = db.add.call_args.args[0]
    assert added.key == "update.last_installed_notified"
    assert added.value == "aaa1111"


@pytest.mark.asyncio
async def test_notify_on_auto_sends_mail_after_installed_update():
    from app.services.update_notify import check_and_notify_once

    send = AsyncMock()
    db = _installed_db(last_installed="aaa1111")
    with patch("app.services.update_notify.read_deployed", return_value=("bbb2222", "2026-07-07T12:00:00Z")), \
         patch("app.services.update_notify.send_update_notification", new=send):
        sent = await check_and_notify_once(db)
    assert sent is True
    send.assert_awaited_once()
    assert send.await_args.args[1] == "admin@example.com"
    subject = send.await_args.args[2]
    assert "installiert" in subject
    assert "bbb2222" in subject


@pytest.mark.asyncio
async def test_notify_on_auto_skips_unchanged_deployment():
    from app.services.update_notify import check_and_notify_once

    send = AsyncMock()
    db = _installed_db(last_installed="aaa1111")
    with patch("app.services.update_notify.read_deployed", return_value=("aaa1111", "2026-07-07T11:33:49Z")), \
         patch("app.services.update_notify.send_update_notification", new=send):
        sent = await check_and_notify_once(db)
    assert sent is False
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_update_mode_persists_notify_on_auto_flag():
    _make_app_with_superadmin_and_db()
    with patch("os.makedirs"), patch("builtins.open", mock_open()), \
         patch("app.api.routes.admin.audit.record", new=AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put("/api/admin/settings/update-mode",
                                 json={"mode": "auto", "notify_on_auto": True})
    assert r.status_code == 204
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_mode_includes_notify_on_auto():
    _make_app_with_superadmin_and_db()
    with patch("os.makedirs"), patch("builtins.open", mock_open()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/settings/update-mode")
    assert r.status_code == 200
    data = r.json()
    assert data["notify_on_auto"] is False  # env default
    app.dependency_overrides.clear()
