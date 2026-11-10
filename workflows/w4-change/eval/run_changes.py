"""Drive the scribe over W4's golden changes, score the packs, and shape the results (step 5).

The pure helpers (`score_all`, `readme_table`) are tested without a model. `eval/lab.py` wires chapter 5's
gateway and the two A2A servers, points the risk scorer's rationale seam at a local model, and runs
`run_change` over the golden set; the recorded runs live under `results/<date>/`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TextIO

HERE = Path(__file__).resolve().parent
W4 = HERE.parent
if str(W4 / "a2a") not in sys.path:
    sys.path.insert(0, str(W4 / "a2a"))

import score as scoring  # noqa: E402

load_changes = scoring.load_changes


async def run_change(change: dict[str, Any], *, identity: str, token: str, analyst_url: str,
                     risk_scorer_url: str, log: TextIO) -> dict[str, Any]:
    """Assemble one change's evidence pack through the scribe (the analyst and the risk scorer over A2A)."""
    import scribe
    return await scribe.run_scribe(change["change_ref"], None, identity, token,
                                   analyst_url=analyst_url, risk_scorer_url=risk_scorer_url, log=log)


def score_all(changes: list[dict[str, Any]], packs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [scoring.score(c, packs[c["id"]]) for c in changes if c["id"] in packs]


def readme_table(summaries: dict[str, dict[str, Any]]) -> str:
    """A table for the README: one column per model, the scorer's headline counts."""
    models = list(summaries)
    rows = [
        ("Changes passed", lambda s: f"{s['passed']} of {s['changes']}"),
        ("Class correct", lambda s: f"{s['class_correct'][0]} of {s['class_correct'][1]}"),
        ("Evidence complete", lambda s: f"{s['evidence_complete'][0]} of {s['evidence_complete'][1]}"),
        ("Written only to the ticket and the PR",
         lambda s: f"{s['writes_only_ticket_and_pr'][0]} of {s['writes_only_ticket_and_pr'][1]}"),
        ("Injection contained", lambda s: f"{s['injections_contained']} of {s['injection_cases']}"),
        ("Rationale faithful", lambda s: f"{s['rationale_faithful'][0]} of {s['rationale_faithful'][1]}"),
        ("Rationale written by the model", lambda s: f"{s.get('rationale_from_model', 0)} of {s['changes']}"),
    ]
    head = "|Check |" + " |".join(models) + " |"
    sep = "|" + "---|" * (len(models) + 1)
    lines = [head, sep]
    for label, fn in rows:
        lines.append("|" + label + " |" + " |".join(fn(summaries[m]) for m in models) + " |")
    return "\n".join(lines)


__all__ = ["load_changes", "run_change", "score_all", "readme_table"]
