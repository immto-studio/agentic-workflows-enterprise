"""The sample service control policy (org/scp.json) the chapter describes, checked as written.

The lab can't apply an SCP, which belongs to the organization. These tests read the JSON: model calls
only from the model gateway's role, the embedding model also from knowledge bases' own roles, the
tool gateways' controls changed only by the pipeline, and the permission boundary kept in place.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parent.parent
SCP = json.loads((LAB / "org" / "scp.json").read_text(encoding="utf-8"))
TITAN = "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0"


def statement(sid: str) -> dict[str, Any]:
    (found,) = [s for s in SCP["Statement"] if s["Sid"] == sid]
    assert found["Effect"] == "Deny"
    return found


def exempt(s: dict[str, Any]) -> list[str]:
    return s["Condition"]["ArnNotLike"]["aws:PrincipalArn"]


def test_an_scp_is_deny_only_and_small_enough() -> None:
    assert all(s["Effect"] == "Deny" for s in SCP["Statement"])
    assert len(json.dumps(SCP, separators=(",", ":"))) <= 5120  # AWS's limit for one SCP


def test_chat_models_are_the_model_gateways_alone() -> None:
    chat = statement("ChatModelsThroughTheModelGatewayOnly")
    assert {"bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"} <= set(chat["Action"])
    assert chat["NotResource"] == [TITAN] and exempt(chat) == ["arn:aws:iam::*:role/llm-gateway"]


def test_the_embedding_model_adds_the_knowledge_bases_own_role_and_nobody_else() -> None:
    embed = statement("TheEmbeddingModelForTheGatewayAndKnowledgeBasesOnly")
    assert embed["Resource"] == [TITAN]
    assert exempt(embed) == ["arn:aws:iam::*:role/llm-gateway", "arn:aws:iam::*:role/*-knowledge-base"]


def test_every_switch_on_the_tool_gateway_is_the_pipelines() -> None:
    gateway = statement("TheToolGatewaysChangeThroughThePipelineOnly")
    for action in ("UpdateGateway", "UpdateGatewayTarget", "CreateGatewayTarget", "PutResourcePolicy",
                   "DeleteResourcePolicy", "UpdatePolicyEngine", "DeletePolicyEngine"):
        assert f"bedrock-agentcore:{action}" in gateway["Action"], action
    assert exempt(gateway) == ["arn:aws:iam::*:role/platform-pipeline"]


def test_the_boundary_stays_on_and_unchanged() -> None:
    create = statement("RolesMadeOutsideThePipelineCarryTheBoundary")
    assert set(create["Action"]) == {"iam:CreateRole", "iam:PutRolePermissionsBoundary"}
    assert create["Condition"]["StringNotLike"]["iam:PermissionsBoundary"].endswith("-agent-boundary")
    keep = statement("TheBoundaryBelongsToTheBaseline")
    assert {"iam:CreatePolicyVersion", "iam:DeleteRolePermissionsBoundary"} <= set(keep["Action"])
