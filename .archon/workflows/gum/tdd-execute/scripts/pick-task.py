"""Select the first task not yet recorded as done."""
import json
import os
import sys
from pathlib import Path

artifacts = Path(os.environ["ARTIFACTS_DIR"])
tasks = json.loads((artifacts / "tasks.json").read_text())["tasks"]
progress = artifacts / "progress.json"
done = json.loads(progress.read_text())["done"] if progress.is_file() else []

for index, task in enumerate(tasks, start=1):
    if task["id"] not in done:
        (artifacts / task["id"]).mkdir(exist_ok=True)
        print(json.dumps({
            "index": index,
            "task_id": task["id"],
            "title": task["title"],
            "test_command": task["integration_test_command"],
            "total": len(tasks),
        }))
        sys.exit(0)

sys.exit("no remaining tasks; the loop should have stopped")
