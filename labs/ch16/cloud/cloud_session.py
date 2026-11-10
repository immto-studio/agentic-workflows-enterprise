"""What every script of the cloud session shares: the account from the environment, redaction, the clock.

Chapter 16, step 7 (companion #14, O-D1). The AWS session comes from the environment alone: profile `book-lab`
through AWS_PROFILE, the shared credentials file through AWS_SHARED_CREDENTIALS_FILE, AWS_CONFIG_FILE pointing at
a file that doesn't exist, and us-east-2 as AWS_DEFAULT_REGION (book D-034). `require_environment` refuses to run
otherwise, and nothing here opens the credentials file: the SDK reads it. Every file a script keeps goes through
`redact`, which replaces account IDs, access key IDs (with a placeholder that stays distinct per key, so join.py
still matches events by it), principal IDs, user names, session tokens, addresses and public IP addresses, as
chapter 6's results replace account IDs. The raw records stay in cloud/_lab/, which git ignores.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
TERRAFORM = HERE / "terraform"
SCRATCH = HERE / "_lab"
REGION = "us-east-2"
PROFILE = "book-lab"
REQUIRED = ("AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE", "AWS_PROFILE", "AWS_DEFAULT_REGION")
CLOCK = "time.perf_counter() for intervals and datetime.now(timezone.utc) for stamps, both on this workstation"


def results_dir(date: str | None = None) -> Path:
    return LAB / "results" / (date or datetime.now(timezone.utc).strftime("%Y-%m-%d")) / "cloud"


def require_environment(environ: os._Environ | dict[str, str] = os.environ) -> dict[str, str]:
    """The four variables, as the brief fixes them; a session that lacks one doesn't start."""
    missing = [name for name in REQUIRED if not environ.get(name)]
    if missing:
        raise SystemExit(f"the session's environment lacks {', '.join(missing)}")
    if environ["AWS_PROFILE"] != PROFILE:
        raise SystemExit(f"AWS_PROFILE must be {PROFILE!r}")
    if environ["AWS_DEFAULT_REGION"] != REGION:
        raise SystemExit(f"AWS_DEFAULT_REGION must be {REGION!r} (book D-034)")
    if Path(environ["AWS_CONFIG_FILE"]).exists():
        raise SystemExit("AWS_CONFIG_FILE must point at a file that doesn't exist")
    if not Path(environ["AWS_SHARED_CREDENTIALS_FILE"]).is_file():
        raise SystemExit("AWS_SHARED_CREDENTIALS_FILE points at nothing")
    return {name: environ[name] for name in REQUIRED}


def session(region: str = REGION) -> Any:
    import boto3

    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", PROFILE), region_name=region)


def aws_environment(environ: os._Environ | dict[str, str] = os.environ) -> dict[str, str]:
    """The AWS variables a child process gets, and nothing else of the account."""
    out = {name: environ[name] for name in REQUIRED if name in environ}
    out["AWS_REGION"] = environ.get("AWS_DEFAULT_REGION", REGION)
    out["AWS_EC2_METADATA_DISABLED"] = "true"
    return out


# --- redaction ----------------------------------------------------------------------------------------------

_SESSION_TOKEN = re.compile(r"\b(FwoG|IQoJ)[A-Za-z0-9+/=]{20,}")
_KEY = re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b")
_PRINCIPAL = re.compile(r"\b(AIDA|AROA)[A-Z0-9]{16,}\b")
_ACCOUNT = re.compile(r"\b[0-9]{12}\b")
_USER = re.compile(r"(:user/)[^\s\"',/]+")
_USER_NAME = re.compile(r'("userName":\s*")[^"]+(")')  # CloudTrail's userIdentity.userName and sessionIssuer.userName
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_IPV4 = re.compile(r"(?<![\w:.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")  # not an image tag such as server:26.3.62.3
_KEEP_IP = ("127.", "10.", "0.0.0.0", "169.254.")
_PATH = re.compile(r"[A-Za-z]:(?:\\\\|\\|/)(?:[^\"'\s\\/]+(?:\\\\|\\|/))*([^\"'\s\\/]+)")  # a path of this machine: keep the file's name


def stable_key(key_id: str) -> str:
    """A placeholder for an access key ID: the same key gives the same placeholder, and nothing of the key."""
    return f"{key_id[:4].lower()}-{hashlib.sha256(key_id.encode('ascii')).hexdigest()[:12]}"


def redact_text(text: str) -> str:
    text = _SESSION_TOKEN.sub("<session-token>", text)
    text = _KEY.sub(lambda m: stable_key(m.group(0)), text)
    text = _PRINCIPAL.sub("<principal-id>", text)
    text = _ACCOUNT.sub("<account>", text)
    text = _USER.sub(r"\1<user>", text)
    text = _USER_NAME.sub(r"\1<user>\2", text)
    text = _EMAIL.sub("<address>", text)
    text = _PATH.sub(r"<path>/\1", text)
    return _IPV4.sub(lambda m: m.group(0) if m.group(0).startswith(_KEEP_IP) else "<ip>", text)


def redact(value: Any) -> Any:
    return json.loads(redact_text(json.dumps(value, default=str, ensure_ascii=False)))


def write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(value), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact_text(text), encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def merge_json(path: Path, key: str, value: Any) -> None:
    """One file per check, one key per moment or part, so a check can be run again without losing the rest."""
    path = Path(path)
    current = read_json(path) if path.exists() else {}
    current[key] = value
    write_json(path, current)


# --- the clock ------------------------------------------------------------------------------------------------

def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Clock:
    """Intervals from time.perf_counter(), stamps from datetime.now(UTC): the clock every timing here names."""

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.started = utc()

    def seconds(self) -> float:
        return round(time.perf_counter() - self.t0, 3)

    def mark(self) -> dict[str, Any]:
        return {"at": utc(), "seconds": self.seconds()}


def aws_error(exc: BaseException) -> dict[str, Any]:
    response = getattr(exc, "response", None) or {}
    error = response.get("Error") or {}
    return {"error": type(exc).__name__, "code": error.get("Code"), "message": redact_text(str(exc))[:400]}


def terraform_outputs(folder: Path = TERRAFORM) -> dict[str, Any]:
    run = subprocess.run(["terraform", "output", "-json"], cwd=folder, capture_output=True, text=True, check=True)
    return {name: value["value"] for name, value in json.loads(run.stdout).items()}
