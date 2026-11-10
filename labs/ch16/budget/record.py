"""What step 4 writes to results/: JSON with no path, password or key of the machine that ran it.

The raw records (proxy logs, the cluster, the receiver's outbox) stay in `budget/_lab/`; what is committed
goes through `scrub` first, which replaces the companion's folder, the home folder and the temporary folder
in every string, in either slash style and any case, and masks database URLs and LiteLLM keys.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
COMPANION = HERE.parents[2]
KEY = re.compile(r"sk-[A-Za-z0-9_-]{6,}")
DB_URL = re.compile(r"postgres(?:ql)?://\S+")


def _variants(path: str) -> list[str]:
    forward = path.replace("\\", "/")
    return sorted({path, forward, forward.replace("/", "\\")}, key=len, reverse=True)


def _places() -> list[tuple[re.Pattern[str], str]]:
    places = [(str(COMPANION), "<companion>"), (tempfile.gettempdir(), "<temp>"), (str(Path.home()), "<home>")]
    if os.environ.get("LOCALAPPDATA"):
        places.insert(0, (os.environ["LOCALAPPDATA"], "<localappdata>"))
    found = []
    for path, label in places:
        for variant in _variants(path):
            found.append((re.compile(re.escape(variant), re.IGNORECASE), label))
    return found


def scrub_text(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<secret>")
    text = DB_URL.sub("postgresql://<redacted>", text)
    text = KEY.sub("sk-<redacted>", text)
    for pattern, label in _places():
        text = pattern.sub(label, text)
    return text


def scrub(obj: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(obj, str):
        return scrub_text(obj, secrets)
    if isinstance(obj, list):
        return [scrub(item, secrets) for item in obj]
    if isinstance(obj, dict):
        return {key: scrub(value, secrets) for key, value in obj.items()}
    return obj


def write_json(path: Path, obj: Any, secrets: tuple[str, ...] = ()) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scrub(obj, secrets), indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                    newline="\n")
    return path


def atomic_write(path: Path, text: str) -> None:
    """Write a whole file or nothing: a temporary file beside it, flushed to disk, renamed over it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(50):  # Windows refuses the rename while a reader has the file open
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 49:
                temp.unlink(missing_ok=True)
                raise
            time.sleep(0.01)
