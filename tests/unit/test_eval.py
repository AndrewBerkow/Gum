"""Unit tests for evals/run_eval.py (offline; the classifier is an in-process fake)."""

import pytest

import evals.run_eval as ev


def test_parse_sweep_expands_inclusive_range():
    assert ev.parse_sweep("0.5:0.7:0.1") == pytest.approx([0.5, 0.6, 0.7])


def test_parse_sweep_rejects_malformed_spec():
    for bad in ("0.5", "0.5:0.9", "a:b:c", "0.9:0.5:0.1", "0.5:0.9:0"):
        with pytest.raises(ValueError):
            ev.parse_sweep(bad)


def _write(tmp_path, *rows):
    import json

    p = tmp_path / "d.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n")
    return p


def _item(id="a", **kw):
    base = {"id": id, "text": "hi", "expect_gate": "pass", "expect_tier": "simple", "notes": ""}
    base.update(kw)
    return base


def test_load_dataset_parses_valid_items_and_skips_blank_lines(tmp_path):
    items = ev.load_dataset(_write(tmp_path, _item("a"), _item("b", context=["q", "a"])))
    assert [i["id"] for i in items] == ["a", "b"]


@pytest.mark.parametrize(
    "bad",
    [
        _item(expect_gate="bogus"),
        _item(expect_tier=None),  # pass needs a tier
        _item(expect_gate="unsafe"),  # non-pass must not carry a tier
        _item(text=""),
        _item(context="not a list"),
    ],
)
def test_load_dataset_rejects_schema_violations(tmp_path, bad):
    with pytest.raises(ValueError):
        ev.load_dataset(_write(tmp_path, bad))


def test_load_dataset_rejects_duplicate_ids(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        ev.load_dataset(_write(tmp_path, _item("a"), _item("a")))
