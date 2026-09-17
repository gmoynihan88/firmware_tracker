"""Keep the scrapers on the public internet, and their responses a sane size.

Scrapers follow links they find on vendor pages. Eventide takes absolute URLs from
its downloads index as they come, and Korg's `urljoin` lets an absolute href replace
the host. On a laptop the worst a hostile link reaches is the laptop. In a container
on ECS it reaches the task's credential endpoint at 169.254.170.2, and whatever that
returns is parsed like any vendor page -- which can put it in a field the web UI
displays.

Checking a URL before fetching it is not enough, which is why the checks sit where
they do:

- **An address is checked where the connection is made.** A hostname checked first
  and connected to second can resolve differently the second time (DNS rebinding).
  `GuardedResolver` sits inside aiohttp's connector, so the addresses it approves are
  the ones connected to, redirects included.
- **aiohttp skips the resolver for a literal IP**, so `http://169.254.170.2/` never
  reaches `GuardedResolver` at all. `refuse_literal_addresses` covers it, as a client
  middleware because aiohttp runs middlewares once per redirect hop. A trace signal
  looks equivalent and is not: `on_request_start` fires once, before the redirect
  loop, so it sees the URL a scraper asked for and never the `Location` it was sent
  to.

Rendered pages are checked per *intercepted* request by `url_allowed`, because a page's
own scripts decide what Chromium loads and Playwright offers no resolver hook. Two
things that wording used to gloss over, both of which matter:

- **A redirect Chromium follows is not an intercepted request.** The route handler
  fires for the URL a navigation starts at and never for the `Location` it is sent to,
  so a vendor answering 302 into the network had the target fetched and rendered with
  nothing consulted. `BaseScraper._navigation_chain_allowed` walks the navigation's own
  redirect chain afterwards and throws the body away if any hop was non-public -- the
  request is already gone by then, so what is protected is the data, not the fetch.
- **The rebinding window is per host, for the life of the scraper.** `url_allowed`
  caches a verdict per host in `verdicts`, so a name that answers public once is not
  looked at again for the rest of the run.

Egress rules on the network are what close both; this module is the application's part.

The size cap lives here because it is the same concern from the other side: a
response body is also input the vendor controls.
"""
import asyncio
import codecs
import ipaddress
import socket
from typing import Dict, List, Optional
from urllib.parse import urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver


class BlockedDestination(aiohttp.ClientConnectionError):
    """A fetch that would have reached a non-public address."""


class ResponseTooLarge(aiohttp.ClientPayloadError):
    """A response body over the configured cap."""


def is_public_address(address: str) -> bool:
    """True only for an address on the public internet.

    Loopback, the private ranges, link-local (where cloud metadata lives),
    carrier-grade NAT, multicast and unspecified addresses are all refused. An IPv4
    address mapped into IPv6 -- `::ffff:127.0.0.1` -- is judged as the IPv4 address it
    is, or loopback could walk in wearing IPv6.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def address_allowed(address: str) -> bool:
    """The policy every check calls. Tests replace it to reach a local server."""
    return is_public_address(address)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]").split("%", 1)[0])
    except ValueError:
        return False
    return True


class GuardedResolver(AbstractResolver):
    """aiohttp's resolver, refusing any name that resolves inside the network."""

    def __init__(self, inner: Optional[AbstractResolver] = None):
        self._inner = inner if inner is not None else DefaultResolver()

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ):
        results = await self._inner.resolve(host, port, family)
        refused = [result["host"] for result in results if not address_allowed(result["host"])]
        if refused:
            # The name is refused outright rather than filtered down to its public
            # answers: a name with any answer inside the network is not a vendor page.
            raise BlockedDestination(
                f"{host} resolves to a non-public address ({', '.join(refused)})"
            )
        return results

    async def close(self) -> None:
        await self._inner.close()


async def refuse_literal_addresses(request: aiohttp.ClientRequest, handler):
    """Client middleware: refuse a non-public IP literal on every hop of a request.

    This was first written as an `on_request_start` trace, which passed every test
    but one. `test_fetch_page_refuses_a_redirect_into_the_network` showed the trace
    fires once per request, outside aiohttp's redirect loop: a page redirecting to
    169.254.170.2 went straight to a connection attempt that only the timeout
    stopped. Middlewares are applied inside the loop, so each hop is checked before
    it connects.
    """
    host = request.url.host or ""
    if _is_ip_literal(host) and not address_allowed(host.strip("[]")):
        raise BlockedDestination(f"{request.url} is a non-public address")
    return await handler(request)


async def _resolve(host: str) -> List[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def url_allowed(url: str, verdicts: Dict[str, bool]) -> bool:
    """Whether a rendered page may load `url`. `verdicts` caches answers per host.

    A name that fails to resolve is refused: Chromium could not load it either, and
    a lookup that fails here and succeeds there is exactly the case to refuse.
    """
    parts = urlsplit(url)
    if parts.scheme in ("data", "blob", "about"):
        return True  # never leaves the browser
    if parts.scheme not in ("http", "https", "ws", "wss"):
        return False
    host = parts.hostname
    if not host:
        return False
    if host in verdicts:
        return verdicts[host]

    if _is_ip_literal(host):
        verdict = address_allowed(host)
    else:
        try:
            addresses = await _resolve(host)
        except OSError:
            addresses = []
        verdict = bool(addresses) and all(address_allowed(a) for a in addresses)

    verdicts[host] = verdict
    return verdict


def _text_encoding(response: aiohttp.ClientResponse) -> str:
    """The codec `response.text()` would pick, without needing the body read first.

    aiohttp's own `get_encoding()` raises until it has buffered the body itself, and
    buffering it is exactly what the cap exists to avoid. So this mirrors it: a valid
    `charset` from Content-Type wins, and anything else -- no charset, an unknown one,
    JSON -- falls back to UTF-8, which is what aiohttp's default fallback resolver
    returns. `test_capped_read_decodes_exactly_like_response_text` holds the two
    together.
    """
    charset = response.charset
    if charset:
        try:
            return codecs.lookup(charset).name
        except LookupError:
            pass
    return "utf-8"


async def read_text_capped(response: aiohttp.ClientResponse, limit: int) -> str:
    """The body as text, refusing anything over `limit` bytes.

    Decoded the way `response.text()` decodes -- see `_text_encoding` -- so a page
    that decoded before the cap decodes identically after it. The limit applies to
    the decompressed body, which is what memory pays for: a small gzip can expand to
    gigabytes.
    """
    declared = response.content_length
    if declared is not None and declared > limit:
        raise ResponseTooLarge(
            f"{response.url} declares {declared} bytes, over the {limit}-byte cap"
        )
    body = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        body.extend(chunk)
        if len(body) > limit:
            raise ResponseTooLarge(f"{response.url} exceeded the {limit}-byte cap")
    data = bytes(body)
    try:
        return data.decode(_text_encoding(response))
    except UnicodeDecodeError:
        if response.charset:
            # A declared charset the body does not match is the server's error, and
            # guessing past it could turn a real failure into quiet mojibake.
            raise
        # No charset declared, and not UTF-8: a plain-text file written by a Windows-era
        # tool. REAPER's 1.4MB changelog is Windows-1252, and failing on byte 1,275,402
        # threw away the whole file. cp1252 with replacement never fails, and only the
        # few bytes it cannot map come out as U+FFFD.
        return data.decode("cp1252", errors="replace")
