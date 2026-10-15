import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True, scope="session")
def _the_suite_runs_in_a_scratch_home(tmp_path_factory):
    """Every cache the app reads or writes lives under ``$HOME``: the models
    (``~/Library/Caches/LazyToText``), the Hugging Face hub
    (``~/.cache/huggingface``), the icons and the single-instance lock. A
    test that reaches one of them must reach a scratch copy, never the
    weights a user has already downloaded.

    Fonts and the login keychain are linked in from the real home: the
    layout tests measure real fonts, and the signing tests need the
    identity. Neither is a cache, and nothing here writes to them.
    """
    real_home = Path(os.path.expanduser("~"))
    home = tmp_path_factory.mktemp("home")
    for name in ("Library/Fonts", "Library/Keychains"):
        source = real_home / name
        if source.exists():
            link = home / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(source, target_is_directory=True)
    previous = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    os.environ["LAZY_TO_TEXT_TEST_HOME"] = str(home)
    try:
        yield home
    finally:
        os.environ.pop("LAZY_TO_TEXT_TEST_HOME", None)
        if previous is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous
