"""Make the ledger's, the Collector's, and steps 4 to 9's modules importable, keep caches out of the workflows'
folders, and block the network.

The ledger, collector, budget, capacity, slo, cloud, lifecycle and review folders are plain directories, not packages,
so the tests put them on `sys.path` the way the scripts do; `capacity/`, `slo/`, `cloud/`, `lifecycle/` and `review/`
go last, and no module of theirs shares a name with another folder's. Step 6's month and the kept runs' SLI events are
built once for the session (`kept_slo`, `month`). Step 7's tests answer every AWS call with botocore's Stubber and make
none; step 8's read the register, the configurations and the committed results, and start no gateway and no model;
step 9's read the committed results of the steps before it and W5's ledger.
LITELLM_LOCAL_MODEL_COST_MAP is set before anything imports LiteLLM, so `import litellm` loads the map in its wheel
rather than fetching the main branch's (fact sheet 8.1). Every connection that would
leave the machine raises for the whole session (ledger/offline.py), and LEDGER_OFFLINE carries the same
block into every process a test starts. The Collector's tests reach only the fakes on 127.0.0.1.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["LEDGER_OFFLINE"] = "1"
sys.dont_write_bytecode = True
LAB = Path(__file__).resolve().parents[1]
LEDGER = LAB / "ledger"
COLLECTOR = LAB / "collector"
BUDGET = LAB / "budget"
CAPACITY = LAB / "capacity"
SLO = LAB / "slo"
CLOUD = LAB / "cloud"
LIFECYCLE = LAB / "lifecycle"
REVIEW = LAB / "review"
for folder in (REVIEW, LIFECYCLE, CLOUD, SLO, CAPACITY, BUDGET, COLLECTOR, LEDGER):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import pytest  # noqa: E402

import costlines  # noqa: E402
import offline  # noqa: E402
import price  # noqa: E402

offline.block_network()


@pytest.fixture(scope="session")
def runs() -> list[costlines.Run]:
    """Every run of every kept run, as the ledger reads them."""
    return costlines.collect()


@pytest.fixture(scope="session")
def table() -> dict:
    return price.load()


@pytest.fixture(scope="session")
def kept_slo() -> dict:
    """Every kept run of W1 to W5 as step 6's RunEvents (slo/slis.kept_events)."""
    import slis
    return slis.kept_events()


@pytest.fixture(scope="session")
def month(kept_slo):
    """Step 6's simulated month, as slo/month.yaml builds it."""
    import simulate
    return simulate.build(kept=kept_slo)


def line(**fields) -> costlines.CostLine:
    """A cost line made for a test, with the fields it doesn't name filled in."""
    base = dict(run_id="t", trace_id=None, workflow="w2", gateway_workflow="w2-ops-assistant", kept_run="test",
                case="c", call=1, model="test", model_tag="gpt-oss-20b", alias="larkspur-chat",
                served_alias="larkspur-chat", data_class="internal", input_tokens=1000, output_tokens=100,
                duration_ms=None, fallback=False, source="test")
    return costlines.CostLine(**{**base, **fields})
