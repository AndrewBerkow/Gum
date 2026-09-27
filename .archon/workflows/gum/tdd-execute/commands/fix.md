# Step 3.5: First validation failure, back to implementation

Task **$pick-task.output.task_id: $pick-task.output.title**. The top-level
integration tests failed on validation attempt 1.

Failure log: `$validate-1.output.log_path`
Test command: `$pick-task.output.test_command`

1. Read the log. For each failing test, figure out the root cause: is the implementation
   wrong or missing, is it an environment/config problem, or is the test's expectation wrong?
2. Fix the **implementation** (with a unit test first, if it's a new behavior).
   Do not edit the top-level integration tests. If a test's expectation is truly
   wrong, don't change it; record it as a concern instead.
3. Run the unit suite and the top-level command.
4. Commit the fix.

Append to `$ARTIFACTS_DIR/$pick-task.output.task_id/fix-attempt.md`: the failures,
their root causes, what you changed, and the result of your local rerun.
