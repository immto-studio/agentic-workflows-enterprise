# The gate: live-w2-gemma4-12b.json against baseline.json

- the run is partial (workflows w2); only a complete run is gated
- pins, the judge: the judge's model changed: gemma4-12b -> gpt-oss-20b
- pins, the judge: the judge's served changed: ollama_chat/gemma4:12b -> ollama_chat/gpt-oss:20b
- pins, the judge: the judge's alias map changed: larkspur-chat ollama_chat/gemma4:12b -> ollama_chat/gpt-oss:20b; larkspur-chat-restricted ollama_chat/gemma4:12b -> ollama_chat/gpt-oss:20b
- pins, the judge: the judge's digest changed: 6114515d63c1 -> f38aa0c53da5
- pins, skeleton: the run holds no pins for this set
- pins, w1: the run holds no pins for this set
- pins, w2: the alias map changed: larkspur-chat ollama_chat/gpt-oss:20b -> ollama_chat/gemma4:12b
- pins, w2: ollama_chat/gemma4:12b: the baseline holds no digest for it
- pins, w2: ollama_chat/gpt-oss:20b: the baseline holds no digest for it
- pins, w3: the run holds no pins for this set
- pins, w4: the run holds no pins for this set
- pins, w5: the run holds no pins for this set

The baseline is invalid for the judge, skeleton, w1, w2, w3, w4, w5 until a run is accepted (python ci/live.py --accept live/<run>.json, after review). The checks below are for that review.

|Workflow |Check |Threshold |Baseline |Run |Lost |Gained |Verdict |
|---|---|---|---|---|---|---|---|
|w2 |scorer |not gated |22 of 25 |23 of 25 |w2-05 |w2-14, w2-16 |not gated |
|w2 |deterministic.facts |1 |18 of 20 |18 of 20 |w2-05 |w2-16 |held |
|w2 |deterministic.refusal |0 |4 of 5 |5 of 5 |- |w2-14 |held |
|w2 |deterministic.route |1 |5 of 5 |5 of 5 |- |- |held |
|w2 |deterministic.labels |0 |24 of 24 |24 of 24 |- |- |held |
|w2 |deterministic.planted |0 |3 of 3 |3 of 3 |- |- |held |
|w2 |deterministic.masked |0 |25 of 25 |25 of 25 |- |- |held |
|w2 |trajectory.allowed |1 |25 of 25 |23 of 25 |w2-01, w2-05 |- |regressed |
|w2 |trajectory.order |1 |25 of 25 |25 of 25 |- |- |held |
|w2 |trajectory.forbidden |0 |25 of 25 |25 of 25 |- |- |held |
|w2 |trajectory.budget |0 |25 of 25 |25 of 25 |- |- |held |
|w2 |judge |not gated |21 read, 9 of them sampled texts; no verdict carried |17 right of 19 shown, 0 withheld |- |- |reported |

The gate fails: the comparison is unsound; the baseline is invalid; regressed: w2 trajectory.allowed.
