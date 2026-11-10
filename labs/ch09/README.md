# Lab, chapter 9: the skeleton against a local model

Chapter 9 puts a model Larkspur runs itself behind the chapter 5 gateway. The lab has two parts.

- Part 1 is measured. Ollama serves an open-weight model on one workstation GPU, the chapter 5
  gateway routes the alias `larkspur-chat-restricted` to it with chapter 5's rules unchanged, and
  the chapter 5 golden set runs through the gateway against the real model. Two scripts measure
  what the model does (tool choice, facts, latency) and what the GPU does (load time, prompt and
  decode speed).
- Part 2 is validated but not run. Kubernetes manifests describe the production shape: vLLM on
  GPU nodes, weights pinned and read offline, reachable only from the gateway. kubeconform and a
  set of policy tests check them; the lab has no GPU cluster to run them on.

```
run_local_golden.py     part 1: the chapter 5 golden set through the gateway, scored for tool, facts, latency
measure_throughput.py   part 1: load time, prompt and decode speed, and throughput under concurrent load
measure_gpu_memory.py   part 1: what each model takes of the card, read from nvidia-smi
typography_report.py    part 1: look-alike characters in the stored answers, by kind and by place
check_allowlist.py      part 2: the pod's path allowlist, run with a real nginx in front of a stand-in for vLLM
cost/                   the cost crossover: a dated price sheet and the calculator the chapter quotes
results/2026-10-29/     the raw results behind every number in this README
gateway/
  litellm.config.yaml   part 1: the alias on gpt-oss:20b served by Ollama
  litellm.gemma.yaml    part 1: the same alias on gemma4:12b
  litellm.k8s.yaml      part 2: the same alias on the vLLM deployment of k8s/
  gateway_hooks.py      loads chapter 5's callback, so the rules are the same code
k8s/                    part 2: namespace, vLLM deployment with its allowlist proxy, service and PDB, network
                        policy, PodMonitor, KEDA scaler, model volume, approved weight digests
tests/                  28 tests: facts scoring, cost arithmetic, manifest policy and schemas, the allowlist
                        with nginx, two that need the local model
requirements.txt        the chapter 5 pinned set
```

## Setup

The Python environment is chapter 5's: `pip install -r requirements.txt` installs `../ch05/requirements.txt`.
On Windows set `PYTHONUTF8=1` first.

Install Ollama (0.40.13 was used; gpt-oss needs a recent release) and pull the two models:

```
ollama pull gpt-oss:20b      # 13 GB on disk
ollama pull gemma4:12b       # 8 GB on disk
```

Ollama listens on `127.0.0.1:11434` and has no authentication of its own. That is fine on a laptop
and nowhere else, so part 2 replaces it.

## Part 1: run the golden set against a local model

Terminal 1, the gateway (from `labs/ch09/gateway`; the proxy listens on every interface without `--host`):

```
export LITELLM_MASTER_KEY=sk-local-only
GATEWAY_CONFIG=litellm.config.yaml litellm --config litellm.config.yaml --host 127.0.0.1 --port 4011
```

`GATEWAY_CONFIG` must name the file the proxy was started with, because chapter 5's rules read the
deployments' Regions and the fallback chain from it. To switch models, use `litellm.gemma.yaml` in
both places.

Terminal 2:

```
cd labs/ch09
LITELLM_MASTER_KEY=sk-local-only python run_local_golden.py --json local-golden.json
python measure_throughput.py --model gpt-oss:20b --runs 5
```

The golden set asks each question as workflow W2 with data class Internal. The gateway checks the
W2 manifest and logs a cost line per call (zero cost, the self-hosted Region, the serving model),
and the model answers through the harness and the chapter 5 MCP server.

### What a case is scored on

- Tool: the harness made exactly the expected tool call with the expected arguments, or no call
  for the request to scale a deployment. With a real model this stays an exact match.
- Facts: the answer states what the tool returned, meaning the service, the ready and desired pod
  counts, the number of alerts in the window, or that the service doesn't exist. A number may be
  written as a word. The facts come from the fake platform. A first version took every number in
  the rule model's expected sentence and marked most correct answers wrong, because models don't
  repeat the window or the restart count.
- Typographic: counted separately, and it doesn't fail a case. It marks an answer that wrote an
  identifier with a typographic hyphen or quote. A person reads `billing‑worker` with a
  non-breaking hyphen as `billing-worker`, and kubectl does not.

## Results (2026-10-29)

One RTX 5080 with 16 GB, Windows 11, Ollama 0.40.13, one request at a time. Golden-set runs went
through the gateway, and throughput was measured against Ollama directly.

| | gpt-oss:20b | gemma4:12b |
|---|---|---|
| Right tool call | 19 of 20 | 20 of 20 |
| Facts stated | 17 of 20 | 20 of 20 |
| Answers with any typographic character (the scorer's flag) | 19 of 20 | 0 of 20 |
| Answers with a look-alike hyphen inside a service or pod name | 16 of 20 | 0 of 20 |
| Median seconds per case (90th percentile) | 1.17 (2.34) | 1.30 (2.23) |
| Decode speed, tokens per second (median of runs 2 to 5) | 181 | 198 |
| Prompt speed, tokens per second | 5,575 | 1,394 |
| Cold load (file cache not cleared) | 3.1 s | 18.4 s |
| GPU memory the model takes, MiB, 4,096-token context | 12,549 | 8,811 |

Details behind the table:

- gpt-oss asked "How many minutes back would you like to see alerts for claims-api?" instead of
  calling the tool with the default window. That is its one tool miss, and a person might ask the
  same: the system prompt doesn't say which window to use when the question names none.
- gpt-oss's two other fact misses mention the service only inside a pod name
  (`claims-api-7d9f8b6c4-t8w2c`), where the check doesn't count it. A person would mark both
  answers right.
- The typographic count matters in operations. Sixteen of gpt-oss's answers wrote a service or
  pod name with U+2011, the non-breaking hyphen, and an engineer who copies one into a command
  gets "not found". Twelve put U+202F, a narrow no-break space, beside a name. The scorer flags
  19 answers because it counts a typographic character anywhere in an answer, an en dash or a
  curly quote in prose included; `python typography_report.py results/2026-10-29` splits the
  count by character and by place.
- Decode speed is the median of runs 2 to 5 of five. Ollama's `gemma4:12b` tag ships with a draft
  model, so its decode speed most likely includes speculative decoding. Prompt speed comes from
  the same short prompt sent five times, which Ollama may partly serve from its cache; it says
  little about an agent's long prompts. Cold load is the first run's load time with the file
  cache not cleared.
- GPU memory: `python measure_gpu_memory.py --model gpt-oss:20b --model gemma4:12b` reads
  nvidia-smi before and after each model loads (`results/2026-10-29/gpu-memory.json`). The desktop
  held about 1,570 MiB of the 16,303.
- Both models served every case in about a second on one consumer card. That holds for one user
  at a time; the next table has four.

### Under load

Ollama started with `OLLAMA_NUM_PARALLEL=4`, a warm-up at four requests, then each level three
times with 256 output tokens per request; medians of the three:

```
python measure_throughput.py --model gpt-oss:20b --concurrency 1 2 4 --num-predict 256 --repeat 3
```

| Requests at once | gpt-oss:20b, total tok/s | per request | gemma4:12b, total tok/s | per request |
|---|---|---|---|---|
| 1 | 157 | 179 | 162 | 192 |
| 2 | 127 | 69 | 132 | 72 |
| 4 | 369 | 105 | 431 | 137 |

Two requests at once delivered less in total than one, for both models and in every repetition.
Four delivered about two and a half times as much as one, while each request ran 29 percent
(gemma) to 41 percent (gpt-oss) slower. Ollama is a development server and doesn't batch the way
a serving engine does. vLLM batches requests continuously, and part 2 deploys it.

## The cost crossover

`cost/crossover.py` compares hosted inference, priced per token, with GPUs priced per hour for
every hour of the month. `cost/cost-sheet.yaml` holds the prices as printed on 2026-10-28, with
their sources; re-check them before using the result for anything. The book prints only the
numbers derived from them.

```
python cost/crossover.py --gpu aws-p5.4xlarge-h100-on-demand --replicas 2 --monthly-tokens 100e6
```

For gpt-oss-120b on Bedrock's Standard tier against two on-demand H100 instances, at the 5:1
input-to-output mix the golden set produced through the gateway:

| | |
|---|---|
| Hosted price per million tokens, blended | $0.225 |
| Two GPUs for a month | $10,045 |
| Crossover | 44.6 billion tokens a month |
| Throughput the GPUs would have to sustain | about 17,000 tokens a second (2,800 of them output) |
| A workflow at 100 million tokens a month | the GPUs cost about 446 times the hosted bill |

Engineering time, storage, observability and support subscriptions push the crossover further
out; pass them as `--overhead`. Committed-use prices pull it in.

## Part 2: the production shape on Kubernetes

`k8s/` is what the platform team would apply to a GPU node pool:

- `vllm-deployment.yaml`: vLLM v0.31.0 pinned by image digest. The weights' full commit hash is
  the directory they are read from (`--revision` does nothing for a local path), and an init
  container checks every file against `weights-digests.yaml` before vLLM starts. vLLM listens on
  loopback only, so nothing outside the pod reaches it, not even a process on the node; its probes
  run inside its container. `HF_HUB_OFFLINE=1`, the tiktoken encodings gpt-oss would otherwise
  download read from the store (`TIKTOKEN_ENCODINGS_BASE`, per vLLM's gpt-oss recipe), usage
  reporting off (`VLLM_NO_USAGE_STATS=1`), the parser that matches the model, the API key from a
  Secret. One whole GPU per replica on a node pool of its own (label and taint
  `larkspur.example/llm-restricted`), never on a time-sliced GPU (nodes GPU Feature Discovery
  labels with `nvidia.com/gpu.replicas` above 1), two replicas spread across nodes and, where
  the Region allows, zones. Non-root, read-only root filesystem, every capability dropped. A
  second container, nginx, is the pod's only way in.
- `vllm-allowlist.yaml`: that container's configuration. vLLM's API key guards only the routes
  under `/v1`, `/v2`, `/inference` and `/cohere`; `/invocations` runs the same inference without
  a key, and `/pause`, `/abort_requests` and `/update_weights` answer anyone who reaches the port
  (vLLM's security guide, page dated 27 October 2026). The proxy passes three routes from the
  gateway on port 8080 (`/v1/chat/completions`, `/v1/models`, `/health`), `/metrics` alone on
  port 8081, and answers everything else with a 404.
- `vllm-service.yaml`: port 8080, named `api` like the container port, because EKS's network
  policy support requires the Service port to equal the container port; and a PodDisruptionBudget.
- `networkpolicy.yaml`: the gateway's pods in to port 8080, Prometheus in to port 8081, and
  nothing out. On EKS it takes effect only with `"enableNetworkPolicy": "true"` on the VPC CNI
  add-on, and in the default standard mode a new pod starts allowing everything until its
  policies are in place; `NETWORK_POLICY_ENFORCING_MODE=strict` starts it denied.
- `vllm-podmonitor.yaml`: the Prometheus Operator scrapes `/metrics` through port 8081, which is
  where KEDA's queue metric comes from.
- `namespace.yaml`: Pod Security `restricted` enforced. The read-only root filesystem comes from
  the Deployment; the standard doesn't require one.
- `keda-scaledobject.yaml`: two to four replicas on `vllm:num_requests_waiting`, at an average
  of four waiting per replica (KEDA's default `AverageValue`), so the third replica is asked for
  at about nine. KEDA's `cooldownPeriod` applies only when scaling to zero, so the pace of
  scale-down is set on the HPA: ten minutes after the queue drains, one replica every five.
- `model-store.yaml`: the shared file system the weights live on (ReadOnlyMany; EFS or FSx for
  Lustre on EKS), one directory per approved revision plus the tiktoken files.
- `weights-digests.yaml`: the approved SHA-256 list for the ten files the engine needs (no
  `original/` or `metal/` copies) and the two tiktoken files.

`gateway/litellm.k8s.yaml` points the same alias at the service on port 8080, with the revision
in the deployment's id so the gateway's span names it, and the tests check that chapter 5's
rules accept it for Restricted data from the incident workflow. The chapter 5 gateway also
gives every request to a self-hosted alias a `cache_salt` naming the workflow, so two
workflows sharing the replicas never share cached prompt prefixes; a caller can't choose it.

Validate:

```
kubeconform -strict -summary -kubernetes-version 1.35.0 \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  -skip Kustomization k8s/*.yaml
```

```
Summary: 11 resources found in 10 files - Valid: 10, Invalid: 0, Errors: 0, Skipped: 1
```

The result is the same against 1.37.0, with kubeconform v0.8.0. `tests/test_manifests.py` runs it
when the binary is on `PATH` or named by `KUBECONFORM`, and skips it otherwise.

### The allowlist, run

The proxy is the one part of part 2 that runs without a GPU cluster:

```
python check_allowlist.py --nginx /usr/sbin/nginx --json allowlist.json
```

It starts the ConfigMap's `nginx.conf`, with only its file paths moved to a temporary directory,
in front of a stand-in for vLLM on `127.0.0.1:8000`, and sends thirteen requests. On 2026-10-29,
with nginx 1.30.6 for Windows from nginx.org (signature checked), all thirteen came back as
designed: the three routes and `/metrics` passed, a streamed answer arrived as it was written,
and `/invocations`, `/update_weights`, `/pause`, `/tokenize`, `/v1/completions`, a `../` path and
`/metrics` on the API port all got a 404 (`results/2026-10-29/allowlist.json`).

## Test

```
cd labs/ch09
python -m pytest tests -q
```

28 tests. `test_facts.py`, `test_cost.py` and the policy checks in `test_manifests.py` need
nothing else. The two schema checks need kubeconform, `test_allowlist.py` needs nginx (on `PATH`
or named by `NGINX`), and `test_local.py` needs Ollama with gpt-oss:20b running; each skips when
its dependency is missing.

## Licenses

gpt-oss-20b is Apache 2.0, with a usage policy that asks for compliance with applicable law.
Gemma 4 is Apache 2.0, with Google's prohibited-use policy linked. Ollama is MIT and vLLM is
Apache 2.0. The chapter covers the model licenses that do carry conditions.

## Cost and teardown

Nothing leaves the machine. The models take 21 GB of disk: `ollama rm gpt-oss:20b gemma4:12b`
removes them, and `ollama stop <model>` frees the GPU memory without deleting anything. Stop the
gateway with Ctrl-C.
