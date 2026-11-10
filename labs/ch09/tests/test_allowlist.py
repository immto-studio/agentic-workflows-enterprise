"""The path allowlist, run with a real nginx when one is available (NGINX names it, or PATH has it)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_allowlist  # noqa: E402

NGINX = os.environ.get("NGINX") or shutil.which("nginx")


@pytest.mark.skipif(NGINX is None, reason="nginx is not installed")
def test_the_allowlist_passes_three_routes_and_the_metrics_and_streams() -> None:
    result = check_allowlist.run(Path(NGINX))
    wrong = [p for p in result["probes"] if not p["as_designed"]]
    assert wrong == [], wrong
    assert result["streams"], "the proxy buffered a streamed answer"
