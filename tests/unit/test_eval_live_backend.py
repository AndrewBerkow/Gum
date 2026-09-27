"""Unit tests for evals/run_eval.py's `--backend live` and `--judge` gates (t3 / Fix 3).

Both scenarios here have no real key, so the code must fail fast on the ConfigError /
has_real_key check, before any network is touched -- there's nothing to mock.
"""

import pytest

import evals.run_eval as ev


def test_main_backend_live_without_key_returns_1_naming_typesafe_key(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    code = ev.main(["--backend", "live", "--out", str(tmp_path)])

    out = capsys.readouterr()
    assert code == 1
    assert "TYPESAFE_API_KEY" in out.err
    assert "not available yet" not in out.err.lower()
    assert not list(tmp_path.glob("*.md")), "no report should be written on failure"


def test_main_judge_without_google_key_returns_1_naming_google_key_before_building_classifier(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts_live_test123")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    calls = []
    monkeypatch.setattr(
        "app.providers.build_classifier", lambda settings: calls.append(settings) or object()
    )

    code = ev.main(["--backend", "live", "--judge", "--out", str(tmp_path)])

    out = capsys.readouterr()
    assert code == 1
    assert "GOOGLE_API_KEY" in out.err
    assert calls == [], "the judge gate must fail before any classifier is built"
    assert not list(tmp_path.glob("*.md"))
