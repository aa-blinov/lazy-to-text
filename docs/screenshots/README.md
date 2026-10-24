# Screenshots

The images the README and the project site show, and where each one comes from.

Every image here is a window of the Electron (Monos) interface, taken from the
packaged app talking to its real engine by `scripts/generate_desktop_screenshots.py`.
The script starts the app once per screen against a scratch profile: the model
`vosk-ru-small` already on disk, the light theme, and a history of invented
dictations. The Transcribe picture is a real file dropped on the window and
transcribed by the real model. Nothing is drawn by hand.

```bash
cd desktop && npm run build && node scripts/dist.mjs --dir && cd ..
uv run python scripts/generate_desktop_screenshots.py \
    --app "desktop/release/mac-arm64/Lazy to Text.app" \
    --model-from models/hub --phrase path/to/phrase.wav        # the English set
uv run python scripts/generate_desktop_screenshots.py \
    --app "desktop/release/mac-arm64/Lazy to Text.app" \
    --model-from models/hub --lang ru                          # the Russian set
```

The window is 1120 by 760 and is grabbed at twice that, so each PNG is 2240 by
1520. `--model-from` points at a Hugging Face hub cache that already holds the
model; the script never downloads anything.

| File | Screen |
| --- | --- |
| `transcribe.png` | A dropped file and its editable transcript |
| `models.png` | The model catalogue with search, filters and sort |
| `history.png` | Past dictations, searchable |
| `presets.png` | Post-processing, with the switch in the language-model card |
| `shortcuts.png` | Settings |
| `logs.png` | The log screen |
| `ru/*.png` | The same screens in Russian |
