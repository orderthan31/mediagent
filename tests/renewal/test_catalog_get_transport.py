"""GET-only pin policy tests; no real upstream, key or inference is used."""

import io
import socket
from types import SimpleNamespace

import httpx
import pytest
import video_service.model_catalog as module


def transport(monkeypatch, address="162.159.140.245"):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
        ],
    )
    implementation = getattr(module, "CatalogGetTransport", None)
    assert implementation is not None, (
        "Official catalog requires a GET-only literal-address-pinned transport"
    )
    return implementation("openai")


def test_connection_close_response_keeps_owned_tls_socket_valid_until_bounded_read(
    monkeypatch,
):
    calls, names = [], []

    class Socket:
        closed = False

        def settimeout(self, seconds):
            if self.closed:
                raise OSError(9, "test socket closed before response read")

        def sendall(self, data):
            calls.append(data)

        def makefile(self, mode):
            return io.BytesIO(
                b"HTTP/1.1 401 Unauthorized\r\nConnection: close\r\nContent-Length: 2\r\n\r\n{}"
            )

        def close(self):
            self.closed = True

    sock = Socket()

    def wrap(stream, *, server_hostname):
        names.append(server_hostname)
        return stream

    monkeypatch.setattr(
        module.ssl, "create_default_context", lambda: SimpleNamespace(wrap_socket=wrap)
    )
    policy = transport(monkeypatch)
    entered = []

    def connect(address, *, timeout):
        entered.append(address)
        return sock

    monkeypatch.setattr(socket, "create_connection", connect)
    response = policy.handle_request(
        httpx.Request("GET", "https://api.openai.com/v1/models")
    )
    assert response.status_code == 401 and response.content == b"{}"
    assert names == ["api.openai.com"]
    assert entered == [("162.159.140.245", 443)]
    assert b"Host: api.openai.com" in b"".join(calls)
    assert sock.closed


@pytest.mark.parametrize(
    "method,url",
    [
        ("POST", "https://api.openai.com/v1/models"),
        ("GET", "https://api.openai.com/v1/chat/completions"),
        ("GET", "https://api.x.ai/v1/models"),
        ("GET", "http://api.openai.com/v1/models"),
        ("GET", "https://api.openai.com/v1/models?redirect=https://evil.invalid"),
    ],
)
def test_catalog_pin_refuses_other_methods_origins_paths_and_query(
    monkeypatch, method, url
):
    policy = transport(monkeypatch)
    entered = []
    monkeypatch.setattr(
        socket, "create_connection", lambda *args, **kwargs: entered.append(args)
    )
    with pytest.raises(httpx.TransportError):
        policy.handle_request(httpx.Request(method, url))
    assert entered == []


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "172.21.0.4"])
def test_catalog_pin_rejects_nonpublic_resolution(monkeypatch, address):
    with pytest.raises(module.CatalogFailure):
        transport(monkeypatch, address)
