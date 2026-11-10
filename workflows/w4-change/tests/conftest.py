"""Make W4's a2a modules importable from the tests, and send every span to one session file.

The lab folders are plain directories, not packages, so the tests add them to `sys.path` the way the
scripts do when run directly. Chapter 5's tracing module is reused, so its folder is on the path too.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

W4 = Path(__file__).resolve().parents[1]
CH05 = W4.parents[1] / "labs" / "ch05"
for folder in (W4 / "a2a", W4 / "servers", W4 / "eval", W4 / "tests", CH05 / "tracing"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

os.environ.setdefault("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", "false")

import pytest  # noqa: E402

import a2a_support as support  # noqa: E402
import analyst  # noqa: E402
import risk_scorer  # noqa: E402
import trace_setup as tracing  # noqa: E402


@pytest.fixture
def anyio_backend() -> str:
    # anyio's pytest plugin (installed with mcp) runs `@pytest.mark.anyio` tests; asyncio only.
    return "asyncio"


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The scribe's write targets for a test: the ServiceNow state file and the GitHub comments file."""
    servicenow = tmp_path / "servicenow.json"
    github = tmp_path / "comments.json"
    monkeypatch.setenv("SERVICENOW_STATE_FILE", str(servicenow))
    monkeypatch.setenv("GITHUB_COMMENTS_FILE", str(github))
    return SimpleNamespace(servicenow=servicenow, github=github)


@pytest.fixture(scope="module")
def analyst_server(tmp_path_factory: pytest.TempPathFactory):
    server = support.launch(analyst, support.ANALYST_IDENTITY, "ANALYST_CALLER_TOKENS",
                            support.ANALYST_CALLERS, tmp_path_factory.mktemp("analyst"))
    try:
        yield server
    finally:
        support.stop(server)


@pytest.fixture(scope="module")
def risk_server(tmp_path_factory: pytest.TempPathFactory):
    server = support.launch(risk_scorer, support.RISK_SCORER_IDENTITY, "RISK_SCORER_CALLER_TOKENS",
                            support.RISK_CALLERS, tmp_path_factory.mktemp("risk"))
    try:
        yield server
    finally:
        support.stop(server)


@pytest.fixture(scope="session", autouse=True)
def trace_file(tmp_path_factory: pytest.TempPathFactory):
    """The session's trace file: this process exports to it, subprocesses inherit it via TRACE_FILE."""
    path = tmp_path_factory.mktemp("traces") / "traces.jsonl"
    otlp_env = getattr(tracing, "OTLP_ENDPOINT_ENV", None)
    previous = {tracing.TRACE_FILE_ENV: os.environ.get(tracing.TRACE_FILE_ENV)}
    if otlp_env:
        previous[otlp_env] = os.environ.get(otlp_env)
        os.environ.pop(otlp_env, None)  # the tests never talk to a collector
    os.environ[tracing.TRACE_FILE_ENV] = str(path)
    tracing.configure("pytest", "pytest")
    yield path
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
