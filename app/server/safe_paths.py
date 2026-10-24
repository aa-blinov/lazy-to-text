"""Which paths the runtime will read or write on a caller's word.

The runtime holds the user's words and runs with the user's rights, and any
caller with the channel token can name a path. A save dialog is the only
thing that should produce one, so what comes back is checked as if it had
not: a full path, a text extension, a regular file (or nothing yet) that is
not a link, nowhere inside the application's own folders or its
installation, and not over an existing file unless the caller says so. The text
extension is what takes the sting out of "write attacker-chosen content to a
chosen path": a text file is not a LaunchAgent, a shell profile or an
executable.

Every refusal is ``bad_path`` with a sentence a person can act on, and none
of them quotes the path back with an operating-system error attached.
"""

from __future__ import annotations

import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Any, Iterable, List

from app.server.rpc import RpcError

#: What a transcript or an export may be called.
TEXT_EXTS = (".txt", ".md", ".markdown", ".text")

_MAX_PATH = 4096


def _bad(message: str) -> RpcError:
    return RpcError("bad_path", message, field="path")


_RELATIVE_OUT = (
    "Choose a file with the save dialog. A short or relative name would be "
    "written next to the app instead of where you expect."
)
_RELATIVE_IN = "That is not a full path to a file."


def _clean(raw: Any, relative_message: str = _RELATIVE_OUT) -> str:
    if not isinstance(raw, str):
        raise RpcError("bad_params", "path must be text", field="path")
    text = raw.strip()
    if not text:
        raise RpcError("bad_params", "missing parameter: path", field="path")
    if len(text) > _MAX_PATH:
        raise _bad("That path is too long.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise _bad("That path contains characters a file name cannot have.")
    if not os.path.isabs(text):
        raise _bad(relative_message)
    return text


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return Path(os.path.abspath(path))


#: macOS and Windows volumes ignore case by default, so ``/applications`` is
#: ``/Applications`` there. Folded names catch it for a path that does not
#: exist yet; ``samefile`` below catches it for one that does, on any system.
CASE_INSENSITIVE = sys.platform in ("darwin", "win32")


def _fold(path: Any) -> str:
    text = os.path.normcase(os.path.normpath(str(path)))
    return text.lower() if CASE_INSENSITIVE else text


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _inside(path: Path, folder: Path) -> bool:
    """Whether ``path`` is ``folder`` or below it, by name and by identity."""
    fp, ff = _fold(path), _fold(folder)
    try:
        if os.path.commonpath([fp, ff]) == ff:
            return True
    except ValueError:  # different drives
        pass
    for ancestor in (path, *path.parents):
        if ancestor.exists() and _same_file(ancestor, folder):
            return True
    return False


def _same(a: Path, b: Path) -> bool:
    return _fold(a) == _fold(b) or (a.exists() and b.exists() and _same_file(a, b))


def protected_files(rt: Any) -> List[Path]:
    """Individual files the app owns: the config and the history."""
    found: List[Path] = []
    config_path = getattr(getattr(rt, "config", None), "config_path", None)
    history_file = getattr(getattr(rt, "history", None), "history_file", None)
    for raw in (config_path, history_file):
        if raw:
            found.append(_resolved(Path(str(raw))))
    return found


def protected(rt: Any) -> List[tuple[Path, bool]]:
    """``(folder, recursive)`` pairs the app keeps its own files in.

    The config folder is protected for the files directly in it only: in a
    development checkout it is the project root, and the whole tree is not
    the application's data. Logs, history and the model weights are
    protected at any depth.
    """
    found: List[tuple[Path, bool]] = []

    def add(raw: Any, recursive: bool) -> None:
        if raw:
            found.append((_resolved(Path(str(raw))), recursive))

    config_path = getattr(getattr(rt, "config", None), "config_path", None)
    if config_path:
        add(Path(str(config_path)).parent, False)
    log_path = getattr(rt, "log_path", "")
    if log_path:
        add(Path(str(log_path)).parent, True)
    try:
        from app.utils import get_models_root

        configured = None
        cfg = getattr(rt, "config", None)
        if cfg is not None:
            configured = cfg.get_setting("storage", "models_dir")
        add(get_models_root(configured if isinstance(configured, str) else None), True)
    except Exception:  # pragma: no cover - defensive
        pass
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        add(hf_home, True)
    # The app's own per-user folders, whichever of them this run uses: the
    # runtime's config, log and cache folders, the folder named by
    # ``--data-dir``, and the shell's own profile (Electron ``userData``).
    try:
        from platformdirs import user_cache_dir, user_config_dir, user_log_dir

        for factory in (user_config_dir, user_log_dir, user_cache_dir):
            add(factory("LazyToText", appauthor=False), True)
        add(user_config_dir("Lazy to Text", appauthor=False), True)
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        from app.utils import data_dir_override

        add(data_dir_override(), True)
    except Exception:  # pragma: no cover - defensive
        pass
    return found


#: Where the system and installed applications live. Nothing is written
#: there on a caller's word: a file added inside a signed bundle breaks its
#: seal, and the rest is not the user's document folder either.
_POSIX_SYSTEM_ROOTS = (
    "/System", "/usr", "/bin", "/sbin", "/etc", "/Library", "/Applications",
)
_WINDOWS_SYSTEM_VARS = (
    "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData",
    "SystemRoot", "windir",
)


def installation_folders() -> List[Path]:
    """Folders the running application and the system are installed in.

    The folder of the interpreter (the whole bundle when it sits inside a
    ``.app``), PyInstaller's unpack folder, the ``app`` package itself in a
    development checkout, and the system roots of the platform.
    """
    found: List[Path] = []

    def add(raw: Any) -> None:
        if raw:
            found.append(_resolved(Path(str(raw))))

    try:
        exe = _resolved(Path(sys.executable))
        add(exe.parent)
        for parent in exe.parents:
            if parent.suffix.lower() == ".app":
                add(parent)
    except Exception:  # pragma: no cover - defensive
        pass
    add(getattr(sys, "_MEIPASS", None))
    try:
        import app as package

        add(Path(package.__file__).resolve().parent)
    except Exception:  # pragma: no cover - defensive
        pass
    if os.name == "nt":
        for name in _WINDOWS_SYSTEM_VARS:
            add(os.environ.get(name))
    else:
        for root in _POSIX_SYSTEM_ROOTS:
            add(root)
    return found


def check_output_path(
    rt: Any, raw: Any, *, extensions: Iterable[str] = TEXT_EXTS,
    overwrite: bool = False,
) -> Path:
    """The file to write, or ``RpcError`` saying why it will not be.

    An existing file is replaced only when the caller says ``overwrite``.
    The flag is the caller's word, not proof: the renderer sets it only after
    the native save dialog has asked the user about that very file, and the
    runtime cannot tell a dialog's answer from a call that says ``true``
    (see ``contract.md``). What this check does guarantee is that an
    accident - a path that merely happens to name something - is refused.
    """
    text = _clean(raw)
    allowed = tuple(extensions)
    if not text.lower().endswith(allowed):
        names = ", ".join(allowed[:-1]) + " or " + allowed[-1]
        raise _bad(f"Choose a text file name that ends in {names}.")
    name = os.path.basename(text)
    if not name or name.startswith(".") and Path(name).suffix == "":
        raise _bad("That is not a file name.")

    # Everything below looks at the place the write would really land: the
    # folder is resolved (links followed, ``..`` applied after the links, so
    # ``<dir>/missing/../victim.txt`` is ``<dir>/victim.txt``) before the
    # existence check, not after it. The name stays unresolved, because a
    # link as the last part is a refusal of its own.
    parent = _resolved(Path(os.path.dirname(text)))
    target = parent / name
    if any(part.lower().endswith(".app") for part in target.parts[:-1]):
        raise _bad("That folder belongs to an installed application. "
                   "Choose another place.")
    for folder in installation_folders():
        if _inside(target, folder):
            raise _bad("That folder belongs to an installed application or "
                       "the system. Choose another place.")
    if not parent.is_dir():
        raise _bad("The folder for that file does not exist.")

    try:
        info = os.lstat(target)
    except FileNotFoundError:
        info = None
    except OSError:
        raise _bad("That file cannot be reached.") from None
    if info is not None:
        if stat.S_ISLNK(info.st_mode):
            raise _bad("That name is a shortcut to another file. Choose the file itself.")
        if stat.S_ISDIR(info.st_mode):
            raise _bad("That is a folder, not a file.")
        if not stat.S_ISREG(info.st_mode):
            raise _bad("That is not an ordinary file.")

    if any(_same(target, owned) for owned in protected_files(rt)):
        raise _bad("That file belongs to the app. Choose another name.")
    for folder, recursive in protected(rt):
        if recursive and _inside(target, folder):
            raise _bad("That folder belongs to the app. Choose another place.")
        if not recursive and _same(target.parent, folder):
            raise _bad("That folder belongs to the app. Choose another place.")
    if info is not None and not overwrite:
        raise RpcError(
            "exists",
            "A file with that name already exists. Choose another name, or "
            "confirm that it may be replaced.",
            field="path",
        )
    return target


def check_input_path(raw: Any) -> str:
    """A file that exists, is an ordinary readable file, and is named in full.

    Returned exactly as given: the renderer pairs results with the path it
    sent, so a normalised spelling would stop matching.
    """
    text = _clean(raw, _RELATIVE_IN)
    try:
        info = os.stat(text)
    except FileNotFoundError:
        raise RpcError("not_found", "That file is no longer there.", field="path") from None
    except OSError:
        raise RpcError("not_found", "That file cannot be reached.", field="path") from None
    if not stat.S_ISREG(info.st_mode):
        raise RpcError("not_found", "That is not a file.", field="path")
    if not os.access(text, os.R_OK):
        raise RpcError("not_found", "That file cannot be read.", field="path")
    return text


def replace_atomically(target: Path, write: Any) -> None:
    """Write through a sibling temporary file and rename it into place.

    ``write(tmp_path)`` produces the content. A failure leaves the previous
    file untouched, which opening the target for writing does not.
    """
    tmp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        write(tmp)
        os.replace(tmp, target)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:  # pragma: no cover - defensive
            pass


def os_reason(exc: OSError) -> str:
    """The operating system's own words for a failure, without the path."""
    return (exc.strerror or exc.__class__.__name__).rstrip(".") + "."


__all__ = [
    "TEXT_EXTS", "check_input_path", "check_output_path",
    "installation_folders", "os_reason",
    "protected", "replace_atomically",
]
