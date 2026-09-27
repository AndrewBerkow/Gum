# Step 4: Sub-workflow completion summary

Task **$pick-task.output.task_id: $pick-task.output.title** (task
$pick-task.output.index of $pick-task.output.total) passed top-level validation.

Read the task artifacts in `$ARTIFACTS_DIR/$pick-task.output.task_id/`, the
task list in `$ARTIFACTS_DIR/tasks.json`, and this task's commits (`git log`).
Run the unit suite and the top-level command once so you report real numbers.

Write `$ARTIFACTS_DIR/$pick-task.output.task_id/summary.md`, concise and in this order:

1. **High-level task completed**: id, title, one-line outcome.
2. **Test results**: the number of micro-unit tests passing, and the top-level integration
   tests passing, with the commands used. Say which validation attempt passed (1-4, or after a human fix).
3. **Changes/deliverables**: the files added or changed, each with one line on its purpose.
4. **Concerns**: integration test concerns raised, shortcuts taken, anything the reviewer should check.
5. **Next sub-workflow**: the next task's id, title, and goal from tasks.json, or "none, all tasks complete".

Do not change code.
