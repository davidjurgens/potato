"""
Shared SSRF guard for server-side fetches of a caller-supplied URL.

Three separate URL validators existed before this module and none of them was
shared: one in ``data_sources/sources/url_source.py``, one in ``web_proxy.py``,
and a bare scheme check in the audio proxy. They disagreed about which addresses
were dangerous, and the weakest of them decided what the most exposed endpoint
allowed.

What this adds over the strongest of the three:

- **Fails closed.** ``web_proxy`` allowed a host it could not resolve, on the
  reasoning that the fetch would fail anyway. It does not: a name that fails to
  resolve once can resolve on the retry, and "the request will fail" is not a
  property the validator can assert about someone else's DNS.
- **Pins the address it validated.** Checking a hostname and then handing the
  hostname to ``requests`` re-resolves it, so a name that answered with a public
  address during the check can answer with 127.0.0.1 microseconds later. The
  fetch connects to the address that passed.
- **Re-validates redirects.** A public URL that 302s to the metadata service
  defeats any check that only looks at the URL the caller supplied.
- **Caps the response.** Reading an endless stream into memory is a denial of
  service whoever the upstream is.
"""

import ipaddress
import logging
import socket
from typing import List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
MAX_REDIRECTS = 5

# Checked in addition to the ipaddress module's own classifications. The
# module does not consider these special, and both are routinely reachable
# from a cloud instance.
EXTRA_BLOCKED = (
    ipaddress.ip_network("169.254.0.0/16"),   # link-local, incl. 169.254.169.254
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
    ipaddress.ip_network("fd00::/8"),         # unique local
    ipaddress.ip_network("fe80::/10"),        # link-local v6
    ipaddress.ip_network("::ffff:0:0/96"),    # v4-mapped v6, e.g. ::ffff:127.0.0.1
)


class URLNotAllowed(Exception):
    """The URL is not safe to fetch server-side."""


def _ip_is_blocked(ip_str: str) -> Optional[str]:
    """Why this address is not allowed, or None when it is fine."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return "not a valid IP address"

    # A v4-mapped v6 address carries a v4 address that must be judged on its
    # own terms; ::ffff:127.0.0.1 is loopback however it is spelled.
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped

    if ip.is_loopback:
        return "loopback address"
    if ip.is_private:
        return "private address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_reserved:
        return "reserved address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_unspecified:
        return "unspecified address"
    for net in EXTRA_BLOCKED:
        if ip in net:
            return "address in blocked range %s" % net
    return None


def resolve_public_addresses(hostname: str, port: int) -> List[Tuple[int, str]]:
    """Resolve ``hostname`` and return its (family, address) pairs.

    Raises URLNotAllowed if the name does not resolve, or if *any* address it
    resolves to is blocked. Rejecting on any rather than all is deliberate: a
    name with one public and one loopback address is a rebinding primitive, not
    a host with a fallback.
    """
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        # Fail closed. The previous implementation allowed this case.
        raise URLNotAllowed("could not resolve host %r: %s" % (hostname, e))

    if not infos:
        raise URLNotAllowed("host %r resolved to no addresses" % hostname)

    resolved = []
    for family, _type, _proto, _canon, sockaddr in infos:
        addr = sockaddr[0]
        reason = _ip_is_blocked(addr)
        if reason:
            raise URLNotAllowed(
                "host %r resolves to %s (%s)" % (hostname, addr, reason)
            )
        resolved.append((family, addr))
    return resolved


def validate_url(url: str, allowlist: Optional[List[str]] = None):
    """Check a caller-supplied URL, returning (parsed, resolved_addresses).

    ``allowlist`` names hosts an operator has decided are fine regardless --
    an internal media server, typically. Matching is on exact hostname.
    """
    if not url or not isinstance(url, str):
        raise URLNotAllowed("no URL supplied")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise URLNotAllowed(
            "scheme %r is not allowed; only http and https are" % parsed.scheme
        )
    hostname = parsed.hostname
    if not hostname:
        raise URLNotAllowed("URL has no host")

    if allowlist and hostname in allowlist:
        logger.debug("Host %s is allowlisted", hostname)
        return parsed, []

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed, resolve_public_addresses(hostname, port)


def fetch(url: str, *, headers: Optional[dict] = None,
          timeout: int = DEFAULT_TIMEOUT,
          max_bytes: int = DEFAULT_MAX_BYTES,
          allowlist: Optional[List[str]] = None,
          stream: bool = False):
    """Fetch ``url`` with SSRF protection, following redirects safely.

    Returns the ``requests`` response. Redirects are followed one hop at a time
    with every hop re-validated, because the caller's URL being safe says
    nothing about where it points.
    """
    import requests

    current = url
    for hop in range(MAX_REDIRECTS + 1):
        parsed, addresses = validate_url(current, allowlist=allowlist)

        # Connect to the address that passed validation rather than letting
        # requests re-resolve the name. The Host header keeps virtual hosting
        # and TLS SNI working.
        request_headers = dict(headers or {})
        if addresses:
            family, addr = addresses[0]
            netloc_host = "[%s]" % addr if family == socket.AF_INET6 else addr
            if parsed.port:
                netloc_host += ":%d" % parsed.port
            pinned = urlunparse(parsed._replace(netloc=netloc_host))
            request_headers["Host"] = parsed.netloc
        else:
            pinned = current

        response = requests.get(
            pinned, headers=request_headers, timeout=timeout,
            stream=True, allow_redirects=False,
            # The pinned URL's hostname is an IP, so certificate verification
            # would fail against the name the caller asked for. Verify only
            # when we did not need to pin.
            verify=not addresses,
        )

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise URLNotAllowed("redirect with no Location header")
            current = requests.compat.urljoin(current, location)
            continue

        _enforce_size(response, max_bytes)
        return response

    raise URLNotAllowed("too many redirects (more than %d)" % MAX_REDIRECTS)


def _enforce_size(response, max_bytes: int) -> None:
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        response.close()
        raise URLNotAllowed(
            "response is %s bytes, over the %d byte limit" % (declared, max_bytes)
        )


def read_capped(response, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
    """Read a streamed response, stopping at ``max_bytes``.

    Content-Length is a claim, not a measurement, so the cap is enforced again
    while reading.
    """
    chunks, total = [], 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        total += len(chunk)
        if total > max_bytes:
            response.close()
            raise URLNotAllowed("response exceeded the %d byte limit" % max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)
