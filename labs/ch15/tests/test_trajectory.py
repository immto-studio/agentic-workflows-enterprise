"""The trajectory layer (E-D8) on small fixtures and on kept runs changed by hand: each check passes the path
a workflow should take and fails the ones it shouldn't, with no model."""

from __future__ import annotations

import copy

import deterministic
import registry
import trajectory
from conftest import kept


def run_checks(workflow: str, case: dict, outputs: list[dict]) -> list[dict]:
    with registry.loaded(workflow) as mods:
        ctx = deterministic.context(workflow, mods) | trajectory.context(workflow, mods)
        return [trajectory.check_case(workflow, mods, case, output, ctx) for output in outputs]


def failing(verdict: dict) -> list[str]:
    return sorted(name for name, c in verdict["checks"].items() if c["ok"] is False)


def test_skeleton_the_exact_sequence_the_allowlist_and_the_budget(cases) -> None:
    right = ["get_pod_status", {"service": "claims-api"}]
    alerts = ["get_recent_alerts", {"service": "claims-api", "minutes": 60}]
    restart = ["restart_deployment", {"service": "claims-api"}]
    outputs = [{"calls": [right]}, {"calls": [right, alerts]}, {"calls": [restart]}, {"calls": [right] * 6}]
    ok, extra, write, looping = run_checks("skeleton", cases["skeleton"]["pods-claims-api"], outputs)
    assert ok["pass"] is True and failing(ok) == []
    assert failing(extra) == ["sequence"]
    assert failing(write) == ["allowed", "forbidden", "sequence"]  # a never-list tool the runner doesn't allow
    assert failing(looping) == ["budget", "sequence"]  # more calls than chapter 1's five steps


def w1_output(classes: list[str], answer: str = "an answer") -> dict:
    alias = {"restricted": "larkspur-chat-restricted"}
    return {"answer": answer, "calls": [{"data_class": c, "alias": alias.get(c, "larkspur-chat")} for c in classes],
            "model_calls": [{"prompt_tokens": 1}] * len(classes)}


def test_w1_the_searches_the_route_and_the_page_never_seen(cases) -> None:
    refused = cases["w1"]["gq-01/oncall.engineer"]
    ok, too_many, leaked = run_checks("w1", refused, [w1_output(["internal"] * 3), w1_output(["internal"] * 4),
                                                      w1_output(["internal", "restricted", "restricted"])])
    assert ok["pass"] is True and ok["measures"] == {"searches": 2}
    assert failing(too_many) == ["budget"]  # three searches against W1-D22's two
    assert failing(leaked) == ["forbidden"]  # the Restricted page reached the model for the on-call engineer
    member = cases["w1"]["gq-01/vault.custodian"]
    misrouted = w1_output(["restricted"] * 2)
    misrouted["calls"][1]["alias"] = "larkspur-chat"
    dropped = w1_output(["restricted", "internal"])
    right, wrong_alias, lowered = run_checks("w1", member, [w1_output(["restricted"] * 2), misrouted, dropped])
    assert right["pass"] is True and right["checks"]["forbidden"]["ok"] is None  # the member may read the page
    assert failing(wrong_alias) == ["route"] and failing(lowered) == ["route"]
    assert right["checks"]["sequence"]["ok"] is None  # W1's kept results hold the calls, not the searches


def w2_output(reads: list[tuple[str, bool]], answer: str = "an answer") -> dict:
    return {"answer": answer, "calls": [{"data_class": "internal", "alias": "larkspur-chat"}] * (len(reads) + 1),
            "read_events": [{"tool": t, "ok": ok, "args": {"service": "claims-api"}} for t, ok in reads]}


def test_w2_the_reads_the_case_names_logs_last_and_four_at_most(cases) -> None:
    health = cases["w2"]["w2-01"]  # names get_pod_status
    outputs = [w2_output([("get_pod_status", True)]),
               w2_output([("get_pod_status", True), ("get_recent_alerts", True), ("query_metric", True)]),
               w2_output([("get_pod_status", True), ("restart_deployment", False)]),
               w2_output([("get_pod_status", True)] * 5)]
    ok, over_read, never, over_budget = run_checks("w2", health, outputs)
    assert ok["pass"] is True and ok["measures"]["expected_reads"]["within"] is True
    assert failing(over_read) == ["allowed"] and over_read["checks"]["allowed"]["detail"] == ["get_recent_alerts",
                                                                                               "query_metric"]
    assert failing(never) == ["forbidden"]
    assert failing(over_budget) == ["budget"]
    logs = cases["w2"]["w2-04"]  # names get_pod_logs and search_logs
    in_order, late = run_checks("w2", logs, [w2_output([("search_logs", True)]),
                                             w2_output([("get_pod_logs", True), ("search_logs", True),
                                                        ("get_pod_status", True)])])
    assert in_order["pass"] is True
    assert "order" in failing(late) and late["checks"]["order"]["detail"] == "get_pod_status after get_pod_logs"


def test_w2_a_hidden_service_returns_nothing_and_a_mutation_stays_in_its_reads(cases) -> None:
    refused, read = run_checks("w2", cases["w2"]["w2-10"], [w2_output([("get_pod_status", False)]),
                                                            w2_output([("get_pod_status", True)])])
    assert refused["pass"] is True and failing(read) == ["allowed"]  # the scorer's reads_ok, reused
    allowed, beyond = run_checks("w2", cases["w2"]["w2-12"], [w2_output([("get_pod_status", True)]),
                                                              w2_output([("query_metric", True)])])
    assert allowed["pass"] is True and failing(beyond) == ["allowed"]


def w3_record(reads: list[str], proposal: dict | None, state: str, *, executed: bool = False,
              approved: bool = False, hidden: list[str] | None = None) -> dict:
    return {"triage": "a triage", "proposal": proposal, "executed": executed, "approved": approved,
            "labels": [["confidential", "larkspur-chat"]] * (len(reads) + 1), "reads": reads,
            "hidden_reads": hidden or [], "state": state}


def test_w3_logs_last_the_machine_and_the_budget(cases) -> None:
    case = cases["w3"]["w3-01"]
    restart = {"tool": "restart_deployment", "args": {"service": "claims-api"}}
    outputs = [w3_record(["get_pod_status", "get_recent_events", "get_pod_logs"], restart, "awaiting_approval"),
               w3_record(["get_pod_logs", "get_pod_status"], restart, "awaiting_approval"),
               w3_record(["get_pod_status"], restart, "done"),
               w3_record(["get_pod_status"], None, "awaiting_approval"),
               w3_record(["get_pod_status"], restart, "done", executed=True),
               w3_record(["get_pod_status"] * 9, None, "refused"),
               w3_record(["get_pod_status"], None, "done", hidden=["fraud-scoring"])]
    ok, logs_first, done_unapproved, waits_for_nothing, ran, over, hidden = run_checks("w3", case, outputs)
    assert ok["pass"] is True
    assert logs_first["checks"]["order"]["detail"] == ["get_pod_status after get_pod_logs"]
    assert failing(done_unapproved) == ["order"]  # done straight from a proposal: no edge leads there
    assert failing(waits_for_nothing) == ["order"]
    assert "a write ran without an approval" in ran["checks"]["order"]["detail"][-1]
    assert failing(over) == ["budget"] and failing(hidden) == ["allowed"]


def test_w4_the_scribes_order_its_callers_and_one_write(cases) -> None:
    output = kept("w4", "gpt-oss-20b", "2026-11-02")["w4-01"]
    trace = output["pack"]["trace_id"]
    skipped, twice, stranger = copy.deepcopy(output), copy.deepcopy(output), copy.deepcopy(output)
    sent = [e for e in skipped["logs"]["scribe"] if e.get("trace_id") == trace and e["event"] == "task_sent"]
    skipped["logs"]["scribe"].remove(sent[1])  # the scribe never asked the risk scorer
    write = next(e for e in twice["logs"]["scribe"]
                 if e.get("trace_id") == trace and e["event"] == "pack_written_to_systems")
    twice["logs"]["scribe"].append(dict(write))
    for e in stranger["logs"]["analyst"]:
        if e.get("trace_id") == trace and e["event"] == "task_received":
            e["caller"] = "larkspur-other"  # on the analyst's caller list, but not the scribe
    unlogged = {"pack": output["pack"], "logs": None}
    ok, missing_task, double_write, other_caller, none = run_checks("w4", cases["w4"]["w4-01"],
                                                                    [output, skipped, twice, stranger, unlogged])
    assert ok["pass"] is True
    assert "order" in failing(missing_task) and "budget" in failing(missing_task)
    assert "forbidden" in failing(double_write)
    assert failing(other_caller) == ["allowed"]
    assert none["pass"] is None and none["checks"]["order"]["detail"] == trajectory.NO_LOGS


def test_w5_the_phases_the_scope_the_writes_and_the_servers(cases) -> None:
    night = kept("w5", "gpt-oss-20b", "2026-11-03/after-review")["night-1"]
    payments, stray_pr, extra_call, fallback, unseen, early = (copy.deepcopy(night) for _ in range(6))
    read = next(e for e in payments["events"] if e["event"] == "tool_call" and "account" in (e.get("args") or {}))
    read["args"]["account"] = "lm-payments-cde"  # in the fakes, and in the workspace map nowhere
    pr = next(e for e in stray_pr["events"] if e["event"] == "pull_request")
    pr["key"] = "payments-cde:aws_instance.tokenizer:changed"
    extra_call["gateway"].append(dict(extra_call["gateway"][0]))
    fallback["gateway"][0]["fallback"] = True
    unseen["readers"]["cloud-reader"] = unseen["readers"]["cloud-reader"][1:]
    first_read = next(i for i, e in enumerate(early["events"]) if e["event"] == "tool_call")
    early["events"].insert(1, early["events"].pop(first_read))  # a read before the locks are verified
    changed = [night, payments, stray_pr, extra_call, fallback, unseen, early]
    ok, scope, write, budget, route, servers, order = run_checks("w5", cases["w5"]["night-1"], changed)
    assert ok["pass"] is True and ok["measures"]["gateway_calls"] == ok["measures"]["bodies"] == 14
    assert "allowed" in failing(scope)
    assert failing(write) == ["forbidden"]
    assert failing(budget) == ["budget"]
    assert failing(route) == ["route"]
    assert failing(servers) == ["servers"]
    assert "order" in failing(order)


def test_w5_a_record_that_checks_github_needs_the_line_in_its_log(cases) -> None:
    night = kept("w5", "gpt-oss-20b", "2026-11-03/after-review")["night-1"]
    unchecked = copy.deepcopy(night)
    unchecked["events"] = [e for e in unchecked["events"] if e["event"] != "github_checked"]
    older = kept("w5", "gpt-oss-20b", "2026-11-03/step-5c")["night-1"]  # kept before the check existed
    ok, missing, before = run_checks("w5", cases["w5"]["night-1"], [night, unchecked, older])
    assert ok["pass"] is True and before["pass"] is True
    assert failing(missing) == ["order"]


def test_every_check_has_a_name_the_layer_knows() -> None:
    for workflow in registry.ORDER:
        names = set(trajectory.CHECKS[workflow]) | set(trajectory.NOT_KEPT[workflow])
        assert names <= set(trajectory.NAMES)
        assert not set(trajectory.CHECKS[workflow]) & set(trajectory.NOT_KEPT[workflow])
