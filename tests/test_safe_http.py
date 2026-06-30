"""SSRF guard — the security-critical fetch validation."""

import pytest

from lorekeeper.services import safe_http
from lorekeeper.services.safe_http import UnsafeURLError, _check_url_sync, _ip_is_public


def test_ip_is_public_classification():
    assert _ip_is_public("8.8.8.8")
    assert not _ip_is_public("127.0.0.1")  # loopback
    assert not _ip_is_public("10.0.0.1")  # private
    assert not _ip_is_public("192.168.1.1")  # private
    assert not _ip_is_public("169.254.169.254")  # cloud metadata / link-local
    assert not _ip_is_public("::1")  # ipv6 loopback


def test_rejects_non_http_scheme():
    with pytest.raises(UnsafeURLError):
        _check_url_sync("file:///etc/passwd")
    with pytest.raises(UnsafeURLError):
        _check_url_sync("ftp://host/x")


def test_rejects_embedded_credentials():
    with pytest.raises(UnsafeURLError):
        _check_url_sync("http://user:pass@example.com/")


def test_rejects_literal_private_and_metadata_ip():
    with pytest.raises(UnsafeURLError):
        _check_url_sync("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(UnsafeURLError):
        _check_url_sync("http://127.0.0.1:8000/")


def test_allows_public_host():
    assert _check_url_sync("https://example.com/path") == "example.com"


async def test_ensure_safe_blocks_dns_to_private(monkeypatch):
    def fake_getaddrinfo(host, *a, **k):
        return [(2, 1, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(safe_http.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURLError):
        await safe_http._ensure_safe("https://rebind.example.com/")


async def test_ensure_safe_allows_dns_to_public(monkeypatch):
    def fake_getaddrinfo(host, *a, **k):
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(safe_http.socket, "getaddrinfo", fake_getaddrinfo)
    await safe_http._ensure_safe("https://example.com/")  # must not raise
