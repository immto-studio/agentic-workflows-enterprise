"""The judge (E-D4): one rubric for each workflow's prose, read by a model through chapter 5's gateway.

Chapter 15, step 3 (companion #13). The deterministic and trajectory layers decide what a rule can; the judge
reads only the prose they can't: a W1 answer's faithfulness to its sources, a W2 answer, a W3 triage, a W4
rationale, and the title and prose of a W5 pull request (E-D3). This module is one judgement:

  the prompt    prompt.txt: the judge's system prompt, then the frame of the user message, the same for
                every workflow
  a rubric      rubrics/<workflow>.yaml: the criteria, each with where the workflow's README, scorer, or
                harness already says it; each has a `when`, and the judge reads the ones that hold for the case
  the request   chapter 5's gateway at temperature 0, tagged with the evaluated workflow and the case's data
                class, under a trace id of its own (W5's prose seam's shape); a Restricted case goes to
                larkspur-chat-restricted and every other case to larkspur-chat, the alias chapter 2's grid
                allows it (`alias_for`)
  the parse     two lines, `VERDICT: right` or `VERDICT: wrong`, then `REASON: ` and text. Whitespace is not
                content: the reply's ends, each line's ends, and empty lines are dropped. Anything else is
                unparsable, recorded with its cause, and never read as a verdict.

The prompt file and the rubric file are hashed into every result (registry.sha256_of, CRLF read as LF), and so
is each rendered request (`messages_sha256`), so a result says exactly what its judge read.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

HERE = Path(__file__).resolve().parent
PROMPT = HERE / "prompt.txt"
RUBRICS = HERE / "rubrics"
USER_MARK = "==== user ===="
ALIAS = "larkspur-chat"
# A Restricted prompt may reach only the self-hosted model (chapter 2's grid, chapter 5's gateway_rules), so a
# Restricted case's judgement goes to the restricted alias, as W1's and W3's own Restricted calls do. In a judge's
# gateway both aliases serve the judge's model (run_judge refuses a config where they differ).
RESTRICTED_ALIAS = "larkspur-chat-restricted"
TEMPERATURE = 0
# gpt-oss-20b reasons before it answers, and W5's step 5 measured 8192 as the budget its replies fit in;
# Gemma 4 12B runs with thinking off and uses a fraction of it.
MAX_TOKENS = 8192
TIMEOUT_S = 300.0  # the gateway configs' own timeout
VERDICTS = ("right", "wrong")
JUDGED = ("w1", "w2", "w3", "w4", "w5")  # E-D3: the workflows whose prose a rule can't decide
# The conditions a criterion's `when` may name, per workflow; items.py says which hold for a case.
CONDITIONS: dict[str, tuple[str, ...]] = {
    "w1": ("always", "answerable", "denied", "stale", "injection"),
    "w2": ("always", "facts", "answer", "refusal", "injection"),
    "w3": ("always", "facts", "answer", "refusal", "injection"),
    "w4": ("always",),
    "w5": ("always", "attribution", "no_attribution", "saving", "no_saving"),
}
_VERDICT_LINE = re.compile(r"VERDICT: (right|wrong)")
_REASON = "REASON: "


# --- the prompt and the rubrics ------------------------------------------------------------------------------

def load_prompt(path: Path = PROMPT) -> tuple[str, str]:
    """(the system prompt, the user message's frame with {title}, {criteria}, {reference}, {output})."""
    text = path.read_text(encoding="utf-8")
    system, mark, user = text.partition("\n" + USER_MARK + "\n")
    if not mark:
        raise ValueError(f"{path.name} has no {USER_MARK!r} line")
    return system.strip(), user.strip()


def load_rubric(workflow: str, folder: Path = RUBRICS) -> dict[str, Any]:
    """The workflow's rubric, checked: every criterion has an id, a `when` its workflow knows, a text, and a
    `from` that says where the workflow already says it."""
    data = yaml.safe_load((folder / f"{workflow}.yaml").read_text(encoding="utf-8"))
    if data.get("workflow") != workflow or not str(data.get("title") or "").strip():
        raise ValueError(f"{workflow}.yaml: the workflow or the title is wrong")
    ids = [c.get("id") for c in data.get("criteria") or []]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError(f"{workflow}.yaml: no criteria, or two with one id")
    for c in data["criteria"]:
        if c.get("when") not in CONDITIONS[workflow]:
            raise ValueError(f"{workflow}.yaml: {c.get('id')}: `when` is {c.get('when')!r}")
        if not str(c.get("text") or "").strip() or not str(c.get("from") or "").strip():
            raise ValueError(f"{workflow}.yaml: {c.get('id')}: a criterion needs its text and where it comes from")
    return data


def criteria_for(rubric: dict[str, Any], conditions: tuple[str, ...]) -> list[dict[str, Any]]:
    """The rubric's criteria whose `when` holds for the case, in the rubric's order."""
    return [c for c in rubric["criteria"] if c["when"] in conditions]


def _flat(text: str) -> str:
    return " ".join(str(text).split())


def _inside(text: str, tag: str) -> str:
    """Text as the judge reads it between its tags. A closing tag inside it is broken, so the text cannot end
    the block it sits in."""
    return (text or "").replace(f"</{tag}>", f"</ {tag}>").strip()


def render(prompt: tuple[str, str], rubric: dict[str, Any], conditions: tuple[str, ...], reference: str,
           output: str) -> list[dict[str, str]]:
    """The two messages the judge reads for one output."""
    system, frame = prompt
    chosen = criteria_for(rubric, conditions)
    criteria = "\n".join(f"{n}. {_flat(c['text'])}" for n, c in enumerate(chosen, 1))
    user = frame.format(title=_flat(rubric["title"]), criteria=criteria, reference=_inside(reference, "reference"),
                        output=_inside(output, "output"))
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def messages_sha256(messages: list[dict[str, str]]) -> str:
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


# --- the request ------------------------------------------------------------------------------------------------

def new_trace_id() -> str:
    """32 lowercase hex characters: a join key for the gateway's log and a valid OpenTelemetry trace id."""
    return uuid.uuid4().hex


def alias_for(data_class: str) -> str:
    """The alias a judgement of a case of this class goes to: the restricted one for Restricted, else the chat one."""
    return RESTRICTED_ALIAS if data_class == "restricted" else ALIAS


def request(messages: list[dict[str, str]], tag: str, data_class: str, trace_id: str,
            max_tokens: int = MAX_TOKENS) -> dict[str, Any]:
    """The Chat Completions body. Chapter 5's hooks read the workflow and the class from the tags and the trace
    id from the metadata, apply the manifest and the data-class grid, and log the call under the trace id."""
    return {"model": alias_for(data_class), "temperature": TEMPERATURE, "max_tokens": max_tokens,
            "metadata": {"tags": [f"workflow:{tag}", f"data_class:{data_class}"], "trace_id": trace_id},
            "messages": messages}


def ask(client: httpx.Client, base: str, key: str, body: dict[str, Any]) -> dict[str, Any]:
    """One call through the gateway: the reply's content, or the error. Never raises: a failed call is a
    result to record, like an unparsable reply."""
    started = time.perf_counter()

    def took() -> float:
        return round(time.perf_counter() - started, 2)

    try:
        response = client.post(base.rstrip("/") + "/chat/completions", json=body,
                               headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT_S)
    except httpx.HTTPError as exc:
        return {"content": None, "finish_reason": None, "error": f"{type(exc).__name__}: {exc}"[:300], "seconds": took()}
    if response.status_code != 200:
        return {"content": None, "finish_reason": None, "error": f"HTTP {response.status_code}: {response.text[:300]}",
                "seconds": took()}
    try:
        choice = response.json()["choices"][0]
        content = choice["message"].get("content")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        return {"content": None, "finish_reason": None, "error": f"unreadable response: {type(exc).__name__}",
                "seconds": took()}
    return {"content": content, "finish_reason": choice.get("finish_reason"), "error": None, "seconds": took()}


# --- the parse ----------------------------------------------------------------------------------------------------

def _unparsable(why: str) -> dict[str, Any]:
    return {"verdict": None, "reason": None, "unparsable": why}


def parse(text: str | None) -> dict[str, Any]:
    """The verdict and the reason from a reply in the prompt's form, or None and the cause. Strict: the two
    lines exactly, the labels in capitals, the verdict one of the two words in lower case."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return _unparsable("an empty reply")
    if len(lines) != 2:
        return _unparsable(f"{len(lines)} lines, where the form has 2")
    match = _VERDICT_LINE.fullmatch(lines[0])
    if not match:
        return _unparsable(f"the first line is not VERDICT: right or VERDICT: wrong: {lines[0][:80]!r}")
    if not lines[1].startswith(_REASON) or not lines[1][len(_REASON):].strip():
        return _unparsable(f"the second line is not REASON: and its text: {lines[1][:80]!r}")
    return {"verdict": match.group(1), "reason": lines[1][len(_REASON):].strip(), "unparsable": None}


def judge(client: httpx.Client, base: str, key: str, messages: list[dict[str, str]], tag: str,
          data_class: str, trace_id: str | None = None, max_tokens: int = MAX_TOKENS) -> dict[str, Any]:
    """One judgement: the request through the gateway, the reply parsed. The reply's text is kept only when it
    does not parse, so a result shows what was refused and no more."""
    trace_id = trace_id or new_trace_id()
    body = request(messages, tag, data_class, trace_id, max_tokens)
    reply = ask(client, base, key, body)
    parsed = parse(reply["content"]) if reply["error"] is None else {"verdict": None, "reason": None, "unparsable": None}
    return {"trace_id": trace_id, "alias": body["model"], "messages_sha256": messages_sha256(messages), **parsed,
            "reply": reply["content"] if parsed["unparsable"] else None, "error": reply["error"],
            "finish_reason": reply["finish_reason"], "seconds": reply["seconds"]}
