"""Start the loopback server or issue an ephemeral local CA certificate."""

import argparse
import os
import socket
import sys
from pathlib import Path

import trustme
import uvicorn


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("use a port from 1024 to 65535")
    return port


def make_certificates(output: Path) -> None:
    if output.exists():
        raise ValueError(f"certificate directory already exists: {output}")
    output.mkdir(mode=0o700, parents=True)
    ca = trustme.CA()
    cert = ca.issue_cert("localhost")
    ca.cert_pem.write_to_path(output / "ca.pem")
    cert.cert_chain_pems[0].write_to_path(output / "server.pem")
    key_fd = os.open(output / "server-key.pem", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(key_fd, "wb") as key_file:
        key_file.write(cert.private_key_pem.bytes())
    print(f"Local test certificates created in {output}")  # noqa: T201


def serve(port: int, tls_dir: Path | None) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise ValueError(f"port {port} is unavailable on 127.0.0.1: {exc}") from exc
    options: dict[str, object] = {}
    if tls_dir is not None:
        cert = tls_dir / "server.pem"
        key = tls_dir / "server-key.pem"
        if not cert.is_file() or not key.is_file():
            raise ValueError("TLS directory must contain server.pem and server-key.pem")
        options = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    uvicorn.run("lab.app:app", host="127.0.0.1", port=port, log_level="warning", **options)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local XNova HTTP diagnostics lab")
    actions = parser.add_subparsers(dest="action", required=True)
    server = actions.add_parser("serve", help="run the FastAPI app on loopback")
    server.add_argument("--port", type=port_number, default=8765)
    server.add_argument("--tls-dir", type=Path)
    certs = actions.add_parser("certs", help="create local, disposable TLS certificates")
    certs.add_argument("--output", type=Path, default=Path(".lab-certs"))
    args = parser.parse_args()
    try:
        if args.action == "certs":
            make_certificates(args.output)
        else:
            serve(args.port, args.tls_dir)
    except (OSError, ValueError) as exc:
        print(f"lab: {exc}", file=sys.stderr)  # noqa: T201
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
