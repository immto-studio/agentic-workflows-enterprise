"""Chapter 5's gateway callback, reused unchanged for the self-hosted deployment.

LiteLLM imports `gateway_hooks.hooks` from the config's directory. This file loads the chapter 5
module by path, so there is one implementation of the manifest check, the data-class grid, the
limits, the cost line and the span for every alias, local or cloud.

The chapter 5 hooks read their destinations and fallbacks from the LiteLLM config named by
GATEWAY_CONFIG. Set it to the config the proxy was started with; it defaults to
litellm.config.yaml next to this file. GATEWAY_LOG_FILE chooses where the log goes.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("GATEWAY_CONFIG", str(HERE / "litellm.config.yaml"))

_SOURCE = HERE.parents[1] / "ch05" / "gateway" / "gateway_hooks.py"
_spec = importlib.util.spec_from_file_location("ch05_gateway_hooks", _SOURCE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)  # type: ignore[union-attr]

hooks = _module.hooks
