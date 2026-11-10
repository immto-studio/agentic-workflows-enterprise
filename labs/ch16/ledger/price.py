"""Price the cost lines at chapter 6's design, and give the gateway the same prices.

Chapter 16, step 2 (companion #14, O-D5). A cost line is priced at the deployment that would serve its
alias in chapter 6's design (prices.yaml, `design`): larkspur-chat at Nova Lite through the Canadian
profile, called in ca-central-1; larkspur-chat-restricted at zero per token, since chapter 9's GPUs are
billed by the hour; larkspur-embed at Titan Text Embeddings V2. A fallback is priced at the deployment it
fell back to, in that deployment's own Region (`fallbacks`). A run's cost is the sum of its lines, and a
run whose lines kept no tokens has no cost (None), never zero. Arithmetic is in Decimal, so every machine
writes the same digits.

The same table loads into a LiteLLM deployment as custom prices, `input_cost_per_token` and
`output_cost_per_token` in `litellm_params`. `litellm_yaml` writes that shape for every priced
deployment, one `model_list` per gateway pair (ledger/litellm.prices.yaml), and `check_litellm` loads
each list into LiteLLM's Router in this process, answers one call per alias with a mocked response of
known usage, and reads the cost two ways: the `response_cost` the gateway's callback receives, and
`completion_cost` called with the deployment's id as the proxy calls it. It also asks LiteLLM's own
predicate whether the alias skips budget checks: a deployment priced at exactly zero does (fact sheet
8.1), which leaves the self-hosted alias with each manifest's request rate as its only stop.

What the cost lines don't carry: chapter 6 runs a Bedrock guardrail before and after every call on the
managed aliases, and it bills text units of up to 1,000 characters per policy, not tokens.
`guardrail_estimate` prices it from the line's tokens at LiteLLM's four characters a token, an estimate
the summary keeps apart from the cost lines.

Run (from labs/ch16):  python ledger/price.py --write-litellm      # regenerate ledger/litellm.prices.yaml
                       python ledger/price.py --check-litellm      # needs LITELLM_LOCAL_MODEL_COST_MAP=True
"""

from __future__ import annotations

import copy
import json
import math
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import costlines  # noqa: E402

PRICES = HERE / "prices.yaml"
LITELLM_YAML = HERE / "litellm.prices.yaml"
MILLION = Decimal(1_000_000)
SECTIONS = ("deployments", "gpu", "platform", "observability", "committed")
CHECK_USAGE = (1000, 100)  # the mocked call's input and output tokens


def load(path: Path = PRICES) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def entries(table: dict[str, Any]) -> list[dict[str, Any]]:
    """Every priced entry of the table, the guardrail included."""
    return [e for section in SECTIONS for e in table[section]] + [table["guardrail"]]


def by_id(table: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in entries(table)}


def dec(value: Any) -> Decimal:
    """A YAML number as the decimal it was written as."""
    return Decimal(str(value))


def deployment(table: dict[str, Any], alias: str) -> dict[str, Any]:
    """The deployment that serves the alias in chapter 6's design."""
    return by_id(table)[table["design"][alias]]


def serving_alias(table: dict[str, Any], line: costlines.CostLine) -> str:
    """The alias whose deployment served the line: its own, or the one it fell back to."""
    if not line.fallback:
        return line.alias
    if line.served_alias and line.served_alias != line.alias:
        return line.served_alias
    return table["fallbacks"][line.alias]


def per_token(per_million: Any) -> Decimal:
    return dec(per_million) / MILLION


def line_cost(table: dict[str, Any], line: costlines.CostLine) -> Decimal | None:
    if line.input_tokens is None or line.output_tokens is None:
        return None
    d = deployment(table, serving_alias(table, line))
    return line.input_tokens * per_token(d["input_per_million"]) + line.output_tokens * per_token(d["output_per_million"])


def run_cost(table: dict[str, Any], run: costlines.Run) -> Decimal | None:
    """The sum of the run's lines; None when the run kept no tokens."""
    costs = [line_cost(table, line) for line in run.lines]
    if any(c is None for c in costs):
        return None
    return sum(costs, Decimal(0))


def text_units(table: dict[str, Any], tokens: int) -> int:
    g = table["guardrail"]
    return math.ceil(tokens * g["characters_per_token"] / g["text_unit_characters"])


def guardrail_estimate(table: dict[str, Any], line: costlines.CostLine) -> Decimal | None:
    """The guardrail's cost for one call: the prompt's text units before it, the answer's after it, at the
    price of each policy chapter 6's guardrail applies. Zero on an alias the guardrail doesn't run on."""
    g = table["guardrail"]
    if serving_alias(table, line) not in g["applies_to"]:
        return Decimal(0)
    if line.input_tokens is None or line.output_tokens is None:
        return None
    per_unit = sum((dec(g["per_1000_text_units"][p]) for p in g["policies"]), Decimal(0)) / 1000
    units = text_units(table, line.input_tokens) + text_units(table, line.output_tokens)
    return units * per_unit


def run_guardrail(table: dict[str, Any], run: costlines.Run) -> Decimal | None:
    costs = [guardrail_estimate(table, line) for line in run.lines]
    if any(c is None for c in costs):
        return None
    return sum(costs, Decimal(0))


# --- the table as LiteLLM's custom prices -----------------------------------------------------------------

def litellm_model_lists(table: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Every priced deployment as a LiteLLM model_list entry, grouped by the gateway pair that serves it."""
    lists: dict[str, list[dict[str, Any]]] = {}
    for d in table["deployments"]:
        if d["gateway"] is None or d["input_per_million"] is None:
            continue
        info = {"id": d["id"], "region": d["region"]}
        if d.get("mode"):
            info["mode"] = d["mode"]
        lists.setdefault(d["gateway"], []).append({
            "model_name": d["alias"],
            "litellm_params": {"model": d["litellm_model"], **d["litellm_params"],
                               "input_cost_per_token": float(per_token(d["input_per_million"])),
                               "output_cost_per_token": float(per_token(d["output_per_million"]))},
            "model_info": info,
        })
    return lists


HEADER = """\
# Generated by ledger/price.py from ledger/prices.yaml (python ledger/price.py --write-litellm); a test
# fails when the two differ, so change prices.yaml and regenerate.
#
# The dated table as LiteLLM custom prices, one model_list per gateway pair: the part of each gateway's
# config that carries prices (chapter 6's AWS pair, chapter 8's Azure pair). Per-million prices become
# per-token ones. A deployment's custom price wins over LiteLLM's built-in map, which has no entry for the
# Canadian profile. The self-hosted alias is priced at exactly zero, which makes LiteLLM skip every budget
# check for it; its stop is each manifest's requests_per_minute. Credentials, timeouts, guardrails and the
# fallback chain stay in each gateway's own config (labs/ch06/gateway/litellm.aws.yaml). Gemini in Montréal
# has no price in any source, so it isn't here; LiteLLM would price it from its own map.
"""


def litellm_yaml(table: dict[str, Any]) -> str:
    body = {gateway: {"model_list": entries} for gateway, entries in litellm_model_lists(table).items()}
    return HEADER + yaml.safe_dump(body, sort_keys=False, width=120)


def write_litellm(table: dict[str, Any], path: Path = LITELLM_YAML) -> None:
    path.write_text(litellm_yaml(table), encoding="utf-8", newline="\n")


def check_litellm(table: dict[str, Any], usage: tuple[int, int] = CHECK_USAGE) -> list[dict[str, Any]]:
    """Load each gateway's model_list into LiteLLM's Router and price one mocked call per alias.

    LITELLM_LOCAL_MODEL_COST_MAP must be True before litellm is imported, or LiteLLM fetches the main
    branch's map; this function refuses to run otherwise. Nothing leaves the machine: every call is mocked."""
    if os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") != "True":
        raise RuntimeError("set LITELLM_LOCAL_MODEL_COST_MAP=True before importing litellm (fact sheet 8.1)")
    import litellm
    from litellm import ModelResponse, Router
    from litellm.proxy.auth.auth_checks import is_model_cost_zero
    from litellm.types.utils import Usage

    rows = []
    for gateway, model_list in litellm_model_lists(table).items():
        router = Router(model_list=copy.deepcopy(model_list))
        for entry in model_list:
            alias, params, info = entry["model_name"], entry["litellm_params"], entry["model_info"]
            d = by_id(table)[info["id"]]
            if info.get("mode") == "embedding":
                response = router.embedding(model=alias, input=["the lab's one sentence"], mock_response=[0.0])
                tokens = (response.usage.prompt_tokens, 0)
                by_id_cost = None
            else:
                mocked = ModelResponse(model=params["model"], usage=Usage(prompt_tokens=usage[0],
                                       completion_tokens=usage[1], total_tokens=sum(usage)))
                response = router.completion(model=alias, messages=[{"role": "user", "content": "one question"}],
                                             mock_response=mocked)
                tokens = (response.usage.prompt_tokens, response.usage.completion_tokens)
                by_id_cost = litellm.completion_cost(completion_response=response, model=params["model"],
                                                     custom_pricing=True, router_model_id=info["id"])
            expected = tokens[0] * per_token(d["input_per_million"]) + tokens[1] * per_token(d["output_per_million"])
            rows.append({
                "gateway": gateway, "alias": alias, "deployment": info["id"], "litellm_model": params["model"],
                "input_tokens": tokens[0], "output_tokens": tokens[1], "expected_usd": float(expected),
                "response_cost_usd": response._hidden_params.get("response_cost"),
                "completion_cost_usd": by_id_cost,
                "budget_checks_skipped": is_model_cost_zero(model=alias, llm_router=router),
            })
        if gateway == "aws":
            # The same Canadian deployment priced by its model name alone, now that the Router has
            # registered it: LiteLLM finds the empty entry the registration left and prices it at zero.
            mocked = ModelResponse(model="ca.amazon.nova-lite-v1:0", usage=Usage(prompt_tokens=usage[0],
                                   completion_tokens=usage[1], total_tokens=sum(usage)))
            name = by_id(table)[table["design"]["larkspur-chat"]]["litellm_model"]
            rows.append({"gateway": gateway, "alias": "larkspur-chat", "deployment": "(by name only)",
                         "litellm_model": name, "input_tokens": usage[0], "output_tokens": usage[1],
                         "expected_usd": None, "response_cost_usd": None,
                         "completion_cost_usd": litellm.completion_cost(completion_response=mocked, model=name),
                         "budget_checks_skipped": None})
    return rows


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write-litellm", action="store_true", help="regenerate ledger/litellm.prices.yaml")
    parser.add_argument("--check-litellm", action="store_true", help="load the custom prices into LiteLLM")
    parser.add_argument("--json", action="store_true", help="print the check as JSON")
    args = parser.parse_args(argv)
    table = load()
    if args.write_litellm:
        write_litellm(table)
        print(f"wrote {LITELLM_YAML.name}")
    if args.check_litellm:
        if os.environ.get("LEDGER_OFFLINE") == "1":
            import offline
            offline.block_network()
        rows = check_litellm(table)
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                print(f"{r['gateway']:6s} {r['alias']:26s} {r['deployment']:20s} expected {r['expected_usd']} "
                      f"response_cost {r['response_cost_usd']} completion_cost {r['completion_cost_usd']} "
                      f"budget checks skipped: {r['budget_checks_skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
