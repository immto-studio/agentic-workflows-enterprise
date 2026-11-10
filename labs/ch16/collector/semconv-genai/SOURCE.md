# Pinned span definitions of the OpenTelemetry GenAI semantic conventions

Chapter 5 pinned the GenAI attribute registry (`labs/ch05/tracing/semconv-genai/gen-ai-registry.yaml`) at a
commit of `open-telemetry/semantic-conventions-genai`. The registry names and describes each attribute,
but the requirement level, opt-in included, is set where a span or an event uses the attribute. These two
files are the span definitions at the same commit, so the Collector's content drop can be checked against
the opt-in attributes of the registry chapter 5 pinned (`tests/test_collector_config.py`).

| File here | Upstream path | Commit | Commit date |
|---|---|---|---|
| `gen-ai-spans.yaml` | `model/gen-ai/spans.yaml` | `3fe84604a581b3d50dd5b4bd29383b462d2a5018` | 2026-10-28 |
| `mcp-spans.yaml` | `model/mcp/spans.yaml` | same | same |
| `LICENSE` | `LICENSE` (Apache License 2.0) | same | same |

The files are unmodified. The model's other definitions at that commit (`model/gen-ai/events.yaml`,
`model/a2a/spans.yaml`) set no attribute as opt-in, and the event `gen_ai.client.inference.operation.details`
takes its attributes from the `gen_ai.client.inference` span defined here (`ref_group:
span.gen_ai.client.inference`). To refresh, take the same paths at a newer commit, together with chapter 5's
registry, update both tables, and run the tests.
