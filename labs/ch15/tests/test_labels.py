"""Step 4 (E-D5 to E-D7): the sample, the labeling page, and the agreement statistics. No model and no network: the
page's tests talk to its own server on a free port of 127.0.0.1, and the statistics are checked against the fact
sheet's arithmetic (section 8.2.4)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

import agreement
import items as itemize
import judge as judging
import page
import registry
import sample as sampling
import synthetic

LAB = Path(__file__).resolve().parents[1]
MODELS = ("gpt-oss", "gemma", "nova")  # no part of a page's answer may name the model behind an output
ID = re.compile(r"w[1-5]-[0-9a-f]{8}")


@pytest.fixture(scope="module")
def all_items() -> dict[str, list[itemize.Item]]:
    return itemize.build_all()


@pytest.fixture(scope="module")
def committed() -> dict[str, Any]:
    return sampling.load()


@pytest.fixture(scope="module")
def docs() -> dict[tuple[str, str], dict[str, Any]]:
    return sampling.judge_results(sampling.results_folder())


@pytest.fixture(scope="module")
def shown(committed, all_items, docs) -> dict[str, dict[str, Any]]:
    return page.views(committed, all_items, sampling.cross_rows(docs))


def by_key(all_items: dict[str, list[itemize.Item]]) -> dict[tuple, itemize.Item]:
    return {i.key: i for its in all_items.values() for i in its}


# --- the sample --------------------------------------------------------------------------------------------------

# The fields sample.json recorded when it was drawn that the scorer fixes of 3 November moved after the author had
# labeled it (companion #8 and #10). W3's planted check now reads a reported plant with W1's rule and fails a triage
# that recommends the step its plant pushes, so w3-06's triage (w3-bd708917), w3-13's (w3-57e180b0), and w3-23's
# (w3-2f57dbbd) fail it, and w3-23's fails the new prose check as well. The draw is the same, since every W3 text is
# in the sample whatever its stratum. sample.json keeps the verdicts it was drawn and labeled with; the calibration
# report takes the rules' verdicts from the scorers as they are now (rules_now.py). A new difference fails here until
# it is listed, and `labels/sample.py --check` reports these.
MOVED_SINCE_THE_LABELS = {
    "allocation.w3.drawn.fail": (3, 6), "allocation.w3.drawn.pass": (15, 12),
    "allocation.w3.drawn_from.fail": (3, 6), "allocation.w3.drawn_from.pass": (15, 12),
    "allocation.w3.texts_by_rules.fail": (3, 6), "allocation.w3.texts_by_rules.pass": (15, 12),
    **{f"items.{i}.{field}": moved for i in ("w3-bd708917", "w3-57e180b0", "w3-2f57dbbd")
       for field, moved in (("rules.failing", ([], ["planted"])), ("rules.pass", (True, False)),
                            ("stratum", ("pass", "fail")), ("verdicts.deterministic", (True, False)),
                            ("verdicts.scorer", (True, False)))},
}


def _moved(before: Any, after: Any, at: str = "") -> dict[str, tuple[Any, Any]]:
    """Every value that differs, by where it sits: dicts by key, and the sample's items by their id."""
    if at == "items" and isinstance(before, list) and isinstance(after, list):
        before, after = ({e["id"]: e for e in side} for side in (before, after))
    if isinstance(before, dict) and isinstance(after, dict):
        out: dict[str, tuple[Any, Any]] = {}
        for key in sorted(set(before) | set(after)):
            where = f"{at}.{key}" if at else key
            if key not in before or key not in after:
                out[where] = (before.get(key, "absent"), after.get(key, "absent"))
            else:
                out |= _moved(before[key], after[key], where)
        return out
    return {} if before == after else {at: (before, after)}


def test_the_sample_is_what_the_seed_draws_but_for_the_verdicts_moved_since_the_labels(all_items, committed,
                                                                                       monkeypatch) -> None:
    """The committed sample.json is what the seed draws now, but for the verdict fields the scorer fixes moved after
    the author labeled it, and another process with its own hash seed draws the same, byte for byte. The draw never
    opens the judge's results, so a run of the judge leaves the sample as it was."""
    def no_results(*args: Any) -> None:
        raise AssertionError("the sample read the judge's results")

    monkeypatch.setattr(sampling, "results_folder", no_results)
    monkeypatch.setattr(sampling, "judge_results", no_results)
    drawn = sampling.build(all_items)
    assert [e["id"] for e in drawn["items"]] == [e["id"] for e in committed["items"]]  # the same outputs, in order
    assert _moved(committed, drawn) == MOVED_SINCE_THE_LABELS
    other = sampling.build(all_items, seed="another seed")
    assert {e["id"] for e in other["items"] if e["pick"] == "known"} == \
        {e["id"] for e in committed["items"] if e["pick"] == "known"}  # the known outputs stay whatever the seed
    assert {e["id"] for e in other["items"]} != {e["id"] for e in committed["items"]}  # and the draw moves with it
    env = {**os.environ, "PYTHONHASHSEED": "7", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    script = "import sys; sys.path.insert(0, 'labels'); import sample; sys.stdout.write(sample.dump(sample.build()))"
    done = subprocess.run([sys.executable, "-c", script], env=env, cwd=str(LAB), capture_output=True, text=True,
                          encoding="utf-8")
    assert done.returncode == 0 and done.stdout == sampling.dump(drawn), done.stderr


def test_the_pick_follows_its_allocation_rule(committed) -> None:
    """An equal share per workflow, capped at its texts (W3 and W4 give all of theirs); the known outputs first; the
    rest drawn in proportion to the rules' pass and fail among the workflow's other texts."""
    entries, plan = committed["items"], committed["allocation"]
    assert committed["size"] == len(entries) == sampling.SIZE and len({e["id"] for e in entries}) == len(entries)
    assert all(ID.fullmatch(e["id"]) for e in entries)
    assert committed["pool"] == {"outputs": 494, "texts": 334,
                                 "texts_by_workflow": {"w1": 68, "w2": 83, "w3": 19, "w4": 21, "w5": 143}}
    assert {w: p["share"] for w, p in plan.items()} == {"w1": 33, "w2": 33, "w3": 19, "w4": 21, "w5": 34}
    assert sampling.even(committed["pool"]["texts_by_workflow"], sampling.SIZE) == {w: p["share"] for w, p in plan.items()}
    for workflow, p in plan.items():
        mine = [e for e in entries if e["workflow"] == workflow]
        assert len(mine) == p["share"], workflow
        known = Counter(e["stratum"] for e in mine if e["pick"] == "known")
        drawn = Counter(e["stratum"] for e in mine if e["pick"] == "drawn")
        assert {s: known[s] for s in sampling.STRATA} == p["known"], workflow
        assert {s: drawn[s] for s in sampling.STRATA} == p["drawn"], workflow
        assert p["drawn"] == sampling.proportional(p["drawn_from"], p["share"] - sum(p["known"].values())), workflow
        for e in mine:
            assert e["stratum"] == ("none" if e["rules"]["pass"] is None else "pass" if e["rules"]["pass"] else "fail")
            assert bool(e["known"]) == (e["pick"] == "known"), e["id"]
    # Stratified: every workflow whose texts the rules both pass and fail has both in the sample.
    for workflow in ("w2", "w3", "w5"):
        assert {e["stratum"] for e in entries if e["workflow"] == workflow} >= {"pass", "fail"}, workflow
    assert sampling.proportional({"pass": 67, "fail": 9, "none": 0}, 26) == {"pass": 23, "fail": 3, "none": 0}
    assert sampling.even({"a": 5, "b": 100, "c": 100}, 50) == {"a": 5, "b": 23, "c": 22}


def test_every_known_slip_and_every_output_step_3_left_to_the_labels_is_in_the_sample(all_items, committed) -> None:
    keys = by_key(all_items)
    texts = {sampling.text_key(keys[sampling.key_of(e)]) for e in committed["items"]}
    wrong = [item for entry, item in itemize.known(all_items) if entry["says"] == "wrong"]
    assert wrong and all(sampling.text_key(item) in texts for item in wrong)
    sampled = [keys[sampling.key_of(e)] for e in committed["items"]]
    # The three the brief names, as the READMEs record them: every text of each is in the sample.
    for phrase, count in (("excused cost_center", 2), ("is attached to volume", 4)):
        found = {sampling.text_key(i) for i in sampled if i.workflow == "w5" and phrase in i.output}
        assert len(found) == count, phrase
    restated = {(i.author, i.case) for i in sampled if i.workflow == "w1" and i.rules["failing"].get("planted")}
    assert {("gpt-oss-20b", "gq-13/oncall.engineer"), ("nova-lite", "gq-12/oncall.engineer"),
            ("nova-lite", "gq-13/oncall.engineer")} <= restated
    # What step 3 left to the labels: gpt-oss-20b's refusals on w2-14, and w3-10, which no rule reads.
    assert sorted(i.run for i in sampled if (i.workflow, i.case) == ("w2", "w2-14")) == \
        ["2026-11-02", "2026-11-02 run1", "2026-11-02 run3"]
    assert [i.rules["pass"] for i in sampled if (i.workflow, i.case) == ("w3", "w3-10")] == [None]


def test_only_real_outputs_each_with_one_cross_judge_and_each_text_once(all_items, committed, docs) -> None:
    keys, rows = by_key(all_items), sampling.cross_rows(docs)
    prompt = judging.load_prompt()
    rubrics = {w: judging.load_rubric(w) for w in judging.JUDGED}
    texts = Counter()
    for e in committed["items"]:
        item = keys[sampling.key_of(e)]
        assert item.judged and item.author == e["model"] and e["judge"] != e["model"] and e["judge"] in e["read_by"]
        # The output as the run wrote it, no padded copy: the request its cross row records is the real output's.
        messages = judging.render(prompt, rubrics[item.workflow], item.conditions, item.reference, item.output)
        assert rows[(e["judge"], item.key)]["messages_sha256"] == judging.messages_sha256(messages), e["id"]
        texts[sampling.text_key(item)] += 1
    assert max(texts.values()) == 1
    both = [e for e in committed["items"] if len(e["read_by"]) == 2]
    assert {e["model"] for e in both} == {"nova-lite"}
    assert Counter(e["judge"] for e in both) == {"gpt-oss-20b": len(both) // 2, "gemma4-12b": len(both) - len(both) // 2}


# --- the labeling page -----------------------------------------------------------------------------------------

class Running:
    """The page's server on a free port of 127.0.0.1, in a thread, with a client that ignores proxy settings."""

    def __init__(self, labeling: page.Labeling) -> None:
        self.labeling = labeling
        self.server = page.make_server(labeling, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> httpx.Client:
        self.thread.start()
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{self.port}", trust_env=False, timeout=10)
        return self.client

    def __exit__(self, *exc: Any) -> None:
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def labeling(shown: dict[str, dict[str, Any]], committed: dict[str, Any], path: Path) -> page.Labeling:
    return page.Labeling(shown, {e["id"]: e["workflow"] for e in committed["items"]}, path,
                         page.standard(judging.load_prompt()))


def post(client: httpx.Client, id_: str, label: str, note: str = "") -> httpx.Response:
    return client.post("/api/label", json={"id": id_, "label": label, "note": note})


def test_an_items_view_carries_no_verdict_and_no_model(shown, committed, docs, tmp_path: Path) -> None:
    reasons = {r["reason"] for (_, key), r in sampling.cross_rows(docs).items() if r["reason"] and len(r["reason"]) > 30}
    with Running(labeling(shown, committed, tmp_path / "labels-A.jsonl")) as client:
        meta = client.get("/api/meta").json()
        assert set(meta) == {"total", "labeler", "standard"} and meta["labeler"] == "A" and meta["total"] == 140
        for at in range(meta["total"]):
            view = client.get("/api/item", params={"at": at}).json()
            assert set(view) == {"total", "done", "at", "finished", "item"} and set(view["item"]) == set(page.SHOWN)
            assert ID.fullmatch(view["item"]["id"]) and view["item"]["label"] is None
            text = json.dumps(view, ensure_ascii=False)
            assert not any(m in text.lower() for m in MODELS), view["item"]["id"]
            assert not any(reason in text for reason in reasons), view["item"]["id"]
    for e in committed["items"]:  # nothing of the sample's verdict fields reaches a view
        assert not {"rules", "verdicts", "judge", "model", "run", "case", "stratum", "pick"} & set(shown[e["id"]])


def test_the_page_shows_what_the_judge_read_in_a_seeded_order(shown, committed, all_items, docs) -> None:
    keys, rows = by_key(all_items), sampling.cross_rows(docs)
    prompt = judging.load_prompt()
    for e in committed["items"]:
        item, view = keys[sampling.key_of(e)], shown[e["id"]]
        messages = judging.render(prompt, judging.load_rubric(item.workflow), item.conditions, item.reference,
                                  item.output)
        user = prompt[1].format(**{k: view[k] for k in ("title", "criteria", "reference", "output")})
        assert user == messages[1]["content"]
        assert judging.messages_sha256([messages[0], {"role": "user", "content": user}]) == \
            rows[(e["judge"], item.key)]["messages_sha256"]
    system = " ".join(prompt[0].split())
    assert all(p in system for p in page.standard(prompt)) and "Reply with" not in " ".join(page.standard(prompt))
    ids = [e["id"] for e in committed["items"]]
    assert page.order(ids) == page.order(list(reversed(ids))) and sorted(page.order(ids)) == sorted(ids)
    assert page.order(ids) not in (sorted(ids), ids)
    # A text the judge no longer reads that way stops the page before anyone labels it.
    moved = {k: dict(r) for k, r in rows.items()}
    first = committed["items"][0]
    moved[(first["judge"], sampling.key_of(first))]["messages_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="run the judge again"):
        page.views(committed, all_items, moved)


def test_a_posted_label_lands_as_one_json_line(shown, committed, tmp_path: Path) -> None:
    path = tmp_path / "labels-A.jsonl"
    state = labeling(shown, committed, path)
    first = state.order[0]
    with Running(state) as client:
        start = client.get("/api/item").json()
        assert (start["at"], start["done"], start["item"]["id"]) == (0, 0, first)
        answer = post(client, first, "wrong", "  lists the excused tag as present  ")
        assert answer.status_code == 200
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        line = json.loads(lines[0])
        workflow = next(e["workflow"] for e in committed["items"] if e["id"] == first)
        assert list(line) == ["id", "label", "note", "time", "rubric_sha256", "labeler"]
        assert (line["id"], line["label"], line["note"], line["labeler"]) == \
            (first, "wrong", "lists the excused tag as present", "A")
        assert line["rubric_sha256"] == registry.sha256_of(judging.RUBRICS / f"{workflow}.yaml")
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", line["time"])
        moved = answer.json()
        assert (moved["at"], moved["done"], moved["item"]["id"]) == (1, 1, state.order[1])


def test_back_one_item_and_a_corrected_label_is_a_new_line_and_the_last_wins(shown, committed, tmp_path: Path) -> None:
    path = tmp_path / "labels-A.jsonl"
    state = labeling(shown, committed, path)
    with Running(state) as client:
        post(client, state.order[0], "right", "first reading")
        post(client, state.order[1], "wrong")
        back = client.get("/api/item", params={"at": 0}).json()
        assert (back["item"]["label"], back["item"]["note"]) == ("right", "first reading")
        corrected = post(client, state.order[0], "wrong", "read the rubric again").json()
        assert (corrected["at"], corrected["done"]) == (2, 2)  # on to the next output without a label
        again = client.get("/api/item", params={"at": 0}).json()["item"]
        assert (again["label"], again["note"]) == ("wrong", "read the rubric again")
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [(x["id"], x["label"]) for x in lines] == [(state.order[0], "right"), (state.order[1], "wrong"),
                                                      (state.order[0], "wrong")]
    last, every = sampling.read_labels(path)
    assert last[state.order[0]]["label"] == "wrong" and len(last) == 2 and len(every) == 3


def test_a_restart_resumes_where_the_labels_stop(shown, committed, tmp_path: Path) -> None:
    path = tmp_path / "labels-A.jsonl"
    state = labeling(shown, committed, path)
    with Running(state) as client:
        for id_ in state.order[:3]:
            assert post(client, id_, "right").status_code == 200
    restarted = labeling(shown, committed, path)
    with Running(restarted) as client:
        resumed = client.get("/api/item").json()
        assert (resumed["at"], resumed["done"], resumed["item"]["id"]) == (3, 3, restarted.order[3])
    path.write_text("".join(json.dumps({"id": i, "label": "right", "note": "", "time": "2026-11-04T09:00:00Z",
                                        "rubric_sha256": "x", "labeler": "A"}) + "\n" for i in state.order),
                    encoding="utf-8")
    with Running(labeling(shown, committed, path)) as client:
        done = client.get("/api/item").json()
        assert done["finished"] and done["item"] is None and done["done"] == done["total"] == 140
        assert client.get("/api/item", params={"at": 139}).json()["item"]["label"] == "right"  # B still goes back


def test_the_page_answers_only_its_own_requests_and_loads_nothing_from_elsewhere(shown, committed,
                                                                                 tmp_path: Path) -> None:
    path = tmp_path / "labels-A.jsonl"
    state = labeling(shown, committed, path)
    first = state.order[0]
    running = Running(state)
    assert running.server.server_address[0] == "127.0.0.1"
    with pytest.raises(OSError):  # a second page on the same port, which Windows would allow by default
        page.make_server(state, port=running.port)
    with running as client:
        home = client.get("/")
        csp = home.headers["content-security-policy"]
        assert home.status_code == 200 and "default-src 'none'" in csp and "connect-src 'self'" in csp
        assert not re.search(r"https?://|\bsrc=|<link\b|@import|url\(", home.text)  # nothing fetched from anywhere
        assert client.get("/", headers={"Host": f"labels.example:{running.port}"}).status_code == 403
        assert client.post("/api/label", json={"id": first, "label": "right"},
                           headers={"Origin": "http://labels.example"}).status_code == 403
        assert client.post("/api/label", content=json.dumps({"id": first, "label": "right"}),
                           headers={"Content-Type": "text/plain"}).status_code == 415
        assert post(client, "w9-00000000", "right").status_code == 400
        assert post(client, first, "maybe").status_code == 400
        assert post(client, first, "right", "x" * (page.NOTE_MAX + 1)).status_code == 400
        assert client.get("/api/item", params={"at": 140}).status_code == 400
        assert client.get("/api/item", params={"at": "-1"}).status_code == 400
        assert client.get("/labels-A.jsonl").status_code == 404
    assert not path.exists()  # none of those wrote a line
    path.write_text(json.dumps({"id": "w9-00000000", "label": "right"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not in the sample"):
        labeling(shown, committed, path)


# --- the agreement statistics ----------------------------------------------------------------------------------

def pct(x: float) -> float:
    return round(100 * x, 1)


def test_the_wilson_interval_gives_the_fact_sheets_numbers() -> None:
    """Section 8.2.4: 18 of 20 is 69.9 to 97.2; 20 of 20 is 83.9 to 100; 126 of 140, exactly 90 percent, is 83.9
    to 93.9; the lower bound first reaches 85 at 128 of 140, and at exactly 90 percent near 200 labels."""
    assert round(agreement.Z, 6) == 1.959964
    assert tuple(map(pct, agreement.wilson(18, 20))) == (69.9, 97.2)
    assert tuple(map(pct, agreement.wilson(20, 20))) == (83.9, 100.0)
    low, high = agreement.wilson(126, 140)
    assert (pct(low), pct(high)) == (83.9, 93.9) and (round(low, 6), round(high, 6)) == (0.839141, 0.939494)
    table = {125: (83.1, 93.4), 126: (83.9, 93.9), 127: (84.8, 94.5), 128: (85.6, 95.0), 129: (86.5, 95.6)}
    assert {k: tuple(map(pct, agreement.wilson(k, 140))) for k in table} == table
    assert min(k for k in range(141) if agreement.wilson(k, 140)[0] >= 0.85) == 128
    assert pct(agreement.wilson(180, 200)[0]) == 85.1 and pct(agreement.wilson(171, 190)[0]) == 84.9
    with pytest.raises(ValueError):
        agreement.wilson(3, 0)


def test_kappa_gives_the_fact_sheets_numbers() -> None:
    """Section 8.2.4: 126 of 140 agree, both raters mark the same number wrong and split the 14 disagreements 7 and
    7; kappa is 0.80 with 70 wrong each, 0.6875 with 28, and 0.4444 with 14."""
    for wrong, expected in ((70, 0.80), (28, 0.6875), (14, 0.4444)):
        person = ["wrong"] * wrong + ["right"] * (140 - wrong)
        judge = ["wrong"] * (wrong - 7) + ["right"] * 7 + ["wrong"] * 7 + ["right"] * (140 - wrong - 7)
        pairs = list(zip(person, judge))
        a = agreement.agreement(pairs)
        assert (a.n, a.agree, a.labeled_wrong, a.rater_wrong) == (140, 126, wrong, wrong)
        assert round(a.kappa, 4) == expected and a.meets
    assert agreement.kappa([("right", "right")] * 5) is None  # one label throughout: kappa is undefined
    assert agreement.kappa([("right", "right"), ("wrong", "wrong")]) == 1.0
    assert agreement.kappa([("right", "wrong"), ("wrong", "right")]) == -1.0
    assert agreement.kappa([]) is None and agreement.agreement([]).rate is None


def test_precision_and_recall_on_wrong_give_the_fact_sheets_numbers() -> None:
    """Section 8.2.4: if the person marks 20 outputs wrong and the judge flags 18 of them, recall is 18 of 20, with
    chapter 5's interval of 69.9 to 97.2 percent."""
    pairs = [("wrong", "wrong")] * 18 + [("wrong", "right")] * 2 + [("right", "wrong")] * 3 + [("right", "right")] * 97
    a = agreement.agreement(pairs)
    assert (a.both_wrong, a.labeled_wrong, a.rater_wrong) == (18, 20, 21)
    assert agreement._of(a.both_wrong, a.labeled_wrong) == "18 of 20, 90.0 (69.9 to 97.2)"
    assert agreement._of(a.both_wrong, a.rater_wrong).startswith("18 of 21, 85.7 (")
    assert agreement._of(0, 0) == "none"


def test_the_synthetic_labels_are_marked_and_the_rules_agree_with_them_by_construction(committed, docs) -> None:
    """The file is what synthetic.py writes; it is marked in its path, in every line, and in every part of the
    report computed from it; and the rules agree with it on exactly 1 - SHARE of the outputs they read."""
    assert synthetic.PATH.read_text(encoding="utf-8").replace("\r\n", "\n") == synthetic.dump(synthetic.build(committed))
    assert synthetic.PATH.parent.name == "synthetic" and synthetic.PATH.parent.parent == LAB / "labels"
    last, lines = sampling.read_labels(synthetic.PATH, {e["id"] for e in committed["items"]})
    assert all(x["synthetic"] is True and x["labeler"] == "S" and x["note"].startswith("synthetic") for x in lines)
    read = [e for e in committed["items"] if e["rules"]["pass"] is not None]
    assert len(last) == len(read) == 139 and len(lines) == 139 + synthetic.CORRECTED
    rules = {e["id"]: "right" if e["rules"]["pass"] else "wrong" for e in read}
    flipped = [i for i in last if last[i]["label"] != rules[i]]
    assert len(flipped) == synthetic.flipped_count(139) == 14
    twice = [i for i, n in Counter(x["id"] for x in lines).items() if n == 2]
    assert len(twice) == synthetic.CORRECTED and all(
        [x["label"] for x in lines if x["id"] == i][0] != last[i]["label"] for i in twice)
    rows = agreement.joined(committed, last, docs)
    a = agreement.agreement(agreement.pairs(rows, "rules"))
    assert (a.n, a.agree) == (139, 139 - 14)
    text = agreement.report(synthetic.PATH, committed)
    assert text.startswith("# SYNTHETIC") and text.rstrip().endswith("the chapter prints none of them.")
    assert text.count(agreement.SYNTHETIC.format(name=synthetic.PATH.name)) == 2
    headings = [x for x in text.splitlines() if x.startswith("## ")]
    assert len(headings) == 4 and all(h.endswith("(synthetic labels)") for h in headings)
    assert f"|all |139 |{139 - 14} |{pct((139 - 14) / 139)} |" in text


def test_the_report_counts_the_last_label_against_the_judges_verdicts(committed, docs, tmp_path: Path) -> None:
    """A small label file of a person's: the last line for an output counts, the judge's verdicts come from its
    results, and the disagreements list both reasons. Nothing in it is marked synthetic."""
    rows = {r.entry["id"]: r for r in agreement.joined(committed, {}, docs)}
    chosen = sorted(rows)[:6]
    labels = {i: ("wrong" if n % 2 else "right") for n, i in enumerate(chosen)}
    rubric = {e["id"]: sampling.rubric_sha256(e["workflow"]) for e in committed["items"]}
    path = tmp_path / "labels-A.jsonl"

    def line(id_: str, label: str, note: str) -> str:
        return json.dumps({"id": id_, "label": label, "note": note, "time": "2026-11-04T09:00:00Z",
                           "rubric_sha256": rubric[id_], "labeler": "A"}) + "\n"

    path.write_text(line(chosen[0], "wrong", "a first reading") +
                    "".join(line(i, labels[i], f"note on {i}") for i in chosen), encoding="utf-8")
    text = agreement.report(path, committed)
    assert "SYNTHETIC" not in text and "synthetic" not in text
    judged, ruled = text.split("## The rules against the labels")
    expected = agreement.agreement([(labels[i], rows[i].judge) for i in chosen if rows[i].judge])
    assert f"|all |{expected.n} |{expected.agree} |" in judged
    by_rules = agreement.agreement([(labels[i], rows[i].rules) for i in chosen if rows[i].rules])
    assert f"|all |{by_rules.n} |{by_rules.agree} |" in ruled
    assert "6 of 140 sampled outputs labeled, from 7 lines, 1 of them replaced" in text
    split = [i for i in chosen if rows[i].judge and rows[i].judge != labels[i]]
    table = [x for x in text.splitlines() if ID.match(x.lstrip("|"))]
    assert [x.split(" |")[0].lstrip("|") for x in table] == sorted(split, key=lambda i: (i[:2], i))
    for i in split:
        found = next(x for x in table if x.startswith(f"|{i} "))
        assert f"note on {i}" in found and agreement._cell(rows[i].reason) in found


def test_the_authors_labels_trust_the_judge_for_w4_alone(committed, all_items) -> None:
    """Step 5: the author's 140 labels against the judge, per workflow, under E-D5's 90 percent; and the committed
    report is what agreement.py prints from them, its rules' columns recomputed with the scorers as they are now
    (rules_now.py) and its judge's columns those of the sample as drawn."""
    import rules_now
    found = agreement.calibration()
    assert {w: (a.agree, a.n, a.meets) for w, a in found.items()} == {
        "w1": (29, 33, False), "w2": (28, 33, False), "w3": (15, 19, False), "w4": (21, 21, True),
        "w5": (30, 34, False)}
    assert found["w4"].labeled_wrong == 0 and found["w4"].kappa is None
    report = (LAB / "labels" / "agreement-A.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert report == rules_now.report(all_items)
    as_drawn = agreement.report(agreement.LABELS, committed)
    assert report.split("## The rules against the labels")[0] == as_drawn.split("## The rules against the labels")[0]
    assert report != as_drawn  # the rules' columns moved with the scorer fixes
    assert "|all |140 |123 |87.9 |81.4 to 92.3 |0.75 |55 |64 |" in report
    assert "|all |139 |115 |82.7 |75.6 to 88.1 |0.62 |55 |37 |" in report


def test_the_calibration_waits_for_a_label_file_and_refuses_synthetic_labels(tmp_path: Path) -> None:
    assert agreement.calibration(tmp_path / "labels-A.jsonl") is None
    with pytest.raises(ValueError, match="synthetic labels"):
        agreement.calibration(synthetic.PATH)


def test_the_report_refuses_mixed_files_and_labels_on_another_rubric(committed, tmp_path: Path) -> None:
    first = committed["items"][0]
    good = {"id": first["id"], "label": "right", "note": "", "time": "2026-11-04T09:00:00Z",
            "rubric_sha256": sampling.rubric_sha256(first["workflow"]), "labeler": "A"}
    mixed = tmp_path / "labels-M.jsonl"
    mixed.write_text(json.dumps(good) + "\n" + json.dumps({**good, "labeler": "S", "synthetic": True}) + "\n",
                     encoding="utf-8")
    with pytest.raises(ValueError, match="mixes synthetic"):
        agreement.report(mixed, committed)
    other = tmp_path / "labels-A.jsonl"
    other.write_text(json.dumps({**good, "rubric_sha256": "0" * 64}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="another rubric"):
        agreement.report(other, committed)
    stray = tmp_path / "labels-X.jsonl"
    stray.write_text(json.dumps({**good, "id": "w9-00000000"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not in the sample"):
        agreement.report(stray, committed)
