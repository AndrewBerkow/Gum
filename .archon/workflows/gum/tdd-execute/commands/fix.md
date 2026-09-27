# Step 3.5: Validation failure, back to implementation (fix attempt $INPUTS.attempt of 3)

Task **$pick-task.output.task_id: $pick-task.output.title**. The top-level
integration tests failed validation.

Failure log: `$INPUTS.log_path`
Test command: `$pick-task.output.test_command`
Earlier fix attempts, if any: `$ARTIFACTS_DIR/$pick-task.output.task_id/fix-attempt.md`

1. Read the log. If there were earlier attempts, read their notes and don't repeat
   an approach that already failed.
2. For each failing test, figure out the root cause: is the implementation wrong or
   missing, is it an environment/config problem, or is the test's expectation wrong?
3. Fix the **implementation** (with a unit test first, if it's a new behavior).
   Do not edit the top-level integration tests. If a test's expectation is truly
   wrong, don't change it; record it as a concern instead.
4. Run the unit suite and the top-level command.
5. Commit the fix.

Append a section `## Attempt $INPUTS.attempt` to
`$ARTIFACTS_DIR/$pick-task.output.task_id/fix-attempt.md` with: the failures,
their root causes, what you changed, and the result of your local rerun.
