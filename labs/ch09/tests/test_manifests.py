"""Part 2: the Kubernetes manifests for vLLM, checked without a cluster.

Two kinds of check. The policy checks below read the YAML and assert what a review would ask:
pinned images and weights, no network path out, only the gateway in and only through the path
allowlist, Prometheus on the metrics port alone, non-root, GPU requested, the tool parser that
matches the model, probes, a gateway entry the chapter 5 rules accept. The schema check runs
kubeconform (strict, Kubernetes 1.35 and 1.37, the KEDA and Prometheus Operator CRDs from the
datree catalog) when the binary is on PATH or named by KUBECONFORM, and is skipped otherwise.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

LAB = Path(__file__).resolve().parents[1]
K8S = LAB / "k8s"
CH05 = LAB.parent / "ch05"
for folder in (CH05 / "gateway", CH05 / "manifest"):
    sys.path.insert(0, str(folder))


def docs(name: str) -> list[dict]:
    return [d for d in yaml.safe_load_all((K8S / name).read_text(encoding="utf-8")) if d]


DEPLOYMENT = docs("vllm-deployment.yaml")[0]
POD = DEPLOYMENT["spec"]["template"]["spec"]
CONTAINER, PROXY = POD["containers"]
ARGS = dict(a.removeprefix("--").split("=", 1) if "=" in a else (a.removeprefix("--"), True)
            for a in CONTAINER["args"])
ENV = {e["name"]: e for e in CONTAINER["env"]}
[INIT] = POD["initContainers"]
NGINX = docs("vllm-allowlist.yaml")[0]["data"]["nginx.conf"]
DIGESTS = docs("weights-digests.yaml")[0]
REVISION = ARGS["model"].rsplit("/", 1)[1]


def digest_list(key: str) -> dict[str, str]:
    """`<sha256>  <file>` lines of a digest list, as {file: sha256}."""
    return {name: digest for digest, name in
            (line.split("  ", 1) for line in DIGESTS["data"][key].splitlines() if line.strip())}


def server_blocks(conf: str) -> dict[int, str]:
    """The body of each nginx server block, by the port it listens on."""
    blocks = {}
    for body in re.findall(r"server \{(.*?)\n  \}", conf, flags=re.S):
        port = int(re.search(r"listen (\d+);", body).group(1))
        blocks[port] = body
    return blocks


def test_images_are_pinned_by_digest() -> None:
    assert re.fullmatch(r"docker\.io/vllm/vllm-openai@sha256:[0-9a-f]{64}", CONTAINER["image"])
    assert re.fullmatch(r"docker\.io/nginxinc/nginx-unprivileged@sha256:[0-9a-f]{64}", PROXY["image"])


def test_the_weights_path_is_the_pin_and_the_bytes_are_checked_before_start() -> None:
    # --revision does nothing for a local directory, so the revision is the directory itself.
    assert "revision" not in ARGS
    assert re.fullmatch(r"[0-9a-f]{40}", REVISION)  # the full commit hash, not a branch
    assert ARGS["model"] == f"/models/openai/gpt-oss-20b/{REVISION}"
    for labelled in (docs("model-store.yaml")[0], DIGESTS):
        assert labelled["metadata"]["labels"]["larkspur.example/revision"] == REVISION
    script = INIT["args"][0]
    assert f"cd /models/openai/gpt-oss-20b/{REVISION} &&" in script
    assert "sha256sum -c /digests/gpt-oss-20b.sha256" in script and "sha256sum -c /digests/tiktoken.sha256" in script
    assert re.fullmatch(r"docker\.io/library/busybox@sha256:[0-9a-f]{64}", INIT["image"])
    weights = digest_list("gpt-oss-20b.sha256")
    assert all(re.fullmatch(r"[0-9a-f]{64}", d) for d in weights.values())
    assert not any(name.startswith(("original/", "metal/")) for name in weights)  # one copy of the weights
    assert any(name.endswith(".safetensors") for name in weights)
    assert not any(name.endswith((".bin", ".pt", ".pth", ".pkl")) for name in weights)  # nothing pickled
    assert ENV["HF_HUB_OFFLINE"]["value"] == "1"
    mounts = {m["name"]: m for m in CONTAINER["volumeMounts"] + INIT["volumeMounts"]}
    assert mounts["models"]["readOnly"] is True and mounts["digests"]["readOnly"] is True
    claim = [v for v in POD["volumes"] if v["name"] == "models"][0]["persistentVolumeClaim"]
    assert claim["readOnly"] is True


def test_gpt_oss_reads_its_tiktoken_encodings_from_the_store() -> None:
    # The Harmony library downloads them otherwise, and the pod has no egress.
    assert ENV["TIKTOKEN_ENCODINGS_BASE"]["value"] == "/models/tiktoken"
    assert set(digest_list("tiktoken.sha256")) == {"o200k_base.tiktoken", "cl100k_base.tiktoken"}


def test_the_engine_does_not_report_usage() -> None:
    # vLLM sends anonymous usage data by default. The network policy would block it; this stops it at the source.
    assert ENV["VLLM_NO_USAGE_STATS"]["value"] == "1"


def test_only_the_gateway_gets_in_and_nothing_gets_out() -> None:
    policy = docs("networkpolicy.yaml")[0]["spec"]
    assert policy["policyTypes"] == ["Ingress", "Egress"] and policy["egress"] == []
    gateway, prometheus = policy["ingress"]
    [peer] = gateway["from"]
    assert peer["namespaceSelector"]["matchLabels"] == {"kubernetes.io/metadata.name": "llm-gateway"}
    assert peer["podSelector"]["matchLabels"] == {"app": "litellm"}
    assert gateway["ports"] == [{"port": 8080, "protocol": "TCP"}]  # the allowlist's API port
    [peer] = prometheus["from"]
    assert peer["namespaceSelector"]["matchLabels"] == {"kubernetes.io/metadata.name": "monitoring"}
    assert prometheus["ports"] == [{"port": 8081, "protocol": "TCP"}]  # the allowlist's metrics port
    # vLLM listens on loopback and exposes no port, so nothing outside the pod reaches it, not even
    # a process on the node, which network policies always admit.
    assert ARGS["host"] == "127.0.0.1" and "ports" not in CONTAINER
    assert all(p["port"] != 8000 for rule in policy["ingress"] for p in rule["ports"])
    proxy_ports = {p["name"]: p["containerPort"] for p in PROXY["ports"]}
    assert proxy_ports == {"api": 8080, "metrics": 8081}
    service = docs("vllm-service.yaml")[0]
    assert service["spec"]["type"] == "ClusterIP"
    # EKS: the Service port must equal the container port, and named ports must match.
    assert service["spec"]["ports"] == [{"name": "api", "port": 8080, "targetPort": "api"}]
    monitor = docs("vllm-podmonitor.yaml")[0]["spec"]
    assert [e["port"] for e in monitor["podMetricsEndpoints"]] == ["metrics"]


def test_the_allowlist_passes_three_routes_and_the_metrics() -> None:
    # vLLM's API key guards only /v1, /v2, /inference and /cohere; /invocations and the
    # operational endpoints answer anyone, so the proxy names every route it passes on.
    blocks = server_blocks(NGINX)
    assert set(blocks) == {8080, 8081}
    exact = {port: set(re.findall(r"location = (\S+) \{ proxy_pass http://vllm; \}", body))
             for port, body in blocks.items()}
    assert exact == {8080: {"/v1/chat/completions", "/v1/models", "/health"}, 8081: {"/metrics"}}
    for body in blocks.values():
        assert "location / { return 404; }" in body
        assert len(re.findall(r"location ", body)) == len(exact[int(re.search(r"listen (\d+);", body).group(1))]) + 1
    assert re.search(r"upstream vllm \{ server 127\.0\.0\.1:8000; keepalive \d+; \}", NGINX)
    assert "invocations" not in NGINX and "update_weights" not in NGINX


def test_the_pod_runs_restricted() -> None:
    namespace = docs("namespace.yaml")[0]
    assert namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"
    assert POD["securityContext"]["runAsNonRoot"] is True
    assert POD["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert POD["automountServiceAccountToken"] is False
    for container in (INIT, CONTAINER, PROXY):
        sc = container["securityContext"]
        assert sc["allowPrivilegeEscalation"] is False and sc["capabilities"]["drop"] == ["ALL"]
        assert sc["readOnlyRootFilesystem"] is True
    assert not POD.get("hostNetwork") and not POD.get("hostPID")


def test_one_gpu_per_replica_and_more_than_one_replica() -> None:
    assert CONTAINER["resources"]["limits"]["nvidia.com/gpu"] == 1
    assert DEPLOYMENT["spec"]["replicas"] >= 2
    pdb = docs("vllm-service.yaml")[1]
    assert pdb["kind"] == "PodDisruptionBudget" and pdb["spec"]["minAvailable"] == 1
    scaler = docs("keda-scaledobject.yaml")[0]["spec"]
    assert scaler["minReplicaCount"] >= 2 and "num_requests_waiting" in scaler["triggers"][0]["metadata"]["query"]
    # cooldownPeriod and activation only matter when scaling to zero; the pace of scale-down is the HPA's.
    assert "cooldownPeriod" not in scaler and "activationThreshold" not in scaler["triggers"][0]["metadata"]
    down = scaler["advanced"]["horizontalPodAutoscalerConfig"]["behavior"]["scaleDown"]
    assert down["stabilizationWindowSeconds"] >= 600
    assert down["policies"] == [{"type": "Pods", "value": 1, "periodSeconds": 300}]


def test_whole_gpus_on_a_node_pool_of_their_own() -> None:
    assert POD["nodeSelector"] == {"larkspur.example/node-pool": "llm-restricted"}
    assert {t["key"] for t in POD["tolerations"]} == {"larkspur.example/llm-restricted", "nvidia.com/gpu"}
    terms = POD["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"]
    # GPU Feature Discovery labels a time-sliced node with nvidia.com/gpu.replicas; either term admits a node.
    assert [t["matchExpressions"] for t in terms] == [
        [{"key": "nvidia.com/gpu.replicas", "operator": "DoesNotExist"}],
        [{"key": "nvidia.com/gpu.replicas", "operator": "In", "values": ["1"]}]]
    spread = {c["topologyKey"]: c["whenUnsatisfiable"] for c in POD["topologySpreadConstraints"]}
    assert spread == {"kubernetes.io/hostname": "DoNotSchedule", "topology.kubernetes.io/zone": "ScheduleAnyway"}


def test_tool_calling_matches_the_model() -> None:
    # gpt-oss speaks Harmony; vLLM's parser for it is called "openai", and tool_choice="auto"
    # needs --enable-auto-tool-choice.
    assert ARGS["enable-auto-tool-choice"] is True and ARGS["tool-call-parser"] == "openai"
    assert ARGS["served-model-name"] == "gpt-oss-20b"


def test_the_api_key_comes_from_a_secret_and_the_probes_exist() -> None:
    assert ENV["VLLM_API_KEY"]["valueFrom"]["secretKeyRef"]["name"] == "vllm-api-key"
    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
        command = CONTAINER[probe]["exec"]["command"]  # inside the container, where loopback is vLLM
        assert command[:2] == ["python3", "-c"] and "http://127.0.0.1:8000/health" in command[2]
        assert CONTAINER[probe]["timeoutSeconds"] >= 5
    assert PROXY["readinessProbe"]["httpGet"] == {"path": "/health", "port": "api"}  # through the allowlist
    assert PROXY["livenessProbe"]["tcpSocket"] == {"port": "api"}


def test_the_gateway_entry_passes_the_chapter_5_rules() -> None:
    import gateway_rules
    import manifest

    destinations, _ = gateway_rules.read_config(LAB / "gateway" / "litellm.k8s.yaml")
    [dest] = destinations["larkspur-chat-restricted"]
    assert gateway_rules.may_receive("restricted", dest)  # self-hosted, in Canada
    manifests = manifest.load_manifests(CH05 / "manifest")
    decision = gateway_rules.decide("larkspur-chat-restricted", {"workflow": "w3-incident", "data_class": "restricted"},
                                    "0af7651916cd43dd8448eb211c80319c", manifests, destinations, {})
    assert decision == gateway_rules.Decision()
    config = yaml.safe_load((LAB / "gateway" / "litellm.k8s.yaml").read_text(encoding="utf-8"))
    entry = config["model_list"][0]["litellm_params"]
    assert entry["api_base"] == "http://vllm-gpt-oss-20b.llm-serving.svc:8080/v1"  # the Service's port
    assert entry["api_key"] == "os.environ/VLLM_API_KEY"
    # The deployment id carries the revision, so the gateway's span names the weights that answered.
    assert config["model_list"][0]["model_info"]["id"] == f"vllm-gpt-oss-20b-{REVISION[:7]}"


def kubeconform() -> str | None:
    return os.environ.get("KUBECONFORM") or shutil.which("kubeconform")


@pytest.mark.skipif(kubeconform() is None, reason="kubeconform is not installed")
@pytest.mark.parametrize("version", ["1.35.0", "1.37.0"])
def test_manifests_validate_against_the_kubernetes_schemas(version: str) -> None:
    files = sorted(p.name for p in K8S.glob("*.yaml"))
    result = subprocess.run(
        [kubeconform(), "-strict", "-summary", "-kubernetes-version", version,
         "-schema-location", "default",
         "-schema-location", "https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/"
                             "{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json",
         "-skip", "Kustomization", *files],
        cwd=K8S, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Invalid: 0, Errors: 0" in result.stdout
