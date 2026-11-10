"""Step 4's key-binding callback, loaded from `budget/` unchanged, so a config in this folder can name it.

LiteLLM loads `binding_hooks.hooks` from the folder the config sits in. This module loads
`budget/key_binding.py` under another name, so the two never shadow each other on one path, and hands LiteLLM the
same `hooks` object.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "budget" / "key_binding.py"
_spec = importlib.util.spec_from_file_location("budget_key_binding", _PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
hooks = _module.hooks
