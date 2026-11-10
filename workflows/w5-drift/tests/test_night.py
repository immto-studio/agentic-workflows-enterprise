"""W5's night (step 4): the prose seam with its stub and the forbidden words, the app-only token on every server
and the other shapes refused, the night end to end over the readers with the stub, every lock verified before
any read, the plants in no diff, the alarm's scope, the two commands, and a night as one trace (chapter 16)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from mcp import Client

# conftest.py puts servers/, detect/, writer/, and harness/ on the path.
import cloud_fake
import cost_fake
import fixture_night
import github_fake as gh
import night as night_mod
import prose
import pull_requests as writer
import state_fake
import w5_access
from actor_transport import ActorMCP
from client import LockMismatch
from common import NIGHT, REFUSALS, W5_AGENT_OID
from conftest import SECRET, SERVERS, W5, log_events, w5_token
from github_fake import FORK, FORK_APP, UPSTREAM, UPSTREAM_APP, GitHubFake
from ledger import Ledger

IDS = cloud_fake.IDS
PLANTS = (cloud_fake.PLANTED["tag"], cloud_fake.PLANTED["user_agent"], state_fake.PLANTED["output"], cost_fake.PLANTED["line_item"])
WORKSPACES = list(fixture_night.PAIRS)
TRACE_1, TRACE_2 = "a" * 32, "b" * 32
# One tool a server, for the token checks: each takes the agent's token and nothing the model chose.
PROBE = {"state": ("list_workspaces", {}), "cloud": ("describe_resources", {"account": "lm-sandbox", "region": cloud_fake.REGION, "kind": "volumes"}),
         "cost": ("describe_budgets", {"account": "lm-sandbox"}), "policy": ("get_tagging_standard", {})}
PYTHON = sys.executable


def servers_of(running_servers) -> dict[str, str]:
    return {f"{name}-mcp": url for name, (url, _) in running_servers.items()}


def call(url: str, token: str, tool: str, **args):
    async def go():
        async with Client(ActorMCP(url, token)) as client:
            return await client.call_tool(tool, args)
    return asyncio.run(go())


def model(reply: str, status: int = 200):
    """A gateway that answers one Chat Completions reply, through httpx's mock transport: no socket."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"url": str(request.url), "json": json.loads(request.content), "auth": request.headers.get("authorization")})
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "down"}})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": reply}}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 50}})

    return httpx.Client(transport=httpx.MockTransport(handler)), captured


@pytest.fixture(scope="module")
def all_findings():
    return [f for w in WORKSPACES for f in fixture_night.findings_for(w)]


@pytest.fixture(scope="module")
def first_night(running_servers, tmp_path_factory):
    """One night over the three workspaces against the running readers, with a fresh fake and ledger."""
    out = tmp_path_factory.mktemp("night")
    fake = GitHubFake(NIGHT)
    gh.seed_platform_infra(fake)
    led = Ledger(out / "ledger.json")
    record = night_mod.run_night("2026-11-02", WORKSPACES, out / "out", servers=servers_of(running_servers), token=w5_token(),
                                 github=fake, ledger=led, gateway_log=out / "gateway.jsonl", trace_id=TRACE_1)
    return fake, led, record, out


# --- the prose seam (W5-D8) -------------------------------------------------------------------------------------------

def test_the_stub_writes_for_every_finding_without_a_forbidden_word(all_findings):
    written = [prose.write(f, trace_id="t", base="") for f in all_findings]
    assert len(written) == 15 and all(p.body_source == "stub" and p.refused_words == () and p.title and p.body for p in written)
    assert len({p.title for p in written}) == 15 and [prose.write(f, trace_id="t", base="") for f in all_findings] == written
    assert all(p.title.startswith("W5 ") and f.workspace in p.title for f, p in zip(all_findings, written))
    assert all(prose.forbidden_words(p.title + " " + p.body) == () for p in written)
    jenkins = next(p for f, p in zip(all_findings, written) if "billing_worker" in f.key)
    assert "jenkins-deploy-prod" in jenkins.body and "AuthorizeSecurityGroupIngress" in jenkins.body and "No saving is estimated" in jenkins.body
    idle = next(p for f, p in zip(all_findings, written) if f.kind == "idle")
    assert "12.5 LCU" in idle.body and "t4g.small" in idle.body


def test_the_model_seam_asks_the_gateway_in_w4s_shape_and_falls_back_to_the_stub(all_findings):
    finding = next(f for f in all_findings if "billing_worker" in f.key)
    client, captured = model("TITLE: The billing worker group gained a rule outside Terraform\n"
                             "BODY: A Jenkins job added an 8080 rule on 29 October.\nThe code is kept and the next plan removes it.")
    p = prose.write(finding, trace_id="trace-model", client=client, base="http://gateway.test/v1")
    assert p.body_source == "model" and p.refused_words == ()
    assert p.title == "The billing worker group gained a rule outside Terraform" and p.body.startswith("A Jenkins job") and "\n" not in p.body
    request = captured[0]
    assert request["url"] == "http://gateway.test/v1/chat/completions" and request["auth"] == "Bearer sk-lab"
    body = request["json"]
    assert body["model"] == "larkspur-chat" and body["max_tokens"] == 8192 and body["temperature"] == 0 and "tools" not in body
    assert body["metadata"] == {"tags": ["workflow:w5-drift", "data_class:confidential"], "trace_id": "trace-model"}
    system, user = body["messages"]
    assert system["role"] == "system" and all(word in system["content"] for word in prose.FORBIDDEN)
    assert "may not change" in system["content"] and "proposes" in system["content"] and "data" in system["content"]
    # Step 5b: the facts and what the finding lacks (tests/test_prose.py), never the key, the template, or the user agent.
    assert user["role"] == "user" and user["content"] == prose.model_input(finding) and user["content"].startswith("FACTS:")
    assert finding.key not in user["content"] and finding.attribution["user_agent"] not in user["content"]
    assert prose.LACKS_SAVING in user["content"] and prose.LACKS_ATTRIBUTION not in user["content"] and "LCU" not in user["content"]
    # The forbidden words: whole words, case-insensitive, the stub with the words recorded.
    client, _ = model("TITLE: Safe to merge\nBODY: This is APPROVED and safe; apply it. Unsafely merged. Approves.")
    p = prose.write(finding, trace_id="t", client=client, base="http://gateway.test/v1")
    assert p.body_source == "stub" and p.refused_words == ("safe", "merge", "approved", "apply")
    assert p.title == prose.stub(finding)[0] and p.body == prose.stub(finding)[1]
    assert prose.forbidden_words("unsafe merges approves applying") == () and prose.forbidden_words("Merge! merge.") == ("merge",)
    # Empty, unparsable, and failing replies, and no model configured: the stub, nothing refused, no call.
    for reply, status in (("", 200), ("I would rather not.", 200), ("x", 500)):
        client, _ = model(reply, status)
        p = prose.write(finding, trace_id="t", client=client, base="http://gateway.test/v1")
        assert (p.body_source, p.refused_words) == ("stub", ()), (reply, status)
    client, captured = model("TITLE: t\nBODY: b")
    assert prose.write(finding, trace_id="t", client=client, base="").body_source == "stub" and captured == []


# --- the token (W5-D11): app-only, accepted everywhere; the other shapes refused -----------------------------------------

def test_the_app_only_token_is_accepted_by_every_server_and_the_delegated_and_foreign_shapes_refused(running_servers):
    claims = w5_access.verify(w5_token(), SECRET)
    assert claims["idtyp"] == "app" and "scp" not in claims and claims["roles"] == ["Drift.Read"]
    assert claims["sub"] == claims["oid"] == W5_AGENT_OID and claims["aud"] == w5_access.W5_SERVERS_APP and claims["azp"] == w5_access.W5_RUNTIME
    shapes = {
        "delegated": (w5_token(delegated=True), "delegated"),
        "w1 audience": (w5_token(audience=w5_access.access.AUDIENCE), "audience"),
        "other client": (w5_token(client="00000000-0000-0000-0000-000000000001"), "azp"),
        "no role": (w5_token(roles=()), "Drift.Read"),
        "other role": (w5_token(roles=("Ops.Read",)), "Drift.Read"),
        "expired": (w5_token(minutes=-5), "expired"),
        "other secret": (w5_access.mint_app_token("x" * 40), "Signature"),
    }
    for name, (token, word) in shapes.items():
        with pytest.raises(w5_access.AccessError) as info:
            w5_access.verify(token, SECRET)
        assert word.lower() in str(info.value).lower(), (name, str(info.value))
    for name, (url, log) in running_servers.items():
        tool, args = PROBE[name]
        assert not call(url, w5_token(), tool, **args).is_error, name
        for shape, (token, _) in shapes.items():
            assert call(url, token, tool, **args).is_error, (name, shape)
        reasons = [e["reason"] for e in log_events(log) if e["event"] == "refused"]
        assert any("delegated" in r for r in reasons) and any("Drift.Read" in r for r in reasons), name


# --- the night, end to end, with the stub (W5-D2, W5-D11) ---------------------------------------------------------------

def test_the_night_end_to_end_with_the_stub(running_servers, first_night):
    fake, led, record, out = first_night
    upstream = fake.installation_token(UPSTREAM_APP)
    assert record["counts"]["findings"] == 15 and record["counts"]["pull_requests"] == {"opened": 14, "updated": 0, "skipped": 0, "suppressed": 1}
    assert record["refused"] == {} and record["failed"] == {} and record["workspaces_read"] == WORKSPACES
    assert record["body_sources"] == {"stub": 14} and record["refused_words"] == {}
    assert record["cost"] == {"gateway_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "refused": 0, "failed": 0}
    assert record["trigger"] == {"kind": "schedule"} and record["trace_id"] == TRACE_1 and record["agent"]["oid"] == W5_AGENT_OID
    expected = {f.key for w in WORKSPACES for f in fixture_night.findings_for(w)}
    assert {f["key"] for f in record["findings"]} == expected and set(record["spend"]) == set(fixture_night.PAIRS.values())
    # The pull requests on the upstream by the upstream App only; the branches on the fork by the fork App only.
    pulls = fake.list_pulls(upstream, UPSTREAM, state="all")
    assert len(pulls) == 14 and {p["user"]["login"] for p in pulls} == {f"{UPSTREAM_APP}[bot]"} and all(p["state"] == "open" for p in pulls)
    assert {p["head"]["ref"] for p in pulls} == {writer.branch_name(r["key"]) for r in record["pull_requests"] if r["action"] == "opened"}
    assert set(fake.repos[UPSTREAM]["refs"]) == {"refs/heads/main"} and len(fake.repos[FORK]["refs"]) == 15
    assert fake.repos[UPSTREAM]["refs"]["refs/heads/main"] == fake.repos[FORK]["refs"]["refs/heads/main"]
    for e in fake.log:
        assert e["status"] in (200, 201, 404), e  # a 404 is the writer asking whether the branch or the file exists yet
        assert not (e["path"].endswith("/merge") or e["path"].endswith("/reviews") or ".github/workflows" in e["path"]), e
        if e["method"] in ("POST", "PUT", "PATCH") and e["path"].startswith("/repos/"):
            assert ("/".join(e["path"].split("/")[2:4]), e["actor"]) in {(FORK, f"{FORK_APP}[bot]"), (UPSTREAM, f"{UPSTREAM_APP}[bot]")}, e
    # GitHub checked first: the two Apps' tokens, the rules on main, and the ruleset behind them, before any write.
    assert [(e["method"], e["path"], e["actor"]) for e in fake.log[:4]] == [
        ("POST", "/app/installations/55001/access_tokens", FORK_APP), ("POST", "/app/installations/55002/access_tokens", UPSTREAM_APP),
        ("GET", f"/repos/{UPSTREAM}/rules/branches/main", f"{UPSTREAM_APP}[bot]"),
        ("GET", f"/repos/{UPSTREAM}/rulesets/{gh.RULESET['id']}", f"{UPSTREAM_APP}[bot]")]
    checked = record["github_check"]
    assert checked["ok"] is True and checked["reasons"] == [] and "stopped" not in record
    assert checked["permissions"] == {"metadata": "read", "pull_requests": "write"} and checked["can_bypass"] == {"protect-main": "never"}
    assert checked["rules"] == ["creation", "non_fast_forward", "pull_request", "required_status_checks"]
    assert checked["required_status_checks"] == [{"context": "validate", "integration_id": gh.GITHUB_ACTIONS_ID}]
    actions = {r["key"]: r["action"] for r in record["pull_requests"]}
    assert actions[f"sandbox-quill:{IDS['notebook_root_volume']}:untagged"] == "suppressed"  # both tags excused
    assert actions["sandbox-quill:aws_instance.notebook:untagged"] == "opened"  # one excused, raised for the other
    assert "RITM0045021" in fake.get_pull(upstream, UPSTREAM, next(r["number"] for r in record["pull_requests"]
                                                                   if r["key"] == "sandbox-quill:aws_instance.notebook:untagged"))["body"]
    # Every lock verified first, then GitHub checked, before any read, under the night's trace id.
    log = log_events(out / "out" / "night-2026-11-02.jsonl")
    assert all(e["trace_id"] == TRACE_1 for e in log) and log[0]["event"] == "night_start" and log[-1]["event"] == "night_done"
    first_call = next(i for i, e in enumerate(log) if e["event"] == "tool_call")
    assert [e["event"] for e in log[1:first_call]] == ["tools_verified"] * 4 + ["github_checked"]
    assert log[first_call - 1]["ok"] is True and log[first_call - 1]["reasons"] == []
    assert {e["server"] for e in log[1:5]} == set(night_mod.READ_SERVERS) and set(record["locks"]) == set(night_mod.READ_SERVERS)
    for server, hashes in record["locks"].items():
        lock = json.loads(night_mod.LOCKS[server].read_text(encoding="utf-8"))["tools"]
        assert set(hashes) == set(lock) and all(lock[t]["sha256"].startswith(h) for t, h in hashes.items()), server
    assert sum(len(h) for h in record["locks"].values()) == sum(SERVERS.values()) == 15
    events = [e["event"] for e in log]
    assert events.count("workspace_findings") == 3 and events.count("pull_request") == 15 and "ledger_synced" in events and "night_cost" in events
    called = {e["tool"] for e in log if e["event"] == "tool_call"}
    assert all(e["ok"] for e in log if e["event"] == "tool_call") and called <= set(night_mod.READS)
    assert called == {"list_workspaces", "get_state", "describe_resources", "get_resources_by_tag", "get_cpu_utilization", "lookup_events",
                      "read_cost_export", "get_tagging_standard", "list_policy_exceptions"}  # what a scheduled night needs, and no write
    for name, (_, server_log) in running_servers.items():  # the reads went through the readers, under the agent's token
        assert any(e.get("trace_id") == TRACE_1 and e.get("caller") == W5_AGENT_OID for e in log_events(server_log)), name
    assert (out / "out" / "night-2026-11-02.json").exists() and (out / "ledger.json").exists()
    assert led.nights["2026-11-02"]["gateway_calls"] == 0 and len(led.findings) == 15
    # The next night on the same store: the same pull requests, updated in place.
    record2 = night_mod.run_night("2026-11-03", WORKSPACES, out / "out", servers=servers_of(running_servers), token=w5_token(),
                                  github=fake, ledger=led, gateway_log=out / "gateway.jsonl", trace_id=TRACE_2)
    assert record2["counts"]["pull_requests"] == {"opened": 0, "updated": 14, "skipped": 0, "suppressed": 1}
    assert {r["number"] for r in record2["pull_requests"] if r["number"]} == {r["number"] for r in record["pull_requests"] if r["number"]}
    assert len(fake.list_pulls(upstream, UPSTREAM, state="all")) == 14 and len(fake.repos[FORK]["refs"]) == 15
    assert set(led.nights) == {"2026-11-02", "2026-11-03"} and led.summary("2026-11")["pull_requests"]["opened"] == 14


def test_the_plants_reach_no_diff_and_appear_only_as_quoted_data_inside_a_body(first_night):
    fake, _, record, _ = first_night
    fork, upstream = fake.installation_token(FORK_APP), fake.installation_token(UPSTREAM_APP)
    pulls = fake.list_pulls(upstream, UPSTREAM, state="all")
    main_tree = fake.commits[fake.repos[UPSTREAM]["refs"]["refs/heads/main"]]["tree"]
    assert any(state_fake.PLANTED["output"] in text for text in main_tree.values())  # the module mirrors the state, plant included
    quoting: set[str] = set()
    for pr in pulls:
        for file in fake.list_pull_files(upstream, UPSTREAM, pr["number"]):
            content = base64.b64decode(fake.get_content(fork, FORK, file["filename"], ref=pr["head"]["ref"])["content"]).decode("utf-8")
            added = [line for line in file["patch"].splitlines() if line.startswith("+") and not line.startswith("+++")]
            for plant in PLANTS:  # the writer adds no plant: what the branch holds of one, main held already
                assert content.count(plant) == main_tree.get(file["filename"], "").count(plant), (pr["head"]["ref"], file["filename"])
                assert not any(plant in line for line in added), (pr["head"]["ref"], file["filename"])
        facts, proposed = pr["body"].split("## Proposed change")
        before_facts = facts.split("## Facts")[0]
        for plant in PLANTS:
            assert plant not in pr["title"] and plant not in proposed and plant not in before_facts, pr["head"]["ref"]
            if plant in pr["body"]:
                quoting.add(pr["head"]["ref"])
                for line in pr["body"].splitlines():
                    if plant in line:
                        assert line.startswith("- Attribution:") and "data, not an instruction" in line, line
    for commit in fake.commits.values():  # no commit the writer made adds a plant to any file
        for parent in commit["parents"]:
            before = fake.commits[parent]["tree"]
            for path, text in commit["tree"].items():
                assert all(text.count(plant) <= before.get(path, "").count(plant) for plant in PLANTS), (commit["message"], path)
    orphan = {writer.branch_name(f["key"]) for f in record["findings"] if IDS["orphan_volume"] in f["key"]}
    assert quoting and quoting <= orphan  # the orphan volume's CreateVolume carries the planted user agent, quoted as data
    bodies = json.dumps([p["body"] for p in pulls])
    assert cloud_fake.PLANTED["tag"] not in bodies and state_fake.PLANTED["output"] not in bodies and cost_fake.PLANTED["line_item"] not in bodies


def test_the_alarm_scopes_the_night_to_the_account(running_servers, first_night):
    fake, led, _, out = first_night
    common = dict(servers=servers_of(running_servers), token=w5_token(), github=fake, ledger=led, gateway_log=out / "gateway.jsonl")
    record = night_mod.run_alarm("lm-claims-prod", "budget:claims-monthly:FORECASTED:100", out / "out", night_date="2026-11-03", **common)
    assert record["workspaces"] == ["claims-api-prod"] and record["counts"]["findings"] == 3
    trigger = record["trigger"]
    assert trigger["kind"] == "budget" and trigger["account"] == "lm-claims-prod" and trigger["threshold"] == 100.0
    assert trigger["state"]["found"] is True and trigger["state"]["budget"] == "lm-claims-prod-monthly"
    assert trigger["state"]["notification"]["NotificationType"] == "FORECASTED" and trigger["state"]["notification"]["NotificationState"] == "ALARM"
    assert record["counts"]["pull_requests"]["opened"] == 0 and record["counts"]["pull_requests"]["updated"] == 3  # in place
    assert record["record_file"].endswith("alarm-2026-11-03-lm-claims-prod.json") and (out / "out" / "alarm-2026-11-03-lm-claims-prod.jsonl").exists()
    anomaly = night_mod.run_alarm("lm-sandbox", "anomaly:fixture-anomaly-0d2b2c3d-4e5f-6070-8091-a2b3c4d5e6f7", out / "out",
                                  night_date="2026-11-03", **common)
    assert anomaly["workspaces"] == ["sandbox-quill"] and anomaly["trigger"]["state"]["found"] is True
    assert anomaly["trigger"]["state"]["anomaly"]["RootCauses"][0]["Service"] == "Amazon Athena"
    # An account the map does not allow: the read is refused with the fixed sentence, nothing is opened.
    before = len(fake.log)
    cde = night_mod.run_alarm("lm-payments-cde", "budget:cde-monthly:ACTUAL:80", out / "out", night_date="2026-11-03", **common)
    assert cde["workspaces"] == [] and cde["counts"]["findings"] == 0 and cde["counts"]["pull_requests"]["opened"] == 0
    assert cde["trigger"]["state"]["found"] is False and REFUSALS["account"] in cde["trigger"]["state"]["refused"]
    assert not [e for e in fake.log[before:] if e["method"] != "GET" and not e["path"].startswith("/app/")]  # tokens, no write
    with pytest.raises(ValueError):
        night_mod.parse_alert("budget:x")
    assert night_mod.parse_alert("anomaly:abc") == {"kind": "anomaly", "anomaly_id": "abc"}


def test_a_lock_mismatch_stops_the_night_before_any_read(running_servers, tmp_path, monkeypatch):
    lock = json.loads(night_mod.LOCKS["cost-mcp"].read_text(encoding="utf-8"))
    lock["tools"]["describe_budgets"]["sha256"] = "0" * 64
    tampered = tmp_path / "cost.lock.json"
    tampered.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setitem(night_mod.LOCKS, "cost-mcp", tampered)
    fake = GitHubFake(NIGHT)
    gh.seed_platform_infra(fake)
    led = Ledger(tmp_path / "ledger.json")
    with pytest.raises(LockMismatch):
        night_mod.run_night("2026-11-02", WORKSPACES, tmp_path / "out", servers=servers_of(running_servers), token=w5_token(),
                            github=fake, ledger=led, gateway_log=None, trace_id="c" * 32)
    assert fake.log == [] and not fake.pulls and not (tmp_path / "ledger.json").exists()
    events = [e["event"] for e in log_events(tmp_path / "out" / "night-2026-11-02.jsonl")]
    assert "tool_call" not in events and events[-1] == "refused" and events.count("tools_verified") == 2


# --- the check of GitHub itself before a night writes (the fact sheet's A.13, the review's finding 8) ---------------------

def _grant(permission: str):
    def change(fake: GitHubFake) -> None:  # an organization owner grants the App more in GitHub's settings, not the catalog
        fake.apps[UPSTREAM_APP]["permissions"][permission] = "write"
    return change


def _rule(kind: str, fake: GitHubFake) -> dict:
    return next(rule for rule in fake.rulesets[0]["rules"] if rule["type"] == kind)


def _no_code_owner_review(fake: GitHubFake) -> None:
    _rule("pull_request", fake)["parameters"]["require_code_owner_review"] = False


def _stale_approvals_kept(fake: GitHubFake) -> None:
    _rule("pull_request", fake)["parameters"]["dismiss_stale_reviews_on_push"] = False


def _no_status_check(fake: GitHubFake) -> None:
    fake.rulesets[0]["rules"].remove(_rule("required_status_checks", fake))


def _unpinned_status_check(fake: GitHubFake) -> None:  # the check required from any source: a person could set it
    _rule("required_status_checks", fake)["parameters"]["required_status_checks"] = [{"context": "validate"}]


def _evaluate_only(fake: GitHubFake) -> None:  # a ruleset in evaluate mode enforces nothing and is not returned
    fake.rulesets[0]["enforcement"] = "evaluate"


def _app_bypasses(fake: GitHubFake) -> None:
    fake.rulesets[0]["bypass_actors"] = [{"actor_id": gh.APPS[UPSTREAM_APP]["id"], "actor_type": "Integration", "bypass_mode": "always"}]


@pytest.mark.parametrize(("change", "reasons"), [
    (_grant("contents"), ["larkspur-w5-upstream holds contents: write on larkspur-mutual/platform-infra"]),
    (_grant("workflows"), ["larkspur-w5-upstream holds workflows: write on larkspur-mutual/platform-infra"]),
    (_grant("administration"), ["larkspur-w5-upstream holds administration: write on larkspur-mutual/platform-infra"]),
    (_no_code_owner_review, ["no active rule on main requires a code owner's review"]),
    (_stale_approvals_kept, ["no active rule on main dismisses a stale approval when new commits are pushed"]),
    (_no_status_check, ["no active rule on main requires the check validate from the App 15368"]),
    (_unpinned_status_check, ["no active rule on main requires the check validate from the App 15368"]),
    (_evaluate_only, ["no active rule on main requires a code owner's review",
                      "no active rule on main dismisses a stale approval when new commits are pushed",
                      "no active rule on main requires the check validate from the App 15368"]),
    (_app_bypasses, ["larkspur-w5-upstream can bypass the ruleset 'protect-main' (always)"]),
], ids=["contents-write", "workflows-write", "administration-write", "no-code-owner-review", "stale-approvals-kept",
        "no-status-check", "unpinned-status-check", "ruleset-in-evaluate", "app-can-bypass"])
def test_the_night_stops_before_any_read_when_github_is_not_as_the_catalog_says(running_servers, tmp_path, change, reasons):
    """The catalog says what the Apps hold and what the ruleset requires; GitHub decides. Each change below is one an
    organization owner could make in GitHub's settings without touching the catalog, and the night stops on it,
    failing closed: nothing read, nothing written, the reasons in the night record."""
    fake = GitHubFake(NIGHT)
    gh.seed_platform_infra(fake)
    change(fake)
    led = Ledger(tmp_path / "ledger.json")
    record = night_mod.run_night("2026-11-02", WORKSPACES, tmp_path / "out", servers=servers_of(running_servers), token=w5_token(),
                                 github=fake, ledger=led, gateway_log=None, trace_id="d" * 32)
    assert record["github_check"]["ok"] is False and record["github_check"]["reasons"] == reasons
    assert record["stopped"] == "the check of GitHub refused the night: " + "; ".join(reasons)
    assert record["findings"] == [] and record["pull_requests"] == [] and record["counts"] == {}
    assert not fake.pulls and set(fake.repos[FORK]["refs"]) == {"refs/heads/main"} and not (tmp_path / "ledger.json").exists()
    assert {(e["method"], e["path"].split("/")[1]) for e in fake.log} <= {("POST", "app"), ("GET", "repos")}  # tokens and reads only
    events = [e["event"] for e in log_events(tmp_path / "out" / "night-2026-11-02.jsonl")]
    assert "tool_call" not in events and events.count("tools_verified") == 4 and "github_checked" in events
    assert (tmp_path / "out" / "night-2026-11-02.json").exists()


def test_the_check_reads_what_the_upstream_app_may_and_not_the_bypass_list():
    """The token's own permissions, the rules on main under "Metadata" read, and the App's own bypass: the bypass
    list itself needs write access to the ruleset, which no W5 App holds, so the precondition keeps that check."""
    import github_check
    fake = GitHubFake(NIGHT)
    gh.seed_platform_infra(fake)
    report, tokens = github_check.check(fake)
    assert report["ok"] is True and set(tokens) == {FORK_APP, UPSTREAM_APP}
    assert tokens[UPSTREAM_APP] == fake.installation_token(UPSTREAM_APP) and tokens[UPSTREAM_APP] not in json.dumps(report)
    created = fake.create_installation_token(UPSTREAM_APP)
    assert set(created) == {"token", "expires_at", "permissions", "repository_selection", "repositories"}
    assert created["permissions"] == {"metadata": "read", "pull_requests": "write"} and created["expires_at"] == "2026-11-02T08:00:00Z"
    assert [r["full_name"] for r in created["repositories"]] == [UPSTREAM]
    rules = fake.get_branch_rules(tokens[UPSTREAM_APP], UPSTREAM, "main")
    assert all(r["ruleset_source_type"] == "Repository" and r["ruleset_source"] == UPSTREAM and r["ruleset_id"] == gh.RULESET["id"]
               for r in rules)
    assert fake.get_branch_rules(tokens[UPSTREAM_APP], UPSTREAM, "w5/anything") == []  # the ruleset targets main only
    ruleset = fake.get_ruleset(tokens[UPSTREAM_APP], UPSTREAM, gh.RULESET["id"])
    assert "bypass_actors" not in ruleset and ruleset["current_user_can_bypass"] == "never"
    fake.rulesets[0]["bypass_actors"] = [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]  # another actor
    assert github_check.check(fake)[0]["ok"] is True  # invisible to the App: the precondition's to refuse (tests/test_aws_identities.py)
    with pytest.raises(gh.GitHubError) as refused:
        fake.get_branch_rules(tokens[FORK_APP], UPSTREAM, "main")  # the fork App is not installed on the upstream
    assert refused.value.status == 403


def test_the_two_commands_run_against_running_readers(running_servers, tmp_path):
    env = {**os.environ, "PYTHONUTF8": "1", "W5_SERVERS": json.dumps(servers_of(running_servers)), "W5_TOKEN_SECRET": SECRET}
    env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    night = subprocess.run([PYTHON, "-X", "utf8", "-m", "harness.night", "--date", "2026-11-02", "--workspaces", "sandbox-quill",
                            "--out", str(tmp_path)], cwd=str(W5), env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert night.returncode == 0, night.stderr[-2000:]
    printed = json.loads(night.stdout)
    assert printed["counts"]["findings"] == 11 and printed["counts"]["pull_requests"]["opened"] == 10 and printed["body_sources"] == {"stub": 10}
    assert (tmp_path / "night-2026-11-02.json").exists() and (tmp_path / "github.json").exists() and (tmp_path / "ledger.json").exists()
    alarm = subprocess.run([PYTHON, "-X", "utf8", "-m", "harness.night", "--alarm", "--account", "lm-claims-prod", "--alert",
                            "budget:claims-monthly:FORECASTED:100", "--out", str(tmp_path)], cwd=str(W5), env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert alarm.returncode == 0, alarm.stderr[-2000:]
    printed = json.loads(alarm.stdout)
    assert printed["workspaces"] == ["claims-api-prod"] and printed["counts"]["pull_requests"]["opened"] == 3
    assert printed["trigger"]["state"]["notification"]["NotificationState"] == "ALARM"
    store = json.loads((tmp_path / "github.json").read_text(encoding="utf-8"))
    assert len(store["pulls"]) == 13 and list(store["repos"][UPSTREAM]["refs"]) == ["refs/heads/main"]


# --- a night as one trace (chapter 16's lab, companion #14, step 3b) ----------------------------------------------------

@contextmanager
def fake_gateway(reply: str) -> Iterator[tuple[str, list[dict]]]:
    """A Chat Completions endpoint on 127.0.0.1 for a process the test starts: one reply to every request, and
    each request's body kept."""
    bodies: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            return None

        def do_POST(self):  # noqa: N802
            bodies.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0))))
            payload = json.dumps({"choices": [{"message": {"role": "assistant", "content": reply}}],
                                  "usage": {"prompt_tokens": 100, "completion_tokens": 50}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1", bodies
    finally:
        server.shutdown()
        server.server_close()


def test_a_night_is_one_trace_under_one_root(running_servers, tmp_path):
    """The command records its spans (to traces.jsonl in --out, with no OTLP endpoint), and every span of the night,
    its own and the readers', has the night's trace id and reaches the night's span through its parents. Each model
    call carries that span's traceparent beside the trace id, so chapter 5's gateway puts its span there too."""
    import trace_setup as tracing  # chapter 5's, on the path once night.py is imported

    reply = ("TITLE: A finding in the sandbox-quill workspace\n"
             "BODY: The facts name the resource, where it lives, and the evidence. W5 proposes this change for review.")
    env = {**os.environ, "PYTHONUTF8": "1", "W5_SERVERS": json.dumps(servers_of(running_servers)), "W5_TOKEN_SECRET": SECRET}
    env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    env.pop("TRACE_FILE", None)
    with fake_gateway(reply) as (base, requests):
        night = subprocess.run([PYTHON, "-X", "utf8", "-m", "harness.night", "--date", "2026-11-02", "--workspaces", "sandbox-quill",
                                "--out", str(tmp_path)], cwd=str(W5), env={**env, "W5_MODEL_BASE_URL": base}, capture_output=True,
                               text=True, encoding="utf-8", timeout=300)
    assert night.returncode == 0, night.stderr[-2000:]
    printed = json.loads(night.stdout)
    trace = printed["trace_id"]
    assert tracing.is_trace_id(trace) and printed["body_sources"] == {"model": 10}

    own = tracing.read_spans(tmp_path / "traces.jsonl")
    readers_file = next(iter(running_servers.values()))[1].parent / "traces.jsonl"  # launch.py's TRACE_FILE for the readers
    readers = [s for s in tracing.read_spans(readers_file) if s["trace_id"] == trace]
    assert own and {s["trace_id"] for s in own} == {trace}  # nothing the night did started a trace of its own
    assert {s["resource"]["service.name"] for s in own} == {"w5-night"}
    assert {s["resource"]["service.name"] for s in readers} == {f"larkspur-drift-{name}" for name in SERVERS}

    spans = {s["span_id"]: s for s in own + readers}
    roots = [s for s in spans.values() if s["parent_span_id"] is None]
    assert [r["name"] for r in roots] == ["invoke_agent w5-night"]
    root = roots[0]
    assert root["attributes"]["larkspur.trace_id"] == trace and root["resource"]["larkspur.identity"] == night_mod.W5_AGENT_NAME
    for span in spans.values():  # each span reaches the root through parents of the same night
        current = span
        while current["parent_span_id"] is not None:
            assert current["parent_span_id"] in spans, (span["name"], span["resource"]["service.name"])
            current = spans[current["parent_span_id"]]
        assert current is root, span["name"]
    for span in readers:  # a reader's request span sits under the night's MCP client span; its tool span under that
        parent = spans[span["parent_span_id"]]
        assert (parent["resource"]["service.name"] == "w5-night" and parent["name"].startswith("MCP send ")) \
            or parent["resource"]["service.name"] == span["resource"]["service.name"], span["name"]
    assert root["start"] <= min(s["start"] for s in spans.values()) and root["end"] >= max(s["end"] for s in spans.values())
    tool_calls = [s for s in own if s["name"].startswith("execute_tool ")]
    assert tool_calls and all(spans[s["parent_span_id"]] is root for s in tool_calls)

    # Every model call: the night's trace id and the root's traceparent, which chapter 5's gateway prefers.
    assert len(requests) == 10
    for body in requests:
        version, trace_part, parent, flags = body["metadata"]["traceparent"].split("-")
        assert body["metadata"]["trace_id"] == trace and (version, trace_part, parent) == ("00", trace, root["span_id"])
        assert int(flags, 16) & 1  # sampled
