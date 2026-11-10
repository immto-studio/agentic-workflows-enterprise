"""Which LiteLLM config the gateway's rules read: the one the proxy was started with.

Chapter 5's callback reads every alias's destinations (Region, jurisdiction, hosting) from a config
file. If it reads a different file from the one the proxy routes with, the data-class grid judges
the wrong deployments. In the lab that happened once: the proxy ran on litellm.bedrock.yaml, the
rules read litellm.config.yaml, took larkspur-chat for the self-hosted model, and added a cache salt
that Amazon Bedrock refused. LiteLLM's command line saves its --config in WORKER_CONFIG for its
workers before the callbacks load, so the rules take the path from there, and a GATEWAY_CONFIG that
names another file stops the proxy instead of weakening the grid.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


class ConfigMismatch(RuntimeError):
    """GATEWAY_CONFIG and the proxy's --config name different files."""


def proxy_config(environ: Mapping[str, str]) -> str | None:
    """The --config the LiteLLM proxy was started with, as its command line saves it."""
    try:
        saved = json.loads(environ.get("WORKER_CONFIG") or "{}")
    except ValueError:
        return None
    path = saved.get("config") if isinstance(saved, dict) else None
    return path if isinstance(path, str) and path else None


def gateway_config(environ: Mapping[str, str], default: Path) -> str:
    """The config file the rules read. A GATEWAY_CONFIG that disagrees with the proxy is refused."""
    loaded = proxy_config(environ)
    chosen = environ.get("GATEWAY_CONFIG")
    if chosen and loaded and Path(chosen).resolve() != Path(loaded).resolve():
        raise ConfigMismatch(f"GATEWAY_CONFIG names {chosen}, but the proxy was started with {loaded}")
    return chosen or loaded or str(default)
