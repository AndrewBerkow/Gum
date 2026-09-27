# Decompose the execution plan

Plan file: `$INPUTS.plan` (relative to the repo root). Invocation message: $ARGUMENTS

Read the whole plan. Split it into **3 to 5 high-level tasks** that run in order.
Each task must be:

- **Independently executable**: it builds only on earlier tasks, never later ones.
- **Isolated**: it has a clear boundary (module, layer or feature slice).
- **Verifiably testable**: a single shell command runs its top-level integration
  tests and exits 0 only when the task's acceptance criteria are met.

If the plan already has its own finer task list, group those items into 3-5
tasks. Keep the plan's own IDs in each task's `plan_refs`, and carry over the
tests and acceptance criteria the plan lists.

This run is unattended. If a plan item needs real API keys or external accounts,
check whether those environment variables are set (e.g. `test -n "$TYPESAFE_API_KEY"`).
If any are missing, leave that item out of `tasks.json`, and list it in `tasks.md` under
"Deferred" with the missing variables. Its tests could only skip or fail.

For `integration_test_command`, use the toolchain the plan specifies. Point the
command only at that task's integration test path, e.g.
`uv run pytest tests/integration/test_t1_guardrail.py -q`. Every task needs its
own path, and a command must never pass because a test file is missing.

Write two files:

1. `$ARTIFACTS_DIR/tasks.json`:
   ```json
   {"tasks": [{
     "id": "t1",
     "title": "short title",
     "goal": "one paragraph: what exists when this task is done",
     "plan_refs": ["T1", "T2"],
     "depends_on": [],
     "acceptance_criteria": ["observable, testable statement", "..."],
     "integration_test_command": "uv run pytest tests/integration/test_t1_x.py -q",
     "out_of_scope": ["what this task must not build"]
   }]}
   ```
2. `$ARTIFACTS_DIR/tasks.md`: the same breakdown written for a human reviewer, in order,
   with one line per task explaining why it's separate from the others.

Do not write any code or tests. Return `task_count`.
