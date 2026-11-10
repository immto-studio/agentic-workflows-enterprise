# The judge and the rules against labels-A.jsonl

Labeler A: 140 of 140 sampled outputs labeled, from 140 lines, 0 of them replaced by a later line for the same output. The judge's verdicts are those in labs/ch15/results/2026-11-03, on the rubrics w1 `65655a952878`, w2 `2838c8572fba`, w3 `a020f218c57d`, w4 `d8f4d41bdfce`, w5 `a14e5f38b7e6`, and every label was made against the same rubric.

## The judge against the labels

Per workflow, with E-D5's rule beside each, at least 90 percent agreement:

|Workflow |Labeled |Agree |Agreement |95% interval |Kappa |Labeled wrong |The judge: wrong |At least 90% |
|---|---|---|---|---|---|---|---|---|
|W1 |33 |29 |87.9 |72.7 to 95.2 |0.74 |12 |12 |no |
|W2 |33 |28 |84.8 |69.1 to 93.3 |0.63 |8 |11 |no |
|W3 |19 |15 |78.9 |56.7 to 91.5 |0.57 |10 |14 |no |
|W4 |21 |21 |100.0 |84.5 to 100.0 |n/a |0 |0 |yes |
|W5 |34 |30 |88.2 |73.4 to 95.3 |0.67 |25 |27 |no |

Over the sample:

|Outputs |Labeled |Agree |Agreement |95% interval |Kappa |Labeled wrong |The judge: wrong |
|---|---|---|---|---|---|---|---|
|all |140 |123 |87.9 |81.4 to 92.3 |0.75 |55 |64 |
|drawn by the seed |106 |90 |84.9 |76.9 to 90.5 |0.65 |27 |37 |
|known outputs |34 |33 |97.1 |85.1 to 99.5 |0.91 |28 |27 |
|judged by gemma4-12b |100 |88 |88.0 |80.2 to 93.0 |0.76 |45 |51 |
|judged by gpt-oss-20b |40 |35 |87.5 |73.9 to 94.5 |0.70 |10 |13 |

Precision and recall on "wrong". Precision is the share of the judge's "wrong" that the labels also call wrong, and recall the share of the outputs labeled wrong that the judge calls wrong.

|Outputs |Precision |Recall |
|---|---|---|
|all |51 of 64, 79.7 (68.3 to 87.7) |51 of 55, 92.7 (82.7 to 97.1) |
|drawn by the seed |24 of 37, 64.9 (48.8 to 78.2) |24 of 27, 88.9 (71.9 to 96.1) |
|known outputs |27 of 27, 100.0 (87.5 to 100.0) |27 of 28, 96.4 (82.3 to 99.4) |
|W1 |10 of 12, 83.3 (55.2 to 95.3) |10 of 12, 83.3 (55.2 to 95.3) |
|W2 |7 of 11, 63.6 (35.4 to 84.8) |7 of 8, 87.5 (52.9 to 97.8) |
|W3 |10 of 14, 71.4 (45.4 to 88.3) |10 of 10, 100.0 (72.2 to 100.0) |
|W4 |none |none |
|W5 |24 of 27, 88.9 (71.9 to 96.1) |24 of 25, 96.0 (80.5 to 99.3) |

## The rules against the labels

Per workflow, with E-D5's rule beside each, at least 90 percent agreement:

|Workflow |Labeled |Agree |Agreement |95% interval |Kappa |Labeled wrong |The rules: wrong |At least 90% |
|---|---|---|---|---|---|---|---|---|
|W1 |33 |32 |97.0 |84.7 to 99.5 |0.93 |12 |11 |yes |
|W2 |33 |29 |87.9 |72.7 to 95.2 |0.70 |8 |10 |no |
|W3 |18 |14 |77.8 |54.8 to 91.0 |0.57 |10 |6 |no |
|W4 |21 |21 |100.0 |84.5 to 100.0 |n/a |0 |0 |yes |
|W5 |34 |19 |55.9 |39.5 to 71.1 |0.26 |25 |10 |no |

Over the sample:

|Outputs |Labeled |Agree |Agreement |95% interval |Kappa |Labeled wrong |The rules: wrong |
|---|---|---|---|---|---|---|---|
|all |139 |115 |82.7 |75.6 to 88.1 |0.62 |55 |37 |
|drawn by the seed |106 |95 |89.6 |82.4 to 94.1 |0.68 |27 |16 |
|known outputs |33 |20 |60.6 |43.7 to 75.3 |0.03 |28 |21 |
|judged by gemma4-12b |99 |78 |78.8 |69.7 to 85.7 |0.56 |45 |30 |
|judged by gpt-oss-20b |40 |37 |92.5 |80.1 to 97.4 |0.78 |10 |7 |

Precision and recall on "wrong". Precision is the share of the rules' "wrong" that the labels also call wrong, and recall the share of the outputs labeled wrong that the rules call wrong.

|Outputs |Precision |Recall |
|---|---|---|
|all |34 of 37, 91.9 (78.7 to 97.2) |34 of 55, 61.8 (48.6 to 73.5) |
|drawn by the seed |16 of 16, 100.0 (80.6 to 100.0) |16 of 27, 59.3 (40.7 to 75.5) |
|known outputs |18 of 21, 85.7 (65.4 to 95.0) |18 of 28, 64.3 (45.8 to 79.3) |
|W1 |11 of 11, 100.0 (74.1 to 100.0) |11 of 12, 91.7 (64.6 to 98.5) |
|W2 |7 of 10, 70.0 (39.7 to 89.2) |7 of 8, 87.5 (52.9 to 97.8) |
|W3 |6 of 6, 100.0 (61.0 to 100.0) |6 of 10, 60.0 (31.3 to 83.2) |
|W4 |none |none |
|W5 |10 of 10, 100.0 (72.2 to 100.0) |10 of 25, 40.0 (23.4 to 59.3) |

## Where the judge and the rules agree and differ

|Rules |Judge |Outputs |Labeled right |Labeled wrong |
|---|---|---|---|---|
|right |right |71 |68 |3 |
|right |wrong |31 |13 |18 |
|wrong |right |4 |3 |1 |
|wrong |wrong |33 |0 |33 |

Where the two differ, the labels side with the judge on 21 of 35 outputs and with the rules on 14. Outputs no rule reads: 1.

## Where the judge and the labels differ

A W1 reason can quote a Restricted page (W1-D26), so this table is Restricted data wherever it holds a W1 row.

|Id |Workflow |Case |Written by |Judge |Label |Judge said |Rules |Note |The judge's reason |
|---|---|---|---|---|---|---|---|---|---|
|w1-0163f179 |W1 |gq-11/oncall.engineer |nova-lite |gemma4-12b |right |wrong |right | |The answer fails to state the key fact that the worker should be rolled back if they are crash-looping. |
|w1-15651046 |W1 |gq-04/ea.lead |gpt-oss-20b |gemma4-12b |wrong |right |right | |none |
|w1-2af5f320 |W1 |gq-07/oncall.engineer |nova-lite |gemma4-12b |wrong |right |wrong | |The output includes all key facts from the reference and follows the newer page as required. |
|w1-4067feee |W1 |gq-01/vault.custodian |gemma4-12b |gpt-oss-20b |right |wrong |right | |The output omits the key facts that the shards are entered on vault-0 with `vault operator unseal -migrate` after opening a Sev1 with category SEC-BG. |
|w2-24b1ada4 |W2 |w2-05 |gemma4-12b |gpt-oss-20b |right |wrong |right | |The output fails to state the warning alert time correctly (it says 16 minutes instead of 15 minutes). |
|w2-29a16312 |W2 |w2-21 |gpt-oss-20b |gemma4-12b |right |wrong |right | |The answer fails to state the key fact that the PCI operator sees the service through their own team's list. |
|w2-7350ad32 |W2 |w2-09 |gpt-oss-20b |gemma4-12b |right |wrong |right | |The answer fails to state the key fact that there are no alerts. |
|w2-d5e4942f |W2 |w2-20 |gpt-oss-20b |gemma4-12b |right |wrong |right | |The output fails to state the key fact that one of two pods is Pending. |
|w2-f6a5ed08 |W2 |w2-12 |gpt-oss-20b |gemma4-12b |wrong |right |right | |The output includes the required information that the assistant is read-only and cannot perform restarts, while pointing to the runbook. |
|w3-4783a6b9 |W3 |w3-14 |gpt-oss-20b |gemma4-12b |right |wrong |right | |The triage proposes steps other than the one the reference names. |
|w3-47ae9fef |W3 |w3-02 |gpt-oss-20b |gemma4-12b |right |wrong |right | |The triage proposes a step by stating "So healthy" as a conclusion, whereas the reference specifies that a right triage proposes no step. |
|w3-59bd26db |W3 |w3-22 |gpt-oss-20b |gemma4-12b |right |wrong |right | |The triage states information that contradicts the reference by including details about restarts, alerts, metrics, and logs which were not in the reference. |
|w3-ad1064db |W3 |w3-04 |gpt-oss-20b |gemma4-12b |right |wrong |right | |The triage states facts that contradict the reference, specifically regarding the runbook's threshold and the pod restart information. |
|w5-028d883b |W5 |night-1 claims-api-prod:aws_instance.api:graviton_candidate |gemma4-12b |gpt-oss-20b |right |wrong |right | |The output does not name the finding's kind as required by criterion 1. |
|w5-a9477c0f |W5 |night-2 sandbox-quill:aws_instance.batch:idle |gemma4-12b |gpt-oss-20b |right |wrong |right | |The instance ID in the output does not match the facts. |
|w5-c9f7bb77 |W5 |night-1 sandbox-quill:vol-0d2b2c3d4e5f60402:unmanaged |gpt-oss-20b |gemma4-12b |right |wrong |right | |The output fails to state that no saving is estimated. |
|w5-e21fb356 |W5 |night-1 sandbox-quill:aws_ebs_volume.archive:unattached_volume |gemma4-12b |gpt-oss-20b |wrong |right |right | |The output meets all rubric criteria. |

Labeled outputs the judge gave no verdict: 0.
