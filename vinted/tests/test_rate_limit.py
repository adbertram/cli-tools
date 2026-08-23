"""Rate limiter tests. No test sleeps; the clock and the sleep are injected."""

import pytest
from cli_tools_shared.http_session import RequestsRetryPolicy

from vinted_cli.rate_limit import (
    MAX_REQUEST_INTERVAL,
    MIN_REQUEST_INTERVAL,
    RECOVERY_REQUESTS,
    THROTTLED_STATUS_CODES,
    RateLimiter,
    parse_retry_after,
)

# No jitter, so a test asserts an exact delay.
_POLICY = RequestsRetryPolicy(max_retries=4, base_delay=2.0, max_delay=60.0, jitter=0.0)


class _Clock:
    """A clock that only moves when a sleep moves it."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def __call__(self):
        return self.now


def _limiter(**kwargs):
    clock = _Clock()
    kwargs.setdefault("policy", _POLICY)
    return RateLimiter(sleep=clock.sleep, clock=clock, **kwargs), clock


# --- pacing ----------------------------------------------------------------

def test_the_first_request_of_a_session_waits_for_nothing():
    limiter, clock = _limiter()

    assert limiter.acquire() == 0.0
    assert clock.slept == []


def test_the_second_request_waits_out_the_interval():
    limiter, clock = _limiter()
    limiter.acquire()

    assert limiter.acquire() == pytest.approx(MIN_REQUEST_INTERVAL)
    assert clock.slept == [pytest.approx(MIN_REQUEST_INTERVAL)]


def test_a_caller_that_took_longer_than_the_interval_waits_for_nothing():
    limiter, clock = _limiter()
    limiter.acquire()
    clock.now += MIN_REQUEST_INTERVAL * 3  # the request itself took this long

    assert limiter.acquire() == 0.0
    assert clock.slept == []


# --- backoff ---------------------------------------------------------------

def test_pushback_doubles_the_interval_and_sleeps_the_backoff():
    limiter, clock = _limiter()

    assert limiter.on_throttled(0) == pytest.approx(2.0)
    assert limiter.interval == pytest.approx(MIN_REQUEST_INTERVAL * 2)
    assert clock.slept == [pytest.approx(2.0)]


def test_each_retry_backs_off_further():
    limiter, clock = _limiter()
    for attempt in range(3):
        limiter.on_throttled(attempt)

    assert clock.slept == [pytest.approx(2.0), pytest.approx(4.0), pytest.approx(8.0)]


def test_a_server_retry_after_value_wins_over_the_exponential_delay():
    limiter, clock = _limiter()

    assert limiter.on_throttled(3, retry_after=5.0) == pytest.approx(5.0)
    assert clock.slept == [pytest.approx(5.0)]


def test_the_interval_stops_growing_at_the_ceiling():
    limiter, _ = _limiter()
    for attempt in range(20):
        limiter.on_throttled(attempt)

    assert limiter.interval == pytest.approx(MAX_REQUEST_INTERVAL)


def test_a_widened_interval_paces_the_next_request():
    limiter, clock = _limiter()
    limiter.on_throttled(0)
    clock.slept.clear()

    assert limiter.acquire() == pytest.approx(MIN_REQUEST_INTERVAL * 2)


# --- recovery --------------------------------------------------------------

def test_a_run_of_clean_requests_narrows_the_interval_again():
    limiter, _ = _limiter()
    limiter.on_throttled(0)
    widened = limiter.interval

    for _ in range(RECOVERY_REQUESTS - 1):
        limiter.on_answered()
    assert limiter.interval == pytest.approx(widened)

    limiter.on_answered()
    assert limiter.interval == pytest.approx(MIN_REQUEST_INTERVAL)


def test_recovery_never_goes_below_the_floor():
    limiter, _ = _limiter()
    for _ in range(RECOVERY_REQUESTS * 4):
        limiter.on_answered()

    assert limiter.interval == pytest.approx(MIN_REQUEST_INTERVAL)


def test_fresh_pushback_restarts_the_recovery_count():
    limiter, _ = _limiter()
    limiter.on_throttled(0)
    limiter.on_throttled(1)
    widened = limiter.interval

    for _ in range(RECOVERY_REQUESTS - 1):
        limiter.on_answered()
    limiter.on_throttled(2)
    for _ in range(RECOVERY_REQUESTS - 1):
        limiter.on_answered()

    # The count restarted, so the interval is still above where it recovered.
    assert limiter.interval > widened


# --- Retry-After parsing ---------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        ("7", 7.0),
        ("0", 0.0),
        ("2.5", 2.5),
        (None, None),
        ("", None),
        ("-1", None),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
    ],
)
def test_parse_retry_after(value, expected):
    assert parse_retry_after(value) == expected


# --- policy ----------------------------------------------------------------

def test_both_throttling_statuses_are_recognized():
    assert THROTTLED_STATUS_CODES == frozenset({429, 503})
