"""Delivery of notifications to an external transport.

A Notification row is the record and the UI's data source; a transport is how that
record reaches the user. Delivery is therefore a side effect of creating the row and
must never be able to lose it -- a transport that fails logs and returns False, and
the row stands regardless.
"""
import logging
from typing import Optional, Protocol

import aiohttp

from src.config import Settings

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    """Somewhere a notification can be delivered."""

    name: str

    async def send(self, title: str, message: str, url: Optional[str] = None) -> bool:
        """Deliver one notification. Returns whether it was accepted."""
        ...


class NullNotifier:
    """Records nothing anywhere. The default, so the app runs with no config."""

    name = "none"

    async def send(self, title: str, message: str, url: Optional[str] = None) -> bool:
        logger.debug("Notification delivery disabled; not sending %r", title)
        return False


class NtfyNotifier:
    """Publish to an ntfy topic (https://ntfy.sh or a self-hosted server).

    A notification is a plain HTTP POST: the body is the message and the title and
    optional click-through URL travel as headers.
    """

    name = "ntfy"

    def __init__(self, topic: str, server: str = "https://ntfy.sh", timeout: int = 10):
        self.topic = topic
        self.server = server.rstrip("/")
        self.timeout = timeout

    @property
    def endpoint(self) -> str:
        return f"{self.server}/{self.topic}"

    def _headers(self, title: str, url: Optional[str]) -> dict:
        # Headers must be latin-1 encodable. Product names carry the odd dash or
        # accent, so anything outside it is replaced rather than raising.
        headers = {
            "Title": title.encode("latin-1", "replace").decode("latin-1"),
            "Tags": "arrow_up",
        }
        if url:
            headers["Click"] = url
        return headers

    async def send(self, title: str, message: str, url: Optional[str] = None) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.endpoint,
                    data=message.encode("utf-8"),
                    headers=self._headers(title, url),
                ) as response:
                    if response.status >= 400:
                        logger.warning(
                            "ntfy rejected notification %r with status %s",
                            title,
                            response.status,
                        )
                        return False
                    return True
        except Exception as exc:
            # Never propagate: the Notification row matters more than its delivery.
            logger.warning("Could not deliver notification %r via ntfy: %s", title, exc)
            return False


def get_notifier(settings: Settings) -> Notifier:
    """Build the notifier named by configuration.

    An unknown transport, or ntfy without a topic, falls back to NullNotifier with a
    warning rather than failing startup -- a misconfigured notifier should not stop
    the tracker from tracking.
    """
    transport = (settings.notify_transport or "none").strip().lower()

    if transport in ("", "none"):
        return NullNotifier()

    if transport == "ntfy":
        if not settings.ntfy_topic:
            logger.warning("NOTIFY_TRANSPORT=ntfy but NTFY_TOPIC is unset; disabling delivery")
            return NullNotifier()
        return NtfyNotifier(topic=settings.ntfy_topic, server=settings.ntfy_server)

    logger.warning("Unknown NOTIFY_TRANSPORT %r; disabling delivery", transport)
    return NullNotifier()
