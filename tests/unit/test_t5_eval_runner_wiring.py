"""Unit test for the --out tmp_path wiring in test_t5_frontend_e2e.py (t2 / Fix 2).

Loads the real integration test file as an isolated module and stubs out subprocess.run on it,
so the real evals/run_eval.py is never actually invoked from this unit test.
"""

import subprocess

from tests.unit._load_test_module import load


def _load_t5():
    return load(
        "tests/integration/test_t5_frontend_e2e.py", "unit_test_view_of_test_t5_frontend_e2e"
    )


def test_eval_runner_test_passes_out_under_tmp_path(monkeypatch, tmp_path):
    t5 = _load_t5()
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "some output\n", "")

    monkeypatch.setattr(t5.subprocess, "run", fake_run)

    t5.test_eval_runner_stub_backend_produces_report(tmp_path)

    assert len(calls) == 1
    argv = calls[0]
    assert "--out" in argv, f"eval runner must be invoked with --out: {argv}"
    assert argv[argv.index("--out") + 1] == str(tmp_path), (
        f"--out must point at the test's tmp_path, not the real evals/reports/ dir: {argv}"
    )
