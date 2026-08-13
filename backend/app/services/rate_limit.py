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

# Keys are unbounded in principle — one per client IP, and one per user for the
# quota throttles, which includes every ephemeral demo account ever created. So
# expired keys are swept periodically instead of accumulating for the life of
# the process. The sweep runs off a call counter (no background task) and drops
# any key whose newest entry has aged out of the widest window in use.
_SWEEP_INTERVAL_OPS = 1024
_ops_since_sweep = 0
_widest_window = 0.0


def _prune(dq: "deque[float]", cutoff: float) -> None:
    while dq and dq[0] < cutoff:
        dq.popleft()


def _maybe_sweep(now: float) -> None:
    global _ops_since_sweep
    _ops_since_sweep += 1
    if _ops_since_sweep < _SWEEP_INTERVAL_OPS:
        return
    _ops_since_sweep = 0
    cutoff = now - _widest_window
    # A key whose newest entry predates the cutoff would be pruned to empty on
    # its next lookup, so dropping it now cannot change any decision.
    for key in [k for k, dq in _failures.items() if not dq or dq[-1] < cutoff]:
        del _failures[key]


def check(key: str, max_attempts: int, window_seconds: int, *, record: bool) -> int | None:
    """Sliding-window primitive shared by the auth limiter and the upstream
    quota throttles (`app.api.quota`).

    Returns the number of seconds to wait when `key` has exhausted its window,
    or None when the request may proceed — in which case it is added to the
    window if `record` is set.
    """
    global _widest_window
    _widest_window = max(_widest_window, float(window_seconds))

    now = time.monotonic()
    _maybe_sweep(now)
    dq = _failures[key]
    _prune(dq, now - window_seconds)
    if len(dq) >= max_attempts:
        return max(int(window_seconds - (now - dq[0])) + 1, 1)
    if record:
        dq.append(now)
    elif not dq:
        # Read-only probe on an unseen key: don't let the defaultdict lookup
        # leave an empty entry behind until the next sweep.
        _failures.pop(key, None)
    return None


def too_many_requests(retry_after: int) -> HTTPException:
    """The uniform 429 raised by every limiter in the app."""
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Zu viele Anfragen. Bitte später erneut versuchen.",
        headers={"Retry-After": str(retry_after)},
    )


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
        retry_after = check(key, max_attempts, window_seconds, record=count_attempts)
        if retry_after is not None:
            raise too_many_requests(retry_after)

    return _dependency


def register_failure(request: Request, bucket: str) -> None:
    """Record a failed attempt so subsequent requests count toward the limit."""
    if not settings.rate_limit_enabled:
        return
    key = f"{bucket}:{client_ip(request) or 'unknown'}"
    _failures[key].append(time.monotonic())


def reset() -> None:
    """Clear all counters (used by tests)."""
    global _ops_since_sweep, _widest_window
    _failures.clear()
    _ops_since_sweep = 0
    _widest_window = 0.0
