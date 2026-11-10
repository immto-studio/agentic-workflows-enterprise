"""The GitHub fake for W5: one fork network, two App installations, a ruleset, and the REST shapes the
writer and the harness call, each refused with GitHub's 403 when the installation's permissions do not
cover it.

Chapter 14, W5-D6 and W5-D7 as the fact sheet corrected them (section E). W4's fake
(workflows/w4-change/servers/github_fake.py) served a pull request's fields and took one comment back,
updated in place. W5's write is a pull request from a fork, so this fake holds two repositories that
share Git objects as a fork network does ("a fork and its upstream share the same Git data", A.2): the
bot user's fork `larkspur-w5/platform-infra`, where the agent's branches live, and the upstream
`larkspur-mutual/platform-infra`, where its pull requests are opened. Two App registrations, because an
App's permissions belong to its registration and every installing account grants the same set (A.1):

- `larkspur-w5-fork`, installed on the fork with "Contents" write: it creates the branch and writes the file.
- `larkspur-w5-upstream`, installed on the upstream with "Pull requests" write and "Metadata" read: it
  opens and updates the pull request and reads it back, and can do nothing else there.

GitHub Actions is the third installation, on the upstream: it runs the `validate` workflow on a pull
request and reports its job as a check run on the pull request's head commit, which the ruleset requires.

Every call takes a token: an installation token is the fake's own string naming the installation, a
user token names a person. `create_installation_token` is the App's own call for one
(`POST /app/installations/{id}/access_tokens`), and its answer lists the permissions the token carries, as
GitHub's does (A.13.1). Each endpoint is mapped to the permission the reference lists for it (A.1):
`POST git/refs` and `PUT contents/{path}` need "Contents" write on that repository, and "Workflows" write
too when the path is under `.github/workflows/`; `PUT pulls/{n}/merge` needs "Contents" write on the
upstream, where the reference lists it and not under "Pull requests"; `POST pulls`, `PATCH pulls/{n}`,
and `POST pulls/{n}/reviews` need "Pull requests" write; `GET pulls`, `GET pulls/{n}/files`, and
`GET pulls/{n}/reviews` need "Pull requests" read; `POST check-runs` needs "Checks" write; `GET
repos/{owner}/{repo}`, `GET rules/branches/{branch}`, and `GET rulesets/{id}` need "Metadata" read, which
every installation holds on its own repositories (A.13.2). A call outside the permissions gets a 403 with
GitHub's sentence, "Resource not accessible by integration" (the same status when the installation does
not include the repository at all, so a test reads one status), and is logged like every other call.

The ruleset on the upstream's `main` (A.4, A.12): a pull request required, one approving review and a
review from a code owner, stale approvals dismissed on a new push, the most recent push approved by
someone other than its pusher, the `validate` check required and pinned to GitHub Actions as its source,
creations restricted, force pushes blocked, no bypass actor. "Restrict updates" is not in it: no page says
what it does to a merge, and "Require a pull request before merging" already keeps every direct push out
(A.12.1, A.12.2). CODEOWNERS names users and teams with write access, as GitHub's page says it must, and
no App. So the merge endpoint refuses until GitHub Actions has reported the `validate` job's success on the
pull request's head commit and a person who is a code owner has approved; an approving review by an App
is recorded and counted for nothing here, which is the fake's reading (GitHub counts approvals from people
with write access and says nothing of an App's, A.8.1); the author's own approval is refused as GitHub
refuses it; and a push to the head branch dismisses the approvals on it. `get_branch_rules` answers "Get
rules for a branch" with each active rule, its parameters, and the ruleset it comes from, and
`get_ruleset` answers "Get a repository ruleset" with `current_user_can_bypass` for the caller and
`bypass_actors` only for a caller with write access to the ruleset (A.13.2, A.13.3).

Everything is in memory in one `GitHubFake`; a test may change an installation's permissions
(`fake.apps`) or the ruleset (`fake.rulesets`), as an organization owner could in GitHub's settings;
`save` and `load` keep it in a JSON file between nights (`GITHUB_STATE_FILE`, W4's store pattern) and
`log` records every call for the tests.
"""

from __future__ import annotations

import base64
import copy
import difflib
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
W5 = HERE.parent
for folder in (W5 / "servers", W5 / "detect"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
from common import NIGHT  # noqa: E402

__all__ = ["FORK", "UPSTREAM", "FORK_APP", "UPSTREAM_APP", "GITHUB_ACTIONS_APP", "GITHUB_ACTIONS_ID", "VALIDATE_CHECK", "BOT_USER",
           "PLATFORM_TEAM", "SECURITY_TEAM", "NETWORK_TEAM", "APPS", "INSTALLATIONS", "USERS", "TEAMS", "CODEOWNERS", "RULESET",
           "WORKFLOWS_DIR", "NOT_ACCESSIBLE", "OWN_APPROVAL", "GitHubError", "GitHubFake", "seed_platform_infra", "report_check",
           "open_store"]

FORK = "larkspur-w5/platform-infra"
UPSTREAM = "larkspur-mutual/platform-infra"
NETWORK = (UPSTREAM, FORK)
FORK_APP = "larkspur-w5-fork"
UPSTREAM_APP = "larkspur-w5-upstream"
GITHUB_ACTIONS_APP = "github-actions"
GITHUB_ACTIONS_ID = 15368  # the GitHub Actions App's id, as GET /apps/github-actions returned it on 3 November 2026
VALIDATE_CHECK = "validate"  # the validate workflow's job: a required check is matched by its job's name (A.12.3)
BOT_USER = "larkspur-w5"  # the bot user that owns the fork (A.2: a fork owned by an organization takes no push grant)
PLATFORM_TEAM = "larkspur-mutual/platform-team"
SECURITY_TEAM = "larkspur-mutual/security"
NETWORK_TEAM = "larkspur-mutual/network-engineering"
DEFAULT_BRANCH = "main"
WORKFLOWS_DIR = ".github/workflows/"
NOT_ACCESSIBLE = "Resource not accessible by integration"
OWN_APPROVAL = "Review Can not approve your own pull request"
LEVELS = {"none": 0, "read": 1, "write": 2, "admin": 3}
IMPLICIT = {"metadata": "read"}  # every App holds it on the repositories it is installed on
TOKEN_HOURS = 1  # "The installation access token will expire after 1 hour." (A.2)

# The two registrations, as catalog/tools.yaml records them, ids included.
APPS: dict[str, dict[str, Any]] = {
    FORK_APP: {"id": 410001, "installation": 55001, "account": BOT_USER, "repositories": [FORK],
               "permissions": {"contents": "write"}},
    UPSTREAM_APP: {"id": 410002, "installation": 55002, "account": "larkspur-mutual", "repositories": [UPSTREAM],
                   "permissions": {"pull_requests": "write", "metadata": "read"}},
}
# Every installation the fake knows: W5's two and GitHub Actions on the upstream, which reports the validate job.
INSTALLATIONS: dict[str, dict[str, Any]] = {
    **APPS,
    GITHUB_ACTIONS_APP: {"id": GITHUB_ACTIONS_ID, "installation": 55003, "account": "larkspur-mutual", "repositories": [UPSTREAM],
                         "permissions": {"checks": "write", "statuses": "write", "contents": "read"}},
}
# The people: the platform team owns the code; the network team owns network-live and holds write access to the
# repository; security co-owns the workflows (no test needs one of its members, so none is modeled); FinOps reads the
# pull requests, and its approval counts for nothing, because only write access counts (A.3).
TEAMS: dict[str, list[str]] = {PLATFORM_TEAM: ["priya.raman", "tomasz.nowak", "sam.okafor", "felix.morin"],
                               NETWORK_TEAM: ["rosa.delgado"], SECURITY_TEAM: []}
USERS: dict[str, dict[str, Any]] = {
    "priya.raman": {"teams": [PLATFORM_TEAM]}, "tomasz.nowak": {"teams": [PLATFORM_TEAM]}, "sam.okafor": {"teams": [PLATFORM_TEAM]},
    "felix.morin": {"teams": [PLATFORM_TEAM]}, "rosa.delgado": {"teams": [NETWORK_TEAM]}, "ingrid.holm": {"teams": []},
    BOT_USER: {"teams": []},
}
# Who holds what on each repository. A private fork inherits the upstream's team permissions (A.2).
REPO_ACCESS: dict[str, dict[str, str]] = {
    UPSTREAM: {PLATFORM_TEAM: "write", SECURITY_TEAM: "write", NETWORK_TEAM: "write", "ingrid.holm": "read"},
    FORK: {BOT_USER: "admin", PLATFORM_TEAM: "write", SECURITY_TEAM: "write", NETWORK_TEAM: "write", "ingrid.holm": "read"},
}
CODEOWNERS = ("# Users and teams with explicit write access only (GitHub's rule); no App is a code owner here.\n"
              "*                   @larkspur-mutual/platform-team\n"
              "/.github/workflows/ @larkspur-mutual/platform-team @larkspur-mutual/security\n")
VALIDATE_WORKFLOW = ("# The check a pull request from the agent's fork runs: with the organization's fork settings, a read-only\n"
                     "# GITHUB_TOKEN and no secret reach it (fact sheet A.5, A.9), so it validates and formats and never plans\n"
                     "# with credentials. The ruleset requires its job, validate, from GitHub Actions.\n"
                     "name: validate\non:\n  pull_request:\njobs:\n  validate:\n    runs-on: ubuntu-24.04\n"
                     "    steps:\n      - uses: actions/checkout@v4\n      - run: terraform init -backend=false\n"
                     "      - run: terraform validate\n      - run: terraform fmt -check -recursive\n")
# GitHub's REST shape for a repository ruleset (the "Rules" reference), with the rules A.4 and A.12 name. The
# required check is pinned to GitHub Actions through integration_id, so no other App or person can satisfy it.
RULESET: dict[str, Any] = {
    "id": 7701, "name": "protect-main", "target": "branch", "source_type": "Repository", "source": UPSTREAM,
    "enforcement": "active", "bypass_actors": [],
    "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
    "rules": [
        {"type": "creation"},
        {"type": "non_fast_forward"},
        {"type": "pull_request", "parameters": {
            "required_approving_review_count": 1, "require_code_owner_review": True,
            "dismiss_stale_reviews_on_push": True, "require_last_push_approval": True,
            "required_review_thread_resolution": False}},
        {"type": "required_status_checks", "parameters": {
            "required_status_checks": [{"context": VALIDATE_CHECK, "integration_id": GITHUB_ACTIONS_ID}],
            "strict_required_status_checks_policy": False}},
    ],
}
# How a bypass actor's mode reads back as `current_user_can_bypass` (A.13.3).
_BYPASS_MODES = {"always": "always", "pull_request": "pull_requests_only", "exempt": "exempt"}


class GitHubError(Exception):
    """GitHub's error answer: the status and the message."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status, self.message = status, message


def _sha(*parts: Any) -> str:
    return hashlib.sha256("\n".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:40]


def _blob_sha(text: str) -> str:
    return hashlib.sha1(f"blob {len(text.encode('utf-8'))}\0{text}".encode("utf-8")).hexdigest()


def _ref(name: str) -> str:
    """`refs/heads/x` from `heads/x` or `x`, as the endpoints take either."""
    if name.startswith("refs/"):
        return name
    return f"refs/{name}" if name.startswith("heads/") else f"refs/heads/{name}"


class GitHubFake:
    """Two repositories, three installations, the people, the ruleset, the checks, and every call logged."""

    def __init__(self, now: datetime = NIGHT, path: Path | None = None) -> None:
        self.now = now
        self.path = path
        self.apps: dict[str, dict[str, Any]] = copy.deepcopy(INSTALLATIONS)
        self.rulesets: list[dict[str, Any]] = [copy.deepcopy(RULESET)]
        self.commits: dict[str, dict[str, Any]] = {}
        self.repos: dict[str, dict[str, Any]] = {
            UPSTREAM: {"full_name": UPSTREAM, "private": True, "fork": False, "parent": None, "refs": {}, "pushers": {}},
            FORK: {"full_name": FORK, "private": True, "fork": True, "parent": UPSTREAM, "refs": {}, "pushers": {}},
        }
        self.pulls: dict[int, dict[str, Any]] = {}
        self.reviews: dict[int, list[dict[str, Any]]] = {}
        self.check_runs: list[dict[str, Any]] = []
        self.log: list[dict[str, Any]] = []
        self.next_pull = 2300
        self.next_review = 9000
        self.next_check = 31000
        self.counter = 0

    # --- tokens and identities -------------------------------------------------------------------------------

    def installation_token(self, app: str) -> str:
        """The token string an installation's token creation returns: the fake's own, naming the installation."""
        return f"ghs_{app}_{self.apps[app]['installation']}"

    def create_installation_token(self, app: str) -> dict[str, Any]:
        """POST /app/installations/{installation_id}/access_tokens, the App's own call under its JWT: the token,
        when it expires, the permissions it carries, and the repositories it reaches (A.13.1, the REST example's
        fields). Without a `permissions` body the token carries every permission the installation was granted."""
        registration = self.apps.get(app)
        path = f"/app/installations/{registration['installation'] if registration else '?'}/access_tokens"
        if registration is None:
            self.log.append({"at": self._stamp(), "method": "POST", "path": path, "actor": app, "status": 401,
                             "message": "A JSON web token could not be decoded"})
            raise GitHubError(401, "A JSON web token could not be decoded")
        body = {"token": self.installation_token(app),
                "expires_at": (self.now + timedelta(hours=TOKEN_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "permissions": {**IMPLICIT, **registration["permissions"]}, "repository_selection": "selected",
                "repositories": [{"full_name": repo, "name": repo.split("/")[1], "private": self.repos[repo]["private"]}
                                 for repo in registration["repositories"] if repo in self.repos]}
        self.log.append({"at": self._stamp(), "method": "POST", "path": path, "actor": app, "status": 201})
        self._persist()
        return json.loads(json.dumps(body))

    def user_token(self, login: str) -> str:
        return f"ghu_{login}"

    def _identity(self, token: str) -> dict[str, Any]:
        for slug, app in self.apps.items():
            if token == self.installation_token(slug):
                return {"type": "Bot", "login": f"{slug}[bot]", "app": slug, "app_id": app["id"], "installation": app["installation"],
                        "repositories": list(app["repositories"]), "permissions": {**IMPLICIT, **app["permissions"]}}
        if token.startswith("ghu_") and token[4:] in USERS:
            return {"type": "User", "login": token[4:]}
        raise GitHubError(401, "Bad credentials")

    def _user_level(self, login: str, repo: str) -> int:
        access = REPO_ACCESS[repo]
        levels = [LEVELS[access[login]]] if login in access else []
        levels += [LEVELS[access[team]] for team in USERS[login]["teams"] if team in access]
        return max(levels, default=0)

    def _permit(self, identity: dict[str, Any], repo: str, permission: str, level: str, *, path: str | None = None,
                user_level: str | None = None) -> None:
        """The permissions reference's rule for one endpoint: the App's installation must include the
        repository and hold the permission at the level; a person must hold the level on the repository
        (`user_level` when a person's need differs from an App's: a review takes read access)."""
        if repo not in self.repos:
            raise GitHubError(404, "Not Found")
        if identity["type"] == "Bot":
            if repo not in identity["repositories"]:
                raise GitHubError(403, f"{NOT_ACCESSIBLE} (the installation does not include {repo})")
            held = LEVELS.get(identity["permissions"].get(permission, "none"), 0)
            if held < LEVELS[level]:
                raise GitHubError(403, f"{NOT_ACCESSIBLE} ({permission}: {level} is not held)")
            if path and path.startswith(WORKFLOWS_DIR) and LEVELS.get(identity["permissions"].get("workflows", "none"), 0) < 2:
                raise GitHubError(403, f"{NOT_ACCESSIBLE} (workflows: write is not held)")
            return
        level = user_level or level
        needed = LEVELS[level]
        held = self._user_level(identity["login"], repo)
        if held < 1:
            raise GitHubError(404, "Not Found")
        if held < needed:
            raise GitHubError(403, f"Must have {level} access to this repository")

    def _stamp(self) -> str:
        return self.now.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _call(self, method: str, path: str, token: str, work: Callable[[dict[str, Any]], tuple[int, Any]]) -> Any:
        """One endpoint: the identity, the work, one log line whatever the outcome, the store written."""
        identity: dict[str, Any] | None = None
        try:
            identity = self._identity(token)
            status, body = work(identity)
        except GitHubError as exc:
            self.log.append({"at": self._stamp(), "method": method, "path": path, "actor": identity["login"] if identity else None,
                             "status": exc.status, "message": exc.message})
            raise
        self.log.append({"at": self._stamp(), "method": method, "path": path, "actor": identity["login"], "status": status})
        self._persist()
        return body

    # --- the rulesets ----------------------------------------------------------------------------------------------

    def _rules_for(self, repo: str, ref: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """(ruleset, rule) for every rule of an active ruleset that targets the ref: what GitHub enforces there.
        A ruleset in "evaluate" or "disabled" enforcement enforces nothing (A.13.2)."""
        out = []
        for ruleset in self.rulesets:
            conditions = ruleset.get("conditions", {}).get("ref_name", {})
            if (ruleset.get("source") != repo or ruleset.get("enforcement") != "active" or ruleset.get("target", "branch") != "branch"
                    or ref not in conditions.get("include", []) or ref in conditions.get("exclude", [])):
                continue
            out.extend((ruleset, rule) for rule in ruleset.get("rules", []))
        return out

    def _protected(self, repo: str, ref: str) -> bool:
        return bool(self._rules_for(repo, ref))

    def _push_refusal(self, repo: str, ref: str) -> str | None:
        """Why the active rules refuse a direct push to the ref, or None. "Require a pull request before merging"
        keeps every direct push out (A.12.2), as a required status check does ("commits must first be pushed to
        another ref where the checks pass", A.12.3)."""
        for ruleset, rule in self._rules_for(repo, ref):
            if rule["type"] == "pull_request":
                return f"Repository rule violations found for {ref}: changes must be made through a pull request (ruleset {ruleset['name']!r})"
            if rule["type"] == "required_status_checks":
                return f"Repository rule violations found for {ref}: required status checks must pass first (ruleset {ruleset['name']!r})"
            if rule["type"] == "update":
                return f"Repository rule violations found for {ref}: updates are restricted (ruleset {ruleset['name']!r})"
        return None

    def _can_write_ruleset(self, identity: dict[str, Any], repo: str) -> bool:
        """Write access to a repository's ruleset: "Administration" write for an App (A.6.1), admin for a person."""
        if identity["type"] == "Bot":
            return repo in identity["repositories"] and LEVELS.get(identity["permissions"].get("administration", "none"), 0) >= 2
        return self._user_level(identity["login"], repo) >= LEVELS["admin"]

    def _can_bypass(self, identity: dict[str, Any], ruleset: dict[str, Any]) -> str:
        """`current_user_can_bypass` for the caller: an App by its id as an `Integration` actor (A.6.4). The fake
        models no person's id, so a person reads `never`."""
        if identity["type"] == "Bot":
            for actor in ruleset.get("bypass_actors", []):
                if actor.get("actor_type") == "Integration" and actor.get("actor_id") == identity["app_id"]:
                    return _BYPASS_MODES.get(actor.get("bypass_mode", "always"), "always")
        return "never"

    def get_branch_rules(self, token: str, repo: str, branch: str = DEFAULT_BRANCH) -> list[dict[str, Any]]:
        """GET repos/{owner}/{repo}/rules/branches/{branch}: every active rule that applies to the branch, each with
        the ruleset it comes from, under "Metadata" read (A.13.2; the REST example's fields)."""
        full = _ref(branch)

        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "metadata", "read")
            out = []
            for ruleset, rule in self._rules_for(repo, full):
                item = {"type": rule["type"]}
                if "parameters" in rule:
                    item["parameters"] = rule["parameters"]
                item.update(ruleset_source_type=ruleset.get("source_type", "Repository"), ruleset_source=ruleset["source"],
                            ruleset_id=ruleset["id"])
                out.append(item)
            return 200, json.loads(json.dumps(out))
        return self._call("GET", f"/repos/{repo}/rules/branches/{branch}", token, work)

    def get_ruleset(self, token: str, repo: str, ruleset_id: int) -> dict[str, Any]:
        """GET repos/{owner}/{repo}/rulesets/{ruleset_id}: anyone with read access can view an active ruleset (A.4),
        `bypass_actors` "only returned if the user making the API request has write access to the ruleset", and
        `current_user_can_bypass` is the caller's own (A.13.3)."""
        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "metadata", "read")
            ruleset = next((r for r in self.rulesets if r["id"] == ruleset_id and r.get("source") == repo), None)
            if ruleset is None:
                raise GitHubError(404, "Not Found")
            body = {k: v for k, v in ruleset.items() if k != "bypass_actors"}
            if self._can_write_ruleset(identity, repo):
                body["bypass_actors"] = ruleset.get("bypass_actors", [])
            body["current_user_can_bypass"] = self._can_bypass(identity, ruleset)
            return 200, json.loads(json.dumps(body))
        return self._call("GET", f"/repos/{repo}/rulesets/{ruleset_id}", token, work)

    # --- git data, shared across the network ---------------------------------------------------------------------

    def _commit(self, repo: str, ref: str, tree: dict[str, str], message: str, author: str, parents: list[str]) -> str:
        self.counter += 1
        sha = _sha(*parents, json.dumps(tree, sort_keys=True), message, author, self.counter)
        self.commits[sha] = {"sha": sha, "parents": parents, "tree": tree, "message": message,
                             "author": author, "date": self._stamp()}
        self.repos[repo]["refs"][ref] = sha
        self.repos[repo]["pushers"][ref] = author
        return sha

    def _on_push(self, repo: str, ref: str, sha: str) -> None:
        """A push to a branch: the pull requests with that head move to the new sha and, where the base's rules
        say so, their approvals are dismissed as stale ("Dismiss stale pull request approvals when new commits
        are pushed", A.4)."""
        branch = ref.removeprefix("refs/heads/")
        for pr in self.pulls.values():
            if pr["state"] != "open" or pr["head"]["repo"]["full_name"] != repo or pr["head"]["ref"] != branch:
                continue
            pr["head"]["sha"] = sha
            pr["updated_at"] = self._stamp()
            rules = self._rules_for(pr["base"]["repo"]["full_name"], _ref(pr["base"]["ref"]))
            if not any(rule["type"] == "pull_request" and rule.get("parameters", {}).get("dismiss_stale_reviews_on_push")
                       for _, rule in rules):
                continue
            for review in self.reviews.get(pr["number"], []):
                if review["state"] == "APPROVED":
                    review.update(state="DISMISSED", dismissed=True,
                                  dismissal_reason="stale: new commits were pushed to the pull request branch")

    def _resolve_head(self, base_repo: str, head: str) -> tuple[str, str]:
        """`owner:branch` names a branch in that owner's repository of the network; `branch` names the base's."""
        if ":" in head:
            owner, branch = head.split(":", 1)
            repo = next((r for r in NETWORK if r.split("/")[0] == owner), None)
            if repo is None:
                raise GitHubError(422, f"Validation Failed: head {head!r} names no repository in the network")
            return repo, branch
        return base_repo, head

    # --- the endpoints ----------------------------------------------------------------------------------------------

    def get_repository(self, token: str, repo: str) -> dict[str, Any]:
        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "metadata", "read")
            r = self.repos[repo]
            parent = {"full_name": r["parent"]} if r["parent"] else None
            return 200, {"full_name": r["full_name"], "private": r["private"], "fork": r["fork"],
                         "default_branch": DEFAULT_BRANCH, "parent": parent}
        return self._call("GET", f"/repos/{repo}", token, work)

    def get_ref(self, token: str, repo: str, ref: str) -> dict[str, Any]:
        full = _ref(ref)

        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "contents", "read")
            sha = self.repos[repo]["refs"].get(full)
            if sha is None:
                raise GitHubError(404, "Not Found")
            return 200, {"ref": full, "object": {"type": "commit", "sha": sha}}
        return self._call("GET", f"/repos/{repo}/git/ref/{full.removeprefix('refs/')}", token, work)

    def create_ref(self, token: str, repo: str, ref: str, sha: str) -> dict[str, Any]:
        full = _ref(ref)

        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "contents", "write")
            if full in self.repos[repo]["refs"]:
                raise GitHubError(422, "Reference already exists")
            if sha not in self.commits:
                raise GitHubError(422, "Object does not exist")
            creation = next((rs for rs, rule in self._rules_for(repo, full) if rule["type"] == "creation"), None)
            if creation is not None:
                raise GitHubError(403, f"Creating {full} is restricted by the ruleset {creation['name']!r}; no bypass actor")
            self.repos[repo]["refs"][full] = sha
            self.repos[repo]["pushers"][full] = identity["login"]
            return 201, {"ref": full, "object": {"type": "commit", "sha": sha}}
        return self._call("POST", f"/repos/{repo}/git/refs", token, work)

    def update_ref(self, token: str, repo: str, ref: str, sha: str, force: bool = False) -> dict[str, Any]:
        full = _ref(ref)

        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "contents", "write")
            current = self.repos[repo]["refs"].get(full)
            if current is None:
                raise GitHubError(422, "Reference does not exist")
            if sha not in self.commits:
                raise GitHubError(422, "Object does not exist")
            blocking = next((rs for rs, rule in self._rules_for(repo, full) if rule["type"] == "non_fast_forward"), None)
            if force and blocking is not None:
                raise GitHubError(422, f"Cannot force-push to this branch: blocked by the ruleset {blocking['name']!r}")
            refusal = self._push_refusal(repo, full)
            if refusal:
                raise GitHubError(403, refusal)
            if not force and current not in self._ancestors(sha):
                raise GitHubError(422, "Update is not a fast forward")
            self.repos[repo]["refs"][full] = sha
            self.repos[repo]["pushers"][full] = identity["login"]
            self._on_push(repo, full, sha)
            return 200, {"ref": full, "object": {"type": "commit", "sha": sha}}
        return self._call("PATCH", f"/repos/{repo}/git/refs/{full.removeprefix('refs/')}", token, work)

    def merge_upstream(self, token: str, repo: str, branch: str = DEFAULT_BRANCH) -> dict[str, Any]:
        """POST repos/{owner}/{repo}/merge-upstream: a fork's branch synced with its upstream's, a "Contents"
        write on the fork (the fork App holds it; the fork network shares the objects, so no upstream read is
        needed). The fake fast-forwards when the fork's branch is behind and reports `none` when it is level;
        a fork branch that diverged gets GitHub's 409, which the agent never causes because it pushes only to
        its w5/ branches. Step 5's golden night 2 found the writer cutting a branch from a stale fork main
        after a person's merge, so the writer syncs before it branches (W5-D9). Whether GitHub lets an App do
        this on a private fork whose upstream it cannot read is not stated anywhere (A.11.3, F)."""
        full = _ref(branch)

        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "contents", "write")
            parent = self.repos[repo].get("parent")
            if not parent:
                raise GitHubError(422, "The repository is not a fork")
            theirs, mine = self.repos[parent]["refs"].get(full), self.repos[repo]["refs"].get(full)
            if theirs is None or mine is None:
                raise GitHubError(422, f"Branch {branch} does not exist on both repositories")
            label = f"{parent.split('/')[0]}:{branch}"
            if theirs == mine or theirs in self._ancestors(mine):
                return 200, {"message": f"This branch is not behind the upstream {label}.", "merge_type": "none", "base_branch": label}
            if mine not in self._ancestors(theirs):
                raise GitHubError(409, f"The branch could not be synced because of a merge conflict with {label}")
            self.repos[repo]["refs"][full] = theirs
            self.repos[repo]["pushers"][full] = identity["login"]
            return 200, {"message": f"Successfully fast-forwarded branch {branch} to {label}.", "merge_type": "fast-forward",
                         "base_branch": label}
        return self._call("POST", f"/repos/{repo}/merge-upstream", token, work)

    def _ancestors(self, sha: str) -> set[str]:
        seen: set[str] = set()
        queue = [sha]
        while queue:
            current = queue.pop()
            if current in seen or current not in self.commits:
                continue
            seen.add(current)
            queue.extend(self.commits[current]["parents"])
        return seen

    def get_content(self, token: str, repo: str, path: str, ref: str = DEFAULT_BRANCH) -> dict[str, Any]:
        full = _ref(ref)

        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "contents", "read")
            sha = self.repos[repo]["refs"].get(full)
            if sha is None or path not in self.commits[sha]["tree"]:
                raise GitHubError(404, "Not Found")
            text = self.commits[sha]["tree"][path]
            return 200, {"type": "file", "path": path, "sha": _blob_sha(text), "encoding": "base64",
                         "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}
        return self._call("GET", f"/repos/{repo}/contents/{path}", token, work)

    def create_or_update_file(self, token: str, repo: str, path: str, message: str, content: str, branch: str,
                              sha: str | None = None) -> dict[str, Any]:
        """PUT contents: "Contents" write, and "Workflows" write too under .github/workflows/ (A.1)."""
        full = _ref(branch)

        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "contents", "write", path=path)
            parent = self.repos[repo]["refs"].get(full)
            if parent is None:
                raise GitHubError(404, "Branch not found")
            refusal = self._push_refusal(repo, full)
            if refusal:
                raise GitHubError(403, refusal)
            tree = dict(self.commits[parent]["tree"])
            existing = tree.get(path)
            if existing is not None and sha != _blob_sha(existing):
                raise GitHubError(409, f"{path} does not match {sha}")
            if existing is None and sha is not None:
                raise GitHubError(422, f"{path} does not exist")
            tree[path] = content
            commit = self._commit(repo, full, tree, message, identity["login"], [parent])
            self._on_push(repo, full, commit)
            return (200 if existing is not None else 201), {
                "content": {"path": path, "sha": _blob_sha(content)},
                "commit": {"sha": commit, "message": message, "author": {"name": identity["login"]}}}
        return self._call("PUT", f"/repos/{repo}/contents/{path}", token, work)

    def _pull(self, repo: str, number: int) -> dict[str, Any]:
        pr = self.pulls.get(number)
        if pr is None or pr["base"]["repo"]["full_name"] != repo:
            raise GitHubError(404, "Not Found")
        return pr

    def create_pull(self, token: str, repo: str, title: str, body: str, head: str, base: str = DEFAULT_BRANCH,
                    draft: bool = False) -> dict[str, Any]:
        """POST pulls: "Pull requests" write on the base. The fake lets an installation that cannot see the head's
        repository open a pull request from it, which no GitHub page settles for a private fork (A.11, F)."""
        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "pull_requests", "write")
            head_repo, head_branch = self._resolve_head(repo, head)
            head_sha = self.repos[head_repo]["refs"].get(_ref(head_branch))
            base_sha = self.repos[repo]["refs"].get(_ref(base))
            if head_sha is None or base_sha is None:
                raise GitHubError(422, "Validation Failed: the head or the base branch does not exist")
            label = f"{head_repo.split('/')[0]}:{head_branch}"
            for pr in self.pulls.values():
                if pr["state"] == "open" and pr["head"]["label"] == label and pr["base"]["ref"] == base:
                    raise GitHubError(422, f"A pull request already exists for {label}.")
            if head_sha == base_sha:
                raise GitHubError(422, f"No commits between {base} and {label}")
            number = self.next_pull
            self.next_pull += 1
            pr = {
                "number": number, "state": "open", "title": title, "body": body, "draft": draft, "merged": False,
                "user": {"login": identity["login"], "type": identity["type"]},
                "head": {"label": label, "ref": head_branch, "sha": head_sha, "repo": {"full_name": head_repo}},
                "base": {"label": f"{repo.split('/')[0]}:{base}", "ref": base, "sha": base_sha, "repo": {"full_name": repo}},
                "html_url": f"https://github.example/{repo}/pull/{number}",
                "created_at": self._stamp(), "updated_at": self._stamp(), "closed_at": None, "merged_at": None,
                "merged_by": None, "merge_commit_sha": None, "maintainer_can_modify": True,
            }
            self.pulls[number] = pr
            self.reviews[number] = []
            return 201, json.loads(json.dumps(pr))
        return self._call("POST", f"/repos/{repo}/pulls", token, work)

    def list_pulls(self, token: str, repo: str, state: str = "open", head: str | None = None,
                   base: str | None = None) -> list[dict[str, Any]]:
        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "pull_requests", "read")
            if state not in ("open", "closed", "all"):
                raise GitHubError(422, "state must be open, closed, or all")
            out = [pr for pr in self.pulls.values() if pr["base"]["repo"]["full_name"] == repo
                   and (state == "all" or pr["state"] == state)
                   and (head is None or pr["head"]["label"] == head)
                   and (base is None or pr["base"]["ref"] == base)]
            out.sort(key=lambda pr: pr["number"], reverse=True)
            return 200, json.loads(json.dumps(out))
        return self._call("GET", f"/repos/{repo}/pulls", token, work)

    def get_pull(self, token: str, repo: str, number: int) -> dict[str, Any]:
        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "pull_requests", "read")
            return 200, json.loads(json.dumps(self._pull(repo, number)))
        return self._call("GET", f"/repos/{repo}/pulls/{number}", token, work)

    def update_pull(self, token: str, repo: str, number: int, title: str | None = None, body: str | None = None,
                    state: str | None = None) -> dict[str, Any]:
        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "pull_requests", "write")
            pr = self._pull(repo, number)
            if pr["merged"] and state is not None:
                raise GitHubError(422, "A merged pull request cannot be reopened or closed")
            if title is not None:
                pr["title"] = title
            if body is not None:
                pr["body"] = body
            if state == "closed" and pr["state"] == "open":
                pr["state"], pr["closed_at"] = "closed", self._stamp()
            elif state == "open" and pr["state"] == "closed":
                pr["state"], pr["closed_at"] = "open", None
            elif state not in (None, "open", "closed"):
                raise GitHubError(422, "state must be open or closed")
            pr["updated_at"] = self._stamp()
            return 200, json.loads(json.dumps(pr))
        return self._call("PATCH", f"/repos/{repo}/pulls/{number}", token, work)

    def _changed_files(self, pr: dict[str, Any]) -> list[dict[str, Any]]:
        before = self.commits[pr["base"]["sha"]]["tree"]
        after = self.commits[pr["head"]["sha"]]["tree"]
        out = []
        for path in sorted(set(before) | set(after)):
            old, new = before.get(path), after.get(path)
            if old == new:
                continue
            status = "added" if old is None else "removed" if new is None else "modified"
            old_lines, new_lines = (old or "").splitlines(), (new or "").splitlines()
            patch = "\n".join(difflib.unified_diff(old_lines, new_lines, lineterm="", n=3))
            additions = sum(1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
            deletions = sum(1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---"))
            out.append({"filename": path, "status": status, "additions": additions, "deletions": deletions,
                        "changes": additions + deletions, "patch": patch})
        return out

    def list_pull_files(self, token: str, repo: str, number: int) -> list[dict[str, Any]]:
        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "pull_requests", "read")
            return 200, self._changed_files(self._pull(repo, number))
        return self._call("GET", f"/repos/{repo}/pulls/{number}/files", token, work)

    def _counts(self, identity: dict[str, Any], repo: str, pr: dict[str, Any]) -> tuple[bool, str | None]:
        """Whether a review counts toward the ruleset's required approvals (A.3): a person with write
        access who is not the author. An App's review is recorded and counts for nothing here: GitHub counts
        people with write access and says nothing of another App's approval (A.8.1), and the code owner's
        approval is required in any case."""
        if identity["type"] == "Bot":
            return False, "an App's review does not count here: only people with write access count toward required approvals"
        if identity["login"] == pr["user"]["login"]:
            return False, "the author's own review never counts"
        if self._user_level(identity["login"], repo) < LEVELS["write"]:
            return False, "no write access to the repository"
        return True, None

    def create_review(self, token: str, repo: str, number: int, event: str, body: str = "") -> dict[str, Any]:
        """POST pulls/{n}/reviews: "Pull requests" write for an App; a person needs only read access, and
        an approval from one without write access is recorded and does not count (A.3)."""
        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "pull_requests", "write", user_level="read")
            pr = self._pull(repo, number)
            states = {"APPROVE": "APPROVED", "REQUEST_CHANGES": "CHANGES_REQUESTED", "COMMENT": "COMMENTED"}
            if event not in states:
                raise GitHubError(422, "event must be APPROVE, REQUEST_CHANGES, or COMMENT")
            if pr["state"] != "open":
                raise GitHubError(422, "The pull request is not open")
            if event == "APPROVE" and identity["login"] == pr["user"]["login"]:
                raise GitHubError(422, OWN_APPROVAL)  # "Pull request authors cannot approve their own pull requests"
            counts, reason = self._counts(identity, repo, pr)
            review = {"id": self.next_review, "user": {"login": identity["login"], "type": identity["type"]},
                      "state": states[event], "body": body, "commit_id": pr["head"]["sha"], "submitted_at": self._stamp(),
                      "dismissed": False, "dismissal_reason": None,
                      "counts_toward_requirements": counts and event == "APPROVE", "does_not_count_because": reason}
            self.next_review += 1
            self.reviews.setdefault(number, []).append(review)
            return 200, dict(review)
        return self._call("POST", f"/repos/{repo}/pulls/{number}/reviews", token, work)

    def list_reviews(self, token: str, repo: str, number: int) -> list[dict[str, Any]]:
        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "pull_requests", "read")
            self._pull(repo, number)
            return 200, json.loads(json.dumps(self.reviews.get(number, [])))
        return self._call("GET", f"/repos/{repo}/pulls/{number}/reviews", token, work)

    def create_check_run(self, token: str, repo: str, name: str, head_sha: str, conclusion: str = "success") -> dict[str, Any]:
        """POST repos/{owner}/{repo}/check-runs: a completed check run on a commit, "Checks" write, an App's call
        only. For a pull request from a fork the workflow runs in the base repository, so its check runs are the
        base's, on the head commit the network shares."""
        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            if identity["type"] != "Bot":
                raise GitHubError(403, "Only a GitHub App can create a check run")
            self._permit(identity, repo, "checks", "write")
            if head_sha not in self.commits:
                raise GitHubError(422, "No commit found for SHA: " + head_sha)
            run = {"id": self.next_check, "name": name, "head_sha": head_sha, "status": "completed", "conclusion": conclusion,
                   "app": {"id": identity["app_id"], "slug": identity["app"]}, "repository": repo, "completed_at": self._stamp()}
            self.next_check += 1
            self.check_runs.append(run)
            return 201, dict(run)
        return self._call("POST", f"/repos/{repo}/check-runs", token, work)

    # --- the merge ----------------------------------------------------------------------------------------------------

    def _owners_of(self, path: str) -> list[str]:
        """CODEOWNERS of the upstream's base branch (the file that governs a pull request from a fork, A.4);
        the last matching pattern wins."""
        main = self.repos[UPSTREAM]["refs"].get(_ref(DEFAULT_BRANCH))
        text = self.commits[main]["tree"].get("CODEOWNERS", "") if main else ""
        owners: list[str] = []
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            pattern, *names = line.split()
            if pattern == "*" or (pattern.startswith("/") and ("/" + path).startswith(pattern)) \
                    or (pattern.startswith("*.") and path.endswith(pattern[1:])):
                owners = [n.lstrip("@") for n in names]
        return owners

    def _is_owner(self, login: str, owners: list[str]) -> bool:
        return any(login == owner or login in TEAMS.get(owner, []) for owner in owners)

    def _check_passed(self, repo: str, sha: str, context: str, integration_id: int | None) -> bool:
        """Whether the latest check run named `context` on the commit, from the pinned App when the rule names one,
        concluded in success. A run from any other source does not count (A.12.3)."""
        runs = [r for r in self.check_runs if r["repository"] == repo and r["head_sha"] == sha and r["name"] == context
                and (integration_id is None or r["app"]["id"] == integration_id)]
        return bool(runs) and runs[-1]["conclusion"] == "success"

    def merge_blockers(self, number: int) -> list[str]:
        """Why the ruleset refuses the merge now, in GitHub's sentences; empty when it would go through."""
        pr = self.pulls[number]
        base_repo, base_ref = pr["base"]["repo"]["full_name"], _ref(pr["base"]["ref"])
        rules = [rule for _, rule in self._rules_for(base_repo, base_ref)]
        approvals = [r for r in self.reviews.get(number, []) if r["state"] == "APPROVED" and r["counts_toward_requirements"]]
        reasons = []
        for rule in (r["parameters"] for r in rules if r["type"] == "pull_request"):
            if len(approvals) < rule["required_approving_review_count"]:
                reasons.append(f"At least {rule['required_approving_review_count']} approving review is required by "
                               "reviewers with write access.")
            if rule["require_code_owner_review"]:
                for file in self._changed_files(pr):
                    owners = self._owners_of(file["filename"])
                    if owners and not any(self._is_owner(r["user"]["login"], owners) for r in approvals):
                        reasons.append(f"Review required from code owners of {file['filename']} ({', '.join('@' + o for o in owners)}).")
                        break
            if rule["require_last_push_approval"]:
                head = pr["head"]
                pusher = self.repos[head["repo"]["full_name"]]["pushers"].get(_ref(head["ref"]))
                if not any(r["user"]["login"] != pusher for r in approvals):
                    reasons.append("The most recent push must be approved by someone other than the person who pushed it.")
        for rule in (r["parameters"] for r in rules if r["type"] == "required_status_checks"):
            for check in rule["required_status_checks"]:
                if not self._check_passed(base_repo, pr["head"]["sha"], check["context"], check.get("integration_id")):
                    reasons.append(f'Required status check "{check["context"]}" is expected.')
        return reasons

    def merge_pull(self, token: str, repo: str, number: int, commit_title: str | None = None) -> dict[str, Any]:
        """PUT pulls/{n}/merge: a "Contents" write on the base repository (A.1), then the ruleset."""
        def work(identity: dict[str, Any]) -> tuple[int, Any]:
            self._permit(identity, repo, "contents", "write")
            pr = self._pull(repo, number)
            if pr["state"] != "open":
                raise GitHubError(405, "Pull Request is not mergeable: it is not open")
            blockers = self.merge_blockers(number)
            if blockers:
                raise GitHubError(405, " ".join(blockers))
            base_ref = _ref(pr["base"]["ref"])
            parent = self.repos[repo]["refs"][base_ref]
            tree = dict(self.commits[parent]["tree"])
            tree.update(self.commits[pr["head"]["sha"]]["tree"])
            for path in self._changed_files(pr):
                if path["status"] == "removed":
                    tree.pop(path["filename"], None)
            message = commit_title or f"Merge pull request #{number} from {pr['head']['label']}"
            sha = self._commit(repo, base_ref, tree, message, identity["login"], [parent, pr["head"]["sha"]])
            pr.update(state="closed", merged=True, merged_at=self._stamp(), closed_at=self._stamp(), updated_at=self._stamp(),
                      merged_by={"login": identity["login"], "type": identity["type"]}, merge_commit_sha=sha)
            return 200, {"sha": sha, "merged": True, "message": "Pull Request successfully merged"}
        return self._call("PUT", f"/repos/{repo}/pulls/{number}/merge", token, work)

    # --- the store -------------------------------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {"now": self.now.isoformat(), "apps": self.apps, "rulesets": self.rulesets, "commits": self.commits,
                "repos": self.repos, "pulls": {str(n): pr for n, pr in self.pulls.items()},
                "reviews": {str(n): r for n, r in self.reviews.items()}, "check_runs": self.check_runs,
                "log": self.log, "next_pull": self.next_pull, "next_review": self.next_review, "next_check": self.next_check,
                "counter": self.counter}

    @classmethod
    def from_dict(cls, data: dict[str, Any], now: datetime | None = None, path: Path | None = None) -> "GitHubFake":
        fake = cls(now or datetime.fromisoformat(data["now"]), path)
        fake.commits, fake.repos, fake.log = data["commits"], data["repos"], data["log"]
        fake.pulls = {int(n): pr for n, pr in data["pulls"].items()}
        fake.reviews = {int(n): r for n, r in data["reviews"].items()}
        fake.next_pull, fake.next_review, fake.counter = data["next_pull"], data["next_review"], data["counter"]
        # A store written before the reader review's changes holds no installations, rulesets, or check runs: the defaults.
        fake.apps = data.get("apps") or fake.apps
        fake.rulesets = data.get("rulesets") or fake.rulesets
        fake.check_runs = data.get("check_runs") or []
        fake.next_check = data.get("next_check", fake.next_check)
        return fake

    def save(self, path: Path | None = None) -> None:
        target = path or self.path
        if target is None:
            raise RuntimeError("no path to save the GitHub fake to")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=target.name, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=1, sort_keys=True)
        os.replace(tmp, target)

    @classmethod
    def load(cls, path: Path, now: datetime | None = None) -> "GitHubFake":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")), now, path)

    def _persist(self) -> None:
        if self.path is not None:
            self.save()


def seed_platform_infra(fake: GitHubFake, workspaces: tuple[str, ...] | None = None) -> str:
    """The upstream's `main`: the fixture modules under live/<workspace>/ (the layout the state keys mirror),
    CODEOWNERS, and the validate workflow; the fork's `main` at the same commit, as a fork synced by its
    owner is. Returns the commit."""
    import validate  # the fixture modules (detect/validate.py); imported here so the fake stays importable alone
    tree = {"CODEOWNERS": CODEOWNERS, ".github/workflows/validate.yml": VALIDATE_WORKFLOW,
            "README.md": "# platform-infra\n\nLarkspur Mutual's Terraform, one workspace per folder under live/.\n"}
    for workspace in workspaces or validate.WORKSPACES:
        for relative, text in validate.module_files(workspace).items():
            tree[f"live/{workspace}/{relative}"] = text
    sha = fake._commit(UPSTREAM, _ref(DEFAULT_BRANCH), tree, "Import platform-infra", "tomasz.nowak", [])
    fake.repos[FORK]["refs"][_ref(DEFAULT_BRANCH)] = sha
    fake.repos[FORK]["pushers"][_ref(DEFAULT_BRANCH)] = BOT_USER
    fake._persist()
    return sha


def report_check(fake: GitHubFake, number: int, conclusion: str = "success", name: str = VALIDATE_CHECK) -> dict[str, Any]:
    """What the upstream's validate workflow does on a pull request: GitHub Actions runs the job and reports it
    as a check run on the pull request's head commit, in the base repository."""
    pr = fake.pulls[number]
    return fake.create_check_run(fake.installation_token(GITHUB_ACTIONS_APP), pr["base"]["repo"]["full_name"], name,
                                 pr["head"]["sha"], conclusion)


def open_store(path: Path | None = None, now: datetime = NIGHT) -> GitHubFake:
    """The fake behind GITHUB_STATE_FILE (or `path`): loaded when the file exists, seeded otherwise."""
    target = path or Path(os.environ.get("GITHUB_STATE_FILE", "").strip() or "")
    if not str(target):
        raise RuntimeError("GITHUB_STATE_FILE is not set")
    if target.exists():
        return GitHubFake.load(target, now)
    fake = GitHubFake(now, target)
    seed_platform_infra(fake)
    return fake
