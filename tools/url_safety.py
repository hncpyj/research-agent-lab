"""
Checks for URLs that come out of a session brief.

A brief is free text the agent reads and acts on, so the URLs in it are not
necessarily the user's own: a pasted brief can point the downloader at
http://127.0.0.1:8000/api/... or at a cloud metadata address, and until
2026-09-20 the downloader fetched whatever it was given. Every hop of a
redirect is checked, not just the first.

Zip archives from the same source are read with a ceiling on how much they
expand to, so a small file cannot fill the disk.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
import zipfile
from urllib.parse import urlparse

import config

ALLOWED_SCHEMES = ("http", "https")
MAX_EXPANSION = 100          # a member may not expand to more than this times its stored size


class UnsafeURL(ValueError):
    """The URL points somewhere a session brief must not reach."""


def _addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURL(f"{host} does not resolve ({exc.strerror})") from exc
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def check_url(url: str, allow_hosts: list[str] | None = None) -> str:
    """Return the URL if a brief may fetch it, otherwise raise UnsafeURL."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURL(f"{parsed.scheme or 'no'} URLs are not fetched; use http or https")
    host = parsed.hostname
    if not host:
        raise UnsafeURL(f"no host in {url}")

    allowed = allow_hosts if allow_hosts is not None else config.DATASET_ALLOWED_HOSTS
    if allowed and not any(host == h or host.endswith("." + h) for h in allowed):
        raise UnsafeURL(f"{host} is not in DATASET_ALLOWED_HOSTS")

    for address in _addresses(host):
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast or address.is_unspecified):
            raise UnsafeURL(f"{host} resolves to {address}, an address inside this network")
    return url


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect may not carry the request to an address the first URL could not use."""

    def __init__(self, allow_hosts: list[str] | None):
        self._allow_hosts = allow_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self._allow_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener(allow_hosts: list[str] | None = None) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_CheckedRedirect(allow_hosts))


def read_zip_member(zf: zipfile.ZipFile, name: str, limit_bytes: int) -> bytes:
    """Read one member, refusing an archive that expands far beyond its size."""
    info = zf.getinfo(name)
    if info.file_size > limit_bytes:
        raise UnsafeURL(f"{name} expands to {info.file_size / 1e6:.0f} MB, "
                        f"above DATASET_MAX_MB={config.DATASET_MAX_MB}")
    if info.compress_size and info.file_size / info.compress_size > MAX_EXPANSION:
        raise UnsafeURL(f"{name} expands {info.file_size // max(info.compress_size, 1)}x — refused")
    with zf.open(name) as fh:
        data = fh.read(limit_bytes + 1)
    if len(data) > limit_bytes:
        raise UnsafeURL(f"{name} is larger than DATASET_MAX_MB={config.DATASET_MAX_MB}")
    return data


def safe_members(zf: zipfile.ZipFile, suffixes: tuple[str, ...] = (".csv", ".tsv")) -> list[str]:
    """Members worth reading, with absolute paths and '..' left out."""
    names = []
    for name in zf.namelist():
        if name.endswith("/") or not name.lower().endswith(suffixes):
            continue
        if name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/"):
            continue
        names.append(name)
    return names
