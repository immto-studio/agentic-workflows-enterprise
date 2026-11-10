# Pinned copy of the OpenTelemetry GenAI semantic conventions registry

The GenAI conventions moved out of `open-telemetry/semantic-conventions` into their own
repository, `open-telemetry/semantic-conventions-genai`, which had no tags or releases when this
copy was taken. The lab pins a commit instead and tests its attribute names against it
(`tests/test_tracing.py`), so a rename, a deprecation or a move to stable shows up as a failing
test when the copy is refreshed.

| File here | Upstream path | Commit | Commit date |
|---|---|---|---|
| `gen-ai-registry.yaml` | `model/gen-ai/registry.yaml` | `3fe84604a581b3d50dd5b4bd29383b462d2a5018` | 2026-10-28 |
| `a2a-registry.yaml` | `model/a2a/registry.yaml` | same | same |
| `LICENSE` | `LICENSE` (Apache License 2.0) | same | same |

The files are unmodified. To refresh, pick a newer commit, download the same three paths from
`https://raw.githubusercontent.com/open-telemetry/semantic-conventions-genai/<commit>/<path>`,
update the table, and run the tests.
