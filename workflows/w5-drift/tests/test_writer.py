"""W5's writer (step 4): the two Apps' permissions enforced by the fake, the ruleset and who counts, one pull
request per key updated in place, the thirty-day rule, the suppressed finding raised nowhere, the calls the
writer never makes and the fake would refuse, the ledger's rows, the realized saving after a merge and a
clean next night, and the night's cost row."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest

# conftest.py puts servers/, detect/, writer/, and harness/ on the path.
import cloud_fake
import fixture_night
import github_fake as gh
import ledger as ledger_mod
import night as night_mod
import prose
import pull_requests as writer
from common import NIGHT
from conftest import W5
from github_fake import BOT_USER, FORK, FORK_APP, UPSTREAM, UPSTREAM_APP, GitHubError, GitHubFake

IDS = cloud_fake.IDS
ARCHIVE_KEY = "sandbox-quill:aws_ebs_volume.archive:unattached_volume"
IDLE_KEY = "sandbox-quill:aws_instance.batch:idle"
NOTEBOOK_KEY = "sandbox-quill:aws_instance.notebook:untagged"  # partly excused: raised for data_classification
ROOT_VOLUME_KEY = f"sandbox-quill:{IDS['notebook_root_volume']}:untagged"  # fully excused: suppressed
ORPHAN_KEY = f"sandbox-quill:{IDS['orphan_volume']}:unmanaged"
JENKINS_KEY = "claims-api-prod:aws_security_group.billing_worker:changed"
ROUTE_KEY = f"network-live:{IDS['rtb_private_a']}_10.251.0.0/24:unmanaged"
FILE = "live/sandbox-quill/w5-drift.tf"


@pytest.fixture
def fake() -> GitHubFake:
    f = GitHubFake(NIGHT)
    gh.seed_platform_infra(f)
    return f


@pytest.fixture(scope="module")
def sandbox():
    return fixture_night.findings_for("sandbox-quill")


def tokens(fake: GitHubFake) -> tuple[str, str]:
    return fake.installation_token(FORK_APP), fake.installation_token(UPSTREAM_APP)


def people(fake: GitHubFake) -> tuple[str, str, str, str, str]:
    """Two of the platform team (a code owner and a platform engineer who merges), Priya, a network engineer with
    write access and no code ownership, and FinOps with read access."""
    return tuple(fake.user_token(u) for u in ("priya.raman", "tomasz.nowak", "felix.morin", "rosa.delgado", "ingrid.holm"))


def refused(call, *args, status: int = 403, **kwargs) -> GitHubError:
    with pytest.raises(GitHubError) as info:
        call(*args, **kwargs)
    assert info.value.status == status, (info.value.status, info.value.message)
    return info.value


def stub_prose(finding) -> writer.Prose:
    return prose.write(finding, trace_id="trace-test", base="")  # no model configured: the stub


def write(fake: GitHubFake, findings, night=NIGHT, trace_id: str = "trace-test") -> list[writer.WriteResult]:
    fake.now = night
    fork, upstream = tokens(fake)
    return writer.write_findings(findings, fake, night=night, trace_id=trace_id, prose_for=stub_prose,
                                 fork_token=fork, upstream_token=upstream)


def agent_pull(fake: GitHubFake, content: str = "# v1\n") -> int:
    """The agent's own pull request, as the writer makes one: the fork App pushes, the upstream App opens."""
    fork, upstream = tokens(fake)
    main = fake.get_ref(fork, FORK, "heads/main")["object"]["sha"]
    fake.create_ref(fork, FORK, "refs/heads/w5/t", main)
    fake.create_or_update_file(fork, FORK, FILE, "m", content, "w5/t")
    return fake.create_pull(upstream, UPSTREAM, "t", "b", head=f"{BOT_USER}:w5/t")["number"]


def repo_of(path: str) -> str:
    return "/".join(path.split("/")[2:4])


# --- the two Apps, as the permissions reference maps each endpoint (A.1) ------------------------------------------

def test_the_fork_app_holds_contents_write_on_the_fork_and_nothing_upstream(fake):
    fork, upstream = tokens(fake)
    main = fake.get_ref(fork, FORK, "heads/main")["object"]["sha"]
    assert fake.create_ref(fork, FORK, "refs/heads/w5/t", main)["ref"] == "refs/heads/w5/t"
    put = fake.create_or_update_file(fork, FORK, FILE, "m", "# x\n", "w5/t")
    assert put["commit"]["author"]["name"] == f"{FORK_APP}[bot]" and put["content"]["path"] == FILE
    number = fake.create_pull(upstream, UPSTREAM, "t", "b", head=f"{BOT_USER}:w5/t")["number"]
    for call, args in ((fake.create_ref, (UPSTREAM, "refs/heads/w5/u", main)),
                       (fake.create_or_update_file, (UPSTREAM, "live/x.tf", "m", "x", "main")),
                       (fake.create_pull, (UPSTREAM, "t", "b", f"{BOT_USER}:w5/t")),
                       (fake.update_pull, (UPSTREAM, number)), (fake.list_pulls, (UPSTREAM,)),
                       (fake.get_repository, (UPSTREAM,)), (fake.merge_pull, (UPSTREAM, number)),
                       (fake.create_review, (UPSTREAM, number, "APPROVE"))):
        err = refused(call, fork, *args)
        assert gh.NOT_ACCESSIBLE in err.message and "does not include" in err.message, call.__name__
    # A workflow file on its own fork needs "Workflows" write too, which it does not hold.
    err = refused(fake.create_or_update_file, fork, FORK, ".github/workflows/w5.yml", "m", "x", "w5/t")
    assert "workflows: write" in err.message
    assert [e for e in fake.log if e["actor"] == f"{FORK_APP}[bot]" and e["status"] == 403]  # every refusal logged


def test_the_upstream_app_opens_and_updates_a_pull_request_and_can_do_nothing_else(fake):
    fork, upstream = tokens(fake)
    main = fake.get_ref(fork, FORK, "heads/main")["object"]["sha"]
    fake.create_ref(fork, FORK, "refs/heads/w5/t", main)
    fake.create_or_update_file(fork, FORK, FILE, "m", "# x\n", "w5/t")
    assert fake.get_repository(upstream, UPSTREAM)["default_branch"] == "main"  # Metadata read
    pr = fake.create_pull(upstream, UPSTREAM, "t", "b", head=f"{BOT_USER}:w5/t")
    assert pr["user"] == {"login": f"{UPSTREAM_APP}[bot]", "type": "Bot"} and pr["state"] == "open"
    assert pr["head"]["label"] == f"{BOT_USER}:w5/t" and pr["head"]["repo"]["full_name"] == FORK and pr["base"]["ref"] == "main"
    assert fake.update_pull(upstream, UPSTREAM, pr["number"], title="t2", body="b2")["title"] == "t2"
    assert [p["number"] for p in fake.list_pulls(upstream, UPSTREAM, head=f"{BOT_USER}:w5/t")] == [pr["number"]]
    assert fake.get_pull(upstream, UPSTREAM, pr["number"])["body"] == "b2"
    files = fake.list_pull_files(upstream, UPSTREAM, pr["number"])
    assert [(f["filename"], f["status"], f["additions"]) for f in files] == [(FILE, "added", 1)]
    refused(fake.create_pull, upstream, UPSTREAM, "t", "b", head=f"{BOT_USER}:w5/t", status=422)  # one per head, GitHub's own rule
    for call, args in ((fake.create_ref, (UPSTREAM, "refs/heads/w5/u", main)), (fake.create_ref, (FORK, "refs/heads/w5/u", main)),
                       (fake.create_or_update_file, (UPSTREAM, "live/x.tf", "m", "x", "main")),
                       (fake.create_or_update_file, (UPSTREAM, ".github/workflows/apply.yml", "m", "x", "main")),
                       (fake.create_or_update_file, (FORK, "live/x.tf", "m", "x", "w5/t")),
                       (fake.merge_pull, (UPSTREAM, pr["number"])), (fake.get_ref, (UPSTREAM, "heads/main")),
                       (fake.update_ref, (UPSTREAM, "heads/main", main))):
        err = refused(call, upstream, *args)
        assert gh.NOT_ACCESSIBLE in err.message, call.__name__
    # Its approving review of its own pull request: GitHub's own refusal (A.3).
    err = refused(fake.create_review, upstream, UPSTREAM, pr["number"], "APPROVE", status=422)
    assert err.message == gh.OWN_APPROVAL


# --- the ruleset: a code owner's approval, and who counts (A.3, A.4) ----------------------------------------------

def test_the_ruleset_needs_a_code_owner_and_an_apps_or_an_authors_or_a_readers_review_never_counts(fake):
    fork, upstream = tokens(fake)
    priya, tomasz, felix, rosa, ingrid = people(fake)
    main = fake.get_ref(priya, FORK, "heads/main")["object"]["sha"]
    fake.create_ref(priya, FORK, "refs/heads/feature/tags", main)
    sha = fake.get_content(priya, FORK, "live/network-live/main.tf", ref="feature/tags")["sha"]  # an existing file: its blob sha
    fake.create_or_update_file(priya, FORK, "live/network-live/main.tf", "tags", "# edited by a person\n", "feature/tags", sha=sha)
    number = fake.create_pull(priya, UPSTREAM, "Tags", "by a person", head=f"{BOT_USER}:feature/tags")["number"]
    err = refused(fake.merge_pull, tomasz, UPSTREAM, number, status=405)  # tomasz holds Contents write: the ruleset refuses
    assert "approving review" in err.message
    review = fake.create_review(upstream, UPSTREAM, number, "APPROVE", "looks fine")  # the App's: recorded, counts for nothing
    assert review["state"] == "APPROVED" and review["counts_toward_requirements"] is False and "App" in review["does_not_count_because"]
    refused(fake.merge_pull, tomasz, UPSTREAM, number, status=405)
    assert refused(fake.create_review, priya, UPSTREAM, number, "APPROVE", status=422).message == gh.OWN_APPROVAL
    assert fake.create_review(ingrid, UPSTREAM, number, "APPROVE")["does_not_count_because"] == "no write access to the repository"
    # The network team holds write access to the repository and owns no path in CODEOWNERS.
    assert fake.create_review(rosa, UPSTREAM, number, "APPROVE")["counts_toward_requirements"] is True  # write access, not an owner
    err = refused(fake.merge_pull, tomasz, UPSTREAM, number, status=405)
    assert "code owners" in err.message and "platform-team" in err.message
    assert fake.create_review(tomasz, UPSTREAM, number, "APPROVE")["counts_toward_requirements"] is True  # a code owner
    assert fake.merge_blockers(number) == ['Required status check "validate" is expected.']  # no check has run on the head
    gh.report_check(fake, number)
    assert fake.merge_blockers(number) == []
    merged = fake.merge_pull(felix, UPSTREAM, number)
    assert merged["merged"] is True and fake.get_pull(upstream, UPSTREAM, number)["merged"] is True
    assert fake.get_ref(tomasz, UPSTREAM, "heads/main")["object"]["sha"] == merged["sha"]
    # The upstream App reads the ruleset and its own bypass, and not the bypass list, which only a caller with
    # write access to the ruleset sees (A.13.3); the fake's own record has no bypass actor.
    ruleset = fake.get_ruleset(upstream, UPSTREAM, gh.RULESET["id"])
    assert "bypass_actors" not in ruleset and ruleset["current_user_can_bypass"] == "never" and ruleset["enforcement"] == "active"
    assert fake.rulesets[0]["bypass_actors"] == []
    assert {r["type"] for r in ruleset["rules"]} == {"creation", "non_fast_forward", "pull_request", "required_status_checks"}
    rule = next(r["parameters"] for r in ruleset["rules"] if r["type"] == "pull_request")
    assert rule["required_approving_review_count"] == 1 and rule["require_code_owner_review"] is True
    assert rule["dismiss_stale_reviews_on_push"] is True and rule["require_last_push_approval"] is True
    checks = next(r["parameters"] for r in ruleset["rules"] if r["type"] == "required_status_checks")
    assert checks["required_status_checks"] == [{"context": "validate", "integration_id": gh.GITHUB_ACTIONS_ID}]
    # With Administration write an App would see the bypass list too, and could change it (A.6.1).
    fake.apps[UPSTREAM_APP]["permissions"]["administration"] = "write"
    assert fake.get_ruleset(upstream, UPSTREAM, gh.RULESET["id"])["bypass_actors"] == []


def test_the_merge_waits_for_github_actions_validate_check_on_the_head_commit(fake):
    """Require status checks to pass, with the validate job pinned to GitHub Actions (A.12.3): the merge waits for
    its success on the pull request's head commit, a check of the same name from any other source counts for
    nothing, and a new push needs the check again."""
    fork, upstream = tokens(fake)
    _, tomasz, felix, _, _ = people(fake)
    number = agent_pull(fake)
    fake.create_review(tomasz, UPSTREAM, number, "APPROVE")
    expected = ['Required status check "validate" is expected.']
    assert fake.merge_blockers(number) == expected
    assert "validate" in refused(fake.merge_pull, felix, UPSTREAM, number, status=405).message
    gh.report_check(fake, number, conclusion="failure")
    assert fake.merge_blockers(number) == expected
    head = fake.pulls[number]["head"]["sha"]
    # Neither W5 App can report a check (no Checks write), and a person cannot create a check run at all.
    for token in (upstream, fork, tomasz):
        refused(fake.create_check_run, token, UPSTREAM, "validate", head)
    # An App given Checks write by mistake reports a validate of its own: the pinned rule does not count it.
    fake.apps[UPSTREAM_APP]["permissions"]["checks"] = "write"
    assert fake.create_check_run(upstream, UPSTREAM, "validate", head)["app"]["id"] == gh.APPS[UPSTREAM_APP]["id"]
    assert fake.merge_blockers(number) == expected
    del fake.apps[UPSTREAM_APP]["permissions"]["checks"]
    run = gh.report_check(fake, number)  # GitHub Actions: the job's success on the head commit
    assert run["app"] == {"id": gh.GITHUB_ACTIONS_ID, "slug": gh.GITHUB_ACTIONS_APP} and fake.merge_blockers(number) == []
    # The agent pushes again: the check ran on the old head, and the approval is stale.
    sha = fake.get_content(fork, FORK, FILE, ref="w5/t")["sha"]
    fake.create_or_update_file(fork, FORK, FILE, "m", "# v2\n", "w5/t", sha=sha)
    blockers = fake.merge_blockers(number)
    assert expected[0] in blockers and any("approving review" in b for b in blockers)
    gh.report_check(fake, number)
    fake.create_review(tomasz, UPSTREAM, number, "APPROVE")
    assert fake.merge_pull(felix, UPSTREAM, number)["merged"] is True


def test_a_new_push_dismisses_an_approval_and_the_last_pusher_cannot_be_the_approver(fake):
    fork, upstream = tokens(fake)
    priya, tomasz, _, _, _ = people(fake)
    number = agent_pull(fake)
    fake.create_review(tomasz, UPSTREAM, number, "APPROVE")
    gh.report_check(fake, number)
    assert fake.merge_blockers(number) == []
    sha = fake.get_content(fork, FORK, FILE, ref="w5/t")["sha"]
    fake.create_or_update_file(fork, FORK, FILE, "m", "# v2\n", "w5/t", sha=sha)  # the fork App pushes again
    reviews = fake.list_reviews(upstream, UPSTREAM, number)
    assert reviews[0]["state"] == "DISMISSED" and "stale" in reviews[0]["dismissal_reason"]
    assert "approving review" in refused(fake.merge_pull, tomasz, UPSTREAM, number, status=405).message
    # A person pushes to the agent's branch (the fork inherits the team's write) and approves: the most
    # recent push must be approved by someone else.
    sha = fake.get_content(priya, FORK, FILE, ref="w5/t")["sha"]
    fake.create_or_update_file(priya, FORK, FILE, "m", "# v3\n", "w5/t", sha=sha)
    gh.report_check(fake, number)
    fake.create_review(priya, UPSTREAM, number, "APPROVE")
    assert "most recent push" in refused(fake.merge_pull, tomasz, UPSTREAM, number, status=405).message
    fake.create_review(tomasz, UPSTREAM, number, "APPROVE")
    assert fake.merge_pull(tomasz, UPSTREAM, number)["merged"] is True


def test_main_takes_no_direct_push_and_no_force_push(fake):
    """No "Restrict updates" rule: "Require a pull request before merging" keeps every direct push out (A.12)."""
    _, tomasz, _, _, _ = people(fake)
    assert "update" not in {rule["type"] for rule in fake.rulesets[0]["rules"]}
    main = fake.get_ref(tomasz, UPSTREAM, "heads/main")["object"]["sha"]
    assert "through a pull request" in refused(fake.create_or_update_file, tomasz, UPSTREAM, "live/x.tf", "m", "x", "main").message
    fake.create_ref(tomasz, UPSTREAM, "refs/heads/hotfix", main)
    sha = fake.create_or_update_file(tomasz, UPSTREAM, "live/x.tf", "m", "x", "hotfix")["commit"]["sha"]
    assert "through a pull request" in refused(fake.update_ref, tomasz, UPSTREAM, "heads/main", sha).message
    assert "force-push" in refused(fake.update_ref, tomasz, UPSTREAM, "heads/main", sha, force=True, status=422).message
    assert fake.get_ref(tomasz, UPSTREAM, "heads/main")["object"]["sha"] == main


# --- the writer's rules: one per key, in place, thirty days, suppression (W5-D9) ------------------------------------

def test_branch_names_are_git_safe_and_distinct():
    assert writer.branch_name("network-live:rtb-0a1b_10.251.0.0/24:unmanaged") == "w5/network-live-rtb-0a1b_10.251.0.0-24-unmanaged"
    assert writer.branch_name("a:..b:c.") == "w5/a--b-c" and writer.branch_name("::") == "w5/finding"
    keys = [f.key for w in fixture_night.PAIRS for f in fixture_night.findings_for(w)]
    names = [writer.branch_name(k) for k in keys]
    assert len(set(names)) == len(keys) == 15 and all(n.startswith("w5/") and ".." not in n and " " not in n for n in names)


def test_the_writer_opens_one_pull_request_per_key_and_updates_it_in_place(fake, sandbox):
    _, upstream = tokens(fake)
    first = write(fake, sandbox)
    assert [r.action for r in first].count("opened") == 10 and [r.action for r in first].count("suppressed") == 1
    numbers = {r.key: r.number for r in first if r.number}
    assert len(set(numbers.values())) == 10 and all(r.pushed for r in first if r.action == "opened")
    assert set(fake.repos[UPSTREAM]["refs"]) == {"refs/heads/main"}
    assert {ref.removeprefix("refs/heads/") for ref in fake.repos[FORK]["refs"]} - {"main"} == {writer.branch_name(k) for k in numbers}
    pulls = fake.list_pulls(upstream, UPSTREAM)
    assert len(pulls) == 10 and {p["user"]["login"] for p in pulls} == {f"{UPSTREAM_APP}[bot]"}
    assert all(p["base"]["ref"] == "main" and p["head"]["label"].startswith(f"{BOT_USER}:w5/") for p in pulls)
    archive = next(p for p in pulls if p["head"]["ref"] == writer.branch_name(ARCHIVE_KEY))
    body = archive["body"]
    for text in (ARCHIVE_KEY, "`unattached_volume`", IDS["archive_volume"], "aws_ebs_volume.archive", "96 LCU", "synthetic unit",
                 "larkspur-w5-drift", f"{UPSTREAM_APP}[bot]", "trace `trace-test`", writer.SENTENCE, writer.MARKER.format(key=ARCHIVE_KEY),
                 "```diff", '-resource "aws_ebs_volume" "archive"', "## Facts", "```json"):
        assert text in body, text
    assert archive["title"] == "W5 unattached volume: aws_ebs_volume aws_ebs_volume.archive in sandbox-quill"
    files = fake.list_pull_files(upstream, UPSTREAM, archive["number"])
    assert [f["filename"] for f in files] == ["live/sandbox-quill/main.tf"] and files[0]["deletions"] > 0 and files[0]["status"] == "modified"
    orphan = next(p for p in pulls if p["head"]["ref"] == writer.branch_name(ORPHAN_KEY))
    assert "import {" in orphan["body"] and [f["filename"] for f in fake.list_pull_files(upstream, UPSTREAM, orphan["number"])] == [FILE]
    assert "quill-svc-notebooks" in orphan["body"] and "CreateVolume" in orphan["body"]  # the attribution
    # The next night: the same numbers, updated in place, no new branch, no new pull request.
    before = len(fake.log)
    second = write(fake, sandbox, NIGHT + timedelta(days=1), "trace-second")
    assert [r.action for r in second].count("updated") == 10 and {r.key: r.number for r in second if r.number} == numbers
    assert len(fake.list_pulls(upstream, UPSTREAM, state="all")) == 10 and len(fake.repos[FORK]["refs"]) == 11
    new = fake.log[before:]
    assert not [e for e in new if e["method"] == "POST"]  # no branch created, no pull request opened
    assert "trace `trace-second`" in fake.get_pull(upstream, UPSTREAM, archive["number"])["body"]
    assert not next(r for r in second if r.key == ARCHIVE_KEY).pushed  # the same file content: no push, no dismissed approval
    # The same night again: nothing to push, nothing to patch.
    before = len(fake.log)
    third = write(fake, sandbox, NIGHT + timedelta(days=1), "trace-second")
    assert all(not r.pushed for r in third if r.action == "updated") and not [e for e in fake.log[before:] if e["method"] in ("PUT", "PATCH", "POST")]


def test_a_closed_pull_request_is_not_raised_again_for_thirty_days_and_a_merged_one_waits_too(fake, sandbox):
    _, upstream = tokens(fake)
    _, tomasz, felix, _, _ = people(fake)
    first = write(fake, sandbox)
    archive_number = next(r.number for r in first if r.key == ARCHIVE_KEY)
    idle_number = next(r.number for r in first if r.key == IDLE_KEY)
    fake.now = NIGHT + timedelta(days=2)
    fake.update_pull(tomasz, UPSTREAM, archive_number, state="closed")  # a person closes it without a merge
    gh.report_check(fake, idle_number)
    fake.create_review(tomasz, UPSTREAM, idle_number, "APPROVE")
    fake.merge_pull(felix, UPSTREAM, idle_number)  # and merges the other
    later = write(fake, sandbox, NIGHT + timedelta(days=12))
    skipped = next(r for r in later if r.key == ARCHIVE_KEY)
    assert skipped.action == "skipped" and skipped.number == archive_number
    assert "closed without a merge on 2026-11-04" in skipped.reason and "2026-12-04" in skipped.reason
    merged = next(r for r in later if r.key == IDLE_KEY)
    assert merged.action == "skipped" and "merged on 2026-11-04" in merged.reason and "apply follows" in merged.reason
    head = f"{BOT_USER}:{writer.branch_name(ARCHIVE_KEY)}"
    assert len(fake.list_pulls(upstream, UPSTREAM, state="all", head=head)) == 1
    assert [r.action for r in later].count("updated") == 8
    reopened = write(fake, sandbox, NIGHT + timedelta(days=33))
    again = next(r for r in reopened if r.key == ARCHIVE_KEY)
    assert again.action == "opened" and again.number != archive_number
    assert [p["state"] for p in fake.list_pulls(upstream, UPSTREAM, state="all", head=head)] == ["open", "closed"]
    assert next(r for r in reopened if r.key == IDLE_KEY).action == "opened"  # the waste is still there after thirty days


def test_a_security_group_or_a_route_finding_has_no_quiet_period(fake):
    """A closed pull request quiets a tag for thirty days; a rule open to the world on the billing worker's group and
    the hand-added production route are raised again the next night, whatever happened to their last pull request."""
    _, upstream = tokens(fake)
    _, tomasz, felix, _, _ = people(fake)
    found = [f for w in fixture_night.PAIRS for f in fixture_night.findings_for(w)]
    types = {f.key: f.resource_type for f in found}
    assert (types[ROUTE_KEY], types[JENKINS_KEY], types[NOTEBOOK_KEY]) == ("aws_route", "aws_security_group", "aws_instance")
    first = {r.key: r for r in write(fake, found)}
    fake.now = NIGHT + timedelta(days=1)
    for key in (ROUTE_KEY, JENKINS_KEY, NOTEBOOK_KEY):  # a reviewer closes all three without a merge
        fake.update_pull(tomasz, UPSTREAM, first[key].number, state="closed")
    second = {r.key: r for r in write(fake, found, NIGHT + timedelta(days=2), "trace-second")}
    for key in (ROUTE_KEY, JENKINS_KEY):
        assert second[key].action == "opened" and second[key].number != first[key].number, key
        head = f"{BOT_USER}:{writer.branch_name(key)}"
        assert [p["state"] for p in fake.list_pulls(upstream, UPSTREAM, state="all", head=head)] == ["open", "closed"], key
    assert second[NOTEBOOK_KEY].action == "skipped" and "closed without a merge on 2026-11-03" in second[NOTEBOOK_KEY].reason
    assert [r.action for r in second.values()].count("updated") == 11  # the rest in place
    # Merged, and the rule still live the next night: raised again, where any other finding's merge waits thirty days.
    number = second[JENKINS_KEY].number
    gh.report_check(fake, number)
    fake.create_review(tomasz, UPSTREAM, number, "APPROVE")
    fake.merge_pull(felix, UPSTREAM, number)
    merged = fake.get_pull(upstream, UPSTREAM, number)
    jenkins = next(f for f in found if f.key == JENKINS_KEY)
    assert writer.quiet_until(merged, NIGHT + timedelta(days=3), jenkins) is None
    assert writer.quiet_until(merged, NIGHT + timedelta(days=3), replace(jenkins, resource_type="aws_ebs_volume")) is not None
    third = {r.key: r for r in write(fake, found, NIGHT + timedelta(days=3), "trace-third")}
    assert third[JENKINS_KEY].action == "opened" and third[JENKINS_KEY].number not in (first[JENKINS_KEY].number, number)
    assert set(writer.NO_QUIET_TYPES) == {"aws_security_group", "aws_route_table", "aws_route"}


def test_an_approved_pull_requests_title_and_body_stay_as_the_approver_read_them(fake, sandbox):
    """Editing a body dismisses no approval, so the writer lists the reviews before it updates the prose and leaves
    an approved pull request's title and body alone, asking no model for them. A diff that changes is still pushed,
    and the ruleset's stale-approval rule dismisses the approval: then the prose follows the new diff."""
    _, tomasz, _, _, ingrid = people(fake)
    first = {r.key: r for r in write(fake, sandbox)}
    _, upstream = tokens(fake)
    number = first[ARCHIVE_KEY].number
    approved = fake.get_pull(upstream, UPSTREAM, number)
    fake.create_review(tomasz, UPSTREAM, number, "APPROVE")
    asked: list[str] = []

    def prose_for(finding):
        asked.append(finding.key)
        return stub_prose(finding)

    def night(findings, days, trace):
        fake.now = NIGHT + timedelta(days=days)
        fork, upstream_token = tokens(fake)
        return {r.key: r for r in writer.write_findings(findings, fake, night=NIGHT + timedelta(days=days), trace_id=trace,
                                                        prose_for=prose_for, fork_token=fork, upstream_token=upstream_token)}

    before = len(fake.log)
    second = night(sandbox, 1, "trace-second")
    kept = second[ARCHIVE_KEY]
    assert kept.action == "skipped" and kept.number == number and not kept.pushed
    assert kept.reason == f"#{number} approved by tomasz.nowak; its title and body stay as the approver read them"
    current = fake.get_pull(upstream, UPSTREAM, number)
    assert (current["title"], current["body"]) == (approved["title"], approved["body"]) and "trace `trace-test`" in current["body"]
    assert ARCHIVE_KEY not in asked and len(asked) == 9  # no prose asked for the approved one; the nine others updated
    assert not [e for e in fake.log[before:] if e["method"] == "PATCH" and e["path"].endswith(f"/pulls/{number}")]
    assert [e for e in fake.log[before:] if e["method"] == "GET" and e["path"].endswith(f"/pulls/{number}/reviews")]
    assert [r.action for r in second.values()].count("updated") == 9
    assert "trace `trace-second`" in fake.get_pull(upstream, UPSTREAM, second[IDLE_KEY].number)["body"]
    # Any standing approval keeps the prose, one that counts toward the ruleset or not: FinOps reads with read access.
    fake.create_review(ingrid, UPSTREAM, second[IDLE_KEY].number, "APPROVE")
    assert night(sandbox, 2, "trace-third")[IDLE_KEY].action == "skipped"
    # The notebook's exception lapses and its diff changes: the push dismisses the approval as stale, and the prose follows.
    notebook = first[NOTEBOOK_KEY].number
    fake.create_review(tomasz, UPSTREAM, notebook, "APPROVE")
    lapsed = [replace(f, evidence={**f.evidence, "missing": ["cost_center", "data_classification"], "excused": {}})
              if f.key == NOTEBOOK_KEY else f for f in sandbox]
    third = night(lapsed, 3, "trace-fourth")
    assert third[NOTEBOOK_KEY].action == "updated" and third[NOTEBOOK_KEY].pushed
    assert fake.list_reviews(upstream, UPSTREAM, notebook)[-1]["state"] == "DISMISSED"
    body = fake.get_pull(upstream, UPSTREAM, notebook)["body"]
    assert "trace `trace-fourth`" in body and '+    cost_center         = "TODO: set by quill-data"' in body


def test_the_suppressed_finding_is_raised_nowhere_and_a_partly_excused_one_names_its_exception(fake, sandbox, tmp_path):
    _, upstream = tokens(fake)
    results = write(fake, sandbox)
    volume = next(r for r in results if r.key == ROOT_VOLUME_KEY)  # both tags excused: nothing remains
    assert volume.action == "suppressed" and volume.number is None and "RITM0045233" in volume.reason
    assert writer.branch_name(ROOT_VOLUME_KEY) not in {ref.removeprefix("refs/heads/") for ref in fake.repos[FORK]["refs"]}
    assert not fake.list_pulls(upstream, UPSTREAM, state="all", head=f"{BOT_USER}:{writer.branch_name(ROOT_VOLUME_KEY)}")
    assert ROOT_VOLUME_KEY not in json.dumps(fake.pulls) and ROOT_VOLUME_KEY not in json.dumps(fake.commits)
    notebook = next(r for r in results if r.key == NOTEBOOK_KEY)  # cost_center excused: raised for data_classification
    assert notebook.action == "opened" and notebook.number
    body = fake.get_pull(upstream, UPSTREAM, notebook.number)["body"]
    assert "- Exceptions (ServiceNow): `cost_center` excused by `RITM0045021`; still missing: `data_classification`" in body
    assert 'data_classification = "TODO: set by quill-data"' in body and "cost_center = " not in body.split("## Proposed change")[1]
    led = ledger_mod.Ledger(tmp_path / "ledger.json")
    led.observe(sandbox, NIGHT)
    led.record_writes(results, NIGHT)
    assert led.findings[ROOT_VOLUME_KEY]["suppressed_by"] == "RITM0045233" and led.findings[ROOT_VOLUME_KEY]["pull_request"] is None
    assert led.findings[NOTEBOOK_KEY]["suppressed_by"] is None and led.findings[NOTEBOOK_KEY]["pull_request"]["number"] == notebook.number
    assert sum(1 for r in led.findings.values() if r["pull_request"]) == 10 and sum(1 for r in led.findings.values() if r["suppressed_by"]) == 1


def test_the_writer_calls_no_merge_review_or_workflow_write_and_the_fake_would_refuse_them(fake):
    source = (W5 / "writer" / "pull_requests.py").read_text(encoding="utf-8")
    for name in ("merge_pull", "create_review", "update_ref", ".github/workflows", "WORKFLOWS_DIR"):
        assert name not in source, name
    results = write(fake, fixture_night.findings_for("claims-api-prod"))
    assert [r.action for r in results] == ["opened"] * 3
    for e in fake.log:
        assert not (e["path"].endswith("/merge") or e["path"].endswith("/reviews") or ".github/workflows" in e["path"]), e
        if e["method"] in ("POST", "PUT", "PATCH"):
            assert (repo_of(e["path"]), e["actor"]) in {(FORK, f"{FORK_APP}[bot]"), (UPSTREAM, f"{UPSTREAM_APP}[bot]")}, e
            assert e["status"] in (200, 201), e
    assert {e["actor"] for e in fake.log} == {f"{FORK_APP}[bot]", f"{UPSTREAM_APP}[bot]"}
    fork, upstream = tokens(fake)
    number = next(r.number for r in results if r.key == JENKINS_KEY)
    branch = next(r.branch for r in results if r.key == JENKINS_KEY)
    refused(fake.merge_pull, fork, UPSTREAM, number)
    refused(fake.merge_pull, upstream, UPSTREAM, number)
    refused(fake.create_review, fork, UPSTREAM, number, "APPROVE")
    assert refused(fake.create_review, upstream, UPSTREAM, number, "APPROVE", status=422).message == gh.OWN_APPROVAL
    refused(fake.create_or_update_file, upstream, UPSTREAM, ".github/workflows/apply.yml", "m", "x", "main")
    refused(fake.create_or_update_file, fork, FORK, ".github/workflows/apply.yml", "m", "x", branch)
    assert fake.get_pull(upstream, UPSTREAM, number)["state"] == "open" and not fake.get_pull(upstream, UPSTREAM, number)["merged"]
    body = fake.get_pull(upstream, UPSTREAM, number)["body"]
    assert "jenkins-deploy-prod" in body and "AuthorizeSecurityGroupIngress" in body and "Jenkins/2.479.2" in body


# --- the ledger: the rows, the realized saving, the cost row (W5-D9, W5-D10) ----------------------------------------

def test_the_ledger_rows_the_realized_saving_after_a_merge_and_a_clean_night_and_the_cost_row(fake, sandbox, tmp_path):
    _, upstream = tokens(fake)
    _, tomasz, felix, _, _ = people(fake)
    led = ledger_mod.Ledger(tmp_path / "ledger.json")
    led.observe(sandbox, NIGHT)
    results = write(fake, sandbox)
    led.record_writes(results, NIGHT)
    row = led.findings[ARCHIVE_KEY]
    assert row["first_seen"] == row["last_seen"] == "2026-11-02" and row["kind"] == "unattached_volume"
    assert row["pull_request"]["state"] == "open" and row["pull_request"]["opened"] == "2026-11-02"
    assert row["estimated_monthly_saving"] == 96.0 and row["realized_monthly_saving"] is None and row["realized_on"] is None
    assert set(led.findings) == {f.key for f in sandbox} and len(led.findings) == 11
    # The night's cost row, from a gateway log in chapter 5's shape (W4's gateway.jsonl): this trace's calls only.
    gateway = tmp_path / "gateway.jsonl"
    lines = [{"event": "call", "trace_id": "trace-test", "workflow": "w5-drift", "data_class": "confidential",
              "requested_alias": "larkspur-chat", "prompt_tokens": 150, "completion_tokens": 40, "cost_usd": 0.0, "latency_ms": 900},
             {"event": "call", "trace_id": "trace-test", "prompt_tokens": 120, "completion_tokens": 900},
             {"event": "refused", "trace_id": "trace-test", "reason": "request refused: over budget"},
             {"event": "call", "trace_id": "another-night", "prompt_tokens": 999, "completion_tokens": 999}]
    gateway.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    inputs = fixture_night.gather("sandbox-quill")
    spend = {"lm-sandbox": sum(float(r["line_item_unblended_cost"]) for r in inputs.export["rows"])}
    night_row = led.record_night(NIGHT, trace_id="trace-test", duration_s=1.5, gateway_log=gateway, findings=sandbox, results=results,
                                 spend=spend, workspaces=["sandbox-quill"])
    assert (night_row["gateway_calls"], night_row["prompt_tokens"], night_row["completion_tokens"], night_row["refused"]) == (2, 270, 940, 1)
    assert night_row["duration_s"] == 1.5 and night_row["pull_requests"] == {"opened": 10, "updated": 0, "skipped": 0, "suppressed": 1}
    assert night_row["body_sources"] == {"stub": 10} and night_row["refused_words"] == {}
    led.save()
    led = ledger_mod.Ledger(tmp_path / "ledger.json")  # what the file holds
    assert led.nights["2026-11-02"]["trace_id"] == "trace-test" and led.findings[ARCHIVE_KEY]["pull_request"]["number"]
    # The validate check passes, a code owner approves, and a person merges the archive volume's pull request;
    # the pipeline applies.
    number = led.findings[ARCHIVE_KEY]["pull_request"]["number"]
    fake.now = NIGHT + timedelta(days=3)
    gh.report_check(fake, number)
    fake.create_review(tomasz, UPSTREAM, number, "APPROVE")
    assert fake.merge_pull(felix, UPSTREAM, number)["merged"] is True
    # The next night reads the volume gone (through a parameter, not a second fixture): the saving is realized.
    night2 = NIGHT + timedelta(days=4)
    clean = night_mod.without_resources(fixture_night.gather("sandbox-quill", night2), {IDS["archive_volume"]})
    found = fixture_night.findings_from(clean, night2)
    keys = {f.key for f in found}
    assert ARCHIVE_KEY not in keys and "sandbox-quill:aws_ebs_volume.archive:missing" not in keys
    # The volume's old snapshot is now a snapshot of nothing in Terraform: an unmanaged finding of its own.
    assert keys - {f.key for f in sandbox} == {f"sandbox-quill:{IDS['old_snapshot']}:unmanaged"} and len(found) == 11
    led.observe(found, night2)
    assert led.sync_pull_requests(fake, upstream)[ARCHIVE_KEY] == "merged" and led.findings[ARCHIVE_KEY]["pull_request"]["merged"] == "2026-11-05"
    assert led.realize(keys, night2, ["sandbox-quill"]) == [ARCHIVE_KEY]
    row = led.findings[ARCHIVE_KEY]
    assert row["realized_monthly_saving"] == 96.0 and row["realized_on"] == "2026-11-06" and row["last_seen"] == "2026-11-02"
    assert led.realize(keys, night2, ["sandbox-quill"]) == []  # once
    results2 = write(fake, found, night2, "trace-2")
    led.record_writes(results2, night2)
    led.record_night(night2, trace_id="trace-2", duration_s=0.5, gateway_log=gateway, findings=found, results=results2, spend=spend,
                     workspaces=["sandbox-quill"], realized=[ARCHIVE_KEY])
    summary = led.summary("2026-11")
    proposed = sum(f.estimated_monthly_saving or 0 for f in sandbox if not f.suppressed_by)
    assert [r.action for r in results2].count("opened") == 1 and [r.action for r in results2].count("updated") == 9  # the snapshot's new finding
    assert summary["nights"] == 2 and summary["findings"]["seen"] == 12 and summary["findings"]["suppressed"] == 1
    assert summary["pull_requests"] == {"open": 10, "merged": 1, "closed": 0, "opened": 11, "updated": 9, "skipped": 0}
    assert summary["savings"] == {"proposed_share_of_spend": round(proposed / spend["lm-sandbox"], 4),
                                  "realized_share_of_spend": round(96.0 / spend["lm-sandbox"], 4),
                                  "realized_share_of_proposed": round(96.0 / proposed, 4), "realized_findings": 1}
    assert summary["agent"] == {"gateway_calls": 2, "prompt_tokens": 270, "completion_tokens": 940, "refused": 1, "failed": 0,
                                "seconds": 2.0, "accounts_read": ["lm-sandbox"]}  # trace-2 made no gateway call
    text = json.dumps(summary)
    assert "LCU" not in text and "amount" not in text.lower() and "usd" not in text.lower()  # shares and counts, never a currency
    assert all(0 <= v <= 1 for k, v in summary["savings"].items() if k != "realized_findings")
    assert led.summary("2026-12") == {**led.summary("2026-12"), "nights": 0} and led.summary("2026-12")["savings"]["proposed_share_of_spend"] is None
