# Step 3.5: Still failing after 3 fix attempts, diagnostic report

Task **$pick-task.output.task_id: $pick-task.output.title** is still failing top-level
validation after 3 fix attempts. Execution halts after this report, so a human can step in.

Read:
- Validation logs: `$ARTIFACTS_DIR/$pick-task.output.task_id/validate-1.log` through `validate-4.log`
- Fix attempt notes: `$ARTIFACTS_DIR/$pick-task.output.task_id/fix-attempt.md`
- Micro-task notes: `$ARTIFACTS_DIR/$pick-task.output.task_id/microtasks.md`
- `git log --oneline` and the diff for this task

Do not change any code. Write `$ARTIFACTS_DIR/$pick-task.output.task_id/diagnosis.md` with:

1. **Failing tests**: names, and the exact assertion or error for each.
2. **Expected vs actual**: for each failure, what the test expects and what happened.
3. **Attempted fixes**: what was tried in the implement pass and each fix attempt, and why each didn't work.
4. **Most likely root cause**, plus any other plausible causes, with evidence.
5. **Recommended human action**: the specific code change, environment fix, or test
   correction, and whether the acceptance criteria themselves need revisiting.
6. **How to continue**: fix it in the run's worktree, then `archon workflow resume <run-id>`.
