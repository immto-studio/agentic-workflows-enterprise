"""Starting and stopping step 4's processes on Windows and elsewhere.

Two things the smoke test found. The `litellm` command on Windows is a launcher, `litellm.exe`, which runs
the proxy as its child, and the proxy runs Prisma's query engines as its children; stopping the launcher
alone left two query engines running with no parent. So a proxy is stopped by its whole tree, while the tree
is still there (`taskkill /T`). And the proxy gets a console of its own with its window hidden, as a
terminal would give it, so no console control event can pass between it and the process that started it.
"""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any


def new_console() -> dict[str, Any]:
    """Popen arguments for a console of the child's own, its window hidden."""
    if os.name != "nt":
        return {"start_new_session": True}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0  # SW_HIDE
    return {"creationflags": subprocess.CREATE_NEW_CONSOLE, "startupinfo": info}


def stop_tree(process: subprocess.Popen, timeout: float = 20) -> None:
    """Stop a process and everything it started."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=60)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)
