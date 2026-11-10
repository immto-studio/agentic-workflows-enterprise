"""Chapter 5's gateway callback, reused unchanged for W2, with W2's manifest.

LiteLLM imports `gateway_hooks.hooks` from the config's directory. This file loads the chapter 5
module by path, as W1's does, so the manifest check, the data-class grid, the limits, the cost line
and the span are the same code for every workflow. It points the module at W2's manifest
(MANIFEST_DIR) and at the config the proxy was started with, through W1's config_path.py.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
W2 = HERE.parent
W1_GATEWAY = W2.parent / "w1-knowledge-assistant" / "gateway"

_paths_spec = importlib.util.spec_from_file_location("w1_gateway_config_path", W1_GATEWAY / "config_path.py")
_paths = importlib.util.module_from_spec(_paths_spec)
_paths_spec.loader.exec_module(_paths)  # type: ignore[union-attr]
os.environ["GATEWAY_CONFIG"] = _paths.gateway_config(os.environ, HERE / "litellm.config.yaml")
os.environ.setdefault("MANIFEST_DIR", str(W2 / "manifest"))
os.environ.setdefault("GATEWAY_LOG_FILE", str(W2 / "gateway.log"))

_SOURCE = W2.parents[1] / "labs" / "ch05" / "gateway" / "gateway_hooks.py"
_spec = importlib.util.spec_from_file_location("ch05_gateway_hooks", _SOURCE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)  # type: ignore[union-attr]
hooks = _module.hooks
