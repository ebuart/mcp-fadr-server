"""URL validation with SSRF prevention.

The validator checks:
1. Scheme is in the configured allowlist (default: ``https`` only).
2. Hostname resolves to a non-private IP address.
3. If a port is specified on an https URL, it must be 443.
4. The URL path extension is a supported audio format.

The DNS resolver is injectable so tests can avoid real network calls.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable
from urllib.parse import urlparse

from server.exceptions import UrlValidationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {"mp3", "wav", "aac", "flac", "ogg", "m4a"}
)

_PRIVATE_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv4Network("224.0.0.0/4"),
    ipaddress.IPv4Network("0.0.0.0/8"),
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fe80::/10"),
    ipaddress.IPv6Network("fc00::/7"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_resolve_host(hostname: str) -> list[str]:
    try:
        results = socket.getaddrinfo(hostname, None)
        return [str(r[4][0]) for r in results]
    except socket.gaierror as exc:
        raise UrlValidationError(
            "Cannot resolve audio URL hostname.",
            details={"issue": "dns_resolution_failed"},
        ) from exc


def _is_private_ip(addr_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(addr_str)
    except ValueError:
        return True  # unparseable → treat as unsafe
    return any(addr in net for net in _PRIVATE_NETWORKS)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class UrlValidator:
    """Validates an audio URL for scheme, SSRF safety, and extension."""

    def __init__(
        self,
        allowed_schemes: frozenset[str],
        resolve_host: Callable[[str], list[str]] = _default_resolve_host,
    ) -> None:
        self._allowed_schemes = allowed_schemes
        self._resolve_host = resolve_host

    def validate(self, url: str) -> None:
        """Raise :class:`~server.exceptions.UrlValidationError` if ``url`` is invalid."""
        parsed = urlparse(url)

        # 1. Scheme check
        if parsed.scheme.lower() not in self._allowed_schemes:
            raise UrlValidationError(
                f"URL scheme '{parsed.scheme}' is not allowed.",
                details={
                    "field": "audio_url",
                    "issue": "invalid_scheme",
                    "allowed": sorted(self._allowed_schemes),
                },
            )

        # 2. Hostname present
        if not parsed.hostname:
            raise UrlValidationError(
                "URL has no hostname.",
                details={"field": "audio_url", "issue": "missing_hostname"},
            )

        # 3. Port check (https must use 443 or default)
        if parsed.port is not None and parsed.scheme == "https" and parsed.port != 443:
            raise UrlValidationError(
                f"HTTPS audio URL must use port 443, got {parsed.port}.",
                details={"field": "audio_url", "issue": "invalid_port"},
            )

        # 4. Extension check (advisory; Fadr validates on upload)
        path_lower = parsed.path.lower()
        last_segment = path_lower.split("/")[-1]
        if "." in last_segment:
            ext = last_segment.rsplit(".", 1)[-1]
            if ext not in SUPPORTED_AUDIO_EXTENSIONS:
                raise UrlValidationError(
                    f"Unsupported audio extension '.{ext}'.",
                    details={
                        "field": "audio_url",
                        "issue": "unsupported_extension",
                        "extension": ext,
                        "supported": sorted(SUPPORTED_AUDIO_EXTENSIONS),
                    },
                )

        # 5. SSRF: resolve hostname and block private ranges
        resolved_ips = self._resolve_host(parsed.hostname)
        for ip in resolved_ips:
            if _is_private_ip(ip):
                raise UrlValidationError(
                    "The provided audio_url resolves to a disallowed address.",
                    details=None,
                )
