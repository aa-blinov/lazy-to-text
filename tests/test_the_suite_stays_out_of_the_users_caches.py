"""The suite must not reach the user's caches.

The models the app downloads live under ``$HOME``, and a test that reached
them could delete them. The session therefore runs in a scratch home (see
``conftest.py``). These tests fail if that redirect stops covering one of the
cache roots the app actually uses.
"""

import os
from pathlib import Path


def test_the_home_directory_is_the_scratch_home():
    scratch = Path(os.environ["LAZY_TO_TEXT_TEST_HOME"]).resolve()
    assert Path.home().resolve() == scratch


def test_the_app_cache_root_resolves_inside_the_scratch_home():
    import platformdirs

    scratch = Path(os.environ["LAZY_TO_TEXT_TEST_HOME"]).resolve()
    cache = Path(platformdirs.user_cache_dir("LazyToText", appauthor=False)).resolve()
    assert scratch in cache.parents


def test_the_hugging_face_default_cache_resolves_inside_the_scratch_home():
    scratch = Path(os.environ["LAZY_TO_TEXT_TEST_HOME"]).resolve()
    assert Path("~/.cache/huggingface").expanduser().resolve() == scratch / ".cache" / "huggingface"
