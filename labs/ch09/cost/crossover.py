"""When does running the model yourself cost less than paying per token?

Chapter 9. Hosted inference costs a price per token. A self-hosted deployment costs its GPUs for
every hour of the month, whether or not anyone calls it, times the replicas that availability
needs. The crossover is the monthly token volume at which the two are equal:

    crossover_tokens = gpu_cost_per_month / blended_hosted_price_per_token

where the blended price weights input and output prices by the workflow's token mix. Two more
numbers make the crossover honest:

- the sustained throughput the GPUs would need to serve that volume, which says whether the
  crossover is reachable at all with the engine and model you run;
- how far below the crossover a real workflow sits, as a ratio, which is the number a budget
  conversation needs.

Platform overhead (engineers, storage, observability, support subscriptions) only moves the
crossover further out, so it is left as an explicit input rather than guessed.

Run:  python cost/crossover.py --gpu aws-p5.4xlarge-h100-on-demand --replicas 2 --monthly-tokens 100e6
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

SHEET = Path(__file__).resolve().parent / "cost-sheet.yaml"


@dataclass(frozen=True)
class Crossover:
    hosted: str
    gpu: str
    replicas: int
    input_per_output: float
    blended_per_million: float          # hosted price per million tokens at this mix
    gpu_cost_per_month: float           # replicas x hourly price x hours, plus overhead
    crossover_tokens_per_month: float
    sustained_tokens_per_second: float  # input and output together, to serve the crossover volume
    sustained_output_tokens_per_second: float
    monthly_tokens: float | None = None
    hosted_cost_per_month: float | None = None
    self_hosted_over_hosted: float | None = None  # how many times the hosted bill the GPUs cost


def load_sheet(path: Path = SHEET) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def blended_price(hosted: dict, input_per_output: float) -> float:
    """Price per million tokens for a mix of `input_per_output` input tokens per output token."""
    return ((input_per_output * hosted["input_per_million"] + hosted["output_per_million"])
            / (input_per_output + 1))


def crossover(sheet: dict, hosted: str, gpu: str, replicas: int = 2, overhead_per_month: float = 0.0,
              monthly_tokens: float | None = None, input_per_output: float | None = None) -> Crossover:
    mix = input_per_output if input_per_output is not None else sheet["input_per_output"]
    hours = sheet["hours_per_month"]
    price = blended_price(sheet["hosted"][hosted], mix)
    gpu_month = replicas * sheet["gpu"][gpu]["per_hour"] * hours + overhead_per_month
    tokens = gpu_month / price * 1e6
    per_second = tokens / (hours * 3600)
    result = Crossover(hosted, gpu, replicas, mix, price, gpu_month, tokens, per_second, per_second / (mix + 1))
    if monthly_tokens is not None:
        hosted_month = monthly_tokens * price / 1e6
        result = Crossover(**{**asdict(result), "monthly_tokens": monthly_tokens,
                              "hosted_cost_per_month": hosted_month,
                              "self_hosted_over_hosted": gpu_month / hosted_month})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--hosted", default="bedrock-gpt-oss-120b-standard")
    parser.add_argument("--gpu", default="aws-p5.4xlarge-h100-on-demand")
    parser.add_argument("--replicas", type=int, default=2)
    parser.add_argument("--overhead", type=float, default=0.0, help="monthly platform overhead, USD")
    parser.add_argument("--monthly-tokens", type=float, help="a workflow's monthly tokens, input and output")
    parser.add_argument("--input-per-output", type=float)
    args = parser.parse_args(argv)
    result = crossover(load_sheet(), args.hosted, args.gpu, args.replicas, args.overhead,
                       args.monthly_tokens, args.input_per_output)
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
