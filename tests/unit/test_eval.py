"""Unit tests for evals/run_eval.py (offline; the classifier is an in-process fake)."""

import pytest

import evals.run_eval as ev


def test_parse_sweep_expands_inclusive_range():
    assert ev.parse_sweep("0.5:0.7:0.1") == pytest.approx([0.5, 0.6, 0.7])


def test_parse_sweep_rejects_malformed_spec():
    for bad in ("0.5", "0.5:0.9", "a:b:c", "0.9:0.5:0.1", "0.5:0.9:0"):
        with pytest.raises(ValueError):
            ev.parse_sweep(bad)
