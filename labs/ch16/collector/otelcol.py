"""Start and stop the pinned Collector with collector/config.yaml and a run's overlay.

Chapter 16, step 3 (companion #14, O-D3). The local run and the tests start the Collector the same way:
the binary `fetch.verified` hands over, the lab's config.yaml as it is, and a second config file written for
the run that changes only what a run on one machine needs (the ports, the span file, CloudWatch's endpoint
pointed at the fake, a shorter decision_wait in the tests). The Collector merges the files in order, later
over earlier, maps key by key and lists whole (its --config flag), so config.yaml's processors and policies
reach every run unchanged.

The environment the Collector gets is built here, never inherited: the Langfuse keys and the AWS
credentials are dummies, and the AWS SDK is pointed away from this machine's shared files and the instance
metadata service, so no real key can reach the SigV4 signer.

Step 3b runs the workflows on the local models with CloudWatch and Langfuse off, which step 7 turns on:
`local_config` is config.yaml without the two exporters, their authenticators, and Langfuse's pipeline, so
nothing in the Collector can send a span off the machine, and `local_environment` holds no credential at all.
Its overlay (`local_overlay`) adds the tap and a sink, a fake beside the span file that records when each kept
span left the Collector.
"""

from __future__ import annotations

import copy
import os
import signal
import socket
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.yaml"
FEATURE_GATES = ("processor.tailsamplingprocessor.usetracestate", "processor.tailsamplingprocessor.recordpolicy")
# Dummies, recognizable as such: the signer signs with them and the fakes check the result.
DUMMY_ACCESS_KEY_ID = "LARKSPURLABDUMMYKEY0"
DUMMY_SECRET_ACCESS_KEY = "lab-dummy-secret-not-a-key"
DUMMY_LANGFUSE_PUBLIC_KEY = "pk-lab-dummy"
DUMMY_LANGFUSE_SECRET_KEY = "sk-lab-dummy"
# Passed through from this process; everything else in the Collector's environment is set below.
PASS_THROUGH = ("SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "PATH")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def environment(*, span_file: Path, langfuse_endpoint: str, share_percent: float | None = None,
                work: Path) -> dict[str, str]:
    """The Collector's whole environment: dummies for every credential, nothing from this machine's AWS setup."""
    env = {name: os.environ[name] for name in PASS_THROUGH if name in os.environ}
    env |= {
        "LANGFUSE_OTLP_ENDPOINT": langfuse_endpoint,
        "LANGFUSE_PUBLIC_KEY": DUMMY_LANGFUSE_PUBLIC_KEY,
        "LANGFUSE_SECRET_KEY": DUMMY_LANGFUSE_SECRET_KEY,
        "LARKSPUR_SPAN_FILE": str(span_file),
        "AWS_ACCESS_KEY_ID": DUMMY_ACCESS_KEY_ID,
        "AWS_SECRET_ACCESS_KEY": DUMMY_SECRET_ACCESS_KEY,
        # No profile, no shared files, no instance metadata: the static dummies above are all there is.
        "AWS_SHARED_CREDENTIALS_FILE": str(work / "no-aws-credentials"),
        "AWS_CONFIG_FILE": str(work / "no-aws-config"),
        "AWS_EC2_METADATA_DISABLED": "true",
    }
    if share_percent is not None:
        env["LARKSPUR_TRACE_SHARE_PERCENT"] = f"{share_percent:g}"
    return env


def overlay(*, otlp_port: int, cloudwatch_url: str, metrics_port: int, decision_wait: str | None = None,
            tap_url: str | None = None) -> dict[str, Any]:
    """The run's second config file: ports, CloudWatch's fake, the Collector's own metrics, and a tap.

    The tap is the local run's instrument, not part of config.yaml: a pipeline of its own from the same
    receiver, with no processor, exporting to a third fake, so the run can see what the processes sent
    before the content drop and when it reached the Collector.
    """
    out: dict[str, Any] = {
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{otlp_port}"}}}},
        "exporters": {"otlp_http/cloudwatch": {"traces_endpoint": f"{cloudwatch_url}/v1/traces"}},
        "service": {"telemetry": {"metrics": {"readers": [{"pull": {"exporter": {"prometheus": {
            "host": "127.0.0.1", "port": metrics_port}}}}]}}},
    }
    if decision_wait:
        out["processors"] = {"tail_sampling": {"decision_wait": decision_wait}}
    if tap_url:
        out["exporters"]["otlp_http/tap"] = {"endpoint": tap_url, "compression": "none"}
        out["service"]["pipelines"] = {"traces/tap": {"receivers": ["otlp"], "exporters": ["otlp_http/tap"]}}
    return out


# --- step 3b: the workflows on the local models, with CloudWatch and Langfuse off ---------------------------

CLOUD_EXPORTERS = ("otlp_http/cloudwatch", "otlp_http/langfuse")
CLOUD_PIPELINE = "traces/langfuse"
CLOUD_PROCESSOR = "transform/langfuse-cost"  # feeds Langfuse's pipeline alone


def local_config(cfg: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """config.yaml with CloudWatch and Langfuse off. The content drop, the tail sampler and its policies, the
    batch, the forward connector and the span file stay as they are. Removed, and nothing else: the two
    exporters, the two authenticators only they use, Langfuse's pipeline, and the cost copy that feeds it."""
    out = copy.deepcopy(dict(cfg) if cfg is not None else yaml.safe_load(CONFIG.read_text(encoding="utf-8")))
    for name in CLOUD_EXPORTERS:
        del out["exporters"][name]
    del out["extensions"]
    del out["service"]["extensions"]
    del out["processors"][CLOUD_PROCESSOR]
    del out["service"]["pipelines"][CLOUD_PIPELINE]
    stores = out["service"]["pipelines"]["traces/stores"]
    stores["exporters"] = [name for name in stores["exporters"] if name not in CLOUD_EXPORTERS]
    return out


def write_local_config(work: Path) -> Path:
    path = Path(work) / "config.local.yaml"
    path.write_text(yaml.safe_dump(local_config(), sort_keys=False), encoding="utf-8", newline="\n")
    return path


def local_environment(*, span_file: Path, share_percent: float | None = None) -> dict[str, str]:
    """The environment `local_config` needs: the span file and the share. No credential of any kind."""
    env = {name: os.environ[name] for name in PASS_THROUGH if name in os.environ}
    env["LARKSPUR_SPAN_FILE"] = str(span_file)
    if share_percent is not None:
        env["LARKSPUR_TRACE_SHARE_PERCENT"] = f"{share_percent:g}"
    return env


def local_overlay(*, otlp_port: int, metrics_port: int, tap_url: str, sink_url: str, decision_wait: str | None = None,
                  after_root: str | None = None) -> dict[str, Any]:
    """The overlay for a run on the local models: the receiver's port, the Collector's own metrics, the tap, and
    a sink. The sink is the run's instrument on the other side: an exporter beside the span file, after the
    sampler, to a fake on 127.0.0.1, so the run sees when each kept span left. `after_root` sets
    decision_wait_after_root_received, which can only bring a decision forward: decision_wait stays the cap."""
    tail = {key: value for key, value in (("decision_wait", decision_wait),
                                         ("decision_wait_after_root_received", after_root)) if value}
    out: dict[str, Any] = {
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{otlp_port}"}}}},
        "exporters": {"otlp_http/tap": {"endpoint": tap_url, "compression": "none"},
                      "otlp_http/sink": {"endpoint": sink_url, "compression": "none"}},
        "service": {
            "telemetry": {"metrics": {"readers": [{"pull": {"exporter": {"prometheus": {
                "host": "127.0.0.1", "port": metrics_port}}}}]}},
            "pipelines": {"traces/tap": {"receivers": ["otlp"], "exporters": ["otlp_http/tap"]},
                          "traces/stores": {"exporters": ["file", "otlp_http/sink"]}},
        },
    }
    if tail:
        out["processors"] = {"tail_sampling": tail}
    return out


class Collector:
    """The pinned binary running config.yaml plus one overlay, until `stop`."""

    def __init__(self, exe: Path, work: Path, env: Mapping[str, str], extra: Mapping[str, Any],
                 *, config: Path = CONFIG, gates: tuple[str, ...] = FEATURE_GATES) -> None:
        self.exe, self.work, self.env, self.config, self.gates = exe, work, dict(env), config, gates
        self.overlay_path = work / "overlay.yaml"
        self.overlay_path.write_text(yaml.safe_dump(dict(extra), sort_keys=False), encoding="utf-8", newline="\n")
        self.log_path = work / "otelcol.log"
        self.otlp_port = int(extra["receivers"]["otlp"]["protocols"]["http"]["endpoint"].rsplit(":", 1)[1])
        self.proc: subprocess.Popen | None = None
        self.started_at: float | None = None

    @property
    def args(self) -> list[str]:
        return [str(self.exe), f"--config=file:{self.config}", f"--config=file:{self.overlay_path}",
                f"--feature-gates={','.join(self.gates)}"]

    def start(self, timeout: float = 30.0) -> Collector:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self._log = self.log_path.open("ab")
        self.proc = subprocess.Popen(self.args, env=self.env, cwd=str(self.work), stdout=self._log,
                                     stderr=subprocess.STDOUT, creationflags=flags)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self._log.close()
                raise RuntimeError(f"the Collector exited with {self.proc.returncode}; see {self.log_path}")
            try:
                with socket.create_connection(("127.0.0.1", self.otlp_port), timeout=0.5):
                    self.started_at = time.time()
                    return self
            except OSError:
                time.sleep(0.2)
        self.stop()
        raise RuntimeError(f"the Collector didn't open 127.0.0.1:{self.otlp_port} in {timeout:.0f} s; see {self.log_path}")

    def stop(self, timeout: float = 30.0) -> int | None:
        """Stop it the way an operator would, so the exporters flush; kill it only if that fails."""
        if self.proc is None:
            return None
        if self.proc.poll() is None:
            self.proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        self._log.close()
        return self.proc.returncode

    def __enter__(self) -> Collector:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def log(self) -> str:
        return self.log_path.read_text(encoding="utf-8", errors="replace") if self.log_path.exists() else ""


def validate(exe: Path, env: Mapping[str, str], *configs: Path,
             gates: tuple[str, ...] = FEATURE_GATES) -> subprocess.CompletedProcess:
    """The binary's own `validate` command on config.yaml (and any overlay)."""
    args = [str(exe), "validate", *(f"--config=file:{c}" for c in configs), f"--feature-gates={','.join(gates)}"]
    return subprocess.run(args, env=dict(env), capture_output=True, text=True, timeout=120)

