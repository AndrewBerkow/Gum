"""Unit tests for tests.fake_dotenv, the shared helper that is the only way any test may create
a repo-root `.env` (t1 / Fix 7)."""

import pytest

from tests.fake_dotenv import MARKER, fake_dotenv


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
