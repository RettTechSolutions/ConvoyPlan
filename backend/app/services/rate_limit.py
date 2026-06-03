"""Lightweight in-process rate limiting for authentication endpoints.

Counts *failed* attempts per (bucket, client-IP) in a sliding window and
blocks further attempts once the threshold is exceeded — a first-line
brute-force defence (ISO 27001 A.8.5).

Limitations (documented, follow-ups tracked in the ISO gap analysis):
  - In-memory only: state is per-process and resets on restart. For a
    multi-replica deployment a shared store (Redis) would be required.
  - Keyed by IP, so users behind the same NAT share a bucket. Only failed
    attempts are counted, so normal logins are never penalised.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import settings
from app.services.audit import client_ip

_failures: dict[str, deque[float]] = defaultdict(deque)


def _prune(dq: "deque[float]", cutoff: float) -> None:
    while dq and dq[0] < cutoff:
        dq.popleft()


def rate_limit(
    bucket: str,
    max_attempts: int,
    window_seconds: int,
    count_attempts: bool = False,
):
    """FastAPI dependency that rejects with 429 when the window is exhausted.

    Two modes:
      - failure-driven (default): only attempts recorded via `register_failure`
        count toward the limit — successful logins never penalise the bucket.
      - attempt-driven (`count_attempts=True`): every request counts. Use for
        endpoints that always return success (e.g. password reset) where there
        is no failure signal to hook into.
    """

    async def _dependency(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        key = f"{bucket}:{client_ip(request) or 'unknown'}"
        now = time.monotonic()
        dq = _failures[key]
        _prune(dq, now - window_seconds)
        if len(dq) >= max_attempts:
            retry_after = int(window_seconds - (now - dq[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Zu viele Anfragen. Bitte später erneut versuchen.",
                headers={"Retry-After": str(max(retry_after, 1))},
            )
        if count_attempts:
            dq.append(now)

    return _dependency


def register_failure(request: Request, bucket: str) -> None:
    """Record a failed attempt so subsequent requests count toward the limit."""
    if not settings.rate_limit_enabled:
        return
    key = f"{bucket}:{client_ip(request) or 'unknown'}"
    _failures[key].append(time.monotonic())


def reset() -> None:
    """Clear all counters (used by tests)."""
    _failures.clear()
