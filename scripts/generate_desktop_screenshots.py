"""Screenshots of the Electron interface, for the project site and the README.

Starts the packaged app once per screen against a scratch profile with a seeded
history, a model that is already on disk and the configuration chosen for the
set, and saves what the window shows. Nothing in the pictures is a mock-up:
the screens are the real ones talking to the real runtime. Only the history
entries are invented.

    uv run python scripts/generate_desktop_screenshots.py \\
        --app "desktop/release/mac-arm64/Lazy to Text.app" --model-from models/hub
    ... --lang ru

The model has to be on disk already (``--model-from`` copies one from a hub
cache); the script never downloads anything.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"

MODEL_ALIAS = "vosk-ru-small"
MODEL_DIR = "models--alphacep--vosk-model-small-ru"

SAMPLE = [
    ("Отправь Анне черновик к пятнице и поправь вторую главу.", 4.8),
    ("Напомни мне завтра в девять позвонить в типографию.", 3.9),
    ("Встреча перенесена на четверг, начало в одиннадцать тридцать.", 4.4),
    ("В отчёт добавить таблицу с результатами за третий квартал.", 5.1),
    ("Купить молоко, хлеб и батарейки для пульта.", 3.2),
    ("Спасибо за быстрый ответ, всё получилось.", 2.7),
]

# (file name, screen id)
SCREENS = [
    ("transcribe", "transcribe"),
    ("models", "models"),
    ("history", "history"),
    ("presets", "postprocessing"),
    ("shortcuts", "settings"),
    ("logs", "logs"),
]


def executable(app: Path) -> Path:
    if app.suffix == ".app":
        return app / "Contents" / "MacOS" / app.stem
    return app


def seed(home: Path, lang: str, model_from: Path, phrase: Path | None) -> None:
    os.environ["HOME"] = str(home)
    from platformdirs import user_cache_dir, user_config_dir, user_log_dir

    config = Path(user_config_dir("LazyToText", appauthor=False))
    cache = Path(user_cache_dir("LazyToText", appauthor=False))
    logs = Path(user_log_dir("LazyToText", appauthor=False))
    for d in (config, cache, logs):
        d.mkdir(parents=True, exist_ok=True)

    hub = cache / "models" / "hub"
    hub.mkdir(parents=True, exist_ok=True)
    shutil.copytree(model_from / MODEL_DIR, hub / MODEL_DIR, dirs_exist_ok=True)

    (config / "config.yaml").write_text(
        f"whisper:\n  model: {MODEL_ALIAS}\n  language: auto\n  beam_size: 5\n"
        f"onboarding:\n  complete: true\nui:\n  theme: light\n  language: {lang}\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(ROOT))
    from app.history_manager import HistoryManager

    history = HistoryManager(max_entries=100, history_file=str(logs / "transcription_history.jsonl"))
    now = time.time()
    for index, (text, seconds) in enumerate(reversed(SAMPLE)):
        history._add_entry_locked(text, seconds, "alphacep/vosk-model-small-ru", "ru")
        history.entries[0].timestamp = now - (len(SAMPLE) - index) * 1500


def shoot(exe: Path, home: Path, name: str, screen: str, out: Path, drop: Path | None) -> None:
    env = {
        **os.environ,
        "HOME": str(home),
        "L2T_SCREENSHOT": str(out),
        "L2T_SCREENSHOT_DELAY": "9000",
        "L2T_SCREEN": screen,
    }
    if name == "transcribe" and drop is not None:
        env["L2T_SELFTEST_DROP"] = str(drop)
        env.pop("L2T_SCREEN")
        env["L2T_SELFTEST_DELAY"] = "9000"
        env["L2T_SELFTEST_WAIT"] = "4000"
    # The hooks above are live only with --l2t-selftest on the command line.
    # The profile is scratch too: on macOS Electron keeps its own data under
    # the account, not under HOME, and would share a lock with an installed copy.
    subprocess.run([str(exe), "--l2t-selftest", f"--user-data-dir={home / 'electron-profile'}"],
                   env=env, check=True, timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Path(f"{out}.txt").unlink(missing_ok=True)  # the visible text, written for the smoke test


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--model-from", required=True, type=Path, help="a hub cache holding the vosk-ru-small model")
    parser.add_argument("--lang", default="en", choices=["en", "ru"])
    parser.add_argument("--phrase", type=Path, help="an audio file dropped on the Transcribe screen")
    args = parser.parse_args()

    out_dir = OUT / "ru" if args.lang == "ru" else OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    exe = executable(args.app)

    with tempfile.TemporaryDirectory(prefix="l2t-shots-") as tmp:
        home = Path(tmp)
        seed(home, args.lang, args.model_from, args.phrase)
        for name, screen in SCREENS:
            target = out_dir / f"{name}.png"
            shoot(exe, home, name, screen, target, args.phrase)
            print("wrote", target.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
