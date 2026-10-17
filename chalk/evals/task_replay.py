"""The run_local.py fallback's task (spec §15.3, §22.4): replay an output produced locally.

run_local.py runs StormDesk on this machine, uploads each row with its output
in `agent_output`, and this task hands it to the scorers unchanged, so the
outputs are still scored in a real Chalk Evaluation. Self-contained.
"""

import chalkcompute


@chalkcompute.function(name="sd-replay-output", concurrency=8)
def replay_output(agent_output: str) -> str:
    return agent_output
