"""Explicit teaching model of a system resolver, without DNS traffic."""

import socket


def controlled_ipv4(hostname: str) -> str:
    """Resolve only the lab's loopback names; reject every other name."""
    if hostname == "127.0.0.1":
        return hostname
    if hostname == "localhost":
        return "127.0.0.1"
    raise socket.gaierror(socket.EAI_NONAME, "name absent from controlled lab resolver")
