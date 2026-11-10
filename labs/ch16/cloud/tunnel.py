"""The way from this workstation to the Langfuse VM: an EC2 Instance Connect endpoint and the CLI's tunnel.

The VM has no port open to the internet (terraform/network.tf). The AWS CLI opens a websocket tunnel through the
Instance Connect endpoint to one port of the instance (`aws ec2-instance-connect open-tunnel`, fact sheet 8.6),
for at most an hour. The session tries the direct form first, a tunnel to Langfuse's port 3000, and falls back to
a tunnel to port 22 with SSH forwarding Langfuse's port through it, with a key pair made for the session and pushed
for 60 seconds by EC2 Instance Connect. Commands on the VM run over the same SSH. The tunnel's logs and the key stay
in cloud/_lab/, which git ignores.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cloud_session  # noqa: E402

OS_USER = "ubuntu"


def cli_environment() -> dict[str, str]:
    env = dict(os.environ) | cloud_session.aws_environment()
    env["MSYS_NO_PATHCONV"] = "1"
    return env


def port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


class Tunnel:
    """One `open-tunnel` process: the instance's `remote_port` on 127.0.0.1:`local_port` here."""

    def __init__(self, instance_id: str, remote_port: int, local_port: int, work: Path, *,
                 endpoint_id: str | None = None, max_duration: int = 3600, region: str = cloud_session.REGION) -> None:
        self.instance_id, self.remote_port, self.local_port = instance_id, remote_port, local_port
        self.endpoint_id, self.max_duration, self.region = endpoint_id, max_duration, region
        self.log = work / f"tunnel-{remote_port}-{local_port}.log"
        self.proc: subprocess.Popen | None = None

    @property
    def args(self) -> list[str]:
        out = ["aws", "ec2-instance-connect", "open-tunnel", "--instance-id", self.instance_id,
               "--remote-port", str(self.remote_port), "--local-port", str(self.local_port),
               "--max-tunnel-duration", str(self.max_duration), "--region", self.region]
        if self.endpoint_id:
            out += ["--instance-connect-endpoint-id", self.endpoint_id]
        return out

    def start(self, timeout: float = 30.0) -> Tunnel:
        self._log = self.log.open("ab")
        self.proc = subprocess.Popen(self.args, env=cli_environment(), stdout=self._log, stderr=subprocess.STDOUT)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self._log.close()
                raise RuntimeError(f"open-tunnel exited with {self.proc.returncode}: {self.tail()}")
            if port_open(self.local_port):
                return self
            time.sleep(0.5)
        self.stop()
        raise RuntimeError(f"the tunnel's local port {self.local_port} didn't open in {timeout:.0f} s: {self.tail()}")

    def stop(self) -> int | None:
        if self.proc is None:
            return None
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self._log.close()
        return self.proc.returncode

    def tail(self, lines: int = 5) -> str:
        text = self.log.read_text(encoding="utf-8", errors="replace") if self.log.exists() else ""
        return cloud_session.redact_text("\n".join(text.splitlines()[-lines:]))

    def __enter__(self) -> Tunnel:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


# --- SSH through the tunnel ----------------------------------------------------------------------------------

def ssh_path() -> str:
    for candidate in (r"C:\Windows\System32\OpenSSH\ssh.exe", shutil.which("ssh")):
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("no ssh client found")


def keypair(work: Path) -> tuple[Path, str]:
    """An ed25519 key pair for the session, in `work`; the public key is what Instance Connect pushes."""
    private = work / "eice-key"
    if not private.exists():
        keygen = ssh_path().replace("ssh.exe", "ssh-keygen.exe") if ssh_path().endswith("ssh.exe") else "ssh-keygen"
        subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-C", "ch16-step7", "-f", str(private)],
                       check=True, capture_output=True)
    return private, (work / "eice-key.pub").read_text(encoding="utf-8").strip()


def push_key(s: Any, instance_id: str, availability_zone: str, public_key: str, os_user: str = OS_USER) -> dict[str, Any]:
    """EC2 Instance Connect puts the key on the instance for 60 seconds."""
    answer = s.client("ec2-instance-connect").send_ssh_public_key(
        InstanceId=instance_id, InstanceOSUser=os_user, SSHPublicKey=public_key, AvailabilityZone=availability_zone)
    return {"success": answer.get("Success"), "at": cloud_session.utc()}


def ssh_options(private_key: Path, local_port: int, work: Path) -> list[str]:
    return ["-p", str(local_port), "-i", str(private_key), "-o", "StrictHostKeyChecking=no",
            "-o", f"UserKnownHostsFile={work / 'known_hosts'}", "-o", "LogLevel=ERROR", "-o", "IdentitiesOnly=yes",
            "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=30"]


def ssh_run(private_key: Path, local_port: int, work: Path, command: str, *, os_user: str = OS_USER,
            timeout: float = 120.0) -> subprocess.CompletedProcess:
    args = [ssh_path(), *ssh_options(private_key, local_port, work), f"{os_user}@127.0.0.1", command]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


def ssh_forward(private_key: Path, local_port: int, work: Path, forward_local: int, forward_remote: int,
                *, os_user: str = OS_USER) -> subprocess.Popen:
    """`ssh -N -L`: Langfuse's port through the SSH tunnel, when the endpoint won't tunnel it directly."""
    args = [ssh_path(), *ssh_options(private_key, local_port, work), "-N",
            "-L", f"{forward_local}:127.0.0.1:{forward_remote}", f"{os_user}@127.0.0.1"]
    log = (work / f"ssh-forward-{forward_local}.log").open("ab")
    return subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
