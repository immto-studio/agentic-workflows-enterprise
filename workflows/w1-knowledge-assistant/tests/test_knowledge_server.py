"""The knowledge server: the search and caller_class behind its tools, its pinned definitions, and the server over HTTP."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from mcp import Client

from access import Caller, MembershipTable, issue, resolve, verify
from actor_transport import ActorMCP
from conftest import GATEWAY_KEY, MEMBER_OF, SECRET, USERS, W1, fresh_table, log_events
from ingest import Refusal
from search import KnowledgeSearch, highest_class

SERVER_PY = W1 / "knowledge-server" / "server.py"
_spec = importlib.util.spec_from_file_location("w1_server", SERVER_PY)
w1_server = importlib.util.module_from_spec(_spec)
sys.modules["w1_server"] = w1_server  # pydantic resolves the result model's annotations through sys.modules
_spec.loader.exec_module(w1_server)

NOW = datetime.now(timezone.utc)
TABLE = MembershipTable.from_dict(fresh_table(NOW))
STALE = NOW + timedelta(hours=37)


@pytest.fixture(scope="module")
def store():
    served, refusals = w1_server.load_store()
    assert refusals == []
    return served


class GoldenEmbedder:
    """The committed vectors for the golden questions; records the class each query went out as."""

    def __init__(self, golden, vectors):
        self.by_text = {q["question"]: vectors[q["id"]] for q in golden}
        self.classes: list[str] = []

    def __call__(self, query: str, trace_id: str, data_class: str):
        self.classes.append(data_class)
        return self.by_text[query]


def searcher(store, golden, vectors, audit=None, max_class="Restricted"):
    embedder = GoldenEmbedder(golden, vectors)
    return KnowledgeSearch(store, embedder, max_class=max_class, audit=audit or io.StringIO()), embedder


def caller_for(user: str, now: datetime = NOW) -> Caller:
    return resolve(verify(issue(SECRET, USERS[user], f"{user}@larkspur.example"), SECRET), TABLE, now)


def test_the_search_gives_the_on_call_engineer_nothing_restricted_and_logs_no_question(
        store, golden, question_vectors, restricted_docs):
    audit = io.StringIO()
    search, embedder = searcher(store, golden, question_vectors, audit)
    oncall = caller_for("oncall.engineer")
    for q in golden:
        passages = search.search(q["question"], oncall, f"t-{q['id']}")
        assert not {p.doc_id for p in passages} & restricted_docs, q["id"]
    lines = [json.loads(line) for line in audit.getvalue().splitlines()]
    assert len(lines) == len(golden) and all(line["caller"] == USERS["oncall.engineer"] for line in lines)
    assert all(line["groups_from"] == "table" and line["query_class"] == "Internal" for line in lines)
    assert set(embedder.classes) == {"Internal"}
    assert not any(q["question"] in audit.getvalue() for q in golden)  # trace_content: false


def test_a_member_gets_the_restricted_source_and_the_query_carries_the_members_class(
        store, golden, question_vectors):
    search, embedder = searcher(store, golden, question_vectors)
    for q in (q for q in golden if q["trap"] == "access"):
        passages = search.search(q["question"], caller_for(MEMBER_OF[q["required_access_group"]]), "t")
        source = [p for p in passages if p.doc_id == q["source_document"]]
        assert source, q["id"]
        assert highest_class(passages) == source[0].classification  # Confidential or Restricted
        assert embedder.classes[-1] == search.held_class(caller_for(MEMBER_OF[q["required_access_group"]]))
    assert set(embedder.classes) == {"Confidential", "Restricted"}  # the query is part of the conversation


def test_a_stale_table_gives_a_custodian_only_what_everyone_reads(store, golden, question_vectors, restricted_docs):
    audit = io.StringIO()
    search, embedder = searcher(store, golden, question_vectors, audit)
    gq01 = next(q for q in golden if q["id"] == "gq-01")
    custodian = caller_for("vault.custodian", now=STALE)
    assert not {p.doc_id for p in search.search(gq01["question"], custodian, "t")} & restricted_docs
    line = json.loads(audit.getvalue())
    assert line["groups_from"] == "stale table" and line["groups"] == ["lm-all-staff", "lm-eng-all"]
    # The custodian still knows what the runbook says: the query keeps the custodian's class.
    assert line["query_class"] == "Restricted" and embedder.classes == ["Restricted"]


def test_caller_class_is_the_highest_class_the_caller_may_read(store):
    audit = io.StringIO()
    search = KnowledgeSearch(store, lambda q, t, c: np.zeros(1), max_class="Restricted", audit=audit)
    assert search.caller_class(caller_for("oncall.engineer"), "t1") == "Internal"
    assert search.caller_class(caller_for("vault.custodian"), "t2") == "Restricted"
    assert search.caller_class(caller_for("ea.lead"), "t3") == "Confidential"
    stranger = Caller("oid-x", "x@larkspur.example", frozenset({"lm-other"}), "table")
    assert search.caller_class(stranger, "t4") == "Public"
    lines = [json.loads(line) for line in audit.getvalue().splitlines()]
    assert [line["data_class"] for line in lines] == ["Internal", "Restricted", "Confidential", "Public"]
    assert all(line["event"] == "caller_class" and "returned" not in line for line in lines)


def test_a_narrower_grant_today_never_lowers_the_class(store):
    # A stale table grants the custodian only the broad groups, and a token that lists groups can
    # narrow them, but what the custodian may type still counts as Restricted.
    search = KnowledgeSearch(store, lambda q, t, c: np.zeros(1), max_class="Restricted", audit=io.StringIO())
    stale = caller_for("vault.custodian", now=STALE)
    assert stale.groups == {"lm-all-staff", "lm-eng-all"} and search.caller_class(stale, "t") == "Restricted"
    eng_all = next(gid for gid, name in TABLE.group_names.items() if name == "lm-eng-all")
    narrowed = resolve(verify(issue(SECRET, USERS["vault.custodian"], "x", groups=[eng_all]), SECRET), TABLE, NOW)
    assert narrowed.groups == {"lm-eng-all"} and search.caller_class(narrowed, "t") == "Restricted"


def test_the_manifests_cap_binds_the_search_and_caller_class(store, golden, question_vectors, tmp_path):
    assert w1_server.class_cap() == "Restricted"  # manifest/w1-knowledge.yaml
    manifest = tmp_path / "w1-knowledge.yaml"
    manifest.write_text("data_class_max: internal\n", encoding="utf-8")
    cap = w1_server.class_cap(manifest)
    assert cap == "Internal"
    search, _ = searcher(store, golden, question_vectors, max_class=cap)
    for q in (q for q in golden if q["trap"] == "access"):
        member = caller_for(MEMBER_OF[q["required_access_group"]])
        assert {p.classification for p in search.search(q["question"], member, "t")} <= {"Public", "Internal"}
        assert search.caller_class(member, "t") == "Internal"
    with pytest.raises(TypeError):
        KnowledgeSearch(store, lambda q, t, c: np.zeros(1))  # no default cap: the server must pass one


def test_a_caller_with_no_group_that_gates_a_page_causes_no_retrieval_call(store):
    def never(query, trace_id, data_class):
        raise AssertionError("the question was embedded for a caller who can read nothing")

    audit = io.StringIO()
    stranger = Caller("oid-x", "x@larkspur.example", frozenset({"lm-other"}), "table")
    assert KnowledgeSearch(store, never, max_class="Restricted", audit=audit).search("anything", stranger, "t") == []
    assert json.loads(audit.getvalue())["groups"] == []


def test_the_class_of_an_empty_answer_is_the_floor():
    assert highest_class([]) == "Internal"


def test_a_page_refused_after_the_last_build_drops_out_and_the_rest_is_served(monkeypatch, fixed):
    # The committed index holds every page; one of them now fails the gate. The server serves the rest.
    kept = [c for c in fixed if c.doc_id != "rb-claims-aurora-failover.md"]
    refused = [Refusal("rb-claims-aurora-failover.md", "missing last_reviewed", "sre-core")]
    monkeypatch.setattr(w1_server, "read_corpus", lambda variant: (kept, refused))
    served, refusals = w1_server.load_store()
    assert [c.chunk_id for c in served.chunks] == [c.chunk_id for c in kept] and refusals == refused
    full = np.load(w1_server.INDEX_PATH, allow_pickle=False)
    row = [str(i) for i in full["chunk_ids"]].index(kept[-1].chunk_id)
    expected = full["vectors"][row] / np.linalg.norm(full["vectors"][row])
    assert np.allclose(served.vectors[-1], expected)  # each chunk keeps its own vector


def test_a_page_newer_than_the_index_stops_the_server(monkeypatch, fixed, tmp_path):
    index = tmp_path / "fixed.npz"
    np.savez_compressed(index, chunk_ids=[c.chunk_id for c in fixed[1:]], vectors=np.ones((len(fixed) - 1, 4)))
    monkeypatch.setattr(w1_server, "read_corpus", lambda variant: (fixed, []))
    with pytest.raises(SystemExit):
        w1_server.load_store(index)


def test_the_served_definitions_match_the_lock():
    placeholder = KnowledgeSearch(w1_server.VectorStore([], np.zeros((0, 1))), lambda q, t, c: np.zeros(1),
                                  max_class="Restricted", audit=io.StringIO())
    server = w1_server.build_server(placeholder, lambda: TABLE, SECRET, "test", io.StringIO())
    definitions = w1_server.ch05.advertised_definitions(server)
    assert set(definitions) == {"search_docs", "caller_class"}
    w1_server.ch05.verify_lock(definitions, w1_server.ch05.read_lock(w1_server.LOCK_PATH))
    assert definitions["caller_class"]["annotations"]["readOnlyHint"] is True
    assert definitions["caller_class"]["inputSchema"]["properties"] == {}


# --- end to end: the server as a process (conftest), a stand-in for the gateway --------------------

async def call(url: str, token: str | None, tool: str, args: dict):
    transport = ActorMCP(url, token) if token else url
    async with Client(transport) as client:
        return await client.call_tool(tool, args, meta={"trace_id": "e2e"})


def text_of(result) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


def test_end_to_end_the_header_decides_what_comes_back(running_server, fake_gateway, golden, restricted_docs):
    url, log, _ = running_server
    gateway, seen = fake_gateway
    gq01 = next(q for q in golden if q["id"] == "gq-01")
    oncall = issue(SECRET, USERS["oncall.engineer"], "oncall.engineer@larkspur.example")
    custodian = issue(SECRET, USERS["vault.custodian"], "vault.custodian@larkspur.example")
    before = len(seen)

    denied = asyncio.run(call(url, oncall, "search_docs", {"query": gq01["question"]}))
    assert not denied.is_error, text_of(denied) + log.read_text(encoding="utf-8")
    assert not {p["doc_id"] for p in denied.structured_content["passages"]} & restricted_docs

    allowed = asyncio.run(call(url, custodian, "search_docs", {"query": gq01["question"]}))
    assert gq01["source_document"] in {p["doc_id"] for p in allowed.structured_content["passages"]}

    anonymous = asyncio.run(call(url, None, "search_docs", {"query": gq01["question"]}))
    assert anonymous.is_error and "X-Larkspur-Actor" in text_of(anonymous)

    embeddings = [s for s in seen[before:] if s["path"].endswith("/embeddings")]
    assert [s["auth"] for s in embeddings] == [f"Bearer {GATEWAY_KEY}"] * 2
    assert [s["metadata"]["tags"] for s in embeddings] == [["workflow:w1-knowledge", "data_class:internal"],
                                                           ["workflow:w1-knowledge", "data_class:restricted"]]
    events = log_events(log)
    start = next(e for e in events if e["event"] == "server_start")
    assert start["class_cap"] == "Restricted" and start["refused_pages"] == []
    assert set(start["tools"]) == {"search_docs", "caller_class"}
    searches = [e for e in events if e["event"] == "search"]
    assert [e["caller"] for e in searches][-2:] == [USERS["oncall.engineer"], USERS["vault.custodian"]]
    assert any(e["event"] == "refused" for e in events)


def test_end_to_end_caller_class_and_the_token_checks(running_server):
    url, log, _ = running_server
    oncall = issue(SECRET, USERS["oncall.engineer"], "oncall.engineer@larkspur.example")
    custodian = issue(SECRET, USERS["vault.custodian"], "vault.custodian@larkspur.example")
    assert asyncio.run(call(url, oncall, "caller_class", {})).structured_content == {"data_class": "Internal"}
    assert asyncio.run(call(url, custodian, "caller_class", {})).structured_content == {"data_class": "Restricted"}
    other_client = issue(SECRET, USERS["vault.custodian"], "x", client="b2256ae9-764f-50e9-9f14-7c607a8541cf")
    refused = asyncio.run(call(url, other_client, "caller_class", {}))
    assert refused.is_error and "azp" in text_of(refused)


def test_end_to_end_the_server_reads_a_new_table(running_server, golden, restricted_docs):
    url, log, table = running_server
    gq01 = next(q for q in golden if q["id"] == "gq-01")
    custodian = issue(SECRET, USERS["vault.custodian"], "vault.custodian@larkspur.example")
    original = table.read_text(encoding="utf-8")
    try:
        data = json.loads(original)
        data["members"][USERS["vault.custodian"]] = ["lm-all-staff", "lm-eng-all"]  # removed by a delta
        table.write_text(json.dumps(data), encoding="utf-8")
        later = time.time() + 5
        os.utime(table, (later, later))
        result = asyncio.run(call(url, custodian, "search_docs", {"query": gq01["question"]}))
        assert not {p["doc_id"] for p in result.structured_content["passages"]} & restricted_docs
        assert sum(e["event"] == "membership" for e in log_events(log)) >= 2
    finally:
        table.write_text(original, encoding="utf-8")
        os.utime(table, (time.time() + 10, time.time() + 10))
