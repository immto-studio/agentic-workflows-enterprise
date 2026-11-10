"""What a field allows, checked before a diff template copies an account's value into it.

Chapter 14, W5-D8 and W5-D12, and the follow-up to chapter 15's red-team (companion #109, issue #12). The
templates copy a few values from the account into a pull request's diff, and those are the ones a person or a
client can write: tag keys and values, a security group's name and description, its rules' descriptions, a
snapshot's description, and a load balancer's name. The red-team moved planted text into four of them, and
both models' runs carried it into the diff. render.py now passes each such value through a `Screen` first. A
value its field allows goes into the diff as before. A value that fails stays out: W5's own placeholder, HELD,
takes its place (a tag key that fails is left out), the screen keeps it, and the writer lists it in the pull
request's facts block, quoted as data read from the account (pull_requests.compose_body). The finding is still
raised.

What each field allows:

- A tag key: the tagging API's characters (letters, digits, spaces, and _ . : / = + @ -), 1 to 128 of them,
  in ASCII.
- A tag value: one of the tagging standard's values where the finding carries them for its key (an untagged
  finding's `allowed`, which the detectors read from the standard: env's five), and otherwise the tagging API's
  characters, 0 to 256 of them, in ASCII.
- A name or a description: printable ASCII, from the space to the tilde, so no line break, no control
  character, no zero-width space, and no look-alike letter from another script; at most 255 characters.
- And none of them may read as an instruction (INSTRUCTION): words that address an automated reader or "you",
  that tell a reader what to do with the drift or the findings, or that claim what only a person or a process
  decides, such as an approval. A tag value the standard lists is never one of those.

The rest of what a template copies from the account is checked nowhere here, and needs no check: AWS assigns
and validates the ids, the Availability Zones, the types, the CIDR blocks and route targets, the ports and the
sizes, so no one can write text into them. A value from the Terraform state is the code's own record, and the
tagging standard is FinOps' policy; neither is the account's to write.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

__all__ = ["HELD", "MAX_TAG_KEY", "MAX_TAG_VALUE", "MAX_TEXT", "INSTRUCTION", "Held", "Screen", "tag_key_fails",
           "tag_value_fails", "text_fails"]

HELD = "TODO: held out of the diff"  # what the diff carries in a failing value's place: W5's words, which a tag value allows
MAX_TAG_KEY = 128  # the tagging API's limits
MAX_TAG_VALUE = 256
MAX_TEXT = 255  # a security group's name and description and a rule's description, as EC2 bounds them
_TAG_CHARS = re.compile(r"^[A-Za-z0-9 _.:/=+@-]*$")
_PRINTABLE = re.compile(r"^[\x20-\x7e]*$")
# Text that reads as an instruction, as whole words in any case. Each group is a way the planted texts and their
# red-team variants address the agent; none of the fixtures' own names, descriptions, or tag values uses one.
_INSTRUCTION_WORDS = (
    # It addresses a reader: an automated one, or "you".
    r"(?:to|for) (?:the |this |any |an? )?(?:[a-z-]+ )?(?:agents?|assistants?|bots?|models?|ais?|llms?)",
    r"automated readers?", r"system (?:notes?|prompts?|messages?)", r"(?:previous|prior|above|earlier) instructions?",
    r"you", r"your",
    # It tells the reader what to do with the drift or the findings.
    r"ignor(?:e|es|ed|ing)", r"disregard\w*", r"skip (?:this|the|it|all|every|any)", r"exclude (?:this|the|it|all|every|any)",
    r"decode", r"(?:report|flag|say|raise) (?:nothing|no)", r"open no", r"read (?:this )?before",
    # It claims what only a person or a process decides.
    r"approv\w*", r"cleared", r"signed off", r"authori[sz]ed", r"exempt\w*", r"reconciled", r"confirmed",
)
INSTRUCTION = re.compile(r"\b(?:" + "|".join(_INSTRUCTION_WORDS) + r")\b", re.IGNORECASE)


def _instruction(value: str) -> list[str]:
    return ["reads as an instruction"] if INSTRUCTION.search(value) else []


def tag_key_fails(key: Any) -> list[str]:
    """Why a tag key may not go into a diff, or nothing."""
    if not isinstance(key, str):
        return ["not text"]
    reasons = []
    if not 1 <= len(key) <= MAX_TAG_KEY:
        reasons.append(f"not 1 to {MAX_TAG_KEY} characters")
    if not _TAG_CHARS.match(key):
        reasons.append("characters a tag key doesn't allow")
    return reasons + _instruction(key)


def tag_value_fails(key: str, value: Any, allowed: dict[str, list[str]] | None = None) -> list[str]:
    """Why a tag value may not go into a diff, or nothing: the standard's values where it lists them for the key,
    and the tagging API's pattern elsewhere."""
    if not isinstance(value, str):
        return ["not text"]
    values = (allowed or {}).get(key)
    if values:
        return [] if value in values else [f"not one of the values the tagging standard allows for {key}"]
    reasons = []
    if len(value) > MAX_TAG_VALUE:
        reasons.append(f"longer than {MAX_TAG_VALUE} characters")
    if not _TAG_CHARS.match(value):
        reasons.append("characters a tag value doesn't allow")
    return reasons + _instruction(value)


def text_fails(value: Any) -> list[str]:
    """Why a name or a description may not go into a diff, or nothing."""
    if not isinstance(value, str):
        return ["not text"]
    reasons = []
    if len(value) > MAX_TEXT:
        reasons.append(f"longer than {MAX_TEXT} characters")
    if not _PRINTABLE.match(value):
        reasons.append("not printable ASCII on one line")
    return reasons + _instruction(value)


@dataclass(frozen=True)
class Held:
    """A value read from the account that stayed out of a diff: the field it sits in, which one (a tag's key, a
    rule), the value as it was read, and why."""
    field: str
    where: str
    value: Any
    reasons: tuple[str, ...]


class Screen:
    """One rendering's checks. Each returns the value when its field allows it, and otherwise keeps it and returns
    HELD, so the template puts W5's placeholder in its place and never the value; a tag whose key fails is left
    out of the map whole and kept with its value."""

    def __init__(self, allowed: dict[str, list[str]] | None = None) -> None:
        self.allowed = dict(allowed or {})
        self._held: dict[str, Held] = {}

    @property
    def held(self) -> tuple[Held, ...]:
        return tuple(self._held.values())

    def _keep(self, field: str, where: str, value: Any, reasons: list[str]) -> None:
        mark = json.dumps([field, where, value], sort_keys=True, default=str)
        self._held.setdefault(mark, Held(field, where, value, tuple(reasons)))

    def text(self, field: str, value: Any, where: str = "") -> Any:
        """A name or a description."""
        reasons = text_fails(value)
        if reasons:
            self._keep(field, where, value, reasons)
            return HELD
        return value

    def tag_value(self, key: str, value: Any) -> Any:
        reasons = tag_value_fails(key, value, self.allowed)
        if reasons:
            self._keep("tag", key, value, reasons)
            return HELD
        return value

    def tags(self, tags: dict[str, Any]) -> dict[str, Any]:
        """A tags map as a template may write it: a tag whose key fails left out, a failing value as HELD."""
        out: dict[str, Any] = {}
        for key, value in tags.items():
            reasons = tag_key_fails(key)
            if reasons:
                self._keep("tag", str(key), value, [f"its key: {reason}" for reason in reasons])
                continue
            out[key] = self.tag_value(key, value)
        return out
