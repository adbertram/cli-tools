"""Host-wide BrickLink.com request queue (concurrency 1) with throttle recovery."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, TypeVar

from .classify import BrickLinkThrottleError

T = TypeVar("T")


@dataclass
class HostQueueConfig:
    recovery_burst_count: int = 10
    recovery_spacing_seconds: float = 1.0
    throttle_base_delay: float = 120.0
    throttle_max_delay: float = 30 * 60.0
    transient_base_delay: float = 1.0
    transient_max_delay: float = 60.0
    jitter: float = 0.2


@dataclass
class HostRequestQueue:
    name: str = "www.bricklink.com"
    config: HostQueueConfig = field(default_factory=HostQueueConfig)
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    rng: random.Random = field(default_factory=random.Random)

    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _cooldown_remaining: int = field(default=0, init=False, repr=False)
    _last_request_at: float = field(default=0.0, init=False, repr=False)
    _throttle_attempt: int = field(default=0, init=False, repr=False)
    paused_reason: Optional[str] = field(default=None, init=False)

    def submit(self, fn: Callable[[], T]) -> T:
        with self._lock:
            attempt = 0
            while True:
                self._wait_for_slot()
                self.paused_reason = None
                try:
                    result = fn()
                except BrickLinkThrottleError as exc:
                    self.paused_reason = str(exc)
                    self.sleep(self._throttle_delay(self._throttle_attempt))
                    self._throttle_attempt += 1
                    attempt += 1
                    continue
                except (TimeoutError, ConnectionError, OSError) as exc:
                    self.paused_reason = f"transient: {exc}"
                    self.sleep(self._transient_delay(attempt))
                    attempt += 1
                    continue

                if self._throttle_attempt > 0:
                    self._cooldown_remaining = self.config.recovery_burst_count
                self._throttle_attempt = 0
                self._last_request_at = self.monotonic()
                if self._cooldown_remaining > 0:
                    self._cooldown_remaining -= 1
                return result

    def _wait_for_slot(self) -> None:
        if self._cooldown_remaining <= 0:
            return
        elapsed = self.monotonic() - self._last_request_at
        remaining = self.config.recovery_spacing_seconds - elapsed
        if remaining > 0:
            self.sleep(remaining)

    def _throttle_delay(self, attempt: int) -> float:
        delay = min(
            self.config.throttle_base_delay * (2 ** attempt),
            self.config.throttle_max_delay,
        )
        return self._jitter(delay)

    def _transient_delay(self, attempt: int) -> float:
        delay = min(
            self.config.transient_base_delay * (2 ** attempt),
            self.config.transient_max_delay,
        )
        return self._jitter(delay)

    def _jitter(self, delay: float) -> float:
        span = delay * self.config.jitter
        return max(0.0, delay + self.rng.uniform(-span, span))


_BRICKLINK_QUEUE: Optional[HostRequestQueue] = None
_QUEUE_LOCK = threading.Lock()


def get_bricklink_queue() -> HostRequestQueue:
    global _BRICKLINK_QUEUE
    with _QUEUE_LOCK:
        if _BRICKLINK_QUEUE is None:
            _BRICKLINK_QUEUE = HostRequestQueue()
        return _BRICKLINK_QUEUE


def reset_bricklink_queue_for_tests(
    queue: HostRequestQueue | None = None,
) -> HostRequestQueue:
    global _BRICKLINK_QUEUE
    with _QUEUE_LOCK:
        _BRICKLINK_QUEUE = queue if queue is not None else HostRequestQueue()
        return _BRICKLINK_QUEUE
