# Step 3.1: Top-level integration tests (no implementation)

Current task: **$pick-task.output.task_id: $pick-task.output.title**
(task $pick-task.output.index of $pick-task.output.total)

Read this task's entry in `$ARTIFACTS_DIR/tasks.json`, and the plan sections it
references in `$INPUTS.plan`.

Write top-level integration/functional tests that cover **every** acceptance
criterion for this task. They must run under exactly this command:

    $pick-task.output.test_command

Rules:
- Do NOT write functional code. You may add only what the tests need to run:
  test dependencies, `conftest.py`, fixtures, and project/test config
  (e.g. `pyproject.toml` with the test runner) if it doesn't exist yet.
- Test behavior through public entry points, not internals. Mock only
  external services (network APIs, LLMs), the way the plan specifies.
- Each test name states the criterion it checks.
- The tests must currently FAIL, because the behavior doesn't exist yet. The next node
  checks this. A test that already passes is not testing new behavior.

Commit the tests: `git add -A && git commit -m "test($pick-task.output.task_id): top-level integration tests"`.

Write `$ARTIFACTS_DIR/$pick-task.output.task_id/integration-tests.md` mapping each
acceptance criterion to the test(s) that cover it.
