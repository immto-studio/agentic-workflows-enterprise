"""The gate (E-D9): the thresholds file, the baseline against its source, and a live run against the baseline, case by
case and check by check, with the pins that invalidate it. The runs here are the committed baseline changed by hand,
so no test needs a model."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "ci"))

import baseline as baseline_file  # noqa: E402
import gate  # noqa: E402
import measure  # noqa: E402
import registry  # noqa: E402

DIGEST = "a" * 64


@pytest.fixture(scope="module")
def committed() -> dict:
    return registry.read_json(gate.BASELINE)


@pytest.fixture(scope="module")
def thresholds() -> dict:
    found, problems = gate.load_thresholds()
    assert problems == []
    return found


@pytest.fixture(scope="module")
def now() -> dict:
    return measure.current_pins()


def pinned(document: dict) -> dict:
    """The document with a digest for every model, as a baseline accepted from a live run holds one."""
    out = copy.deepcopy(document)
    for pin in out["pins"]["workflows"].values():
        for model in pin["models"].values():
            model["digest"] = DIGEST
    return out


def as_run(document: dict) -> dict:
    run = pinned(document)
    run["kind"] = "live"
    run["run"] = {"id": "2026-11-04T000000Z-gpt-oss-20b", "model": "gpt-oss-20b", "judge": "gemma4-12b", "complete": True,
                  "why_partial": None}
    return run


def passing(workflow: str, check: str, run: dict) -> list[str]:
    return [c for c, v in run["workflows"][workflow]["cases"].items() if v.get(check) is True]


def set_case(run: dict, workflow: str, case: str, check: str, value: bool | None) -> None:
    run["workflows"][workflow]["cases"][case][check] = value
    run["workflows"][workflow]["tally"] = measure.tally(workflow, run["workflows"][workflow]["cases"])


def rows(report: dict, workflow: str) -> dict[str, dict]:
    return {r["check"]: r for r in report["workflows"][workflow]["rows"]}


# --- the thresholds -------------------------------------------------------------------------------------------------

def test_every_check_of_every_set_has_a_threshold_and_a_written_reason(thresholds) -> None:
    for workflow in measure.WORKFLOWS:
        assert list(thresholds[workflow]) == measure.check_names(workflow)
        for name, entry in thresholds[workflow].items():
            assert entry["why"], (workflow, name)


def test_the_controls_hold_at_zero_and_the_judge_is_not_gated(thresholds) -> None:
    """E-D11: the deterministic controls at 100 percent and no forbidden call; the judge waits for E-D5."""
    import deterministic
    for workflow in measure.WORKFLOWS:
        found = thresholds[workflow]
        for name, (family, _, _) in deterministic.CHECKS[workflow].items():
            if family == "controls":
                assert found[f"deterministic.{name}"]["threshold"] == 0, (workflow, name)
        if "trajectory.forbidden" in found:
            assert found["trajectory.forbidden"]["threshold"] == 0
        assert found["scorer"]["threshold"] is None
        if workflow in measure.JUDGED:
            assert found["judge"]["threshold"] is None and found["judge"]["reason"] == "judge"
    # Only the model's own wording or reads, on the sets of 20 to 25 cases, may lose a case.
    loose = {(w, n) for w, found in thresholds.items() for n, e in found.items() if e["threshold"]}
    assert loose and all(thresholds[w][n]["reason"] == "model" and thresholds[w][n]["threshold"] == 1 for w, n in loose)
    assert {w for w, _ in loose} == {"skeleton", "w1", "w2", "w3"}


def test_a_thresholds_file_that_leaves_a_check_out_or_misnames_one_is_refused(tmp_path: Path) -> None:
    data = registry.read_yaml(gate.THRESHOLDS)
    del data["workflows"]["w2"]["deterministic.masked"]
    data["workflows"]["w3"]["deterministic.color"] = {"threshold": 0, "reason": "code"}
    data["workflows"]["w4"]["deterministic.class"] = {"threshold": -1, "reason": "code"}
    data["workflows"]["w5"]["deterministic.bodies"] = {"threshold": True, "reason": "small"}
    data["workflows"]["w1"]["deterministic.facts"] = {"threshold": 1, "reason": "luck"}
    path = tmp_path / "thresholds.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    _, problems = gate.load_thresholds(path)
    assert "w2: no threshold for deterministic.masked" in problems
    assert "w3: deterministic.color is not a check of this set" in problems
    assert any(p.startswith("w4: deterministic.class's threshold is -1") for p in problems)
    assert any(p.startswith("w5: deterministic.bodies's threshold is True") for p in problems)
    assert "w1: deterministic.facts names the reason 'luck', which the file doesn't write" in problems


# --- the baseline -------------------------------------------------------------------------------------------------

def test_the_baseline_is_what_the_kept_results_give(committed) -> None:
    """Built from step 2's replay and step 3's judge files, with the pins they record."""
    assert committed["source"]["kind"] == "kept" and baseline_file.check() == []
    assert committed["source"]["runs"] == baseline_file.RUNS
    for workflow, entry in committed["workflows"].items():
        assert entry["tally"] == measure.tally(workflow, entry["cases"])
        pin = committed["pins"]["workflows"][workflow]
        assert pin["set"]["version"] == convert_version(workflow)
        assert all(m["digest"] is None for m in pin["models"].values())  # no kept run recorded one
    judge = committed["pins"]["judge"]
    assert (judge["model"], judge["served"], judge["server"]) == ("gemma4-12b", "ollama_chat/gemma4:12b", "0.40.13")
    assert judge["digest"].startswith("6114515d63c1")


def convert_version(workflow: str) -> str:
    import convert
    return convert.version(workflow)


def test_the_baseline_carries_no_verdict_of_step_3s_judge(committed) -> None:
    """Counted over the outputs outside the author's sample and set against step 3's tables, step 3's verdicts would
    say how the judge read the sampled ones, so the baseline holds how many outputs the judge read and none of its
    verdicts. Every W3 and W4 output is a sampled text."""
    for workflow in measure.JUDGED:
        judge = committed["workflows"][workflow]["judge"]
        assert (judge["right"], judge["wrong"], judge["no_verdict"]) == (None, None, None) and judge["judged"] > 0
        assert judge["verdicts"] == baseline_file.NOT_CARRIED
    for workflow in ("w3", "w4"):
        assert committed["workflows"][workflow]["judge"]["withheld"] == committed["workflows"][workflow]["judge"]["judged"]
    assert '"verdict"' not in gate.BASELINE.read_text(encoding="utf-8")


def test_a_baseline_edited_by_hand_fails_its_check(committed, tmp_path: Path) -> None:
    edited = copy.deepcopy(committed)
    case = next(iter(edited["workflows"]["w2"]["cases"]))
    edited["workflows"]["w2"]["cases"][case]["deterministic.facts"] = False
    path = tmp_path / "baseline.json"
    measure.write_json(path, edited)
    problems = baseline_file.check(path)
    assert problems and f"/workflows/w2/cases/{case}/deterministic.facts" in problems[0]


# --- a run against the baseline ---------------------------------------------------------------------------------------

def test_the_same_measures_and_pins_pass(committed, thresholds, now) -> None:
    report = gate.compare(pinned(committed), as_run(committed), thresholds, now)
    assert report["passed"] and not report["invalid"] and not report["regressions"]
    assert all(r["verdict"] in ("held", "not gated") for e in report["workflows"].values() for r in e["rows"])


def test_one_case_lost_is_within_a_threshold_of_one_and_two_are_a_regression(committed, thresholds, now) -> None:
    run = as_run(committed)
    first, second = passing("w2", "deterministic.facts", run)[:2]
    set_case(run, "w2", first, "deterministic.facts", False)
    report = gate.compare(pinned(committed), run, thresholds, now)
    assert report["passed"] and rows(report, "w2")["deterministic.facts"]["lost"] == [first]
    set_case(run, "w2", second, "deterministic.facts", False)
    report = gate.compare(pinned(committed), run, thresholds, now)
    assert not report["passed"] and report["regressions"] == [("w2", "deterministic.facts")]
    assert "regressed: w2 deterministic.facts" in gate.render(report, "baseline.json", "run.json")


def test_a_control_that_held_may_not_fail_on_one_case(committed, thresholds, now) -> None:
    run = as_run(committed)
    case = passing("w2", "deterministic.masked", run)[0]
    set_case(run, "w2", case, "deterministic.masked", False)
    report = gate.compare(pinned(committed), run, thresholds, now)
    assert report["regressions"] == [("w2", "deterministic.masked")]


def test_a_case_that_passes_now_offsets_no_case_that_fails(committed, thresholds, now) -> None:
    """W2's refusal check holds the leak control: in the baseline w2-14 fails it on its wording; a run in which
    w2-14 passes and another refusal fails has the same count and still regresses."""
    run = as_run(committed)
    cases = run["workflows"]["w2"]["cases"]
    assert cases["w2-14"]["deterministic.refusal"] is False
    other = passing("w2", "deterministic.refusal", run)[0]
    set_case(run, "w2", "w2-14", "deterministic.refusal", True)
    set_case(run, "w2", other, "deterministic.refusal", False)
    report = gate.compare(pinned(committed), run, thresholds, now)
    row = rows(report, "w2")["deterministic.refusal"]
    assert row["run"]["passed"] == row["baseline"]["passed"]
    assert (row["lost"], row["gained"], row["verdict"]) == ([other], ["w2-14"], "regressed")


def test_a_case_the_run_no_longer_decides_or_lacks_counts_as_lost(committed, thresholds, now) -> None:
    run = as_run(committed)
    case = passing("w4", "trajectory.order", run)[0]
    set_case(run, "w4", case, "trajectory.order", None)
    gone = next(iter(run["workflows"]["w5"]["cases"]))
    del run["workflows"]["w5"]["cases"][gone]
    run["workflows"]["w5"]["tally"] = measure.tally("w5", run["workflows"]["w5"]["cases"])
    report = gate.compare(pinned(committed), run, thresholds, now)
    assert rows(report, "w4")["trajectory.order"]["lost"] == [case]
    assert all(gone in r["lost"] for r in report["workflows"]["w5"]["rows"] if r["baseline"]["passed"] == 3)
    assert ("w4", "trajectory.order") in report["regressions"] and ("w5", "deterministic.findings") in report["regressions"]


def test_the_judge_is_reported_and_not_gated(committed, thresholds, now) -> None:
    run = as_run(committed)
    run["workflows"]["w2"]["judge"] = run["workflows"]["w2"]["judge"] | {"right": 0, "wrong": 99}
    report = gate.compare(pinned(committed), run, thresholds, now)
    assert report["passed"] and report["workflows"]["w2"]["judge"]["run"]["wrong"] == 99


@pytest.mark.parametrize("change, scope, says", [
    (lambda r: r["pins"]["workflows"]["w2"]["models"]["ollama_chat/gpt-oss:20b"].update(digest="b" * 64),
     "w2", "ollama_chat/gpt-oss:20b: the digest changed: aaaaaaaaaaaa -> bbbbbbbbbbbb"),
    (lambda r: r["pins"]["workflows"]["w3"]["models"]["ollama_chat/gpt-oss:20b"].update(server="0.40.13"),
     "w3", "ollama_chat/gpt-oss:20b: Ollama 0.40.13 serves it, where the baseline's was None"),
    (lambda r: r["pins"]["workflows"]["w1"]["aliases"].update({"larkspur-chat": "ollama_chat/gemma4:12b"}),
     "w1", "the alias map changed: larkspur-chat ollama_chat/gpt-oss:20b -> ollama_chat/gemma4:12b"),
    (lambda r: r["pins"]["judge"].update(digest="c" * 64), gate.ALL, "the judge's digest changed"),
])
def test_a_changed_digest_server_or_alias_map_invalidates_the_baseline(committed, thresholds, now, change, scope, says) -> None:
    run = as_run(committed)
    change(run)
    report = gate.compare(pinned(committed), run, thresholds, now)
    assert not report["passed"] and scope in report["invalid"]
    assert any(p.startswith(says) for p in report["pins"][scope]), report["pins"][scope]
    assert "is invalid for" in gate.render(report, "baseline.json", "run.json")


def test_a_baseline_that_holds_no_digest_is_invalid_until_a_run_is_accepted(committed, thresholds, now) -> None:
    """The committed baseline, built from runs that recorded no digest, holds none: the first live run finds it
    unpinned for every set."""
    report = gate.compare(committed, as_run(committed), thresholds, now)
    assert report["invalid"] == sorted(measure.WORKFLOWS)
    assert "ollama_chat/gpt-oss:20b: the baseline holds no digest for it" in report["pins"]["w2"]


def test_a_partial_or_stale_run_is_not_gated(committed, thresholds, now) -> None:
    run = as_run(committed)
    run["run"] |= {"complete": False, "why_partial": "workflows w4, the first 2 cases"}
    run["pins"]["workflows"]["w4"]["set"]["version"] = "0" * 64
    run["pins"]["workflows"]["w4"]["rubric"] = "1" * 64
    report = gate.compare(pinned(committed), run, thresholds, now)
    assert not report["passed"]
    assert any(p.startswith("the run is partial (workflows w4, the first 2 cases)") for p in report["problems"])
    assert any(p.startswith("stale: w4: the set is version") for p in report["problems"])
    assert any(p.startswith("stale: w4: the rubric is") for p in report["problems"])
    assert any(p.startswith("the set changed") for p in report["pins"]["w4"])


# --- the command --------------------------------------------------------------------------------------------------

def test_with_no_live_run_committed_the_gate_checks_the_baseline_and_passes(tmp_path: Path, capsys) -> None:
    assert gate.main(["--live", str(tmp_path / "live")]) == 0
    out = capsys.readouterr().out
    assert "No live run is committed in live/" in out and "|w3 |2026-11-02 |24 |" in out


def test_the_gate_reads_the_last_live_run_and_fails_on_a_regression(committed, tmp_path: Path, capsys) -> None:
    live = tmp_path / "live"
    accepted = tmp_path / "baseline.json"
    measure.write_json(accepted, committed)  # the committed baseline, whose check rebuilds it from the kept results
    good = as_run(committed)
    bad = as_run(committed)
    for case in passing("w4", "deterministic.class", bad)[:1]:
        set_case(bad, "w4", case, "deterministic.class", False)
    measure.write_json(live / "2026-11-04T000000Z-gpt-oss-20b.json", good)
    measure.write_json(live / "2026-11-05T000000Z-gpt-oss-20b.json", bad)
    assert gate.latest_live(live).name.startswith("2026-11-05")
    assert gate.main(["--live", str(live), "--baseline", str(accepted)]) == 1
    out = capsys.readouterr().out
    assert "2026-11-05T000000Z-gpt-oss-20b.json against baseline.json" in out
    assert "|w4 |deterministic.class |0 |8 of 8 |7 of 8 |" in out and "regressed: w4 deterministic.class" in out
    assert json.loads(json.dumps(committed)) == registry.read_json(accepted)  # the gate writes nothing
