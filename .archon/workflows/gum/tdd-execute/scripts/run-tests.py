"""Run the task's integration tests. Reports pass/fail as JSON; with strict, fails the node when red."""
import json
import os
import subprocess
import sys
from pathlib import Path

cmd = os.environ["INPUTS_TEST_COMMAND"]
attempt = os.environ["INPUTS_ATTEMPT"]
strict = os.environ["INPUTS_STRICT"] == "true"
log = Path(os.environ["ARTIFACTS_DIR"]) / os.environ["INPUTS_TASK_ID"] / f"validate-{attempt}.log"

log.parent.mkdir(parents=True, exist_ok=True)
result = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=900)
log.write_text(f"$ {cmd}\nexit {result.returncode}\n\n{result.stdout}\n{result.stderr}")
passed = result.returncode == 0

if strict and not passed:
    sys.exit(f"HALT: integration tests still failing after 3 fix attempts. "
             f"See diagnosis.md and {log}. Fix the code, then `archon workflow resume <run-id>`.")
print(json.dumps({"passed": passed, "log_path": str(log)}))
