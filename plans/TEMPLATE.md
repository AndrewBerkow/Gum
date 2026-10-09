# <Plan title>

<!-- Copy this file to plans/<NAME>.md, fill it in, commit it, then run:
     archon workflow run tdd-execute --no-worktree --detach --input plan=plans/<NAME>.md "Execute plans/<NAME>.md …"
     See ARCHON.md for the full guide. Delete these comments. -->

**<One task. Don't split it.> | <N tasks, in order.>** One or two sentences: what changes, and why.

`PLAN.md` remains the source of truth for architecture, the §0 dependency facts, and the "NO REAL API KEYS" rules. A real `.env` may exist in the developer's checkout: don't touch it, and make no real API calls. Build and test offline (`JEV_BACKEND=stub CHAT_PROVIDER=fake`, `httpx2.MockTransport`).

**Test file naming:** `tests/integration/test_<prefix>N_*.py` (use a prefix no existing test file uses).

## Task 1: <name>

**Problem / goal.** What's wrong or missing. Be concrete: file paths, line numbers, the exact error text, and how to reproduce it.

**Build.**
- What to change, and where.
- Constraints: "Don't change `create_app()`'s signature", "Keep `/api/devlog`'s default behaviour".
- Permissions, if needed: "**This task may edit `tests/integration/test_x.py`**, for this fix only. Don't weaken any assertion."

**Tests first (`tests/integration/test_<prefix>1_<topic>.py`).**
- An observable behaviour this test proves.
- The edge case or failure path (blocked, error, exactly at the threshold).
- Security or privacy checks, if relevant (e.g. no key appears in any output).

**Test command (keep it fast).**
`uv run pytest tests/integration/test_<prefix>1_<topic>.py <closely related test files> -q`

**Accept when:** the tests above pass, and <any whole-suite condition>.

## Out of scope
- What the agents must NOT do (refactors, unrelated fixes, real API calls).
