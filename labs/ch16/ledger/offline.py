"""Refuse every network connection that would leave the machine, in the ledger's scripts and its tests.

The ledger needs no network: the kept runs, the cost sheets, and LiteLLM's bundled price map are all on
disk, and `block_network` enforces it. It replaces `socket.socket.connect`, `connect_ex` and
`socket.getaddrinfo` with checks that let loopback through (asyncio's self-pipe on Windows connects to
127.0.0.1) and raise `NetworkBlocked` for anything else, so a library that tries to fetch something stops
with an error that names the address. The report calls it in its own process, and price.py and
litellm_map.py call it when LEDGER_OFFLINE is 1, which the report and the tests set for every process they
start.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

_ORIGINAL: dict[str, Any] = {}
_LOCAL_NAMES = {"localhost", b"localhost", None}


class NetworkBlocked(RuntimeError):
    pass


def _is_loopback(host: Any) -> bool:
    if host in _LOCAL_NAMES:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


def _allowed(sock: socket.socket, address: Any) -> bool:
    unix = getattr(socket, "AF_UNIX", None)
    if unix is not None and sock.family == unix:
        return True
    host = address[0] if isinstance(address, tuple) else address
    return _is_loopback(host)


def block_network() -> None:
    """From now on in this process, only loopback connections succeed."""
    if _ORIGINAL:
        return
    _ORIGINAL.update(connect=socket.socket.connect, connect_ex=socket.socket.connect_ex,
                     getaddrinfo=socket.getaddrinfo)

    def connect(self: socket.socket, address: Any) -> Any:
        if not _allowed(self, address):
            raise NetworkBlocked(f"the ledger makes no network call (connect to {address!r})")
        return _ORIGINAL["connect"](self, address)

    def connect_ex(self: socket.socket, address: Any) -> Any:
        if not _allowed(self, address):
            raise NetworkBlocked(f"the ledger makes no network call (connect to {address!r})")
        return _ORIGINAL["connect_ex"](self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_loopback(host):
            raise NetworkBlocked(f"the ledger makes no network call (look up {host!r})")
        return _ORIGINAL["getaddrinfo"](host, *args, **kwargs)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = getaddrinfo


def restore() -> None:
    """Undo `block_network` (the tests use it to check the block itself)."""
    if not _ORIGINAL:
        return
    socket.socket.connect = _ORIGINAL["connect"]  # type: ignore[method-assign]
    socket.socket.connect_ex = _ORIGINAL["connect_ex"]  # type: ignore[method-assign]
    socket.getaddrinfo = _ORIGINAL["getaddrinfo"]
    _ORIGINAL.clear()
