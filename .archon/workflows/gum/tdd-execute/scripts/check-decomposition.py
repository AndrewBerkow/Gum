"""Deterministic gate: tasks.json must hold 3-5 well-formed tasks."""
import json
import os
import sys
from pathlib import Path

REQUIRED = ["id", "title", "goal", "depends_on", "acceptance_criteria", "integration_test_command"]

path = Path(os.environ["ARTIFACTS_DIR"]) / "tasks.json"
if not path.is_file():
    sys.exit(f"missing {path}: decompose must write it")

tasks = json.loads(path.read_text())["tasks"]
errors = []
if not 3 <= len(tasks) <= 5:
    errors.append(f"expected 3-5 tasks, got {len(tasks)}")
ids = [t.get("id") for t in tasks]
if len(set(ids)) != len(ids):
    errors.append(f"duplicate task ids: {ids}")
for i, task in enumerate(tasks):
    missing = [k for k in REQUIRED if not task.get(k) and k != "depends_on"]
    if missing:
        errors.append(f"task {i + 1} missing {missing}")
    for dep in task.get("depends_on", []):
        if dep not in ids[:i]:
            errors.append(f"task {task.get('id')} depends on {dep}, which is not an earlier task")

if errors:
    sys.exit("invalid decomposition:\n" + "\n".join(errors))
print(f"{len(tasks)} tasks OK")
