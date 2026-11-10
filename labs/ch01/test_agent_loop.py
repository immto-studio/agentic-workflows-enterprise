from agent_loop import run_agent


def test_answers_after_one_tool_call() -> None:
    assert run_agent("Is claims-api healthy?") == "claims-api has 2 of 3 pods ready."


def test_step_budget_is_a_hard_stop() -> None:
    assert run_agent("Is claims-api healthy?", max_steps=0) == "Stopped: step budget exhausted."


def test_one_step_is_not_enough_to_answer() -> None:
    # One step lets the model request the tool but not read the result.
    assert run_agent("Is claims-api healthy?", max_steps=1) == "Stopped: step budget exhausted."


def test_disallowed_tool_is_refused() -> None:
    def hostile(messages):
        return {"tool_call": {"name": "delete_namespace", "args": {"name": "claims"}}}

    assert run_agent("Clean up", model=hostile) == "Refused: delete_namespace is not an allowed call."


def test_unexpected_arguments_are_refused() -> None:
    def sneaky(messages):
        return {"tool_call": {"name": "get_pod_status", "args": {"service": "x", "shell": "rm -rf /"}}}

    assert run_agent("Status", model=sneaky) == "Refused: get_pod_status is not an allowed call."
