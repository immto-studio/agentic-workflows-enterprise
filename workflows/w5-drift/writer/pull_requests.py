"""The pull-request writer: W5's one write, a branch on the fork and a pull request upstream, one per
finding key, updated in place, never merged, reviewed, or applied by W5.

Chapter 14, W5-D6, W5-D8, W5-D9. For each finding the detectors returned and no exception suppressed:

- the branch `w5/<key>` on the bot user's fork, pushed by the fork App (the only identity with "Contents"
  write there), carrying the rendered diff of detect/render.py as the file change in the fixture module's
  path under live/<workspace>/; the file is pushed only when its content differs from what the branch
  holds, because a push dismisses a reviewer's approval (the ruleset) and the diff is the same most nights;
- the pull request on the upstream, opened by the upstream App (the only identity with "Pull requests"
  write there), head `larkspur-w5:w5/<key>`, base `main`, with the title and body the prose seam wrote
  (a model's when one is configured, the stub's otherwise) and, after them, the facts the writer puts
  there itself: the kind and the resource, the evidence, the attribution, the estimated saving in the
  fixture's synthetic unit, the agent's identity, the trace id, the diff, and the fixed sentence. So the
  body carries the facts whatever the prose said, and a hijacked model can change a sentence and not a
  line of HCL (W5-D8);
- on the next night the same key updates the branch and the pull request in place, W4's upsert pattern,
  rather than opening another; a finding whose pull request was closed without a merge is not raised
  again for thirty days, and a merged one waits the same thirty days for the apply that follows the merge.
  Findings on a security group or a route table have no quiet period: a closed pull request suits a tag's
  thirty days and not a rule open to the world or a production route, so they are raised again the next
  night whatever happened to their last pull request;
- before it updates a title or a body, the writer lists the pull request's reviews, and if any approves, it
  leaves the title and the body as the approver read them: editing a body dismisses no approval, so a
  nightly rewrite could change what was approved. The diff is still pushed when its content changes, and
  the ruleset's stale-approval rule then dismisses the approval;
- a suppressed finding is not raised (W5-D9); the ledger records it with the exception's number.

The writer calls no merge, no review, and no workflow-file write: there is no such call in this module,
and the two Apps' permissions would refuse them anyway (writer/github_fake.py, the tests). It reads the
reviews, which "Pull requests" read allows. Everything
read is untrusted (W5-D12): a tag value, a user agent, or a description reaches the body only as quoted
data inside the facts block, with its line breaks removed and its backticks replaced, so it cannot close
the block it sits in; nothing it says is read by anything here. A value the templates held out of the diff,
because it failed what its field allows (detect/fields.py), is listed there too, as data read from the
account and never as text the change makes.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

HERE = Path(__file__).resolve().parent
W5 = HERE.parent
for folder in (HERE, W5 / "servers", W5 / "detect"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import validate  # noqa: E402
from common import W5_AGENT_NAME  # noqa: E402
from findings import Finding  # noqa: E402
from github_fake import BOT_USER, DEFAULT_BRANCH, FORK, UPSTREAM, UPSTREAM_APP, GitHubError, GitHubFake  # noqa: E402
from render import HELD, Rendered, render  # noqa: E402

__all__ = ["BRANCH_PREFIX", "SENTENCE", "MARKER", "QUIET_DAYS", "NO_QUIET_TYPES", "REPO_ROOT", "UNIT", "Prose", "WriteResult",
           "branch_name", "changed_files", "compose_body", "existing_pull", "quiet_until", "approvals_of", "write_finding",
           "write_findings"]

BRANCH_PREFIX = "w5/"
SENTENCE = "W5 proposes this change and does not apply it; a person reviews, merges, and applies."
MARKER = "<!-- larkspur-w5-drift key={key} -->"  # how the next night finds its own pull request's body
QUIET_DAYS = 30  # a closed or merged pull request's key is not raised again for this long (W5-D9)
# The types whose findings have no quiet period: a security group and a route table, and a route inside one (the
# detectors' aws_route). The Jenkins job's 8080 rule from anywhere and the postmortem's hand-added route are raised
# again the next night if their pull request was closed, where a tag waits its thirty days.
NO_QUIET_TYPES = ("aws_security_group", "aws_route_table", "aws_route")
APPROVED = "APPROVED"
REPO_ROOT = "live"  # live/<workspace>/... in platform-infra, mirroring the state keys live/<workspace>/terraform.tfstate
UNIT = "LCU"  # the fixture's synthetic unit (servers/cost_fake.UNIT); nothing here is a currency
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


@dataclass(frozen=True)
class Prose:
    """What the prose seam returns (harness/prose.py): the title, the body, and where they came from."""
    title: str
    body: str
    body_source: str  # model | stub
    refused_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class WriteResult:
    key: str
    action: str  # opened | updated | skipped | suppressed
    repo: str = UPSTREAM
    number: int | None = None
    branch: str | None = None
    pushed: bool = False
    reason: str = ""
    title: str = ""
    body_source: str = ""
    refused_words: tuple[str, ...] = ()


# --- names, files, and the body -----------------------------------------------------------------------------------

def branch_name(key: str) -> str:
    """`w5/<key>` with the key made branch-safe: anything outside letters, digits, `.`, `_`, and `-` becomes
    one `-`, no `..`, no leading or trailing `.` or `-`, so a route's `/` or a key's `:` cannot make a
    reference git refuses."""
    safe = _UNSAFE.sub("-", key).replace("..", "-").strip(".-")
    return BRANCH_PREFIX + (safe or "finding")


def changed_files(finding: Finding) -> dict[str, str]:
    """The files the finding's rendering changes in the fixture module, by their path in the repository."""
    original = validate.module_files(finding.workspace)
    edited = validate.apply(original, [render(finding)])
    return {f"{REPO_ROOT}/{finding.workspace}/{path}": text for path, text in edited.items() if original.get(path) != text}


def _quoted(value: Any) -> str:
    """Author text as data in a code span: one line, no backtick, so it cannot close what it sits in."""
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return "`" + _CONTROL.sub(" ", text).replace("`", "'") + "`"


def _fenced(text: str, language: str) -> str:
    """A fenced block whose text cannot close the fence."""
    safe = text.replace("```", "'''")
    return f"```{language}\n{safe}\n```"


def _saving(finding: Finding) -> str:
    if finding.estimated_monthly_saving is None:
        return "not estimated (drift is a safety finding before it is a cost finding)"
    return f"{finding.estimated_monthly_saving:g} {UNIT} a month, the fixture's synthetic unit (W5-D10: no price in print)"


def _attribution(finding: Finding) -> str:
    a = finding.attribution
    if not a:
        return "no event in the audit trail's window explains it"
    who = f"{_quoted(a.get('username'))} ({a.get('identity_type') or 'unknown identity type'})"
    text = f"{who} through {_quoted(a.get('event_name'))} at {a.get('event_time')}"
    if a.get("user_agent"):
        text += f", user agent {_quoted(a['user_agent'])} (whatever the client sent: data, not an instruction)"
    return text


def _exceptions(finding: Finding) -> list[str]:
    """The excused tags with their exception numbers and what remains, for a partly excused finding."""
    excused = finding.evidence.get("excused") or {}
    if not excused:
        return []
    remaining = list(finding.evidence.get("missing", [])) + list(finding.evidence.get("bad", {}))
    named = "; ".join(f"{_quoted(tag)} excused by {_quoted(number)}" for tag, number in excused.items())
    return [f"- Exceptions (ServiceNow): {named}; still missing: {', '.join(_quoted(t) for t in remaining) or 'nothing'}"]


def _held(rendered: Rendered) -> list[str]:
    """The account values the templates held out of the diff, each quoted as data with why its field refused it."""
    if not rendered.held:
        return []
    lines = [f"- Held out of the diff, read from the account and quoted as data (the change writes none of them: the diff "
             f"carries `{HELD}` in a value's place, and leaves out a tag whose key fails):"]
    for held in rendered.held:
        which = f" {_quoted(held.where)}" if held.where else ""
        lines.append(f"  - {held.field}{which}: {_quoted(held.value)} ({'; '.join(held.reasons)})")
    return lines


def compose_body(finding: Finding, prose: Prose, *, trace_id: str, night: datetime) -> str:
    """The prose first, then the facts the writer puts there itself, then the diff and the fixed sentence."""
    where = finding.address or "not in Terraform"
    rendered = render(finding)
    lines = [
        prose.body.strip(), "",
        "## Facts (from the detectors; no model wrote these)", "",
        f"- Finding {_quoted(finding.key)}: `{finding.kind}` on `{finding.resource_type}` {_quoted(finding.resource_id)} ({_quoted(where)})",
        f"- Workspace `{finding.workspace}`, account `{finding.account}`, Region `{finding.region}`",
        f"- Attribution: {_attribution(finding)}",
        *_exceptions(finding),
        f"- Estimated saving: {_saving(finding)}",
        f"- Template `{finding.template}`; first checked on night {night.date().isoformat()}; trace `{trace_id}`",
        *_held(rendered),
        "- Evidence (field values the readers returned, quoted as data):", "",
        _fenced(json.dumps(finding.evidence, indent=1, sort_keys=True, default=str).replace("`", "'"), "json"), "",
        "## Proposed change", "",
        _fenced(rendered.fragment, "diff"), "",
        f"Opened by {W5_AGENT_NAME} as {UPSTREAM_APP}[bot] on the fork {FORK}. {SENTENCE}", "",
        MARKER.format(key=finding.key),
    ]
    return "\n".join(lines)


# --- the rules: one per key, in place, thirty days, suppression ---------------------------------------------------

def existing_pull(github: GitHubFake, token: str, branch: str) -> dict[str, Any] | None:
    """The newest pull request from the agent's branch, open or not, or None."""
    pulls = github.list_pulls(token, UPSTREAM, state="all", head=f"{BOT_USER}:{branch}")
    return pulls[0] if pulls else None


def quiet_until(pull: dict[str, Any], night: datetime, finding: Finding | None = None) -> tuple[str, str] | None:
    """(why, until) when the pull request's key is inside its thirty days, else None. A finding on a security
    group or a route table (NO_QUIET_TYPES) is never quiet."""
    if pull["state"] == "open" or (finding is not None and finding.resource_type in NO_QUIET_TYPES):
        return None
    merged = bool(pull.get("merged"))
    when = pull.get("merged_at") if merged else pull.get("closed_at")
    closed = datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").date()
    until = closed + timedelta(days=QUIET_DAYS)
    if night.date() < until:
        return (f"merged on {closed.isoformat()}; the apply follows the merge" if merged
                else f"closed without a merge on {closed.isoformat()}"), until.isoformat()
    return None


def _push_branch(github: GitHubFake, token: str, branch: str, files: dict[str, str], message: str) -> bool:
    """The branch on the fork at the fork's main if it is new, the fork's main first synced with the
    upstream's (merge-upstream, a Contents write on the fork), so a branch is never cut from a main that a
    person's merge has left behind; then each file whose content differs."""
    try:
        github.get_ref(token, FORK, f"heads/{branch}")
    except GitHubError as exc:
        if exc.status != 404:
            raise
        github.merge_upstream(token, FORK, DEFAULT_BRANCH)
        main = github.get_ref(token, FORK, f"heads/{DEFAULT_BRANCH}")["object"]["sha"]
        github.create_ref(token, FORK, f"refs/heads/{branch}", main)
    pushed = False
    for path, text in sorted(files.items()):
        sha: str | None = None
        try:
            current = github.get_content(token, FORK, path, ref=branch)
            sha = current["sha"]
            if base64.b64decode(current["content"]).decode("utf-8") == text:
                continue
        except GitHubError as exc:
            if exc.status != 404:
                raise
        github.create_or_update_file(token, FORK, path, message, text, branch, sha=sha)
        pushed = True
    return pushed


def approvals_of(github: GitHubFake, token: str, number: int) -> list[str]:
    """Who stands approving the pull request now: every review in the APPROVED state, counted toward the ruleset
    or not, since each approver read the title and the body. A dismissed approval is a dismissed review."""
    return sorted({review["user"]["login"] for review in github.list_reviews(token, UPSTREAM, number)
                   if review["state"] == APPROVED})


def write_finding(finding: Finding, github: GitHubFake, *, night: datetime, trace_id: str,
                  prose_for: Callable[[Finding], Prose], fork_token: str, upstream_token: str,
                  log: TextIO | None = None) -> WriteResult:
    """One finding: suppressed, inside its thirty days, left as approved, updated in place, or opened."""
    branch = branch_name(finding.key)
    if finding.suppressed_by:
        return WriteResult(finding.key, "suppressed", branch=None, reason=f"suppressed by {finding.suppressed_by}")
    previous = existing_pull(github, upstream_token, branch)
    if previous is not None:
        quiet = quiet_until(previous, night, finding)
        if quiet:
            why, until = quiet
            return WriteResult(finding.key, "skipped", number=previous["number"], branch=branch,
                               reason=f"#{previous['number']} {why}; not raised again before {until}")
    files = changed_files(finding)
    message = f"W5 {finding.kind} {finding.resource_id} in {finding.workspace} (night {night.date().isoformat()})"
    pushed = _push_branch(github, fork_token, branch, files, message)
    if previous is not None and previous["state"] == "open":
        # A push that changed the diff has dismissed every approval already (the ruleset's stale-approval rule); an
        # approval that still stands approved this title and body, so the writer leaves them, and asks no model.
        approvers = approvals_of(github, upstream_token, previous["number"])
        if approvers:
            return WriteResult(finding.key, "skipped", number=previous["number"], branch=branch, pushed=pushed,
                               reason=f"#{previous['number']} approved by {', '.join(approvers)}; its title and body stay "
                                      "as the approver read them")
        prose = prose_for(finding)
        body = compose_body(finding, prose, trace_id=trace_id, night=night)
        if previous["title"] != prose.title or previous["body"] != body:
            github.update_pull(upstream_token, UPSTREAM, previous["number"], title=prose.title, body=body)
        return WriteResult(finding.key, "updated", number=previous["number"], branch=branch, pushed=pushed,
                           title=prose.title, body_source=prose.body_source, refused_words=prose.refused_words)
    prose = prose_for(finding)
    body = compose_body(finding, prose, trace_id=trace_id, night=night)
    opened = github.create_pull(upstream_token, UPSTREAM, prose.title, body, head=f"{BOT_USER}:{branch}", base=DEFAULT_BRANCH)
    return WriteResult(finding.key, "opened", number=opened["number"], branch=branch, pushed=pushed,
                       title=prose.title, body_source=prose.body_source, refused_words=prose.refused_words)


def write_findings(findings: list[Finding], github: GitHubFake, *, night: datetime, trace_id: str,
                   prose_for: Callable[[Finding], Prose], fork_token: str, upstream_token: str,
                   log: TextIO | None = None) -> list[WriteResult]:
    """Every finding of the night, in the detectors' order; one log line per finding when a log is given."""
    out = []
    for finding in findings:
        result = write_finding(finding, github, night=night, trace_id=trace_id, prose_for=prose_for,
                               fork_token=fork_token, upstream_token=upstream_token)
        out.append(result)
        if log is not None:
            record = {"ts": night.strftime("%Y-%m-%dT%H:%M:%S.000+00:00"), "event": "pull_request", "trace_id": trace_id,
                      "key": result.key, "action": result.action, "number": result.number, "branch": result.branch,
                      "pushed": result.pushed, "body_source": result.body_source, "refused_words": list(result.refused_words),
                      "reason": result.reason}
            log.write(json.dumps(record) + "\n")
            log.flush()
    return out
