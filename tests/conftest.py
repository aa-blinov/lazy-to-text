import os
import sys
from pathlib import Path

import pytest

# ``onnx_backend`` binds ``numpy`` when it is first imported. Some backend
# tests swap ``sys.modules["numpy"]`` for a stub, and whichever worker
# imported the module first under that stub kept it for good, so the load
# probe's ``np.zeros`` failed in a different test on every parallel run.
import app.backends.onnx_backend  # noqa: E402,F401


@pytest.fixture(autouse=True, scope="session")
def _the_suite_runs_in_a_scratch_home(tmp_path_factory):
    """Every cache the app reads or writes lives under ``$HOME``: the models
    (``~/Library/Caches/LazyToText``), the Hugging Face hub
    (``~/.cache/huggingface``), the icons and the single-instance lock. A
    test that reaches one of them must reach a scratch copy, never the
    weights a user has already downloaded.

    The login keychain is linked in from the real home: the signing tests
    need the identity. It is not a cache, and nothing here writes to it.
    """
    real_home = Path(os.path.expanduser("~"))
    home = tmp_path_factory.mktemp("home")
    for name in ("Library/Keychains",):
        source = real_home / name
        if source.exists():
            link = home / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(source, target_is_directory=True)
    previous = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    os.environ["LAZY_TO_TEXT_TEST_HOME"] = str(home)

    # Windows does not read ``HOME``. ``Path.home()`` comes from
    # ``USERPROFILE`` there, and ``platformdirs`` puts the app's cache
    # under ``LOCALAPPDATA`` — so on the Windows leg the redirect above
    # was a no-op and the suite ran against the real user profile, with
    # the three tests that check this guard failing. Measured on the
    # runner: the home directory resolved to ``C:/Users/runneradmin``
    # while the guard expected the scratch copy.
    win_env = {
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
    }
    saved_win = {key: os.environ.get(key) for key in win_env}
    if sys.platform == "win32":
        os.environ.update(win_env)

    try:
        yield home
    finally:
        os.environ.pop("LAZY_TO_TEXT_TEST_HOME", None)
        for key, value in saved_win.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if previous is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous
