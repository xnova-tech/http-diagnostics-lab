"""Real subprocess fixtures for the public baseline checks."""

import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(port: int, tls_dir: Path | None = None) -> subprocess.Popen[str]:
    argv = [sys.executable, "-m", "lab", "serve", "--port", str(port)]
    if tls_dir is not None:
        argv += ["--tls-dir", str(tls_dir)]
    process = subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    scheme = "https" if tls_dir else "http"
    for _ in range(100):
        if process.poll() is not None:
            _, stderr = process.communicate(timeout=2)
            raise RuntimeError(f"server exited early ({process.returncode}): {stderr}")
        try:
            context = ssl.create_default_context(cafile=str(tls_dir / "ca.pem")) if tls_dir else True
            hostname = "localhost" if tls_dir else "127.0.0.1"
            with httpx.Client(trust_env=False, verify=context, timeout=0.15) as client:
                response = client.get(f"{scheme}://{hostname}:{port}/health")
            if response.status_code == 200:
                return process
        except httpx.RequestError:
            time.sleep(0.05)
    process.terminate()
    process.communicate(timeout=5)
    raise RuntimeError("server did not become ready within five seconds")


@pytest.fixture
def http_server():
    port = free_port()
    process = start_server(port)
    yield port
    process.terminate()
    process.communicate(timeout=5)
    assert process.returncode is not None


@pytest.fixture
def tls_server(tmp_path: Path):
    cert_dir = tmp_path / "certs"
    result = subprocess.run(
        [sys.executable, "-m", "lab", "certs", "--output", str(cert_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert "created" in result.stdout
    port = free_port()
    process = start_server(port, cert_dir)
    yield port, cert_dir
    process.terminate()
    process.communicate(timeout=5)
    assert process.returncode is not None
