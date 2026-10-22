"""The autouse guard in conftest.py keeps every test offline."""

import socket
import urllib.request

import pytest

from tests.conftest import NetworkBlockedError


def test_internet_connect_is_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock, pytest.raises(NetworkBlockedError):
        sock.connect(("93.184.216.34", 443))


def test_dns_lookup_is_blocked():
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("open.spotify.com", 443)


def test_http_libraries_are_blocked():
    with pytest.raises(Exception) as raised:
        urllib.request.urlopen("https://open.spotify.com/oembed?url=x", timeout=1)
    assert "NetworkBlockedError" in repr(raised.value) or isinstance(raised.value.__context__, NetworkBlockedError) \
        or isinstance(getattr(raised.value, "reason", None), NetworkBlockedError)


def test_local_unix_sockets_still_work():
    a, b = socket.socketpair()
    with a, b:
        a.sendall(b"ok")
        assert b.recv(2) == b"ok"
