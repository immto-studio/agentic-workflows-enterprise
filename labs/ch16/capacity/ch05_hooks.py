"""Chapter 5's gateway callback, imported from its own folder unchanged, so this step's configs can name it.

LiteLLM loads a callback named `module.instance` from the folder its config sits in, and chapter 5's
`gateway_hooks.py` sits in `labs/ch05/gateway`; step 4's `budget/ch05_callback.py` does the same for its own
config, and this module has a name of its own so that the tests can put both folders on one path. Before the import this points chapter 5's environment at this step: the destinations and the
fallbacks come from the config the drill starts the proxy with (`GATEWAY_CONFIG`), and the cost lines and
spans go to `capacity/_lab/` rather than `labs/ch05/`. A variable already set wins.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CH05_GATEWAY = HERE.parents[1] / "ch05" / "gateway"
os.environ.setdefault("GATEWAY_CONFIG", str(HERE / "litellm.outage.yaml"))
os.environ.setdefault("GATEWAY_LOG_FILE", str(HERE / "_lab" / "gateway.log"))
os.environ.setdefault("TRACE_FILE", str(HERE / "_lab" / "traces.jsonl"))
(HERE / "_lab").mkdir(exist_ok=True)
if str(CH05_GATEWAY) not in sys.path:
    sys.path.insert(0, str(CH05_GATEWAY))

from gateway_hooks import hooks  # noqa: E402,F401  (chapter 5's object, unchanged)
