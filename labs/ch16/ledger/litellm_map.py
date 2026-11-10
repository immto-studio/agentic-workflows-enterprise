"""The dated table against LiteLLM 1.106.6's built-in price map, for every deployment the table names.

Chapter 16, step 2 (companion #14, O-D5; fact sheet 8.1). LiteLLM prices a call from a map of model names
to prices that ships in its wheel. Unless LITELLM_LOCAL_MODEL_COST_MAP is True, `import litellm` fetches
the main branch's copy of that map, and so does the proxy at startup. This module sets the variable before
it imports LiteLLM, so the comparison is with 1.106.6's own map, and it reads the same map from the
wheel's file to show the two agree.

Each row is a name a deployment could go by. It records the map's entry under that name, or its absence;
what LiteLLM's `cost_per_token` makes of the name; the table's price; and the difference:

  missing         no entry, and LiteLLM can't price the name (ModelNotMappedError)
  base price      no entry under the name, and LiteLLM prices it at the base model's entry
  different       LiteLLM's price for the name isn't the table's
  equal           LiteLLM's price for the name is the table's
  no table price  the table has no price to compare

Nova Lite's names come first: the Canadian profile, the US profile (called in either Region, since a
profile bills at the price of the Region it is called in, ch06:162), the bare model, and the bare model
with a Region prefix, LiteLLM's form for a price that varies by Region.

Run it in a fresh process. Once a Router has registered a custom-priced deployment, LiteLLM keeps an
empty entry under the deployment's model name, and the name prices at zero (price.check_litellm shows it).

Run (from labs/ch16):  python ledger/litellm_map.py [--json]
"""

from __future__ import annotations

import os

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"  # before LiteLLM is imported anywhere in this process

import importlib.metadata  # noqa: E402
import importlib.resources  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import price  # noqa: E402

MAP_FILE = "model_prices_and_context_window_backup.json"
MILLION = 1_000_000

# (deployment, the name LiteLLM is asked to price, the map's key for that name, what the name is)
NAMES: tuple[tuple[str, str, str, str], ...] = (
    ("nova-lite-ca", "bedrock/ca.amazon.nova-lite-v1:0", "ca.amazon.nova-lite-v1:0",
     "the Canadian profile, called in ca-central-1, as chapter 6 calls it"),
    ("nova-lite-ca", "bedrock/us.amazon.nova-lite-v1:0", "us.amazon.nova-lite-v1:0",
     "the US profile, called in ca-central-1"),
    ("nova-lite-us", "bedrock/us.amazon.nova-lite-v1:0", "us.amazon.nova-lite-v1:0",
     "the US profile, called in us-east-2"),
    ("nova-lite-us", "bedrock/amazon.nova-lite-v1:0", "amazon.nova-lite-v1:0",
     "the bare model In-Region in us-east-2, as the fallback calls it"),
    ("nova-lite-ca", "bedrock/ca-central-1/amazon.nova-lite-v1:0", "bedrock/ca-central-1/amazon.nova-lite-v1:0",
     "the bare model with ca-central-1 as LiteLLM's Region prefix"),
    ("nova-lite-us", "bedrock/us-east-2/amazon.nova-lite-v1:0", "bedrock/us-east-2/amazon.nova-lite-v1:0",
     "the bare model with us-east-2 as LiteLLM's Region prefix"),
    ("vllm-gpt-oss-20b", "hosted_vllm/gpt-oss-20b", "hosted_vllm/gpt-oss-20b",
     "chapter 9's self-hosted model behind vLLM"),
    ("titan-embed-v2-ca", "bedrock/amazon.titan-embed-text-v2:0", "amazon.titan-embed-text-v2:0",
     "Titan Text Embeddings V2, called in ca-central-1"),
    ("gpt-4o-canada-east", "azure/gpt-4o-2024-11-20", "azure/gpt-4o-2024-11-20",
     "gpt-4o 2024-11-20, a Standard deployment in Canada East"),
    ("gemini-3.5-flash-montreal", "vertex_ai/gemini-3.5-flash", "vertex_ai/gemini-3.5-flash",
     "Gemini 3.5 Flash in Montréal"),
    ("bedrock-gpt-oss-120b-use1", "bedrock/openai.gpt-oss-120b-1:0", "openai.gpt-oss-120b-1:0",
     "gpt-oss-120b on Bedrock's Standard tier in us-east-1, chapter 9's crossover"),
)


def bundled_map() -> dict[str, Any]:
    """The price map in LiteLLM's wheel, the one LITELLM_LOCAL_MODEL_COST_MAP=True loads."""
    return json.loads((importlib.resources.files("litellm") / MAP_FILE).read_text(encoding="utf-8"))


def per_million(per_token: Any) -> float | None:
    return None if per_token is None else float(Decimal(str(per_token)) * MILLION)


def _probe(name: str, mode: str | None) -> dict[str, Any]:
    import litellm
    try:
        if mode == "embedding":
            cost_in, cost_out = litellm.cost_per_token(model=name, prompt_tokens=MILLION, completion_tokens=0,
                                                        call_type="embedding")
        else:
            cost_in, cost_out = litellm.cost_per_token(model=name, prompt_tokens=MILLION, completion_tokens=MILLION)
    except Exception as exc:  # what LiteLLM raises is the finding
        return {"error": type(exc).__name__}
    return {"input_per_million": round(cost_in, 9), "output_per_million": round(cost_out, 9)}


def _kind(table_in: Any, entry: dict[str, Any] | None, probe: dict[str, Any], mode: str | None) -> str:
    if table_in is None:
        return "no table price"
    if "error" in probe:
        return "missing"
    if entry is None:
        return "base price"
    same_in = Decimal(str(probe["input_per_million"])) == Decimal(str(table_in["input"]))
    same_out = mode == "embedding" or Decimal(str(probe["output_per_million"])) == Decimal(str(table_in["output"]))
    return "equal" if same_in and same_out else "different"


def compare(table: dict[str, Any] | None = None) -> dict[str, Any]:
    """The comparison, and the evidence that the map in use is the wheel's."""
    import litellm
    table = table or price.load()
    deployments = price.by_id(table)
    bundled = bundled_map()
    rows = []
    for dep_id, name, key, what in NAMES:
        d = deployments[dep_id]
        mode = d.get("mode")
        entry = bundled.get(key)
        mapped = None if entry is None else {"input_per_million": per_million(entry.get("input_cost_per_token")),
                                             "output_per_million": per_million(entry.get("output_cost_per_token"))}
        table_price = (None if d["input_per_million"] is None else
                       {"input": d["input_per_million"], "output": d["output_per_million"]})
        probe = _probe(name, mode)
        ratio = None
        if table_price and "error" not in probe and probe["input_per_million"]:
            ratio = round(float(Decimal(str(table_price["input"])) / Decimal(str(probe["input_per_million"]))), 4)
        rows.append({"deployment": dep_id, "name": name, "map_key": key, "what": what, "map_entry": mapped,
                     "litellm": probe, "table": table_price, "table_over_litellm": ratio,
                     "kind": _kind(table_price, entry, probe, mode)})
    in_use = {key: litellm.model_cost.get(key) == bundled.get(key) for _, _, key, _ in NAMES if key in bundled}
    return {"litellm": importlib.metadata.version("litellm"), "map": MAP_FILE,
            "local_map": os.environ["LITELLM_LOCAL_MODEL_COST_MAP"], "map_in_use_is_the_wheels": all(in_use.values()),
            "rows": rows}


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if os.environ.get("LEDGER_OFFLINE") == "1":
        import offline
        offline.block_network()
    result = compare()
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"LiteLLM {result['litellm']}, {result['map']}, the wheel's map in use: {result['map_in_use_is_the_wheels']}")
    for r in result["rows"]:
        print(f"{r['kind']:15s} {r['name']:46s} map {r['map_entry']} litellm {r['litellm']} table {r['table']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
