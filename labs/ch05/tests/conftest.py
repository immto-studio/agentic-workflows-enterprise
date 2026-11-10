"""Make the lab's modules importable from the tests, and send every span to one file.

The lab folders are plain directories (one has a hyphen in its name), not packages, so the
tests add them to `sys.path` the same way the scripts do when run directly.

Tracing: one JSON lines file per test session, shared by this process and every subprocess the
tests start (the MCP server, the analyst), through `TRACE_FILE`. The trace tests read it back.

Session storage: every test gets a folder of its own as the Foundry session's storage, so the
runtime adapter's record of a sandbox's user never lands in the real $HOME or leaks between tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
for folder in (LAB / "mcp-server", LAB / "harness", LAB / "tracing", LAB / "a2a", LAB / "golden"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

# The A2A SDK reads this at import time; the a2a scripts set the same default.
os.environ.setdefault("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", "false")

import pytest  # noqa: E402

import trace_setup as tracing  # noqa: E402

GOLDEN_SUMMARY = pytest.StashKey[str]()


@pytest.fixture
def anyio_backend() -> str:
    # anyio's pytest plugin (installed with mcp) runs `@pytest.mark.anyio` tests; asyncio only.
    return "asyncio"


@pytest.fixture(autouse=True)
def session_storage(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The folder the runtime adapter treats as the session's $HOME (its SESSION_STORAGE_ENV)."""
    folder = tmp_path_factory.mktemp("session-home")
    monkeypatch.setenv("SESSION_STORAGE_DIR", str(folder))
    return folder


@pytest.fixture(scope="session", autouse=True)
def trace_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The session's trace file: this process exports to it, subprocesses inherit it via TRACE_FILE."""
    path = tmp_path_factory.mktemp("traces") / "traces.jsonl"
    previous = {k: os.environ.get(k) for k in (tracing.TRACE_FILE_ENV, tracing.OTLP_ENDPOINT_ENV)}
    os.environ[tracing.TRACE_FILE_ENV] = str(path)
    os.environ.pop(tracing.OTLP_ENDPOINT_ENV, None)  # the tests never talk to a collector
    tracing.configure("pytest", "pytest")
    yield path
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="session")
def gateway(tmp_path_factory: pytest.TempPathFactory, trace_file: Path):
    """The lab's gateway (three fakes and the LiteLLM proxy), started once for every test that asks.

    The proxy writes its spans to the session's trace file, next to the harness's own spans.
    """
    from gateway_support import running_gateway

    with running_gateway(tmp_path_factory.mktemp("gateway"), trace_file) as gw:
        yield gw


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter, exitstatus: int, config: pytest.Config) -> None:
    summary = config.stash.get(GOLDEN_SUMMARY, None)
    if summary:
        terminalreporter.write_sep("-", "golden set")
        terminalreporter.write_line(summary)
