"""Unit tests for tests.fake_dotenv, the shared helper that is the only way any test may create
a repo-root `.env` (t1 / Fix 7)."""

import pytest

from tests.fake_dotenv import MARKER, fake_dotenv, heal_dotenv


def test_fake_dotenv_writes_marker_first_line_then_fake_keys(tmp_path):
    target = tmp_path / ".env"

    with fake_dotenv(target):
        lines = target.read_text().splitlines()

    assert lines[0] == MARKER
    assert len(lines) > 1, "fake_dotenv must write fake keys after the marker line"


def test_fake_dotenv_raises_file_exists_error_and_does_not_overwrite(tmp_path):
    target = tmp_path / ".env"
    original = "TYPESAFE_API_KEY=ts_live_realuserkey\n"
    target.write_text(original)

    with pytest.raises(FileExistsError):
        with fake_dotenv(target):
            pass

    assert target.read_text() == original


def test_fake_dotenv_removes_created_file_on_exit(tmp_path):
    target = tmp_path / ".env"

    with fake_dotenv(target) as created_path:
        assert created_path == target
        assert target.exists()

    assert not target.exists()


def test_fake_dotenv_removes_created_file_even_on_exception(tmp_path):
    target = tmp_path / ".env"

    with pytest.raises(RuntimeError):
        with fake_dotenv(target):
            assert target.exists()
            raise RuntimeError("boom")

    assert not target.exists()


def test_heal_dotenv_deletes_marked_file(tmp_path):
    target = tmp_path / ".env"
    target.write_text(f"{MARKER}\nTYPESAFE_API_KEY=ts_live_test1234567890abcdef\n")

    heal_dotenv(target)

    assert not target.exists()


def test_heal_dotenv_leaves_unmarked_file_untouched(tmp_path):
    target = tmp_path / ".env"
    target.write_text("TYPESAFE_API_KEY=ts_live_realuserkey\nGOOGLE_API_KEY=AIzaRealUserKey\n")
    before_bytes = target.read_bytes()
    before_mtime = target.stat().st_mtime_ns

    heal_dotenv(target)

    assert target.exists()
    assert target.read_bytes() == before_bytes
    assert target.stat().st_mtime_ns == before_mtime


def test_heal_dotenv_noop_when_path_missing_or_empty(tmp_path):
    missing = tmp_path / "missing.env"
    heal_dotenv(missing)  # must not raise
    assert not missing.exists()

    empty = tmp_path / "empty.env"
    empty.write_text("")
    heal_dotenv(empty)  # must not raise
    assert empty.exists()
    assert empty.read_text() == ""
