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
        assert set(archs) == {"arm64", "x64"}
    assert set(_targets(config["linux"])) == {"AppImage", "deb"}


def test_the_app_id_is_not_the_qt_applications():
    config = _builder()
    qt = re.search(r'"CFBundleIdentifier":\s*"([^"]+)"',
                   (_ROOT / "setup.py").read_text(encoding="utf-8")).group(1)
    assert config["appId"] != qt, (
        "the two front ends would share macOS permission grants and file "
        "associations; the reason it is separate is in electron-builder.yml"
    )
    assert config["productName"] == "Lazy to Text"


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
    "app.backends.registry_backend", "app.gui.recording_factory",
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


def test_the_release_workflow_attaches_the_desktop_installers():
    text = (_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/desktop.yml" in text
    assert "desktop-*" in text
    # The Qt job is still there and still publishes its own artifacts.
    assert "lazy_to_text.spec" in text
