"""Per-caller throttles for endpoints that spend a metered upstream quota.

`POST /api/auth/demo-session` hands out a working session to anyone who asks
(that is by design — it is the public demo). Creating those sessions is already
rate-limited per IP, but the *session itself* was not: one demo token could
drive an unbounded number of calls to the endpoints that spend real budget —
HERE/TomTom traffic flow, HERE geocoding — or CPU on the self-hosted
GraphHopper. Draining the map/traffic quota of the whole instance therefore
cost an attacker a single request.

These dependencies put a sliding-window budget on those endpoints:

  - keyed by the authenticated user, so one caller cannot spend everyone's
    quota, and legitimate users behind a shared NAT do not share a bucket;
  - additionally keyed by client IP for demo sessions, so cycling through fresh
    demo sessions from one address does not reset the budget;
  - demo sessions get a much smaller budget than licensed users (see the
    QUOTA_* settings), because their credentials are free to obtain.

Like `app.services.rate_limit`, the counters are in-process: state is per worker
and resets on restart. That is a deliberate first-line defence, not a billing
control — a shared store (Redis) would be needed for hard multi-replica limits.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, Request

from app.api.deps import TokenData, get_token_data
from app.config import settings
from app.services.audit import client_ip
from app.services.rate_limit import check, too_many_requests

_WINDOW_SECONDS = 3600


def quota_limit(bucket: str, *, limit: Callable[[bool], int]):
    """FastAPI dependency rejecting with 429 once the hourly budget is spent.

    `bucket` namespaces the counter, so a caller exhausting their geocoding
    budget can still calculate a route. `limit` maps "is this a demo session?"
    to the applicable budget and is evaluated per request, so the settings stay
    overridable at runtime. Requires an authenticated caller — every endpoint
    this guards already does.
    """

    async def _dependency(
        request: Request,
        token_data: TokenData = Depends(get_token_data),
    ) -> None:
        if not settings.rate_limit_enabled:
            return

        max_requests = limit(token_data.is_demo)
        if max_requests <= 0:  # 0/negative disables the throttle for that class
            return

        keys = [f"quota:{bucket}:u:{token_data.user_id}"]
        if token_data.is_demo:
            # Demo users are ephemeral — a per-user budget alone would reset with
            # every new session, so pin demo traffic to its origin as well.
            keys.append(f"quota:{bucket}:demo-ip:{client_ip(request) or 'unknown'}")

        # Check every key before recording, so a request rejected on the second
        # key does not consume budget on the first.
        for key in keys:
            retry_after = check(key, max_requests, _WINDOW_SECONDS, record=False)
            if retry_after is not None:
                raise too_many_requests(retry_after)
        for key in keys:
            check(key, max_requests, _WINDOW_SECONDS, record=True)

    return _dependency


# Route calculation — GraphHopper is self-hosted, so the cost is CPU and graph
# memory rather than a paid quota.
routing_quota = quota_limit(
    "routing",
    limit=lambda is_demo: (
        settings.quota_routing_demo_per_hour if is_demo else settings.quota_routing_per_hour
    ),
)

# Address search — billed per request by HERE (the keyless Photon fallback is a
# courtesy service that should not be hammered either).
geocode_quota = quota_limit(
    "geocode",
    limit=lambda is_demo: (
        settings.quota_geocode_demo_per_hour if is_demo else settings.quota_geocode_per_hour
    ),
)

# Live traffic flow — billed per request by HERE / TomTom.
traffic_quota = quota_limit(
    "traffic",
    limit=lambda is_demo: (
        settings.quota_traffic_demo_per_hour if is_demo else settings.quota_traffic_per_hour
    ),
)
