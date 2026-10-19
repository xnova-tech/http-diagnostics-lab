"""Contract checks using real loopback sockets and HTTP clients."""

import shutil
import socket
import ssl
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from lab.resolver import controlled_ipv4


def local_client(**kwargs: object) -> httpx.Client:
    return httpx.Client(trust_env=False, timeout=2.0, **kwargs)


def test_http_responses_and_redirect(http_server: int) -> None:
    base = f"http://127.0.0.1:{http_server}"
    with local_client() as client:
        health = client.get(base + "/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert client.get(base + "/items/42").json() == {"id": 42, "name": "sample"}
        assert client.get(base + "/missing").status_code == 404
        unavailable = client.get(base + "/unavailable")
        assert unavailable.status_code == 503
        assert unavailable.json() == {"status": "unavailable"}
        redirect = client.get(base + "/redirect")
        assert redirect.status_code == 302
        assert redirect.headers["location"] == "/health"
        assert not redirect.history
    with local_client(follow_redirects=True) as client:
        followed = client.get(base + "/redirect")
        assert followed.status_code == 200
        assert [response.status_code for response in followed.history] == [302]


def test_read_timeout_then_same_url_succeeds(http_server: int) -> None:
    url = f"http://127.0.0.1:{http_server}/slow?delay=0.5"
    with httpx.Client(trust_env=False, timeout=httpx.Timeout(1, read=0.1)) as client, pytest.raises(httpx.ReadTimeout):
        client.get(url)
    with httpx.Client(trust_env=False, timeout=httpx.Timeout(2, read=1)) as client:
        response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "delay": 0.5}


def test_refused_port_is_not_http_503(http_server: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as empty_port:
        empty_port.bind(("127.0.0.1", 0))
        port = int(empty_port.getsockname()[1])
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=1)
    with local_client() as client:
        with pytest.raises(httpx.ConnectError):
            client.get(f"http://127.0.0.1:{port}/health")
        response = client.get(f"http://127.0.0.1:{http_server}/unavailable")
        assert response.status_code == 503


def test_controlled_resolver_is_explicit_model() -> None:
    assert socket.getaddrinfo("localhost", None)
    assert controlled_ipv4("localhost") == "127.0.0.1"
    with pytest.raises(socket.gaierror):
        controlled_ipv4("node.lab")


def test_occupied_port_reports_clear_error(http_server: int) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "lab", "serve", "--port", str(http_server)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2
    assert f"port {http_server} is unavailable" in result.stderr


def test_tls_trust_and_name(tls_server: tuple[int, Path]) -> None:
    port, cert_dir = tls_server
    ca = str(cert_dir / "ca.pem")
    certificate = x509.load_pem_x509_certificate((cert_dir / "server.pem").read_bytes())
    names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert names.get_values_for_type(x509.DNSName) == ["localhost"]
    assert names.get_values_for_type(x509.IPAddress) == []
    with local_client() as client, pytest.raises(httpx.ConnectError):
        client.get(f"https://127.0.0.1:{port}/health")
    context = ssl.create_default_context(cafile=ca)
    with local_client(verify=context) as client:
        response = client.get(f"https://localhost:{port}/health")
        assert response.status_code == 200
        with pytest.raises(httpx.ConnectError) as mismatch:
            client.get(f"https://127.0.0.1:{port}/health")
    assert "IP address mismatch" in str(mismatch.value)
    with (
        socket.create_connection(("127.0.0.1", port), timeout=2) as connection,
        pytest.raises(ssl.SSLCertVerificationError) as direct_mismatch,
    ):
        context.wrap_socket(connection, server_hostname="127.0.0.1")
    assert "IP address mismatch" in str(direct_mismatch.value)


@pytest.mark.skipif(shutil.which("curl") is None, reason="curl is unavailable")
def test_curl_http_and_tls(tls_server: tuple[int, Path], http_server: int) -> None:
    port, cert_dir = tls_server
    base = ["curl", "--noproxy", "*", "--silent", "--show-error", "--include"]
    for path, status in (("/health", "200"), ("/missing", "404"), ("/unavailable", "503"), ("/redirect", "302")):
        result = subprocess.run(
            base + [f"http://127.0.0.1:{http_server}{path}"], capture_output=True, text=True, timeout=5
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith(f"HTTP/1.1 {status}")
        if path == "/redirect":
            assert "location: /health" in result.stdout.lower()
    follow = subprocess.run(
        base + ["--location", f"http://127.0.0.1:{http_server}/redirect"], capture_output=True, text=True, timeout=5
    )
    assert follow.returncode == 0 and "HTTP/1.1 200" in follow.stdout
    url = f"https://localhost:{port}/health"
    resolve = ["--resolve", f"localhost:{port}:127.0.0.1"]
    untrusted = subprocess.run(base + resolve + [url], capture_output=True, text=True, timeout=5)
    assert untrusted.returncode != 0
    trusted = subprocess.run(
        base + resolve + ["--cacert", str(cert_dir / "ca.pem"), url], capture_output=True, text=True, timeout=5
    )
    assert trusted.returncode == 0, trusted.stderr
    assert "HTTP/1.1 200" in trusted.stdout
    mismatch = subprocess.run(
        base + ["--cacert", str(cert_dir / "ca.pem"), f"https://127.0.0.1:{port}/health"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert mismatch.returncode != 0
