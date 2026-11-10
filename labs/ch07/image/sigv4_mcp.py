"""MCP over Streamable HTTP with every request signed by the runtime's role (chapter 6).

AgentCore Gateway's inbound authorization is AWS_IAM for Larkspur's tool gateway: each request
carries a Signature Version 4 signature, and the gateway's policy engine sees the caller as the
runtime's execution role, the workflow identity it permits tools for. The MCP SDK takes an httpx2
client for its Streamable HTTP transport; `SigV4` is that client's auth, and `SignedMCP` is a
transport the harness opens once per question and closes with the question.

The gateway lists each target's tools as `<target>___<tool>`. `GatewayNames` maps them back to
the tools' own names before the harness checks them against its lock, and forward again for
each call, with the targets the platform's tool catalog gives (TOOL_TARGETS).
"""

from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any

import botocore.session
import httpx2
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from mcp.client.streamable_http import streamable_http_client

SERVICE = "bedrock-agentcore"  # the signing name for the gateway's MCP endpoint
SIGNED_HEADERS = ("Authorization", "X-Amz-Date", "X-Amz-Security-Token")
TARGET_SEPARATOR = "___"  # the gateway serves a target's tool as <target>___<tool>


class SigV4(httpx2.Auth):
    """Sign each request with the role's current credentials (botocore refreshes them as they expire)."""

    requires_request_body = True

    def __init__(self, region: str, credentials: Any = None) -> None:
        self.region = region
        self._credentials = credentials  # tests pass static ones; the container uses botocore's chain

    def credentials(self) -> Any:
        if self._credentials is None:
            self._credentials = botocore.session.get_session().get_credentials()
        if self._credentials is None:
            raise RuntimeError("no AWS credentials to sign the MCP request with")
        return self._credentials.get_frozen_credentials()

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response, None]:
        # Sign the host and, when there is one, the content type: headers the request keeps as sent.
        headers = {"host": request.url.netloc.decode()}
        if "content-type" in request.headers:
            headers["content-type"] = request.headers["content-type"]
        signed = AWSRequest(method=request.method, url=str(request.url), data=request.content, headers=headers)
        SigV4Auth(self.credentials(), SERVICE, self.region).add_auth(signed)
        for name in SIGNED_HEADERS:
            if name in signed.headers:
                request.headers[name] = signed.headers[name]
        yield request


class GatewayNames:
    """The names AgentCore Gateway serves tools under, mapped back to the tools' own and forward again.

    "Tool names are constructed in the following pattern: ${target_name}___${tool_name}" (AgentCore
    developer guide, read 2026-10-29). `targets` maps each tool to the target that serves it, from
    the platform's tool catalog. A served name is mapped back only when its prefix is that tool's
    target; any other keeps the name it was served under, and the harness's lock check refuses it.
    """

    def __init__(self, targets: Mapping[str, str] | None = None) -> None:
        self.targets = dict(targets or {})

    def local_tools(self, served: list[Any]) -> list[Any]:
        """The served tools under their own names, for the lock check."""
        return [self._local(tool) for tool in served]

    def _local(self, tool: Any) -> Any:
        target, separator, name = tool.name.partition(TARGET_SEPARATOR)
        if separator and self.targets.get(name) == target:
            return tool.model_copy(update={"name": name})
        return tool

    def served_name(self, name: str) -> str:
        """The name to call a tool by: its target's prefix, when the catalog gives one."""
        target = self.targets.get(name)
        return f"{target}{TARGET_SEPARATOR}{name}" if target else name


class SignedMCP(GatewayNames, AbstractAsyncContextManager):
    """A Streamable HTTP transport whose requests are signed; `transport_name` is what the audit log records."""

    transport_name = "http"

    def __init__(self, url: str, auth: SigV4, targets: Mapping[str, str] | None = None) -> None:
        super().__init__(targets)
        self.url, self.auth = url, auth

    async def __aenter__(self) -> Any:
        self._client = httpx2.AsyncClient(auth=self.auth, timeout=httpx2.Timeout(30.0, read=300.0))
        self._streams = streamable_http_client(self.url, http_client=self._client)
        return await self._streams.__aenter__()

    async def __aexit__(self, *exc: Any) -> bool | None:
        try:
            return await self._streams.__aexit__(*exc)
        finally:
            await self._client.aclose()
