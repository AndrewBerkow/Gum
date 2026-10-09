# Building Gum with Archon

Almost all of the code in this repo was written by AI agents running in **[Archon](https://github.com/coleam00/Archon)**, an open-source engine that runs AI coding workflows defined as DAGs (graphs of steps). A human wrote plans; Archon turned each plan into tests and code through a fixed, test-first workflow, with deterministic gates between the AI steps.

This guide shows how to keep building on Gum the same way. It covers installing Archon, writing a plan, running the workflow, watching it, and what to do when a run fails. It also lists what we learned from 9 real runs, including the ones that broke.

> **Why bother?** A workflow gives you more than "ask an agent to build it": every task goes through *tests first → proven red → implement → validate → bounded fix loop → diagnose and halt*. Python scripts (not the model) decide whether the tests pass, so the agent can't declare victory on its own.

---

## 1. Setup

**You need:**
- **Python 3.12+ and [uv](https://docs.astral.sh/uv/)**: Gum's toolchain.
- **[Claude Code](https://claude.com/claude-code)**, installed and logged in (`curl -fsSL https://claude.ai/install.sh | bash`, then run `claude` once). Archon starts `claude` processes for its AI steps, which run on your Claude subscription or API key.
- **The Archon CLI**: `curl -fsSL https://archon.diy/install | bash` (or `brew install coleam00/archon/archon`). See the [Archon README](https://github.com/coleam00/Archon) for other options.

**Then, from a clone of this repo:**
```bash
uv sync
uv run playwright install chromium      # browser tests
archon doctor                           # checks Claude, git and the database
archon workflow list | grep tdd-execute # the workflow this repo ships
archon workflow test tdd-execute        # its dry-run fixtures: no AI calls, no cost
archon skill install                    # optional: teaches Claude Code how to drive Archon
```

`archon skill install` adds an `archon-cli` skill to `.claude/skills/` (gitignored). After that, you can ask Claude Code things like "write a plan for X and run it through Archon" or "what's my Archon run doing?".

**Optional, a live monitor:**
```bash
ln -s "$PWD/tools/archon-watch" ~/.local/bin/archon-watch
```

**API keys are not needed to build.** Every task is developed and tested offline against stubs and mocks (see `PLAN.md`, "NO REAL API KEYS"). Keys only matter for running the app live; see the README.

---

## 2. The workflow: `tdd-execute`

Located at `.archon/workflows/gum/tdd-execute/`. It takes a plan file and runs:

```
decompose (Opus) ──► check-decomposition (script: 1-5 well-formed tasks?)
                              │
          ┌───────────────────▼──── for each task (loop, max 5) ─────────────────────┐
          │ pick-task                    (script: next unfinished task)              │
          │ integration-tests  (Sonnet)  write top-level tests only, no code         │
          │ commit-tests                 (bash: commit them)                         │
          │ tests-red                    (script: tests MUST fail before any code)   │
          │ implement          (Sonnet)  micro-tasks, each red → green → refactor    │
          │ validate-1                   (script: run the task's test command)       │
          │   fix-1 → validate-2 → fix-2 → validate-3 → fix-3 → validate-4           │
          │                              (runs only while red; up to 3 fixes)        │
          │ diagnose           (Opus)    still red: writes diagnosis.md              │
          │ halt-unless-green            (script: stops the run if still red)        │
          │ summarize          (Opus)    summary.md: results, changes, concerns      │
          │ record-progress              (script: mark done, loop or finish)         │
          └──────────────────────────────────────────────────────────────────────────┘
```

- **Script nodes** (`scripts/*.py`) are the gates. They decide pass or fail from exit codes, never from what the model says.
- **The fix loop may not edit the top-level integration tests.** This is deliberate, so an agent can't make tests pass by weakening them. The flip side is in §6.
- **It runs unattended.** There are no approval gates, so you can start a run and come back later.
- **Models** are set in `.archon/config.yaml`. Code-writing steps use the alias `@coder` (Sonnet 5, the cheaper model). Planning, diagnosing and summarizing use the workflow default `large` (Opus). Change `@coder` there to use a different model.

The workflow is project-specific: its prompts assume `uv` + `pytest` and Gum's rules. To use it elsewhere, copy the folder into another repo's `.archon/workflows/` and adjust the prompts.

---

## 3. Write a plan

A plan is a Markdown file. **Its quality decides the result**: the agents measure everything against it. Start from **[`plans/TEMPLATE.md`](plans/TEMPLATE.md)**. [`plans/`](plans/) has every real plan used to build Gum, with notes on how each run went.

What made plans work here:
1. **State the problem with evidence**: file paths, line numbers, the exact error. "The console test fails" is weak; `test_feat3_console_ui.py:83` raising `TypeError: … takes 2 positional arguments` is strong.
2. **Specify tests first**: name each test file (`tests/integration/test_featN_*.py`) and list what each test must prove.
3. **Give an explicit, fast test command.** Validation reruns it up to 5 times, so a slow command multiplies.
4. **Say what may and may not change**, e.g. "This task may edit `test_x.py`, for this fix only", or "Don't change app code".
5. **Write acceptance criteria and an "Out of scope" list.** Agents expand scope otherwise.
6. **Keep it small.** One task is fine (the workflow allows 1–5). Each task costs a full test-first cycle (about 15–40 minutes).

`PLAN.md` is the project's architecture and rules. New plans should say "`PLAN.md` remains the source of truth" rather than repeat it.

---

## 4. Run it

```bash
git add plans/MY_PLAN.md && git commit -m "Add plan: …"     # runs start from your committed state
archon workflow run tdd-execute --no-worktree --detach \
  --input plan=plans/MY_PLAN.md \
  "Execute plans/MY_PLAN.md using the Archon Execution Framework. PLAN.md remains the source of truth."
```

- `--input plan=…` is the file the `decompose` step reads.
- `--detach` runs it in the background and prints a **run id**.
- `--no-worktree` runs in your checkout and commits to your current branch. Create a branch first if you want to review before merging. If your clone has a GitHub remote, you can drop `--no-worktree` and pass `--branch <name>` for an isolated git worktree instead.
- **Run one workflow at a time per checkout,** and don't edit or restart the app mid-run: the agents are committing into the same files.

---

## 5. Watch it, inspect it, resume it

```bash
archon-watch <run-id>                  # live view: tasks done/current, each step's state (tools/archon-watch)
archon workflow status                 # what's running in this repo
archon workflow get <run-id>           # one run's state
archon workflow logs <run-id>          # full transcript
archon workflow cancel <run-id>        # stop it
archon workflow resume <run-id>        # continue a failed run from its last completed step
```

Each run writes artifacts to `~/.archon/workspaces/<project>/artifacts/runs/<run-id>/`:
- `tasks.md` / `tasks.json`: the decomposition, including anything deferred
- `<task>/integration-tests.md`: which test covers each acceptance criterion
- `<task>/microtasks.md`: the red/green log
- `<task>/validate-*.log`: raw test output
- `<task>/summary.md`: results, files changed, and **concerns** (read these)
- `<task>/diagnosis.md`: written only when a task stays red after 3 fixes

**A completed run doesn't guarantee correct work.** Read the summaries' "Concerns" sections and run the suite yourself.

---

## 6. When a run fails

| Symptom | Cause | What to do |
|---|---|---|
| `halt-unless-green` failed, and `diagnosis.md` says the **test** is broken | The fix loop isn't allowed to edit top-level tests (by design) | Write a one-task plan that explicitly allows that one test fix. This happened 3 times here; see `plans/FEATURE_PLAN_2.md` and `FEATURE_PLAN_3B.md`. |
| A step failed with **exit 143** | A script step hit its timeout (now 30 minutes for test steps) | The test command is too slow. Narrow it in the plan. |
| An AI step produced **"no assistant output"** | Usually resuming a huge previous session | Already fixed: code-writing steps use `context: fresh`. |
| An AI step was rejected around a **usage limit** | Your Claude plan's 5-hour or weekly limit | Wait for the reset, then `archon workflow resume <run-id>`. |
| You **edited the workflow**, then resumed and nothing changed | `resume` reuses the workflow as captured at launch | Start a fresh run after editing `.archon/`. |
| The run left **partial commits** | It failed mid-task | Either keep them and write a follow-up plan that builds on them ("Task X is implemented; finish Y"), or reset to before the run. |

---

## 7. Lessons from building Gum

- **Gates beat trust.** The deterministic checks (tests fail first, tests pass, at most 3 fixes, then halt) caught real problems: tests that already passed before any code existed, fake `.env` files leaking between runs, and a judge that scored the wrong answer.
- **Read the summaries.** The `summarize` step flagged a real bug (the `--judge` order-flip) that every test missed.
- **Tests can be wrong too.** Agents wrote integration tests with harness bugs (a Playwright argument passed positionally, a stream read twice). Because the fix loop can't touch them, each needed a small follow-up plan. That cost is the price of the guarantee in §2.
- **Keep the suite fast.** Tests that run the whole suite inside a test made validation take 20+ minutes and caused timeouts. Prefer targeted test commands in plans.
- **Keys stay out of git and out of tests.** `GUM_ENV_FILE` isolates offline tests from your `.env`; see the README's "Live mode".
- **Small plans finish.** The one-task fix plans were the most reliable runs.

---

## 8. Change the workflow itself

The workflow is a YAML file plus prompts and scripts. Edit them directly, then check:
```bash
archon workflow list                 # load errors show up here
archon workflow test tdd-execute     # dry-run fixtures in fixtures/*.stubs.yaml
```
Dry runs auto-approve gates and run a loop only once, so test real behaviour with a small real run. Archon's own authoring guide: run `archon skill install` and read `.claude/skills/archon-cli/authoring-workflows/`, or see the [Archon repo](https://github.com/coleam00/Archon).
