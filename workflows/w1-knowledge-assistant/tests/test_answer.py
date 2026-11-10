"""The answer step's model adapter: the class of each call, the alias it may use, two searches, and the refusal."""

from __future__ import annotations

import importlib.util
import json
import sys

import jsonschema
import pytest
import yaml

from conftest import W1, printable

_spec = importlib.util.spec_from_file_location("w1_answer", W1 / "harness" / "answer.py")
answer = importlib.util.module_from_spec(_spec)
sys.modules["w1_answer"] = answer
_spec.loader.exec_module(answer)

MANIFEST = yaml.safe_load((W1 / "manifest" / "w1-knowledge.yaml").read_text(encoding="utf-8"))
LOCK = json.loads((W1 / "knowledge-server" / "tools.lock.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((W1.parents[1] / "labs" / "ch05" / "manifest" / "schema.json").read_text(encoding="utf-8"))


def search_result(*classes: str) -> dict[str, str]:
    passages = [{"doc_id": f"p{i}.md", "title": f"Page {i}", "last_reviewed": "2026-08-19",
                 "classification": c, "text": "..."} for i, c in enumerate(classes)]
    return {"role": "tool", "content": json.dumps({"passages": passages})}


def tool(content) -> dict[str, str]:
    return {"role": "tool", "content": content if isinstance(content, str) else json.dumps(content)}


QUESTION = {"role": "user", "content": "How many shards unseal Vault?"}
CALL = {"role": "assistant", "content": json.dumps({"name": "search_docs", "args": {"query": "vault unseal"}})}
PASSAGE = {"doc_id": "rb-vault-break-glass-unseal.md", "title": "Break-glass", "last_reviewed": "2026-06-04",
           "classification": "Restricted", "text": "The recovery threshold is 3 of 5 recovery key shards."}


class NoGateway:
    """A client that fails the test if the adapter calls the gateway."""

    def post(self, *args, **kwargs):
        raise AssertionError("the gateway was called")


def model(floor: str = "Internal", **kwargs) -> answer.ClassifyingGatewayModel:
    return answer.ClassifyingGatewayModel(gateway_url="http://gateway.invalid", alias="larkspur-chat",
                                          tools=answer.pinned_tool_specs(answer.LOCK_PATH, set(answer.ALLOWED)),
                                          api_key="k", trace_id="t1", floor=floor, **kwargs)


def test_the_first_call_carries_only_the_question():
    assert answer.prompt_class([QUESTION]) == "Internal"


def test_a_call_carries_the_highest_class_among_its_passages():
    assert answer.prompt_class([QUESTION, CALL, search_result("Internal", "Public")]) == "Internal"
    assert answer.prompt_class([QUESTION, CALL, search_result("Internal", "Confidential")]) == "Confidential"
    assert answer.prompt_class([QUESTION, CALL, search_result("Confidential"), CALL,
                                search_result("Restricted", "Internal")]) == "Restricted"


@pytest.mark.parametrize("name, content", [
    # The review's probe 4: the same Restricted passage in shapes other than the server's.
    ("wrapped in another key", {"result": {"passages": [PASSAGE]}}),
    ("a bare list", [PASSAGE]),
    ("text, not JSON", "Break-glass (Restricted): The recovery threshold is 3 of 5 recovery key shards."),
    ("passages and another key", {"passages": [PASSAGE], "more": "text"}),
    ("an unknown class", {"passages": [dict(PASSAGE, classification="Secret")]}),
    ("a passage without a class", {"passages": [{"doc_id": "x.md", "text": "..."}]}),
    ("a passage that isn't an object", {"passages": ["3 of 5 shards"]}),
    ("JSON that isn't an object", 42),
])
def test_a_result_w1_cant_read_counts_as_restricted(name, content):
    labeled = answer.prompt_class([QUESTION, CALL, tool(content)])
    assert labeled == "Restricted", name
    assert answer.alias_for(labeled) == "larkspur-chat-restricted"


def test_a_failed_search_carries_no_page():
    assert answer.prompt_class([QUESTION, CALL, tool({"error": "token refused: Signature has expired"})]) == "Internal"


def test_every_call_starts_at_the_callers_class_and_at_least_internal():
    assert answer.prompt_class([QUESTION], floor="Confidential") == "Confidential"
    assert answer.prompt_class([QUESTION], floor="Restricted") == "Restricted"
    assert answer.prompt_class([QUESTION], floor="Public") == "Internal"
    assert answer.prompt_class([QUESTION, CALL, search_result("Internal")], floor="Restricted") == "Restricted"


def test_the_class_picks_the_alias():
    assert answer.alias_for("Public") == answer.alias_for("Internal") == "larkspur-chat"
    assert answer.alias_for("Confidential") == "larkspur-chat"  # the gateway keeps it in Canada
    assert answer.alias_for("Restricted") == "larkspur-chat-restricted"


def test_each_request_is_tagged_and_routed_by_its_own_prompt():
    m = model()
    first = m.request([QUESTION])
    second = m.request([QUESTION, CALL, search_result("Restricted")])
    assert first["model"] == "larkspur-chat"
    assert "data_class:internal" in first["metadata"]["tags"] and "workflow:w1-knowledge" in first["metadata"]["tags"]
    assert second["model"] == "larkspur-chat-restricted"
    assert "data_class:restricted" in second["metadata"]["tags"]
    assert m.labels == [("internal", "larkspur-chat"), ("restricted", "larkspur-chat-restricted")]
    assert second["messages"][0] == {"role": "system", "content": answer.SYSTEM_PROMPT}


def test_a_custodians_first_call_is_already_restricted():
    m = model(floor="Restricted")
    body = m.request([QUESTION])
    assert body["model"] == "larkspur-chat-restricted" and "data_class:restricted" in body["metadata"]["tags"]


def test_the_model_is_offered_search_docs_and_never_caller_class():
    assert set(LOCK["tools"]) == {"search_docs", "caller_class"}
    offered = [spec["function"]["name"] for spec in model().request([QUESTION])["tools"]]
    assert offered == ["search_docs"]


def test_after_two_search_results_the_model_gets_no_tools():
    m = model()
    one = m.request([QUESTION, CALL, search_result("Internal")])
    two = m.request([QUESTION, CALL, search_result("Internal"), CALL, search_result("Internal")])
    assert one["tools"] and "tools" not in two  # the third call has to answer


class Replies:
    """A client whose every reply is the same Chat Completions message, and which counts the posts."""

    def __init__(self, message: dict):
        self.message, self.posts = message, 0

    def post(self, url, json, headers):
        self.posts += 1
        body = {"choices": [{"message": self.message}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        return type("Response", (), {"headers": {}, "raise_for_status": lambda self: None,
                                     "json": lambda self: body})()


def test_a_third_search_the_model_asks_for_anyway_is_refused():
    search = {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "type": "function", "function": {
        "name": "search_docs", "arguments": json.dumps({"query": "vault unseal"})}}]}
    one_result = [QUESTION, CALL, search_result("Internal")]
    m = model(client=Replies(search))
    assert m(one_result) == {"tool_call": {"name": "search_docs", "args": {"query": "vault unseal"}}}
    assert m.searching  # a search is under way until the loop calls the model again
    assert m(one_result + [CALL, search_result("Internal")]) == {"answer": answer.BUDGET_EXHAUSTED}
    assert not m.searching
    assert answer.finish(answer.BUDGET_EXHAUSTED) == answer.REFUSAL


def test_a_call_the_loop_refuses_ends_in_w1s_refusal():
    # The chapter 1 loop refuses a tool it doesn't allow, or the wrong arguments, in its own words.
    assert answer.finish("Refused: caller_class is not an allowed call.") == answer.REFUSAL


def test_a_failed_search_ends_the_question_without_another_model_call():
    m = model(client=NoGateway())
    reply = m([QUESTION, CALL, tool({"error": "Error executing tool search_docs: token refused: Signature has expired"})])
    assert reply == {"answer": answer.SEARCH_FAILED} and m.labels == []
    assert answer.SEARCH_FAILED == "W1 couldn't search the documents just now. Sign in again, or try later."


def test_every_refusal_ends_with_the_route():
    assert answer.ROUTE == ("For anything outside your documents, ask the team that owns the system, "
                            "or the incident commander during an incident.")
    assert answer.finish(answer.BUDGET_EXHAUSTED) == answer.REFUSAL
    assert answer.REFUSAL.endswith(answer.ROUTE)
    worded = "Nothing in the documents you can read answers this question."
    assert answer.finish(worded) == f"{worded} {answer.ROUTE}"
    typeset = f"Nothing in the documents you can read answers it. {answer.ROUTE.replace(' the system', chr(0x202F) + 'the system')}"
    assert answer.finish(typeset) == typeset  # already there, in gpt-oss's typography
    assert answer.finish("The ack time is 15 minutes (reviewed 2026-06-30).") == \
        "The ack time is 15 minutes (reviewed 2026-06-30)."
    assert answer.finish(answer.SEARCH_FAILED) == answer.SEARCH_FAILED


def test_the_system_prompt_asks_for_two_searches_citations_and_the_route():
    prompt = answer.SYSTEM_PROMPT
    assert "last_reviewed" in prompt and "nothing in the documents you can read" in prompt
    assert answer.ROUTE in prompt and "search once more" in prompt


def test_the_manifest_lists_both_tools_and_the_model_gets_one():
    jsonschema.validate(MANIFEST, SCHEMA)
    assert set(MANIFEST["tools"]) == set(LOCK["tools"])
    assert set(answer.ALLOWED) <= set(MANIFEST["tools"])
    assert MANIFEST["tools"]["caller_class"] == {"args": []}
    assert MANIFEST["regions"] == ["ca-central-1", "ca-west-1"]


def test_prompt_class_and_alias_for_stay_printable():
    printable(answer.prompt_class)
    printable(answer.alias_for)
