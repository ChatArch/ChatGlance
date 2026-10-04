"""Small, side-effect-free URL safety helpers."""

from __future__ import annotations

import ipaddress
import unicodedata
import urllib.parse
from typing import Any


_LOCAL_HOST_SUFFIXES = (
    ".internal",
    ".lan",
    ".local",
    ".localdomain",
    ".localhost",
)


def safe_external_url(value: Any) -> str | None:
    """Return a strict public HTTPS URL, or ``None`` when it is unsafe.

    Validation is deliberately lexical and does not perform DNS lookups. Direct
    non-global IP addresses, local-use hostnames, credentials, malformed ports,
    control/space characters, and non-HTTPS schemes are rejected.
    """

    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 2048:
        return None
    if "\\" in value or any(character.isspace() or unicodedata.category(character).startswith("C") for character in value):
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or not parsed.netloc or not hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if port is not None and not 1 <= port <= 65535:
        return None

    normalized_hostname = hostname.rstrip(".").lower()
    if not normalized_hostname or "%" in normalized_hostname:
        return None
    if (
        normalized_hostname == "localhost"
        or normalized_hostname == "localdomain"
        or normalized_hostname == "home.arpa"
        or normalized_hostname.endswith(_LOCAL_HOST_SUFFIXES)
        or normalized_hostname.endswith(".home.arpa")
    ):
        return None

    try:
        address = ipaddress.ip_address(normalized_hostname)
    except ValueError:
        try:
            ascii_hostname = normalized_hostname.encode("idna").decode("ascii")
        except UnicodeError:
            return None
        labels = ascii_hostname.split(".")
        if len(labels) < 2 or len(ascii_hostname) > 253 or all(label.isdigit() for label in labels):
            return None
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or any(not (character.isascii() and (character.isalnum() or character == "-")) for character in label)
            for label in labels
        ):
            return None
    else:
        if not address.is_global:
            return None
    return value


__all__ = ["safe_external_url"]
