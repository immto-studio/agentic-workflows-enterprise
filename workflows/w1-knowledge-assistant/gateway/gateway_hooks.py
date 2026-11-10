"""Chapter 5's gateway callback, reused unchanged for W1, with W1's manifests.

LiteLLM imports `gateway_hooks.hooks` from the config's directory. This file loads the chapter 5
module by path, as chapter 9's does, so the manifest check, the data-class grid, the limits, the
cost line and the span are the same code for every workflow. It points the module at W1's
manifests (MANIFEST_DIR) and at the config the proxy was started with: config_path.py reads it
from the proxy's own record and refuses a GATEWAY_CONFIG that names another file. GATEWAY_LOG_FILE
chooses where the log goes.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
W1 = HERE.parent
_paths_spec = importlib.util.spec_from_file_location("w1_gateway_config_path", HERE / "config_path.py")
_paths = importlib.util.module_from_spec(_paths_spec)
_paths_spec.loader.exec_module(_paths)  # type: ignore[union-attr]
os.environ["GATEWAY_CONFIG"] = _paths.gateway_config(os.environ, HERE / "litellm.config.yaml")
os.environ.setdefault("MANIFEST_DIR", str(W1 / "manifest"))
os.environ.setdefault("GATEWAY_LOG_FILE", str(W1 / "gateway.log"))

_SOURCE = W1.parents[1] / "labs" / "ch05" / "gateway" / "gateway_hooks.py"
_spec = importlib.util.spec_from_file_location("ch05_gateway_hooks", _SOURCE)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)  # type: ignore[union-attr]

hooks = _module.hooks
