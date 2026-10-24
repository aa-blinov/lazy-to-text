"""What the runtime will write or read on a caller's word (QA-SEC-14, QA-RUNTIME-21).

``files.save_text`` and ``history.export`` used to write to any string:
through a link onto another file, over a device, relative to the process's
working directory (inside the installation, when packaged).
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from app.history_manager import HistoryManager
from app.server.handlers import files, history as history_handlers
from app.server.rpc import RpcError


def _rt(tmp_path, **over):
    base = dict(
        config=SimpleNamespace(
            config_path=tmp_path / "cfg" / "config.yaml",
            get_setting=lambda section, key: None,
        ),
        log_path=str(tmp_path / "logs" / "app.log"),
        history=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _save(rt, path, text="words", **extra):
    return files.save_text(rt, {"path": str(path), "text": text, **extra})


def _refused(rt, path):
    with pytest.raises(RpcError) as err:
        _save(rt, path)
    assert err.value.code == "bad_path"
    return err.value


def test_a_normal_save_writes_and_replaces_the_file(tmp_path):
    rt = _rt(tmp_path)
    target = tmp_path / "out.txt"

    assert _save(rt, target, "one") == {"saved": str(target)}
    assert _save(rt, target, "two", overwrite=True) == {"saved": str(target)}

    assert target.read_text(encoding="utf-8") == "two"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


@pytest.mark.parametrize("name", ["out.txt", "OUT.TXT", "notes.md", "a b.text"])
def test_the_text_extensions_are_accepted(tmp_path, name):
    assert _save(_rt(tmp_path), tmp_path / name)["saved"].endswith(name)


@pytest.mark.parametrize("name", ["out", "out.plist", "out.sh", "run.command", ".txt"])
def test_anything_that_is_not_a_text_file_is_refused(tmp_path, name):
    _refused(_rt(tmp_path), tmp_path / name)
    assert not (tmp_path / name).exists()


def test_a_relative_path_is_never_written_to_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rt = _rt(tmp_path)

    for raw in ("rel_out.txt", "../escape_out.txt", "~/out.txt", "./x.txt"):
        with pytest.raises(RpcError) as err:
            files.save_text(rt, {"path": raw, "text": "x"})
        assert err.value.code == "bad_path"
    assert list(tmp_path.glob("*.txt")) == []


def test_a_link_is_not_followed_onto_another_file(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("ORIGINAL")
    link = tmp_path / "link.txt"
    link.symlink_to(victim)

    _refused(_rt(tmp_path), link)

    assert victim.read_text() == "ORIGINAL"


def test_a_link_in_the_folder_chain_into_the_apps_own_folder_is_refused(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    sneaky = tmp_path / "sneaky"
    sneaky.symlink_to(logs, target_is_directory=True)

    _refused(_rt(tmp_path), sneaky / "x.txt")

    assert list(logs.iterdir()) == []


def test_a_folder_a_fifo_and_a_missing_folder_are_refused(tmp_path):
    rt = _rt(tmp_path)
    (tmp_path / "dir.txt").mkdir()
    _refused(rt, tmp_path / "dir.txt")
    if hasattr(os, "mkfifo"):
        os.mkfifo(tmp_path / "pipe.txt")
        _refused(rt, tmp_path / "pipe.txt")
    _refused(rt, tmp_path / "nope" / "x.txt")


@pytest.mark.skipif(sys.platform == "win32", reason="device nodes are POSIX")
def test_a_device_is_refused():
    with pytest.raises(RpcError) as err:
        files.save_text(None, {"path": "/dev/null", "text": "x"})
    assert err.value.code == "bad_path"


def test_the_apps_own_folders_are_refused(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "cfg").mkdir()
    (tmp_path / "models" / "hub").mkdir(parents=True)
    rt = _rt(tmp_path)
    rt.config.get_setting = lambda section, key: str(tmp_path / "models") \
        if (section, key) == ("storage", "models_dir") else None

    _refused(rt, tmp_path / "logs" / "x.txt")
    _refused(rt, tmp_path / "logs" / "deeper" / "x.txt")
    _refused(rt, tmp_path / "cfg" / "x.txt")
    _refused(rt, tmp_path / "models" / "hub" / "x.txt")
    assert _save(rt, tmp_path / "elsewhere.txt")["saved"]


def test_control_characters_and_oversized_paths_are_refused(tmp_path):
    rt = _rt(tmp_path)
    _refused(rt, str(tmp_path / "a\nb.txt"))
    _refused(rt, str(tmp_path / "a\x00b.txt"))
    _refused(rt, str(tmp_path) + "/" + "a" * 5000 + ".txt")


def test_a_failed_write_keeps_the_previous_file(tmp_path, monkeypatch):
    rt = _rt(tmp_path)
    target = tmp_path / "keep.txt"
    target.write_text("PREVIOUS")

    def explode(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(RpcError) as err:
        _save(rt, target, "new", overwrite=True)

    assert err.value.code == "write_failed"
    assert str(tmp_path) not in err.value.message
    assert target.read_text() == "PREVIOUS"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


# ---- an existing file is not replaced silently (QA-SEC-R2) ---------------------


def test_an_existing_file_is_not_replaced_unless_the_caller_says_so(tmp_path):
    rt = _rt(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("MINE")

    with pytest.raises(RpcError) as err:
        _save(rt, victim, "overwritten")
    assert err.value.code == "exists" and err.value.field == "path"
    assert victim.read_text() == "MINE"

    with pytest.raises(RpcError) as err:
        _save(rt, victim, "overwritten", overwrite="yes")
    assert err.value.code == "bad_params"
    assert victim.read_text() == "MINE"

    _save(rt, victim, "replaced", overwrite=True)
    assert victim.read_text() == "replaced"


def test_a_path_through_dots_or_a_linked_folder_is_still_an_existing_file(tmp_path):
    rt = _rt(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("MINE")
    (tmp_path / "sub").mkdir()
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)

    for route in (tmp_path / "sub" / ".." / "victim.txt", tmp_path / "link" / "victim.txt"):
        with pytest.raises(RpcError) as err:
            _save(rt, route)
        assert err.value.code == "exists"
    assert victim.read_text() == "MINE"


def test_history_export_does_not_replace_a_file_either(tmp_path, store):
    rt = _rt(tmp_path, history=store)
    target = tmp_path / "out.txt"
    target.write_text("MINE")

    with pytest.raises(RpcError) as err:
        history_handlers.export(rt, {"path": str(target)})

    assert err.value.code == "exists"
    assert target.read_text() == "MINE"


# ---- the installation is not a place to write (QA-SEC-R2) ----------------------


def test_the_applications_own_installation_is_refused(tmp_path, monkeypatch):
    bundle = tmp_path / "Apps" / "Lazy to Text.app" / "Contents" / "Resources"
    backend = bundle / "backend"
    backend.mkdir(parents=True)
    unpacked = tmp_path / "unpacked"
    unpacked.mkdir()
    monkeypatch.setattr(sys, "executable", str(backend / "server"))
    monkeypatch.setattr(sys, "_MEIPASS", str(unpacked), raising=False)
    rt = _rt(tmp_path)

    for folder in (bundle, backend, bundle.parent, unpacked, unpacked / "app"):
        folder.mkdir(parents=True, exist_ok=True)
        err = _refused(rt, folder / "zz-probe.txt")
        assert "installed application" in err.message or "system" in err.message
        assert not (folder / "zz-probe.txt").exists()


def test_any_app_bundle_is_refused_by_its_name(tmp_path):
    other = tmp_path / "Other.app" / "Contents"
    other.mkdir(parents=True)

    _refused(_rt(tmp_path), other / "x.txt")


@pytest.mark.skipif(os.name == "nt", reason="POSIX roots")
@pytest.mark.parametrize("path", ["/Applications/x.txt", "/usr/local/x.txt",
                                  "/System/x.txt", "/etc/x.txt", "/Library/x.txt"])
def test_the_system_roots_are_refused_before_anything_is_touched(tmp_path, path):
    _refused(_rt(tmp_path), path)


def test_the_app_package_itself_is_refused():
    import app

    from pathlib import Path

    package = Path(app.__file__).resolve().parent
    err = _refused(_rt(package.parent), package / "zz-probe.txt")
    assert "installed" in err.message


# ---- history.export goes through the same gate ---------------------------------


@pytest.fixture
def store(tmp_path):
    manager = HistoryManager(max_entries=10, history_file=str(tmp_path / "logs" / "h.jsonl"))
    manager.add_entry("first", 1.0, "m", "ru")
    return manager


def test_export_refuses_a_link_a_relative_path_and_the_history_file_itself(tmp_path, store):
    rt = _rt(tmp_path, history=store)
    victim = tmp_path / "victim.txt"
    victim.write_text("ORIGINAL")
    link = tmp_path / "link.txt"
    link.symlink_to(victim)

    for raw in (str(link), "rel.txt", str(store.history_file)):
        with pytest.raises(RpcError) as err:
            history_handlers.export(rt, {"path": raw})
        assert err.value.code == "bad_path"
    assert victim.read_text() == "ORIGINAL"


def test_export_replaces_an_existing_file_whole(tmp_path, store):
    rt = _rt(tmp_path, history=store)
    target = tmp_path / "out.txt"
    target.write_text("x" * 10_000)

    result = history_handlers.export(rt, {"path": str(target), "overwrite": True})

    assert result == {"exported": 1, "path": str(target)}
    assert target.read_text(encoding="utf-8").startswith("Transcription History Export")


# ---- files.transcribe reads only what it should --------------------------------


def test_transcribe_refuses_relative_paths_folders_and_pipes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    rt = SimpleNamespace(state_manager=None, stack_error=None)

    for raw in ("a.wav", "../a.wav"):
        with pytest.raises(RpcError) as err:
            files.transcribe(rt, {"path": raw})
        assert err.value.code == "bad_path"
    (tmp_path / "folder.wav").mkdir()
    with pytest.raises(RpcError) as err:
        files.transcribe(rt, {"path": str(tmp_path / "folder.wav")})
    assert err.value.code == "not_found"
    if hasattr(os, "mkfifo"):
        os.mkfifo(tmp_path / "pipe.wav")
        with pytest.raises(RpcError) as err:
            files.transcribe(rt, {"path": str(tmp_path / "pipe.wav")})
        assert err.value.code == "not_found"


# ---- QA-RUNTIME-F4, QA-SEC-F1: the check looks at where the write lands --------------


@pytest.mark.parametrize("route", ["missing/../victim.txt", "a/b/../../victim.txt",
                                   "missing/./../victim.txt"])
def test_a_missing_folder_and_dotdot_is_still_the_existing_file(tmp_path, route):
    rt = _rt(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("ORIGINAL")

    with pytest.raises(RpcError) as err:
        _save(rt, str(tmp_path) + "/" + route)

    assert err.value.code == "exists"
    assert victim.read_text() == "ORIGINAL"


def test_a_missing_folder_and_dotdot_to_a_new_name_writes_where_it_resolves(tmp_path):
    rt = _rt(tmp_path)
    _save(rt, str(tmp_path) + "/missing/../fresh.txt")
    assert (tmp_path / "fresh.txt").read_text() == "words"
    assert not (tmp_path / "missing").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX roots")
@pytest.mark.parametrize("path", ["/applications/x.txt", "/APPLICATIONS/x.txt",
                                  "/library/x.txt", "/Usr/local/x.txt"])
def test_the_system_roots_are_refused_whatever_the_case(tmp_path, monkeypatch, path):
    # The volumes of macOS and Windows ignore case; the check must too.
    monkeypatch.setattr("app.server.safe_paths.CASE_INSENSITIVE", True)
    err = _refused(_rt(tmp_path), path)
    assert "installed application or the system" in err.message


def test_the_apps_own_folders_are_refused_whatever_the_case(tmp_path, monkeypatch):
    monkeypatch.setattr("app.server.safe_paths.CASE_INSENSITIVE", True)
    rt = _rt(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()

    _refused(rt, str(logs).upper() + "/x.txt")
    _refused(rt, str(logs.parent / "LOGS" / "x.txt"))


def test_the_per_user_app_folders_are_refused_even_when_this_run_uses_others(tmp_path):
    from platformdirs import user_cache_dir, user_config_dir, user_log_dir

    rt = _rt(tmp_path)
    for factory in (user_config_dir, user_log_dir, user_cache_dir):
        folder = os.path.join(factory("LazyToText", appauthor=False), "deep")
        os.makedirs(folder, exist_ok=True)
        _refused(rt, os.path.join(folder, "x.txt"))
    shell = user_config_dir("Lazy to Text", appauthor=False)
    os.makedirs(shell, exist_ok=True)
    _refused(rt, os.path.join(shell, "x.txt"))


def test_the_data_dir_named_on_the_command_line_is_refused(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "anything").mkdir(parents=True)
    monkeypatch.setenv("L2T_DATA_DIR", str(data))

    _refused(_rt(tmp_path), data / "anything" / "x.txt")
