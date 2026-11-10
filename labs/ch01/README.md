# Lab, chapter 1: the agent loop

Listing 1.1 from the book. A complete agent loop with a faked model, so it runs on any machine with Python 3.12 and no API key.

## Run

```
python agent_loop.py
```

Expected output:

```
claims-api has 2 of 3 pods ready.
```

## What to look at

- `run_agent` is the whole loop: ask the model, run the tool it names, append the result, repeat.
- `max_steps` is the stop condition the model cannot override. Set it to `0` and the loop returns `Stopped: step budget exhausted.` without ever calling the model.
- `TOOLS` is the only thing the model can reach, and only by name. The model never holds a reference to a function or a credential.

## Test

```
python -m pytest test_agent_loop.py -q
```

## Cost and teardown

Nothing is created. There is nothing to tear down.

Last run: 2026-10-28, Python 3.12.9.
