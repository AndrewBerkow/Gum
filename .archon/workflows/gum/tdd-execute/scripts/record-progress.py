"""Mark the task done; report whether any tasks remain."""
import json
import os
from pathlib import Path

artifacts = Path(os.environ["ARTIFACTS_DIR"])
tasks = json.loads((artifacts / "tasks.json").read_text())["tasks"]
progress = artifacts / "progress.json"
done = json.loads(progress.read_text())["done"] if progress.is_file() else []
if os.environ["INPUTS_TASK_ID"] not in done:
    done.append(os.environ["INPUTS_TASK_ID"])
progress.write_text(json.dumps({"done": done}, indent=2))

remaining = [t for t in tasks if t["id"] not in done]
print(json.dumps({"all_done": not remaining, "next_title": remaining[0]["title"] if remaining else ""}))
