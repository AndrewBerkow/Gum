# Steps 3.2-3.3: Micro-task breakdown and micro-TDD loop

Current task: **$pick-task.output.task_id: $pick-task.output.title**

Inputs:
- Task spec: this task's entry in `$ARTIFACTS_DIR/tasks.json`
- Plan: `$INPUTS.plan`
- Top-level tests (committed, currently red): see `$ARTIFACTS_DIR/$pick-task.output.task_id/integration-tests.md`
- Top-level test command: `$pick-task.output.test_command`

## 3.2 Micro-task breakdown
Break the task into granular, atomic micro-tasks. Each one should be a single
behavior that one unit test can prove. Write the list to
`$ARTIFACTS_DIR/$pick-task.output.task_id/microtasks.md` before writing any code.

## 3.3 Micro-TDD loop, for each micro-task in order
a. **Red**: write one failing unit test under `tests/unit/`. Run it and confirm it
   fails for the right reason (a missing behavior, not a typo or import error in the test).
b. **Green**: write the minimal implementation that makes it pass. Run it.
c. **Refactor**: clean up while keeping all unit tests green. Run the full unit suite.
d. Commit: `git commit -am "feat($pick-task.output.task_id): <micro-task>"` (use `git add` for new files).

In `microtasks.md`, record each micro-task's red/green status with the test name.

Rules:
- **Do not edit the top-level integration tests.** If one looks wrong, say so in
  `microtasks.md` under "Integration test concerns", but leave it unchanged.
- Stay inside this task's scope; `out_of_scope` items belong to later tasks.
- When all micro-tasks are done, run the top-level command once and note the result.
