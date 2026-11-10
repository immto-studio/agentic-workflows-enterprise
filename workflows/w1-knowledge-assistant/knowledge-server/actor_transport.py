"""The harness's side of the identity hand-off: an MCP transport that forwards the engineer's token.

Chapter 6 has AgentCore Gateway propagate one header to the MCP servers, X-Larkspur-Actor, which
carries the engineer's token for the server. Locally the harness talks to the knowledge server
directly, so this transport puts the same header on every request, the way chapter 7's SignedMCP
puts a signature on them. `mcp.Client(ActorMCP(url, token))` is all the harness changes.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx2
from mcp.client.streamable_http import streamable_http_client

ACTOR_HEADER = "X-Larkspur-Actor"


class ActorMCP(AbstractAsyncContextManager):
    """A Streamable HTTP transport whose every request carries the engineer's token."""

    transport_name = "http"

    def __init__(self, url: str, token: str) -> None:
        self.url, self.token = url, token

    async def __aenter__(self) -> Any:
        self._client = httpx2.AsyncClient(headers={ACTOR_HEADER: self.token},
                                          timeout=httpx2.Timeout(30.0, read=300.0))
        self._streams = streamable_http_client(self.url, http_client=self._client)
        return await self._streams.__aenter__()

    async def __aexit__(self, *exc: Any) -> bool | None:
        try:
            return await self._streams.__aexit__(*exc)
        finally:
            await self._client.aclose()
