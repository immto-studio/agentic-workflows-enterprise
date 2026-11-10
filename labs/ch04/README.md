# Lab, chapter 4: the identity chain, an injection and a poisoned tool, contained

Companion to chapter 4. Local Python 3.12 or newer, standard library plus pytest. No API key, no cloud.

The lab takes the agent loop from `labs/ch01` and wires in the identity chain: one identity for the workflow, one per tool, with explicit scopes. Then it attacks the loop twice, with a fake model that obeys any instruction it reads, and shows that the structural controls contain both attacks.

## Files

| File | What it is |
|---|---|
| `identity.py` | Three identities as plain objects: `WORKFLOW` (may invoke two tools, holds no cluster scope), `POD_READER` (`pods:get`), `DEPLOYMENT_RESTARTER` (`deployments:restart`, requires an approval token). `ApprovalToken` covers one tool call with one exact argument set, in one run (its trace id), until it expires, and only when someone other than the requester approved it. |
| `tools.py` | The tool catalog. Each tool is bound to one identity and checks its scope. `PINNED` holds the SHA-256 of every reviewed tool definition. |
| `harness.py` | The loop. Four controls, none of which consult the model: pinned-hash check on the catalog, allowlist and argument check, per-tool identity lookup, approval gate. Every refusal is logged with the trace id of the run; every call that ran is logged with the tool identity, the person who asked and the approver. |
| `attacks.py` | Attack A, a tool result with an indirect prompt injection. Attack B, a tool description with a smuggled instruction. `obedient_model`, which falls for both. The demo. |
| `tests/test_containment.py` | Proof that the attacks succeed at the model layer and are refused by the harness. |

## Run

```
python attacks.py
```

Expected output (the log goes to stderr and the results to stdout, so the lines may interleave):

```
INFO ch04.harness ran trace_id=demo-baseline tool=get_pod_status identity=tool:get_pod_status requested_by=sam.okafor@larkspur.example approved_by=-
INFO ch04.harness ran trace_id=demo-injection tool=get_pod_status identity=tool:get_pod_status requested_by=sam.okafor@larkspur.example approved_by=-
WARNING ch04.harness refused trace_id=demo-injection tool=restart_deployment reason=needs an approval token
WARNING ch04.harness refused trace_id=demo-poisoning tool=get_pod_status reason=definition hash does not match the pinned hash
INFO ch04.harness ran trace_id=demo-stale tool=get_pod_status identity=tool:get_pod_status requested_by=sam.okafor@larkspur.example approved_by=-
WARNING ch04.harness refused trace_id=demo-stale tool=restart_deployment reason=the approval is for another run
WARNING ch04.harness refused trace_id=demo-self tool=restart_deployment reason=the requester cannot approve their own call
INFO ch04.harness ran trace_id=demo-approved tool=restart_deployment identity=tool:restart_deployment requested_by=sam.okafor@larkspur.example approved_by=tomasz.nowak@larkspur.example
baseline:   claims-api has 2 of 3 pods ready.
injection:  Refused: restart_deployment: needs an approval token.
poisoning:  Refused: get_pod_status: definition hash does not match the pinned hash.
stale:      Refused: restart_deployment: the approval is for another run.
self:       Refused: restart_deployment: the requester cannot approve their own call.
approved:   claims-api restarted.
```

The demo passes fixed trace ids so the output is reproducible. In the book's workflows the harness creates the trace id when a run starts and passes it to every hop, so a refusal in the log joins up with the rest of the trace.

## What to look at

- The model layer was never trusted. `obedient_model` does whatever the last thing it read told it to do, and the tests prove it: the injected result and the poisoned description both make it ask for `restart_deployment`. Containment comes from the harness, which never reads the model's reasons, only its requested call.
- Attack A cannot be caught by a hash. The tool definition is honest; the data it returned was written by an attacker. The approval gate holds: `restart_deployment` runs under `DEPLOYMENT_RESTARTER`, which requires a token, and tokens are minted by a person and handed to the harness, never to the model.
- A token is narrow on four counts. It covers one tool with one exact argument set, in the one run whose trace id it carries, until it expires (fifteen minutes by default), and only when the approver is not the person who asked. The demo's `stale` run shows last week's approval refused for today's injected restart, and `self` shows Sam unable to approve Sam's own request. The approver is in the log line of the call that ran.
- Attack B is caught before the model reads anything. The harness hashes every tool definition in the catalog it was given and compares it with `PINNED`. One extra sentence in a description changes the hash and the run is refused.
- The argument check is also the anti-forgery check. A model that tries to pass `approval_token` as an argument is refused because the arguments do not match the declared set.
- Identities are separate. `WORKFLOW` has no cluster scope at all. `restart_deployment` raises `PermissionError` if handed the reader identity. In the cloud chapters these objects become IAM roles, service accounts and Entra agent identities; the shape is the same.

## Test

```
python -m pytest tests -q
```

Expected: 18 passed.

If `test_shipped_catalog_matches_pins` fails, somebody changed a tool definition. Read the diff, then re-pin with `python tools.py` and paste the output into `PINNED`.

## Cost and teardown

Nothing is created. There is nothing to tear down.

Last run: 2026-10-29, Python 3.12.9 on Windows 11, pytest 9.2.0.
