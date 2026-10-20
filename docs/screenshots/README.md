# Screenshots

The images the README shows, and where each one comes from.

Every image in this folder is rendered from the code by
`scripts/generate_screenshots.py`, so it shows the release it was rendered
for and cannot drift away from it. The script builds the real application
with a fake configuration and a fake history, seeds the log pane, the
resource meters and the transcribe view with realistic data, grants the
macOS permissions so the permission banners are not in the picture, and
grabs the window.

```bash
uv run python scripts/generate_screenshots.py          # the English set
uv run python scripts/generate_screenshots.py --lang ru # the Russian set
```

The window is 1100 by 720 and is grabbed at twice that, so the PNG is 2200
by 1440. The narrow shot is 920 by 660, which is below the 1000px threshold
where the sidebar turns into an icon rail, and it is 1840 by 1320.

| Image | What it shows |
| --- | --- |
| `hero.png` | The Models screen, which is the first thing the window shows. |
| `models.png` | The same Models screen, with the model list and the download buttons. |
| `transcribe.png` | The Transcribe tab, with a seeded file and its transcript. |
| `history.png` | The History tab, with the seeded dictations. |
| `logs.png` | The Logs tab, with the seeded log lines. |
| `presets.png` | The Post-processing tab. The file name is the old one, from before the tab was renamed. |
| `shortcuts.png` | The Settings tab. The file name is the old one, from before the tab was renamed. |
| `narrow.png` | The Models screen in a window below 1000px, with the icon rail. |

`hero.png` and `models.png` are the same file. The script captures the six
sections, returns to Models and grabs it again as the hero, and the two
images come out identical.

The `ru/` folder holds the same eight images in the Russian interface. The
script writes them there when `--lang ru` is passed, and it sets the
`ui.language` value in the configuration to the language it renders, so the
shot shows the language the application starts in.

The two file names that no longer match their tab, `presets.png` and
`shortcuts.png`, are still linked from the README. Renaming them means
changing the references there in the same commit.
