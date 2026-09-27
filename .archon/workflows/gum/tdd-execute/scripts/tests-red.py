"""Gate: the new integration tests must exist and fail before implementation."""
import os
import subprocess
import sys
from pathlib import Path

cmd = os.environ["INPUTS_TEST_COMMAND"]
log = Path(os.environ["ARTIFACTS_DIR"]) / os.environ["INPUTS_TASK_ID"] / "tests-red.log"
log.parent.mkdir(parents=True, exist_ok=True)
result = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=1700)
log.write_text(f"$ {cmd}\nexit {result.returncode}\n\n{result.stdout}\n{result.stderr}")

if result.returncode == 0:
    sys.exit(f"integration tests already pass before implementation; they are not testing new behavior ({log})")
if result.returncode == 5:  # pytest: no tests collected
    sys.exit(f"no tests collected by '{cmd}' ({log})")
print(f"red as expected (exit {result.returncode})")
