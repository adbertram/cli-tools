"""Host queue pause / recovery tests with fake clock."""

from bricklink_cli.buy.classify import (
    BrickLinkThrottleError,
    ClassifiedResponse,
    ResponseClass,
)
from bricklink_cli.buy.host_queue import HostQueueConfig, HostRequestQueue


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _throttle():
    raise BrickLinkThrottleError(
        ClassifiedResponse(ResponseClass.THROTTLE, 403, detail="empty 403")
    )


def test_queue_retries_throttle_then_succeeds():
    clock = FakeClock()
    q = HostRequestQueue(
        config=HostQueueConfig(
            throttle_base_delay=10.0,
            throttle_max_delay=100.0,
            jitter=0.0,
            recovery_burst_count=2,
            recovery_spacing_seconds=1.0,
        ),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            _throttle()
        return "ok"

    assert q.submit(fn) == "ok"
    assert calls["n"] == 3
    assert clock.sleeps[0] == 10.0
    assert clock.sleeps[1] == 20.0


def test_recovery_burst_spaces_requests():
    clock = FakeClock()
    q = HostRequestQueue(
        config=HostQueueConfig(
            throttle_base_delay=5.0,
            throttle_max_delay=5.0,
            jitter=0.0,
            recovery_burst_count=2,
            recovery_spacing_seconds=1.0,
        ),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] == 1:
            _throttle()
        return state["n"]

    assert q.submit(flaky) == 2
    assert q.submit(lambda: "a") == "a"
    assert q.submit(lambda: "b") == "b"
    assert any(abs(s - 1.0) < 1e-6 for s in clock.sleeps[1:])
