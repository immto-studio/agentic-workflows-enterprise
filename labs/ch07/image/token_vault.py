"""The model gateway's key from AgentCore Identity's token vault (chapter 6).

On AgentCore Runtime the image gets no GATEWAY_KEY. The key sits in a Secrets Manager secret that
an API-key credential provider names (GATEWAY_KEY_PROVIDER), and the harness asks AgentCore
Identity for it with the workload access token the runtime sends with each request, which the
runtime adapter keeps in `WORKLOAD_TOKEN` for that request only. The runtime role's policy names
that provider and no other: AgentCore doesn't bind a workload identity to a credential provider
itself, so the policy's Resource block is the binding.

The key is held for fifteen minutes at most, so a rotated key is in use within that time, and each
fetch needs a request's token, so nothing is fetched at start-up.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gateway_model import GatewayModel
from runtime_adapter import WORKLOAD_TOKEN


class KeyUnavailable(RuntimeError):
    """No key: the vault said no, or there was no request token to ask with."""


class TokenVaultKey:
    """`key()` returns the gateway key, fetched from the token vault with the current request's token."""

    def __init__(self, provider: str, region: str, *, client: Any = None, ttl_s: float = 900.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.provider, self.region, self.ttl_s, self.clock = provider, region, ttl_s, clock
        self._client = client
        self._key: str | None = None
        self._fetched = 0.0

    def client(self) -> Any:
        if self._client is None:
            import boto3  # the runtime role's credentials, from the container's credential endpoint

            self._client = boto3.client("bedrock-agentcore", region_name=self.region)
        return self._client

    def __call__(self) -> str:
        if self._key is not None and self.clock() - self._fetched < self.ttl_s:
            return self._key
        token = WORKLOAD_TOKEN.get()
        if not token:
            raise KeyUnavailable("no workload access token on this request; AgentCore Runtime sends one with each")
        try:
            reply = self.client().get_resource_api_key(workloadIdentityToken=token,
                                                       resourceCredentialProviderName=self.provider)
        except Exception as exc:  # botocore's ClientError and its kin; the name is enough for the log
            raise KeyUnavailable(f"the token vault refused {self.provider!r}: {type(exc).__name__}") from None
        self._key, self._fetched = reply["apiKey"], self.clock()
        return self._key


@dataclass
class VaultKeyedModel(GatewayModel):
    """Chapter 5's gateway model, with its key from the token vault at each call."""

    key_source: Callable[[], str] = field(default=lambda: "", repr=False)

    def __call__(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.api_key = self.key_source()
        return super().__call__(messages)
