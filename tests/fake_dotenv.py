"""The only way any test may create a repo-root `.env` (t1 / Fix 7).

`fake_dotenv(path)` creates `path` with a marked first line, only if `path` doesn't already
exist, and removes it (only if it created it) when the `with` block exits -- even if the process
is later killed before that `finally` runs, the marker lets a fresh top-level pytest session heal
it via `heal_dotenv`. `heal_dotenv(path)` never deletes a file whose first line isn't exactly the
marker, so a real user `.env` is never at risk.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MARKER = "# GUM-TEST-FAKE-ENV: created by the test suite; safe to delete"

_FAKE_TYPESAFE_KEY = "ts_live_test1234567890abcdef"
_FAKE_GOOGLE_KEY = "AIzaTEST1234567890abcdefghijklmnopqrs"


@contextmanager
def fake_dotenv(path: Path) -> Iterator[Path]:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite an existing .env at {path}")

    path.write_text(
        f"{MARKER}\nTYPESAFE_API_KEY={_FAKE_TYPESAFE_KEY}\nGOOGLE_API_KEY={_FAKE_GOOGLE_KEY}\n"
    )
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@contextmanager
def dotenv_present(path: Path) -> Iterator[Path]:
    """Ensure a `.env` exists at `path` for the duration of the block: reuse a pre-existing file
    as-is (never modified, never removed), or create one via `fake_dotenv` (and clean it up on
    exit) if none exists."""
    path = Path(path)
    if path.exists():
        yield path
    else:
        with fake_dotenv(path) as created_path:
            yield created_path


def heal_dotenv(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        return
    lines = path.read_text().splitlines()
    if lines and lines[0] == MARKER:
        path.unlink()
