"""The check of GitHub itself before a night writes anything: the upstream App's token and the rules on main.

Chapter 14, W5-D6 and the fact sheet's A.13, after the reader review's finding 8. aws/'s precondition reads the
catalog, so an organization owner who gave `larkspur-w5-upstream` Contents write in GitHub's settings, or took the
code owner's review off the ruleset, would leave the plan passing. Before the night reads or writes anything, the
harness asks GitHub two things, both open to the upstream App:

1. the permissions its installation token was granted, which the token's creation response lists (A.13.1): the
   night stops if the App holds "Contents", "Workflows", or "Administration" write, the three that merge, write
   a workflow file, or edit the rules W5 relies on (A.1, A.6);
2. the active rules on `main`, through "Get rules for a branch", which needs only "Metadata" read (A.13.2): the
   night stops if no rule requires a code owner's review, if none dismisses a stale approval on a new push (the
   writer leaves an approved pull request's prose as the approver read it and lets that rule void the approval
   when the diff changes), or if none requires the catalog's status check from its pinned source.

It also reads each ruleset behind those rules for `current_user_can_bypass`, the App's own bypass, and stops the
night unless it reads `never` (A.13.3). The rest of the bypass list it cannot see: GitHub returns
`bypass_actors` only to a caller with write access to the ruleset, which no W5 App holds (A.13.3), so the check
that no actor at all may bypass stays in aws/'s precondition, a check of the catalog.

Every failure, a call GitHub refused included, stops the night: the check fails closed, and the night record
carries the reasons.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
W5 = HERE.parent
if str(W5 / "writer") not in sys.path:
    sys.path.insert(0, str(W5 / "writer"))

from github_fake import DEFAULT_BRANCH, FORK_APP, UPSTREAM, UPSTREAM_APP, GitHubError, GitHubFake  # noqa: E402

__all__ = ["MERGE_CAPABLE", "REQUIRED_CHECKS", "check"]

CATALOG = yaml.safe_load((W5 / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
MERGE_CAPABLE = ("contents", "workflows", "administration")
# The status checks main must require, each from its pinned App: the catalog's record of the ruleset.
REQUIRED_CHECKS: list[dict[str, Any]] = list(CATALOG["github"]["ruleset"]["require_status_checks"])


def _token(github: GitHubFake, app: str, reasons: list[str]) -> dict[str, Any] | None:
    try:
        return github.create_installation_token(app)
    except GitHubError as exc:
        reasons.append(f"{app}: no installation token ({exc.status}: {exc.message})")
        return None


def check(github: GitHubFake, branch: str = DEFAULT_BRANCH) -> tuple[dict[str, Any], dict[str, str]]:
    """The night's check of GitHub: (the report the night record keeps, the two Apps' tokens). The report's
    `ok` is False with its `reasons` whenever the night must stop; the tokens are never part of the report."""
    reasons: list[str] = []
    report: dict[str, Any] = {"ok": False, "app": UPSTREAM_APP, "repository": UPSTREAM, "branch": branch, "permissions": {},
                              "rules": [], "required_status_checks": [], "can_bypass": {}, "reasons": reasons}
    fork, upstream = _token(github, FORK_APP, reasons), _token(github, UPSTREAM_APP, reasons)
    if fork is None or upstream is None:
        return report, {}
    tokens = {FORK_APP: fork["token"], UPSTREAM_APP: upstream["token"]}

    held = dict(upstream.get("permissions") or {})
    report["permissions"] = held
    for permission in MERGE_CAPABLE:
        if held.get(permission) in ("write", "admin"):
            reasons.append(f"{UPSTREAM_APP} holds {permission}: {held[permission]} on {UPSTREAM}")

    try:
        rules = github.get_branch_rules(tokens[UPSTREAM_APP], UPSTREAM, branch)
    except GitHubError as exc:
        reasons.append(f"the rules on {branch} could not be read ({exc.status}: {exc.message})")
        return report, tokens
    report["rules"] = sorted({rule["type"] for rule in rules})
    reviews = [rule.get("parameters") or {} for rule in rules if rule["type"] == "pull_request"]
    if not any(p.get("require_code_owner_review") for p in reviews):
        reasons.append(f"no active rule on {branch} requires a code owner's review")
    if not any(p.get("dismiss_stale_reviews_on_push") for p in reviews):
        reasons.append(f"no active rule on {branch} dismisses a stale approval when new commits are pushed")
    required = [c for rule in rules if rule["type"] == "required_status_checks"
                for c in (rule.get("parameters") or {}).get("required_status_checks") or []]
    report["required_status_checks"] = required
    for want in REQUIRED_CHECKS:
        if not any(c.get("context") == want["context"] and c.get("integration_id") == want["integration_id"] for c in required):
            reasons.append(f"no active rule on {branch} requires the check {want['context']} from the App {want['integration_id']}")

    for ruleset_id in sorted({rule["ruleset_id"] for rule in rules if rule.get("ruleset_id") is not None}):
        try:
            ruleset = github.get_ruleset(tokens[UPSTREAM_APP], UPSTREAM, ruleset_id)
        except GitHubError as exc:
            reasons.append(f"the ruleset {ruleset_id} could not be read ({exc.status}: {exc.message})")
            continue
        can = ruleset.get("current_user_can_bypass")
        report["can_bypass"][ruleset.get("name") or str(ruleset_id)] = can
        if can != "never":
            reasons.append(f"{UPSTREAM_APP} can bypass the ruleset {ruleset.get('name') or ruleset_id!r} ({can or 'not reported'})")

    report["ok"] = not reasons
    return report, tokens
