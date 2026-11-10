"""Part 3: the model gateway. Three fake backends and a LiteLLM proxy, started as subprocesses.

What is proven, through the real proxy: the alias routes to the primary and the call is priced;
a failing primary is served by the fallback, and the cost line names the serving alias and its
Region; a failover that would leave the workflow's Regions does not happen; requests without
metadata, without a manifest, above the manifest's data class or to a destination the grid
forbids are refused before they leave; Restricted data reaches the self-hosted alias; a run that
has spent its budget is refused with 429; every served call leaves a span in the caller's trace.
The rules themselves are unit-tested in test_gateway_rules.py.
"""

from __future__ import annotations

import httpx

from gateway_support import MASTER_KEY, cache_salt_seen, calls_served, lines, set_failing, wait_for_line

TRACE = "0af7651916cd43dd8448eb211c80319c"
GOOD_TAGS = ["workflow:w2-ops-assistant", "data_class:internal", "owner:platform-team"]


def chat(gw: dict, text: str, *, model: str = "larkspur-chat", tags: list[str] | None = None,
         trace_id: str | None = TRACE, traceparent: str | None = None) -> httpx.Response:
    metadata: dict = {}
    if tags is not None:
        metadata["tags"] = tags
    if trace_id:
        metadata["trace_id"] = trace_id
    if traceparent:
        metadata["traceparent"] = traceparent
    body = {"model": model, "messages": [{"role": "user", "content": text}], "metadata": metadata}
    return httpx.post(f"{gw['url']}/chat/completions", json=body, timeout=30,
                      headers={"Authorization": f"Bearer {MASTER_KEY}"})


def content(r: httpx.Response) -> str:
    return r.json()["choices"][0]["message"]["content"]


# --- routing, cost and the span -------------------------------------------------------------------

def test_alias_routes_to_primary_prices_the_call_and_leaves_a_span(gateway):
    parent_span = "b7ad6b7169203331"
    r = chat(gateway, "Is claims-api healthy?", tags=GOOD_TAGS,
             traceparent=f"00-{TRACE}-{parent_span}-01")
    assert r.status_code == 200, r.text
    assert content(r).startswith("[primary] ")
    assert float(r.headers["x-litellm-response-cost"]) > 0
    line = wait_for_line(gateway["log"], lambda e: e["event"] == "call" and e["trace_id"] == TRACE)
    assert line["workflow"] == "w2-ops-assistant" and line["data_class"] == "internal"
    assert line["requested_alias"] == line["served_alias"] == "larkspur-chat"
    assert line["deployment"] == "primary" and line["region"] == "ca-central-1"
    assert line["fallback"] is False and line["fallbacks_disabled"] is False
    assert line["cost_usd"] > 0 and line["prompt_tokens"] > 0
    span = wait_for_line(gateway["traces"], lambda s: s["name"] == "chat larkspur-chat" and s["trace_id"] == TRACE)
    assert span["parent_span_id"] == parent_span  # inside the caller's trace, under the caller's span
    assert span["kind"] == "CLIENT"
    attrs = span["attributes"]
    assert attrs["gen_ai.operation.name"] == "chat" and attrs["gen_ai.request.model"] == "larkspur-chat"
    assert attrs["gen_ai.response.model"] and attrs["larkspur.region"] == "ca-central-1"
    assert attrs["larkspur.component"] == "gateway" and attrs["larkspur.fallback"] is False


def test_failing_primary_is_served_by_the_fallback_and_the_region_is_logged(gateway):
    trace = "1af7651916cd43dd8448eb211c80319c"
    set_failing(8801, True)
    try:
        r = chat(gateway, "Is policy-admin healthy?", tags=GOOD_TAGS, trace_id=trace)
    finally:
        set_failing(8801, False)
    assert r.status_code == 200, r.text
    assert content(r).startswith("[fallback] ")
    line = wait_for_line(gateway["log"], lambda e: e["event"] == "call" and e["trace_id"] == trace)
    assert line["requested_alias"] == "larkspur-chat" and line["served_alias"] == "larkspur-chat-fallback"
    assert line["fallback"] is True and line["region"] == "us-east-2"


def test_failover_out_of_the_workflow_regions_does_not_happen(gateway):
    # W3 may only be served in ca-central-1. Its request runs with fallbacks disabled, so when the
    # primary fails the caller gets the error, and the US fallback never sees the prompt.
    trace = "2af7651916cd43dd8448eb211c80319c"
    tags = ["workflow:w3-incident", "data_class:confidential"]
    before = calls_served(8802)
    set_failing(8801, True)
    try:
        r = chat(gateway, "Summarize the incident for claims-api", tags=tags, trace_id=trace)
    finally:
        set_failing(8801, False)
    assert r.status_code >= 500, r.text
    assert calls_served(8802) == before
    disabled = wait_for_line(gateway["log"], lambda e: e["event"] == "fallback_disabled" and e["trace_id"] == trace)
    assert "'larkspur-chat-fallback' (managed, us-east-2, US)" in disabled["reason"]
    # With the primary up, the same request is served in Canada, and the line says no fallback was allowed.
    r = chat(gateway, "Summarize the incident for claims-api", tags=tags, trace_id=trace)
    assert r.status_code == 200 and content(r).startswith("[primary] ")
    line = wait_for_line(gateway["log"], lambda e: e["event"] == "call" and e["trace_id"] == trace)
    assert line["fallbacks_disabled"] is True and line["region"] == "ca-central-1"


# --- refusals --------------------------------------------------------------------------------------

def test_request_without_metadata_is_refused_before_it_leaves(gateway):
    before = calls_served(8801)
    r = chat(gateway, "Is claims-api healthy?", tags=None, trace_id=None)
    assert r.status_code == 400, r.text
    assert "missing workflow, data_class, trace_id" in r.text
    assert calls_served(8801) == before
    assert "missing" in wait_for_line(gateway["log"], lambda e: e["event"] == "refused")["reason"]


def test_workflow_without_a_manifest_is_refused(gateway):
    r = chat(gateway, "hello", tags=["workflow:w9-shadow-it", "data_class:public"])
    assert r.status_code == 400 and "no manifest for workflow 'w9-shadow-it'" in r.text


def test_data_class_above_the_manifest_is_refused(gateway):
    r = chat(gateway, "hello", tags=["workflow:w2-ops-assistant", "data_class:confidential"])
    assert r.status_code == 400 and "above the maximum of 'w2-ops-assistant'" in r.text


def test_restricted_data_may_not_go_to_the_managed_alias(gateway):
    r = chat(gateway, "Summarize this claim file", tags=["workflow:w3-incident", "data_class:restricted"])
    assert r.status_code == 400, r.text
    assert "may not go to 'larkspur-chat' (managed, ca-central-1, CA)" in r.text


def test_restricted_data_may_go_to_the_self_hosted_alias(gateway):
    trace = "3af7651916cd43dd8448eb211c80319c"
    r = chat(gateway, "Summarize this claim file", model="larkspur-chat-restricted",
             tags=["workflow:w3-incident", "data_class:restricted"], trace_id=trace)
    assert r.status_code == 200, r.text
    assert content(r).startswith("[self-hosted] ")
    line = wait_for_line(gateway["log"], lambda e: e["event"] == "call" and e["trace_id"] == trace)
    assert line["fallback"] is False and line["deployment"] == "self-hosted"


def test_an_alias_the_manifest_does_not_list_is_refused(gateway):
    r = chat(gateway, "hello", model="gpt-4o", tags=GOOD_TAGS)
    assert r.status_code == 400, r.text
    assert "'gpt-4o' is not a model in the manifest" in r.text


def test_a_run_over_its_budget_is_refused_with_429(gateway):
    trace = "4af7651916cd43dd8448eb211c80319c"
    tags = ["workflow:w0-budget-test", "data_class:internal"]
    first = chat(gateway, "Is claims-api healthy?", tags=tags, trace_id=trace)
    assert first.status_code == 200, first.text
    wait_for_line(gateway["log"], lambda e: e["event"] == "call" and e["trace_id"] == trace)
    second = chat(gateway, "And policy-admin?", tags=tags, trace_id=trace)
    assert second.status_code == 429, second.text
    assert f"run {trace} has spent" in second.text


# --- what a caller cannot steer ---------------------------------------------------------------------

def test_a_fallback_list_in_the_request_body_is_removed(gateway):
    # The router would take `fallbacks` from the body. The hook removes it, so Restricted data on
    # the self-hosted alias cannot be sent abroad when that alias fails.
    trace = "5af7651916cd43dd8448eb211c80319c"
    body = {"model": "larkspur-chat-restricted",
            "messages": [{"role": "user", "content": "Summarize claim 12345"}],
            "metadata": {"tags": ["workflow:w3-incident", "data_class:restricted"], "trace_id": trace},
            "fallbacks": ["larkspur-chat-fallback"], "disable_fallbacks": False}
    before = calls_served(8802)
    set_failing(8803, True)
    try:
        r = httpx.post(f"{gateway['url']}/chat/completions", json=body, timeout=30,
                       headers={"Authorization": f"Bearer {MASTER_KEY}"})
    finally:
        set_failing(8803, False)
    assert r.status_code >= 500, r.text
    assert calls_served(8802) == before
    removed = wait_for_line(gateway["log"], lambda e: e["event"] == "routing_override_removed" and e["trace_id"] == trace)
    assert removed["fields"] == ["fallbacks"]


def test_the_span_joins_the_metadata_trace_id_without_a_traceparent(gateway):
    trace = "6af7651916cd43dd8448eb211c80319c"
    r = chat(gateway, "Is claims-api healthy?", tags=GOOD_TAGS, trace_id=trace)
    assert r.status_code == 200, r.text
    span = wait_for_line(gateway["traces"], lambda s: s["name"] == "chat larkspur-chat" and s["trace_id"] == trace)
    assert span["parent_span_id"] is None  # a root in the caller's trace, not a child of LiteLLM's own spans
    assert not [s for s in lines(gateway["traces"]) if s["resource"].get("service.name") == "gateway"
                and not s["name"].startswith("chat ")]  # and nothing of LiteLLM's in the lab's trace file


def test_a_caller_cannot_set_the_fallback_flags(gateway):
    trace = "7af7651916cd43dd8448eb211c80319c"
    body = {"model": "larkspur-chat", "messages": [{"role": "user", "content": "Is claims-api healthy?"}],
            "metadata": {"tags": GOOD_TAGS, "trace_id": trace, "fallbacks_disabled": True,
                         "requested_alias": "larkspur-chat-restricted"}}
    r = httpx.post(f"{gateway['url']}/chat/completions", json=body, timeout=30,
                   headers={"Authorization": f"Bearer {MASTER_KEY}"})
    assert r.status_code == 200, r.text
    line = wait_for_line(gateway["log"], lambda e: e["event"] == "call" and e["trace_id"] == trace)
    assert line["fallbacks_disabled"] is False and line["requested_alias"] == "larkspur-chat"


def test_a_trace_id_that_is_not_a_string_is_refused(gateway):
    body = {"model": "larkspur-chat", "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"tags": GOOD_TAGS, "trace_id": {"not": "a string"}}}
    r = httpx.post(f"{gateway['url']}/chat/completions", json=body, timeout=30,
                   headers={"Authorization": f"Bearer {MASTER_KEY}"})
    assert r.status_code == 400 and "missing trace_id" in r.text


# --- the prefix cache on self-hosted replicas -------------------------------------------------------

def test_each_workflow_gets_its_own_cache_salt_on_the_self_hosted_alias(gateway):
    # Two workflows share the self-hosted replicas; the salt keeps their cached prefixes apart.
    r = chat(gateway, "Summarize this claim file", model="larkspur-chat-restricted",
             tags=["workflow:w3-incident", "data_class:restricted"])
    assert r.status_code == 200, r.text
    assert cache_salt_seen(8803) == "w3-incident"
    r = chat(gateway, "Is claims-api healthy?", model="larkspur-chat-restricted", tags=GOOD_TAGS)
    assert r.status_code == 200, r.text
    assert cache_salt_seen(8803) == "w2-ops-assistant"


def test_a_caller_cannot_choose_the_cache_salt(gateway):
    body = {"model": "larkspur-chat-restricted",
            "messages": [{"role": "user", "content": "Summarize claim 12345"}],
            "metadata": {"tags": ["workflow:w3-incident", "data_class:restricted"], "trace_id": TRACE},
            "cache_salt": "w2-ops-assistant", "extra_body": {"cache_salt": "w2-ops-assistant"}}
    r = httpx.post(f"{gateway['url']}/chat/completions", json=body, timeout=30,
                   headers={"Authorization": f"Bearer {MASTER_KEY}"})
    assert r.status_code == 200, r.text
    assert cache_salt_seen(8803) == "w3-incident"


def test_a_managed_alias_never_receives_a_cache_salt(gateway):
    r = chat(gateway, "Is claims-api healthy?", tags=GOOD_TAGS)
    assert r.status_code == 200, r.text
    assert cache_salt_seen(8801) is None
