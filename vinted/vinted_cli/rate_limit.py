"""Request pacing and backoff for every Vinted request.

Vinted answers HTTP 429 when requests arrive too fast, so the client sends
nothing without asking this limiter first. The limiter holds one interval for
the whole session. Vinted pushback widens the interval, and a run of clean
answers narrows it back to the floor, so a throttled session slows down and a
recovered one speeds up again without a restart.

The backoff delay comes from the shared ``RequestsRetryPolicy``. Its
``calculate_delay`` is transport independent (exponential growth, bounded
jitter, a ``Retry-After`` value wins), so the math lives in one place even
though Vinted runs its requests through a browser page.
"""

import time
from typing import Callable, Optional

from cli_tools_shared.http_session import RequestsRetryPolicy

# The floor is the fastest pace confirmed safe against live item pages. Faster
# reads made Vinted answer HTTP 429.
MIN_REQUEST_INTERVAL = 0.9

# The ceiling bounds how slow one session can get after repeated pushback.
MAX_REQUEST_INTERVAL = 30.0

# Vinted pushback doubles the interval. A clean run halves it.
INTERVAL_GROWTH = 2.0
INTERVAL_DECAY = 0.5
RECOVERY_REQUESTS = 5

# Statuses that mean "you are sending too fast", not "this request is wrong".
THROTTLED_STATUS_CODES = frozenset({429, 503})

MAX_RETRIES = 4

# Backoff is slower than a generic API retry, because a throttled Cloudflare
# origin needs real time rather than a fast second try.
BACKOFF_POLICY = RequestsRetryPolicy(
    max_retries=MAX_RETRIES,
    base_delay=2.0,
    max_delay=60.0,
    jitter=0.2,
)


def parse_retry_after(value) -> Optional[float]:
    """Return the ``Retry-After`` header as seconds.

    Vinted sends a number of seconds. The header also allows an HTTP date,
    which this returns as None so the exponential backoff decides the delay.
    """
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


class RateLimiter:
    """Paces every request and backs off when Vinted pushes back."""

    def __init__(
        self,
        min_interval: float = MIN_REQUEST_INTERVAL,
        max_interval: float = MAX_REQUEST_INTERVAL,
        policy: RequestsRetryPolicy = BACKOFF_POLICY,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.interval = min_interval
        self.max_retries = policy.max_retries
        self._policy = policy
        self._sleep = sleep
        self._clock = clock
        self._next_allowed_at: Optional[float] = None
        self._clean_requests = 0

    def acquire(self) -> float:
        """Block until the next request is allowed. Return the seconds waited.

        The first request of a session goes out with no wait.
        """
        waited = 0.0
        if self._next_allowed_at is not None:
            waited = self._next_allowed_at - self._clock()
            if waited > 0:
                self._sleep(waited)
            else:
                waited = 0.0
        self._next_allowed_at = self._clock() + self.interval
        return waited

    def on_answered(self) -> None:
        """Record a request that Vinted answered without pushback.

        The interval narrows one step after a run of clean requests, so one
        burst of throttling does not slow the rest of the session forever.
        """
        if self.interval <= self.min_interval:
            return
        self._clean_requests += 1
        if self._clean_requests < RECOVERY_REQUESTS:
            return
        self._clean_requests = 0
        self.interval = max(self.min_interval, self.interval * INTERVAL_DECAY)

    def on_throttled(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Widen the interval, wait out the backoff, and return the delay used."""
        self._clean_requests = 0
        self.interval = min(self.max_interval, self.interval * INTERVAL_GROWTH)
        delay = self._policy.calculate_delay(attempt, retry_after)
        self._sleep(delay)
        self._next_allowed_at = self._clock() + self.interval
        return delay
