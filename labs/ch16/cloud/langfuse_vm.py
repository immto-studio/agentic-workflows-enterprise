"""The Langfuse VM from this workstation: wait for the stack, read its markers, and hold the tunnel for the run.

Step 7, item 7 (O-D4, amended). The VM has no port open to the internet; everything here goes through the EC2
Instance Connect endpoint (cloud/tunnel.py). `wait` tunnels to the VM's SSH port, pushes a key made for the
session (valid 60 seconds each time), and asks for the `ready` marker the user data writes once Langfuse's health
endpoint answered; then it reads the markers back: Docker's and Compose's versions, whether the pinned image tags
were served, the pull and start times, Langfuse's health answer with its version, the images with their digests,
the containers, and the machine's cores, memory and disk. `tunnel` opens the way the Collector exports through:
first the endpoint's own tunnel straight to Langfuse's port 3000, and when that doesn't carry HTTP, a tunnel to
port 22 with SSH forwarding 3000 through it; it records which worked and holds it until the stop file appears.

Run (from labs/ch16, with the session's environment):
    python cloud/langfuse_vm.py wait --out results/<date>/cloud
    python cloud/langfuse_vm.py tunnel --local-port 3100 --stop-file cloud/_lab/stop-tunnel --out results/<date>/cloud
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
for folder in (HERE, HERE.parent / "collector"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import cloud_session  # noqa: E402
import tunnel  # noqa: E402
from otelcol import free_port  # noqa: E402

MARKERS = ("ready", "pin.txt", "versions.txt", "timeline.txt", "health.json", "files.sha256", "ps.txt", "digests.txt")
MACHINE = {"cores": "nproc", "memory": "free -m | sed -n 2p", "disk": "df -h / | tail -1", "uptime": "uptime -p",
           "os": "grep PRETTY_NAME /etc/os-release"}


def vm_outputs() -> dict[str, str]:
    out = cloud_session.terraform_outputs()
    return {"instance_id": out["instance_id"], "endpoint_id": out["instance_connect_endpoint_id"],
            "availability_zone": out["availability_zone"], "instance_type": out["instance_type"], "ami_id": out["ami_id"]}


def launch_time(s: Any, instance_id: str) -> datetime:
    answer = s.client("ec2").describe_instances(InstanceIds=[instance_id])
    return answer["Reservations"][0]["Instances"][0]["LaunchTime"]


def over_ssh(s: Any, vm: dict[str, str], key: Path, public: str, local_port: int, work: Path, command: str,
             timeout: float = 60.0) -> Any:
    """Push the key (60 seconds of validity) and run one command over the tunnel."""
    tunnel.push_key(s, vm["instance_id"], vm["availability_zone"], public)
    return tunnel.ssh_run(key, local_port, work, command, timeout=timeout)


def wait(s: Any, work: Path, *, limit: float = 1200.0, every: float = 20.0) -> dict[str, Any]:
    vm = vm_outputs()
    launched = launch_time(s, vm["instance_id"])
    record: dict[str, Any] = {"vm": vm, "launched": launched.isoformat(), "clock": cloud_session.CLOCK, "attempts": []}
    clock = cloud_session.Clock()
    record["started"] = clock.started
    key, public = tunnel.keypair(work)
    with tunnel.Tunnel(vm["instance_id"], 22, free_port(), work, endpoint_id=vm["endpoint_id"]) as t:
        record["ssh_tunnel"] = {"local_port": t.local_port, "opened_after_s": clock.seconds()}
        ready = None
        while clock.seconds() < limit:
            try:
                run = over_ssh(s, vm, key, public, t.local_port, work,
                               "cat /opt/langfuse/ready 2>/dev/null || tail -n 2 /var/log/ch16-langfuse.log 2>/dev/null || echo booting")
                line = (run.stdout or run.stderr).strip().splitlines()
                first = line[-1] if line else ""
                record["attempts"].append({"seconds": clock.seconds(), "returncode": run.returncode,
                                           "last_line": cloud_session.redact_text(first)[:160]})
                if run.returncode == 0 and first[:4].isdigit() and first.endswith("Z") and "T" in first:
                    ready = first
                    break
            except Exception as exc:  # the tunnel's connection refused while sshd isn't up yet
                record["attempts"].append({"seconds": clock.seconds(), "error": f"{type(exc).__name__}: {exc}"[:160]})
            time.sleep(every)
        record["ready"] = ready
        record["ready_after_poll_s"] = clock.seconds() if ready else None
        if ready:
            record["ready_after_launch_s"] = round((datetime.fromisoformat(ready.replace("Z", "+00:00")) - launched).total_seconds(), 1)
            markers: dict[str, Any] = {}
            for name in MARKERS:
                run = over_ssh(s, vm, key, public, t.local_port, work, f"cat /opt/langfuse/{name} 2>/dev/null")
                text = run.stdout.strip()
                markers[name] = json.loads(text) if name == "health.json" and text.startswith("{") else text
            record["markers"] = markers
            machine = {}
            for name, command in MACHINE.items():
                machine[name] = over_ssh(s, vm, key, public, t.local_port, work, command).stdout.strip()
            record["machine"] = machine
            log = over_ssh(s, vm, key, public, t.local_port, work, "grep -i -E 'error|fail|warn' /var/log/ch16-langfuse.log | tail -n 20").stdout
            record["log_errors_or_warnings"] = [cloud_session.redact_text(line)[:200] for line in log.splitlines()]
    record["ended_s"] = clock.seconds()
    return record


def health_through(local_port: int, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        try:
            answer = httpx.get(f"http://127.0.0.1:{local_port}/api/public/health", timeout=5)
            last = {"ok": answer.status_code == 200, "status": answer.status_code,
                    "body": answer.json() if answer.status_code == 200 else answer.text[:200]}
            if last["ok"]:
                return last
        except httpx.HTTPError as exc:
            last = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        time.sleep(1)
    return last


def hold_tunnel(s: Any, work: Path, local_port: int, stop_file: Path, *, limit: float = 3300.0) -> dict[str, Any]:
    vm = vm_outputs()
    record: dict[str, Any] = {"vm": vm, "local_port": local_port, "clock": cloud_session.CLOCK, "attempts": []}
    clock = cloud_session.Clock()
    record["started"] = clock.started
    processes: list[Any] = []
    direct = tunnel.Tunnel(vm["instance_id"], 3000, local_port, work, endpoint_id=vm["endpoint_id"])
    try:
        direct.start()
        health = health_through(local_port)
        record["attempts"].append({"path": "open-tunnel to port 3000", "tunnel_opened": True, "health": health, "seconds": clock.seconds()})
    except Exception as exc:
        health = {"ok": False}
        record["attempts"].append({"path": "open-tunnel to port 3000", "tunnel_opened": False,
                                   "error": cloud_session.redact_text(f"{type(exc).__name__}: {exc}")[:300], "seconds": clock.seconds()})
    if health.get("ok"):
        record["path"] = "open-tunnel to port 3000"
        processes.append(direct)
    else:
        direct.stop()
        record["attempts"][-1]["tunnel_log"] = direct.tail()
        ssh_tunnel = tunnel.Tunnel(vm["instance_id"], 22, free_port(), work, endpoint_id=vm["endpoint_id"]).start()
        key, public = tunnel.keypair(work)
        tunnel.push_key(s, vm["instance_id"], vm["availability_zone"], public)
        forward = tunnel.ssh_forward(key, ssh_tunnel.local_port, work, local_port, 3000)
        deadline = time.time() + 30
        while time.time() < deadline and not tunnel.port_open(local_port):
            time.sleep(0.5)
        health = health_through(local_port)
        record["attempts"].append({"path": "open-tunnel to port 22, ssh -L 3000", "health": health, "seconds": clock.seconds()})
        record["path"] = "open-tunnel to port 22, ssh -L 3000" if health.get("ok") else None
        processes += [ssh_tunnel, forward]
    record["health"] = health
    record["langfuse_version"] = (health.get("body") or {}).get("version") if isinstance(health.get("body"), dict) else None
    cloud_session.write_json(work / "tunnel.json", record)
    (work / "tunnel-ready").write_text(json.dumps({"path": record["path"], "local_port": local_port}), encoding="utf-8")
    while clock.seconds() < limit and not stop_file.exists():
        time.sleep(2)
        if any((getattr(p, "proc", p).poll() if hasattr(getattr(p, "proc", p), "poll") else None) is not None for p in processes):
            record["died"] = {"seconds": clock.seconds()}
            break
    record["held_s"] = clock.seconds()
    record["stopped_by"] = "stop file" if stop_file.exists() else ("death" if "died" in record else "limit")
    for p in processes:
        if hasattr(p, "stop"):
            p.stop()
        else:
            p.terminate()
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("wait", "tunnel"))
    parser.add_argument("--out", type=Path, default=cloud_session.results_dir())
    parser.add_argument("--work", type=Path, default=cloud_session.SCRATCH / "vm")
    parser.add_argument("--local-port", type=int, default=3100)
    parser.add_argument("--stop-file", type=Path, default=cloud_session.SCRATCH / "stop-tunnel")
    parser.add_argument("--limit", type=float, default=None)
    args = parser.parse_args(argv)
    cloud_session.require_environment()
    s = cloud_session.session()
    args.work.mkdir(parents=True, exist_ok=True)
    if args.action == "wait":
        record = wait(s, args.work, **({"limit": args.limit} if args.limit else {}))
        cloud_session.merge_json(args.out / "langfuse-vm.json", "wait", record)
        print(f"ready={record['ready']} after launch {record.get('ready_after_launch_s')} s; "
              f"health {record.get('markers', {}).get('health.json')}; pin {record.get('markers', {}).get('pin.txt')}")
    else:
        if args.stop_file.exists():
            args.stop_file.unlink()
        record = hold_tunnel(s, args.work, args.local_port, args.stop_file, **({"limit": args.limit} if args.limit else {}))
        cloud_session.merge_json(args.out / "langfuse-vm.json", "tunnel", record)
        print(f"tunnel path={record['path']} held {record['held_s']} s, stopped by {record['stopped_by']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
