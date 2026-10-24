"""What the Electron build is held to.

None of this runs Electron or PyInstaller. It reads the packaging files and
pins the facts that fail silently when they drift: a runtime that is not in
the installer, an entitlements file without the microphone, a Qt import in
the headless runtime that adds hundreds of megabytes, a desktop version that
disagrees with the one the release is tagged with. Each of those builds
green and breaks on a user's machine.
"""

from __future__ import annotations

import ast
import json
import plistlib
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_DESKTOP = _ROOT / "desktop"
_BUILD = _DESKTOP / "build"

AUDIO_INPUT = "com.apple.security.device.audio-input"
NO_LIBRARY_VALIDATION = "com.apple.security.cs.disable-library-validation"


def _builder() -> dict:
    return yaml.safe_load((_DESKTOP / "electron-builder.yml").read_text(encoding="utf-8"))


def _entitlements(name: str) -> dict:
    with (_BUILD / name).open("rb") as handle:
        return plistlib.load(handle)


def _targets(section: dict) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for item in section["target"]:
        found[item["target"]] = list(item["arch"])
    return found


# ---- the runtime is inside the installer ------------------------------------

def test_the_runtime_is_copied_to_the_folder_the_shell_looks_in():
    entry = next(e for e in _builder()["extraResources"] if e["to"] == "backend")
    assert entry["from"].endswith("dist/lazy-to-text-server")

    # backend.cjs resolves resources/backend/lazy-to-text-server[.exe].
    shell = (_DESKTOP / "electron" / "backend.cjs").read_text(encoding="utf-8")
    assert "lazy-to-text-server" in shell
    assert "'backend'" in shell

    spec = (_ROOT / "lazy_to_text_server.spec").read_text(encoding="utf-8")
    assert 'name="lazy-to-text-server"' in spec


def test_the_shell_ships_the_renderer_and_assets_and_nothing_else():
    files = _builder()["files"]
    for needed in ("electron/**/*", "dist-renderer/**/*", "assets/**/*"):
        assert needed in files
    assert not any("node_modules" in f for f in files)


def test_the_three_platforms_each_have_their_targets():
    config = _builder()
    assert set(_targets(config["win"])) == {"nsis", "portable"}
    mac = _targets(config["mac"])
    assert set(mac) == {"dmg", "zip"}
    for archs in mac.values():
        assert set(archs) == {"arm64"}
    assert set(_targets(config["linux"])) == {"AppImage", "deb"}


# The bundle id of the Qt application this one replaces (its py2app
# `CFBundleIdentifier`, and the macOS grants and file associations that are
# keyed to it). Written out rather than read from setup.py, which goes away
# with the Qt build.
QT_APP_ID = "ai.eora.lazytotext"


def test_the_app_id_is_the_same_as_the_application_it_replaces():
    config = _builder()
    assert config["appId"] == QT_APP_ID, (
        "a different id installs next to the Qt build instead of over it, and macOS "
        "drops the Microphone and Accessibility grants that are keyed to the bundle id"
    )
    assert config["productName"] == "Lazy to Text"


def test_the_single_instance_lock_keeps_the_qt_name():
    # An old build still running, or its login item, must make the new one
    # say "already running" instead of starting a second engine on the same data.
    main = (_ROOT / "app" / "server" / "__main__.py").read_text(encoding="utf-8")
    assert '"LazyToTextQt"' in main


def test_the_windows_installer_offers_to_remove_the_inno_installed_qt_build():
    nsh = (_BUILD / "installer.nsh").read_text(encoding="utf-8")
    assert "!macro customInit" in nsh
    # Inno's AppId (installer/lazy_to_text.iss), with its "_is1" suffix: the
    # key the Qt installer's uninstaller is recorded under.
    assert "{D7B4F3A2-8C5E-4D9F-9A1B-3F2E1D8C7B6A}_is1" in nsh
    assert "UninstallString" in nsh and "InstallLocation" in nsh
    # In place, or Inno's first process exits while a temporary copy is still deleting.
    assert "_?=" in nsh
    # Per-user first (the Inno default), then an all-users install.
    assert nsh.index("l2tRemoveQtBuild HKCU") < nsh.index("l2tRemoveQtBuild HKLM")
    # Silent installs are answered, not blocked on a question nobody can see.
    assert "/SD IDYES" in nsh
    # The installer stays per-user by default.
    assert _builder()["nsis"]["perMachine"] is False


def test_the_icons_the_config_names_exist():
    config = _builder()
    for icon in (config["win"]["icon"], config["mac"]["icon"], config["linux"]["icon"]):
        assert (_DESKTOP / icon).is_file(), icon


def test_the_build_resources_are_not_ignored_by_git():
    # ``build/`` is ignored repository-wide for Python's build output, and
    # that pattern also swallows desktop/build, entitlements included.
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "desktop/build/entitlements.mac.plist"],
            cwd=_ROOT, capture_output=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        pytest.skip("git is unavailable")
    assert result.returncode == 1, "desktop/build is ignored, so the entitlements would not be committed"


# ---- macOS: hardened runtime and entitlements -------------------------------

def test_the_mac_build_is_hardened_and_asks_for_the_microphone():
    mac = _builder()["mac"]
    assert mac["hardenedRuntime"] is True
    assert mac["entitlements"] == "build/entitlements.mac.plist"
    assert mac["entitlementsInherit"]
    description = mac["extendInfo"]["NSMicrophoneUsageDescription"]
    assert description.strip()


@pytest.mark.parametrize("name", [
    "entitlements.mac.plist",
    "entitlements.mac.inherit.plist",
    "entitlements.mac.local.plist",
    "entitlements.mac.local.inherit.plist",
])
def test_every_entitlements_file_allows_the_microphone_and_v8(name):
    # The runtime process opens the input device, so the nested-code file
    # needs the key as much as the app's own.
    keys = _entitlements(name)
    assert keys[AUDIO_INPUT] is True
    assert keys["com.apple.security.cs.allow-jit"] is True


def test_only_the_local_entitlements_switch_library_validation_off():
    """A Developer ID build keeps the protection; the self-signed one cannot.

    A certificate Apple did not issue has no Team ID, so under the hardened
    runtime the app cannot load its own frameworks without the key. Adding
    it to the shipped file turns off a real check for nothing, and the
    local file is the same file plus that one key.
    """
    for strict, local in (
        ("entitlements.mac.plist", "entitlements.mac.local.plist"),
        ("entitlements.mac.inherit.plist", "entitlements.mac.local.inherit.plist"),
    ):
        strict_keys = _entitlements(strict)
        local_keys = _entitlements(local)
        assert NO_LIBRARY_VALIDATION not in strict_keys
        assert local_keys[NO_LIBRARY_VALIDATION] is True
        assert {k: v for k, v in local_keys.items() if k != NO_LIBRARY_VALIDATION} == strict_keys


def test_the_dist_script_picks_the_local_files_only_without_a_developer_id():
    script = (_DESKTOP / "scripts" / "dist.mjs").read_text(encoding="utf-8")
    assert "entitlements.mac.local.plist" in script
    assert "process.env.CSC_NAME" in script
    assert "lipo" in script, "the runtime's architecture must be checked against the target"


# ---- the runtime spec -------------------------------------------------------

def _spec_excludes() -> list[str]:
    tree = ast.parse((_ROOT / "lazy_to_text_server.spec").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "excludes" for t in node.targets)):
            return list(ast.literal_eval(node.value))
    raise AssertionError("the spec has no excludes list")


def test_the_runtime_spec_excludes_qt():
    excludes = _spec_excludes()
    assert "PySide6" in excludes
    assert "shiboken6" in excludes


def test_the_runtime_spec_builds_the_server_entry_point():
    spec = (_ROOT / "lazy_to_text_server.spec").read_text(encoding="utf-8")
    assert '"server" / "__main__.py"' in spec
    assert "PySide6.Qt" not in re.sub(r"#.*", "", spec).replace('"PySide6"', ""), (
        "the spec names a Qt module as an import it wants"
    )
    # The handlers are found with pkgutil, so no import statement names them.
    assert 'collect_submodules("app.server.handlers")' in spec


def test_the_runtime_imports_no_qt():
    """The runtime is Qt-free, and what it imports lazily counts.

    ``app.model_mapping`` used to import ``app.language`` for a function
    that returns its argument, and ``app.language`` is built on QTranslator:
    PySide6 arrived through a one-line import that no start-up check would
    have noticed. A meta-path guard sees every import, wherever it sits.
    """
    code = r"""
import sys
class Guard:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("PySide6", "shiboken6"):
            raise ImportError("Qt import: " + name)
sys.meta_path.insert(0, Guard())

import importlib
for name in (
    "app.server.__main__", "app.server.httpd", "app.server.runtime",
    "app.bootstrap", "app.config_manager", "app.resource_sampler",
    "app.backends.subprocess_backend", "app.backends.subprocess_worker",
    "app.backends.registry_backend", "app.recording_factory",
    "app.model_mapping", "app.history_manager", "app.audio_formats",
    "app.inference_settings", "app.state_manager", "app.utils",
):
    importlib.import_module(name)
from app.server import rpc
rpc.load_handlers()
print("clean")
"""
    result = subprocess.run([sys.executable, "-I", "-c", code], cwd=_ROOT,
                            capture_output=True, text=True, timeout=120,
                            env={**__import__("os").environ, "PYTHONPATH": str(_ROOT)})
    assert result.returncode == 0 and "clean" in result.stdout, result.stderr[-2000:]


# ---- one version everywhere --------------------------------------------------

def _pyproject_version() -> str:
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def test_the_desktop_version_is_the_release_version():
    version = _pyproject_version()
    package = json.loads((_DESKTOP / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((_DESKTOP / "package-lock.json").read_text(encoding="utf-8"))
    assert package["version"] == version
    assert lock["version"] == version
    assert lock["packages"][""]["version"] == version


# ---- CI ---------------------------------------------------------------------

def test_the_desktop_workflow_covers_three_platforms_and_syncs_frozen():
    text = (_ROOT / ".github" / "workflows" / "desktop.yml").read_text(encoding="utf-8")
    for runner in ("ubuntu-latest", "macos-latest", "windows-latest"):
        assert runner in text
    assert "uv sync --frozen" in text
    assert not re.search(r"uv sync(?! --frozen)", text)
    assert "scripts/build_server.py" in text
    assert "workflow_call" in text



# ---- hardening the shipped binary --------------------------------------------

_WORKFLOWS = _ROOT / ".github" / "workflows"

_CSP = {
    "default-src": "'self'",
    "script-src": "'self'",
    "style-src": "'self' 'unsafe-inline'",
    "connect-src": "http://127.0.0.1:*",
    "img-src": "'self' data:",
    "font-src": "'self'",
    "object-src": "'none'",
    "base-uri": "'none'",
    "form-action": "'none'",
}


def _csp_of(path: Path) -> dict[str, str]:
    html = path.read_text(encoding="utf-8")
    match = re.search(
        r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html)
    assert match, f"{path.name} has no Content-Security-Policy meta tag"
    policy = {}
    for part in match.group(1).split(";"):
        name, _, value = part.strip().partition(" ")
        policy[name] = value
    return policy


@pytest.mark.parametrize("page", ["index.html", "overlay.html", "popup.html"])
def test_every_renderer_page_carries_the_strict_policy(page):
    # Exactly this policy: no script from anywhere but the app, no eval, no
    # remote origin, no plugin, no form posting. The only network the page
    # may reach is the loopback runtime.
    assert _csp_of(_DESKTOP / "renderer" / page) == _CSP


def test_the_start_up_page_has_a_policy_too_and_no_inline_script():
    html = (_DESKTOP / "electron" / "splash.html").read_text(encoding="utf-8")
    assert "Content-Security-Policy" in html
    assert "default-src 'none'" in html
    assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", html), "an inline script"
    assert "unsafe-eval" not in html


def test_only_the_dev_server_may_open_a_websocket():
    # Hot reload needs one; the files that are built must not allow it.
    config = (_DESKTOP / "vite.config.js").read_text(encoding="utf-8")
    assert "ws://127.0.0.1:*" in config
    assert "apply: 'serve'" in config
    for page in ("index.html", "overlay.html", "popup.html"):
        assert "ws:" not in (_DESKTOP / "renderer" / page).read_text(encoding="utf-8")


def test_the_electron_fuses_are_flipped_for_the_signed_binary():
    fuses = _builder()["electronFuses"]
    assert fuses["runAsNode"] is False, "ELECTRON_RUN_AS_NODE would reuse the app's microphone grant"
    assert fuses["enableNodeOptionsEnvironmentVariable"] is False
    assert fuses["enableNodeCliInspectArguments"] is False
    assert fuses["onlyLoadAppFromAsar"] is True
    assert fuses["enableEmbeddedAsarIntegrityValidation"] is True
    assert fuses["grantFileProtocolExtraPrivileges"] is False


def test_the_main_process_never_relies_on_run_as_node_or_file_pages():
    # The fuse above would break a main process that spawned itself as Node,
    # and file:// pages lose their extra rights with the last fuse.
    code = "\n".join(p.read_text(encoding="utf-8") for p in (_DESKTOP / "electron").glob("*.cjs"))
    assert "ELECTRON_RUN_AS_NODE" not in code
    assert "process.execPath" not in code
    assert "startsWith('file://')" not in code
    assert "startsWith('http://127.0.0.1:5173')" not in code
    # Nothing is loaded from file://: the renderer and the start-up page are on
    # the app's own scheme. (A file:// page inside app.asar did not load with
    # the file-protocol fuse off.)
    assert "loadFile" not in code
    assert "l2t-app" in (_DESKTOP / "electron" / "guard.cjs").read_text(encoding="utf-8")


def test_test_hooks_need_the_command_line_flag_and_the_scripts_pass_it():
    env = (_DESKTOP / "electron" / "env.cjs").read_text(encoding="utf-8")
    assert "--l2t-selftest" in env
    main = (_DESKTOP / "electron" / "main.cjs").read_text(encoding="utf-8")
    assert "process.env.L2T_SCREENSHOT" not in main
    assert "process.env.L2T_SELFTEST" not in main
    backend = (_DESKTOP / "electron" / "backend.cjs").read_text(encoding="utf-8")
    assert "process.env.L2T_BACKEND_CMD" not in backend
    assert "process.env.L2T_DEV" not in backend
    for script in (_DESKTOP / "scripts" / "smoke.mjs", _ROOT / "scripts" / "generate_desktop_screenshots.py",
                   _ROOT / "scripts" / "linux_container_electron.sh"):
        assert "--l2t-selftest" in script.read_text(encoding="utf-8"), script.name


def test_the_preload_exposes_the_backend_contract_the_renderer_codes_against():
    preload = (_DESKTOP / "electron" / "preload.cjs").read_text(encoding="utf-8")
    block = preload[preload.index("backend: {"):]
    for name in ("onExit", "restart", "onRestarted", "logPath"):
        assert re.search(rf"\b{name}\b", block), name
    assert "connection: () =>" in preload
    # Channels that no handler serves are surface for nothing.
    assert "popup" not in preload
    assert "l2t:overlay:show" not in preload
    main = (_DESKTOP / "electron" / "main.cjs").read_text(encoding="utf-8")
    for channel in re.findall(r"(?:ipcRenderer\.(?:send|sendSync)|\binvoke)\('([^']+)'", preload):
        assert f"'{channel}'" in main, f"{channel} has no handler in main.cjs"


def test_the_preload_offers_the_file_handshake_and_the_pull_route():
    preload = (_DESKTOP / "electron" / "preload.cjs").read_text(encoding="utf-8")
    assert "ready: () => ipcRenderer.send('l2t:ready')" in preload
    assert "pendingFiles: () => invoke('l2t:pending-files')" in preload
    assert "'l2t:file-ack'" in preload
    main = (_DESKTOP / "electron" / "main.cjs").read_text(encoding="utf-8")
    # The page loading is not the page listening: nothing is sent and forgotten.
    assert "pendingFiles.splice" not in main
    assert "createFileInbox" in main


def test_the_runtime_child_starts_with_onnxruntime_telemetry_off():
    backend = (_DESKTOP / "electron" / "backend.cjs").read_text(encoding="utf-8")
    assert "ORT_DISABLE_TELEMETRY: '1'" in backend


def test_the_runtime_is_told_which_origin_the_window_has():
    # The runtime refuses a page whose Origin it was not told about.
    backend = (_DESKTOP / "electron" / "backend.cjs").read_text(encoding="utf-8")
    assert "--allow-origin" in backend
    guard = (_DESKTOP / "electron" / "guard.cjs").read_text(encoding="utf-8")
    assert "APP_SCHEME = 'l2t-app'" in guard and "APP_HOST = 'app'" in guard


# ---- file types, licences and the Info.plist ----------------------------------

# Every extension the runtime accepts (the same tuple `files.formats` answers
# with), without the dot. The three platform lists below are checked against it,
# so a format added to the runtime cannot be left out of "Open with".
from app.audio_formats import AUDIO_EXTS  # noqa: E402

_MEDIA_EXT = [e.lstrip(".") for e in AUDIO_EXTS]

# One MIME type per extension that the desktop entry has to list.
_MIME_FOR_EXT = {
    "wav": "audio/x-wav", "flac": "audio/flac", "ogg": "audio/ogg", "oga": "audio/ogg",
    "opus": "audio/opus", "aiff": "audio/x-aiff", "aif": "audio/x-aiff",
    "mp3": "audio/mpeg", "m4a": "audio/x-m4a", "aac": "audio/aac",
    "wma": "audio/x-ms-wma", "amr": "audio/amr", "ac3": "audio/ac3", "alac": "audio/mp4",
    "mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
    "mkv": "video/x-matroska", "avi": "video/x-msvideo", "flv": "video/x-flv",
    "3gp": "video/3gpp", "m4v": "video/x-m4v", "wmv": "video/x-ms-wmv", "ts": "video/mp2t",
}


def test_the_app_is_offered_for_audio_and_video_on_all_three_platforms():
    config = _builder()
    # macOS: CFBundleDocumentTypes, offered without taking the default.
    (assoc,) = config["mac"]["fileAssociations"]
    assert set(assoc["ext"]) == set(_MEDIA_EXT)
    assert assoc["rank"] == "Alternate"
    # Linux: the desktop entry's MimeType list, existing types only.
    mimes = config["linux"]["mimeTypes"]
    assert mimes and all(m.startswith(("audio/", "video/")) for m in mimes)
    assert {"audio/mpeg", "audio/x-wav", "video/mp4"} <= set(mimes)
    # Windows: a custom include. electron-builder's fileAssociations would
    # make the app the default player for every one of these extensions.
    assert "fileAssociations" not in config and "fileAssociations" not in config["nsis"]
    nsh = (_BUILD / "installer.nsh").read_text(encoding="utf-8")
    assert "customInstall" in nsh and "customUnInstall" in nsh
    assert "OpenWithProgids" in nsh
    listed = re.findall(r'!insertmacro \$\{ACTION\} "([^"]+)"', nsh)
    assert sorted(listed) == sorted(_MEDIA_EXT)
    assert not re.search(r'WriteRegStr\s+SHELL_CONTEXT\s+"Software\\Classes\\\.\$?\{?\w+\}?"\s+""', nsh), (
        "the extension's default class is written"
    )


def test_every_runtime_format_has_a_mime_type_in_the_desktop_entry():
    assert set(_MIME_FOR_EXT) == set(_MEDIA_EXT), "a format was added without a MIME type here"
    mimes = set(_builder()["linux"]["mimeTypes"])
    missing = sorted(ext for ext, mime in _MIME_FOR_EXT.items() if mime not in mimes)
    assert not missing, f"no MIME type in the Linux desktop entry for: {missing}"


def test_the_licences_that_must_travel_are_in_the_package():
    config = _builder()
    shipped = {e["to"]: e["from"] for e in config["extraResources"]}
    assert shipped["THIRD_PARTY_NOTICES.md"] == "../THIRD_PARTY_NOTICES.md"
    assert shipped["LICENSE"] == "../LICENSE"
    assert shipped["licenses"] == "licenses"
    for name in ("GPL-2.0.txt", "OFL-Inter.txt", "OFL-JetBrains-Mono.txt", "OFL-Source-Serif-4.txt"):
        assert (_DESKTOP / "licenses" / name).stat().st_size > 1000, name
    assert "GNU GENERAL PUBLIC LICENSE" in (_DESKTOP / "licenses" / "GPL-2.0.txt").read_text(encoding="utf-8")
    notices = (_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for needle in ("ffmpeg", "--enable-gpl", "GPL-2.0.txt", "SIL Open Font License", "JetBrains Mono",
                   "Heroicons", "LICENSE.electron.txt", "LICENSES.chromium.html", "pynput", "source code"):
        assert needle in notices, needle
    assert (_ROOT / "LICENSE").is_file()


def test_the_runtime_leaves_out_what_an_mit_application_cannot_ship():
    assert "mouseinfo" in _spec_excludes(), "GPL-3.0-or-later, pulled in by pyautogui"
    build = (_ROOT / "scripts" / "build_server.py").read_text(encoding="utf-8")
    assert 'rglob("mouseinfo")' in build


def test_the_linux_runtime_carries_its_own_portaudio():
    """An AppImage has no dependency mechanism; the wheel has no PortAudio."""
    spec = (_ROOT / "lazy_to_text_server.spec").read_text(encoding="utf-8")
    assert "libportaudio" in spec and "binaries=binaries" in spec
    hook = (_ROOT / "scripts" / "pyi_runtime_hook.py").read_text(encoding="utf-8")
    assert "find_library" in hook and "libportaudio.so" in hook
    # sounddevice looks up PortAudio on Linux only through ctypes.util.find_library.
    build = (_ROOT / "scripts" / "build_server.py").read_text(encoding="utf-8")
    assert "libportaudio.so" in build


def test_the_hook_answers_the_portaudio_lookup_with_the_bundled_library(tmp_path):
    code = r"""
import ctypes.util, sys
sys.platform = "linux"
mei = sys.argv[1]
sys._MEIPASS = mei
import runpy
runpy.run_path(sys.argv[2])
print(ctypes.util.find_library("portaudio"))
print(ctypes.util.find_library("c") is not None or True)
"""
    (tmp_path / "libportaudio.so.2").write_bytes(b"x")
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(tmp_path), str(_ROOT / "scripts" / "pyi_runtime_hook.py")],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == str(tmp_path / "libportaudio.so.2")


def test_the_mac_plist_loses_the_keys_electron_ships_for_nothing():
    hook = (_BUILD / "after-pack.cjs").read_text(encoding="utf-8")
    for key in ("NSCameraUsageDescription", "NSBluetoothAlwaysUsageDescription",
                "NSAudioCaptureUsageDescription", "NSAppTransportSecurity"):
        assert key in hook
    config = _builder()
    assert config["afterPack"] == "build/after-pack.cjs"
    assert (_DESKTOP / config["afterPack"]).is_file()
    # The one usage string the app needs is not among them.
    assert "NSMicrophoneUsageDescription" not in hook.split("const UNUSED = [")[1].split("];")[0]
    assert set(config["electronLanguages"]) == {"en-US", "ru"}


# ---- the release workflow ------------------------------------------------------

def _workflow(name: str) -> dict:
    data = yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML reads a bare `on` as True
    return data




def test_third_party_actions_are_pinned_by_commit():
    third_party = []
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        for use in re.findall(r"uses:\s*(\S+)", path.read_text(encoding="utf-8")):
            if use.startswith("./") or use.startswith("actions/"):
                continue
            third_party.append((path.name, use))
    assert third_party, "no third-party action found: the check is not looking at anything"
    for name, use in third_party:
        assert re.search(r"@[0-9a-f]{40}$", use), f"{name}: {use} is not pinned by commit"


def test_the_smoke_test_runs_with_the_sandbox_on_linux():
    text = (_WORKFLOWS / "desktop.yml").read_text(encoding="utf-8")
    commands = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "--no-sandbox" not in commands
    assert "chrome-sandbox" in commands and "4755" in commands
    smoke = (_DESKTOP / "scripts" / "smoke.mjs").read_text(encoding="utf-8")
    assert "L2T_SMOKE_SANDBOX" in smoke
    # The default on Linux is the sandbox whenever the helper is usable.
    assert "sandboxHelperReady" in smoke


def test_the_windows_portable_target_is_documented_as_unpacking_on_start():
    text = (_DESKTOP / "electron-builder.yml").read_text(encoding="utf-8")
    assert "unpacks the whole app" in text


def test_certifi_is_past_the_distrusted_root():
    """certifi 2026.4.22 still trusted the emSign ECC G3 root (fixed in 2026.10.19)."""
    lock = (_ROOT / "uv.lock").read_text(encoding="utf-8")
    version = re.search(r'name = "certifi"\nversion = "([^"]+)"', lock).group(1)
    assert tuple(int(part) for part in version.split(".")) >= (2026, 10, 19), version


# ---- the macOS artifact: patched PortAudio, hardened runtime, the worker -----
#
# The Qt tests that held these (tests/test_bundle_contents.py) read a built
# py2app bundle. These read the configuration that makes the Electron one, so
# they run everywhere and need no build (spec 010 FR-015); the artifact itself
# is checked when one exists, below.

def test_the_mac_build_signs_with_the_hardened_runtime_and_the_microphone_entitlement():
    mac = _builder()["mac"]
    assert mac["hardenedRuntime"] is True
    for key in ("entitlements", "entitlementsInherit"):
        assert _entitlements(Path(mac[key]).name)[AUDIO_INPUT] is True, key
    # The runtime is signed by scripts/dist.mjs, with the same flags: the
    # hardened runtime is enforced per process, so the worker needs it itself.
    dist = (_DESKTOP / "scripts" / "dist.mjs").read_text(encoding="utf-8")
    assert "'--options', 'runtime'" in dist
    assert "'--entitlements'" in dist
    assert "entitlements.mac.inherit.plist" in dist
    assert "Contents/Resources/backend/" in mac["signIgnore"]


def test_the_runtime_is_built_with_the_patched_portaudio_on_macos():
    build = (_ROOT / "scripts" / "build_server.py").read_text(encoding="utf-8")
    tree = ast.parse(build)
    main = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
    main_src = ast.get_source_segment(build, main)
    # Patched right after the build, on macOS only, before the folder is checked.
    assert 'sys.platform == "darwin"' in main_src
    assert main_src.index("patch_portaudio()") < main_src.index("check_bundle()")
    # The patch itself: the vendored one, installed into the folder, re-signed.
    assert "build_patched_portaudio.py" in build and '"--dist"' in build
    assert '"codesign"' in build and "libportaudio.dylib" in build
    assert (_ROOT / "vendor" / "portaudio").is_dir()
    assert list((_ROOT / "vendor" / "portaudio").glob("*.patch"))
    # And a bundle without the marker is refused, so CI fails on the macOS leg.
    check = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "check_bundle")
    check_src = ast.get_source_segment(build, check)
    assert "libportaudio.dylib.patched.json" in check_src
    patcher = (_ROOT / "scripts" / "build_patched_portaudio.py").read_text(encoding="utf-8")
    assert ".patched.json" in patcher


def test_the_runtime_spec_ships_the_worker_entry_point():
    # The inference worker is a spawned copy of the runtime's own executable:
    # `multiprocessing.freeze_support()` has to be the first thing main does,
    # or the child starts a second server instead of the worker, and the
    # worker function has to be where the spawn looks for it.
    main = (_ROOT / "app" / "server" / "__main__.py").read_text(encoding="utf-8")
    body = main[main.index("def main("):]
    assert body.index("multiprocessing.freeze_support()") < body.index("argparse.ArgumentParser")
    worker = (_ROOT / "app" / "backends" / "subprocess_worker.py").read_text(encoding="utf-8")
    assert re.search(r"^def _worker_main\(", worker, re.M)
    backend = (_ROOT / "app" / "backends" / "subprocess_backend.py").read_text(encoding="utf-8")
    assert "target=_worker_main" in backend
    spec = (_ROOT / "lazy_to_text_server.spec").read_text(encoding="utf-8")
    assert '"server" / "__main__.py"' in spec
    # One folder, one executable: the worker is that executable, not a second one.
    assert spec.count("name=\"lazy-to-text-server\"") == 2  # EXE and COLLECT


def test_a_built_mac_app_carries_the_patched_portaudio():
    """Reads the unpacked app when one has been built here; skips otherwise."""
    apps = sorted((_DESKTOP / "release").glob("mac-*/Lazy to Text.app"))
    if not apps:
        pytest.skip("no built macOS app under desktop/release")
    backend = apps[-1] / "Contents" / "Resources" / "backend"
    assert (backend / "lazy-to-text-server").is_file()
    assert list(backend.rglob("libportaudio.dylib.patched.json")), "the shipped PortAudio is the wheel's"
