"""Throttling for failed logins.

`/login` is the one endpoint an unauthenticated caller may POST to, so it is the one
that needs a limit before the app goes on a public address. The limit counts
*failures*: a correct password clears the caller's record, so normal use never meets
it, and a password guesser meets it after `login_max_attempts` tries.

**Kept in memory, deliberately.** The app runs as a single task with an in-process
scheduler, so there is nothing to share state with; a Redis for five counters would
be more moving parts than the thing it protects. The cost is that a restart forgets
the counters, which is acceptable against guessing a scrypt-hashed password.

**Keyed on the client address as the server sees it.** Behind CloudFront and API
Gateway that is only the real caller when uvicorn runs with `--proxy-headers` (and
`--forwarded-allow-ips` naming the proxy), which rewrites the client from
`X-Forwarded-For`. Without it every request arrives from the proxy's address and one
guesser would lock out everyone -- so the deployment must set it, and the fallback is
still safer than no limit at all.
"""
import math
import time
from collections import OrderedDict, deque
from typing import Callable, Deque, Optional


class LoginThrottle:
    """A sliding window of failed attempts per client address."""

    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        max_clients: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._clock = clock
        # Ordered so the oldest client can be dropped when the map is full: a stream
        # of addresses must not grow this without bound.
        self._failures: "OrderedDict[str, Deque[float]]" = OrderedDict()

    def _recent(self, client: str) -> Deque[float]:
        attempts = self._failures.get(client)
        if attempts is None:
            return deque()
        cutoff = self._clock() - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            self._failures.pop(client, None)
        return attempts

    def retry_after(self, client: str) -> Optional[int]:
        """Seconds until this client may try again, or None if it may try now."""
        if self.max_attempts <= 0:
            return None
        attempts = self._recent(client)
        if len(attempts) < self.max_attempts:
            return None
        return max(1, math.ceil(attempts[0] + self.window_seconds - self._clock()))

    def record_failure(self, client: str) -> None:
        attempts = self._recent(client)
        attempts.append(self._clock())
        self._failures[client] = attempts
        self._failures.move_to_end(client)
        while len(self._failures) > self.max_clients:
            self._failures.popitem(last=False)

    def clear(self, client: str) -> None:
        """Forget a client's failures, which a correct password does."""
        self._failures.pop(client, None)


_throttle: Optional[LoginThrottle] = None


def get_login_throttle(settings) -> LoginThrottle:
    """The process-wide throttle, rebuilt when the configured limits change."""
    global _throttle
    if (
        _throttle is None
        or _throttle.max_attempts != settings.login_max_attempts
        or _throttle.window_seconds != settings.login_window_seconds
    ):
        _throttle = LoginThrottle(settings.login_max_attempts, settings.login_window_seconds)
    return _throttle


def reset_login_throttle() -> None:
    """Drop the throttle, so one test's failures cannot reach another's."""
    global _throttle
    _throttle = None


def client_address(request) -> str:
    return request.client.host if request.client else "unknown"
