# Plans

Every plan used to build Gum with Archon's `tdd-execute` workflow, in order. Read them as worked examples of what to put in a plan, and of how a run can go wrong. **To write a new one, start from [`TEMPLATE.md`](TEMPLATE.md)** and follow [`../ARCHON.md`](../ARCHON.md).

The original specification, [`../PLAN.md`](../PLAN.md), stays at the repo root: it's the architecture and rules every plan refers to, and some tests read it.

| Plan | What it did | How the run went |
|---|---|---|
| [`../PLAN.md`](../PLAN.md) | The whole app: the Jev guardrail and routing, the LangGraph graph, SSE, the terminal UI, the eval harness | 5 tasks, all green on the first validation (~31 min). T13 was deferred because no API keys were available. |
| [`FIX_PLAN.md`](FIX_PLAN.md) | The module-level `app.main:app`, tests writing into the repo, the T13 live-test scaffolding | 3 tasks, all green on the first try. The summary flagged a real `--judge` order-flip bug. |
| [`FIX_PLAN_2.md`](FIX_PLAN_2.md) | Offline tests must never read your `.env`, live paths must read it, judge correctness | Failed twice on **workflow** bugs: a 2-minute script timeout, and an empty-output failure from resuming a huge session. Both are fixed in the workflow now. Fix 4 landed. |
| [`FIX_PLAN_3.md`](FIX_PLAN_3.md) | Self-cleaning fake `.env`, no test may require that `.env` is absent | Cancelled after task 1 to cut scope. |
| [`FIX_PLAN_4.md`](FIX_PLAN_4.md) | Suite green with and without a real `.env` (two test-only bugs) | 1 task, green on the first validation. The first run to use a single task. |
| [`FEATURE_PLAN.md`](FEATURE_PLAN.md) | **The live Jev dev console**: `/api/devlog` stream, decision explanations, the split-panel UI | Tasks 1–2 green. Task 3 halted: a bug in its own test (a Playwright argument passed positionally) that the fix loop isn't allowed to edit. |
| [`FEATURE_PLAN_2.md`](FEATURE_PLAN_2.md) | Fix that test helper, the README demo section, a conftest test fix | Both done. The run then timed out re-running slow tests after validation had passed, so a workflow fix now skips that rerun. |
| [`FEATURE_PLAN_3.md`](FEATURE_PLAN_3.md) | The console clears on reload, plus a Clear button | 19 of 20 tests green. The 1 failure was again a test-helper bug (a stream read twice). |
| [`FEATURE_PLAN_3B.md`](FEATURE_PLAN_3B.md) | Fix that helper | All tests pass. Validation timed out because the console tests are slow. |

Patterns worth copying: concrete evidence in the problem statement, an explicit fast test command, explicit permission to edit a specific test, and an "Out of scope" list.
