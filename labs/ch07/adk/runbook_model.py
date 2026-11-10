"""A rule-based stand-in for Gemini, so the approval tests run with no account and no model.

Chapter 7. The model does what the incident workflow's model does at its first write: it asks for
one restart, then answers from whatever came back. With an approval tool on offer it asks for
approval first and calls the write tool with the approval's number once a yes arrives. It reads
only the conversation ADK sends it, so the tests exercise ADK's own handling of tool calls,
pauses, and resumes, not a shortcut around them.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

APPROVAL_TOOL = "request_approval"
WRITE_TOOL = "restart_deployment"
RESTART = {"namespace": "claims", "deployment": "claims-api"}


def latest_result(contents: list[types.Content], tool: str) -> dict[str, Any] | None:
    """The newest function response for `tool` in the conversation, or None before the call."""
    for content in reversed(contents):
        for part in content.parts or []:
            if part.function_response and part.function_response.name == tool:
                return dict(part.function_response.response or {})
    return None


def answer_for(result: dict[str, Any]) -> str:
    """What the model says once a tool has answered, in the words an engineer would read."""
    status = result.get("status")
    if status == "pending":
        return f"Restart of claims-api is waiting for approval {result.get('approval_id')}."
    if status == "restarted":
        return f"Restarted claims-api in claims ({result.get('change')})."
    if status in ("rejected", "refused"):
        return f"claims-api was not restarted: {result.get('reason', 'the approver said no')}."
    # ADK's own refusal when a confirmation is declined arrives as an error, not a status
    return f"claims-api was not restarted: {result.get('error', result)}."


def call(name: str, args: dict[str, Any]) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


class RunbookModel(BaseLlm):
    """Asks for the restart (through approval when it can), then answers from the newest result."""

    model: str = "larkspur-rule-model"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        approval = latest_result(llm_request.contents, APPROVAL_TOOL)
        write = latest_result(llm_request.contents, WRITE_TOOL)
        if write is not None:
            part = types.Part(text=answer_for(write))
        elif approval is None and APPROVAL_TOOL in llm_request.tools_dict:
            part = call(APPROVAL_TOOL, {"action": WRITE_TOOL, **RESTART})
        elif approval is None:
            part = call(WRITE_TOOL, dict(RESTART))
        elif approval.get("status") == "approved":
            part = call(WRITE_TOOL, {**RESTART, "approval_id": approval["approval_id"]})
        else:
            part = types.Part(text=answer_for(approval))
        yield LlmResponse(content=types.Content(role="model", parts=[part]), turn_complete=True)
