"""Unit test for tests/integration/test_fix7_fake_dotenv_self_heals.py's
`_ROOT_DOTENV_PATH_RE`: the repo-root-.env-writer check must catch the actual offending pattern
(`ROOT / ".env"` immediately used as a `.write_text(...)` target), not merely the string `ROOT /
".env"` occurring anywhere in a file that also happens to call `.write_text(` on something else
entirely (e.g. a docstring that discusses the pattern in prose)."""

from tests.integration.test_fix7_fake_dotenv_self_heals import _ROOT_DOTENV_PATH_RE


_ROOT_NAME = "RO" + "OT"  # split so this file's own source text isn't itself flagged as an offender


def test_regex_matches_root_dotenv_used_directly_as_a_write_text_target():
    offending = f'({_ROOT_NAME} / ".env").write_text("junk")'
    assert _ROOT_DOTENV_PATH_RE.search(offending)


def test_regex_does_not_match_prose_mention_plus_unrelated_write_text_elsewhere():
    prose_plus_unrelated_write = (
        f'not the `{_ROOT_NAME} / ".env"` slash form, as this docstring explains.\n'
        "DOTENV_PATH.write_text(_UNMARKED_DOTENV_CONTENT)\n"
    )
    assert not _ROOT_DOTENV_PATH_RE.search(prose_plus_unrelated_write)
