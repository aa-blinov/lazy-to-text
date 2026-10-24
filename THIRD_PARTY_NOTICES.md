# Third-party notices

Lazy to Text is MIT-licensed (see `LICENSE`). The installers contain software
written by other people, under the licences below. This file ships inside the
application (`resources/THIRD_PARTY_NOTICES.md`, with the licence texts it
refers to in `resources/licenses/`).

Speech models are not part of the application. They are downloaded on request
from Hugging Face, each under its own licence, which is shown on the model's
page and recorded by the download.

## Electron and Chromium

The desktop interface runs on Electron (MIT) and so on Chromium and its
dependencies, which carry many licences. Electron's own licence is shipped as
`LICENSE.electron.txt` and the full list for Chromium as
`LICENSES.chromium.html`, both in the application's resources folder (the
same folder as this file on Windows and Linux, next to `app.asar` on macOS).

## ffmpeg (GPL)

The runtime ships the `ffmpeg` executable from the Python package
`imageio-ffmpeg`, which the application uses to decode audio and video files
that the sound library cannot read. That executable is a static build of
FFmpeg configured with `--enable-gpl` (including libx264 and libx265), so it is
distributed under the **GNU General Public License, version 2 or later**. The
text is in `licenses/GPL-2.0.txt`.

- It is a separate program. The application starts it as a child process with
  a list of arguments and exchanges only files and a text stream with it; it is
  not linked into any other part of the application.
- FFmpeg's source code is available at <https://ffmpeg.org/releases/>. The
  binaries come from the `imageio-ffmpeg` project
  (<https://github.com/imageio/imageio-ffmpeg>, BSD-2-Clause), whose binaries
  repository records which FFmpeg release and which build each file is. The
  version a given build reports is printed by running the executable with
  `-version`; its path is under `backend/_internal/imageio_ffmpeg/binaries/`.
- Written offer: for as long as a release containing it is available, the
  maintainer will provide the corresponding source of the FFmpeg build it
  contains on request, through an issue at
  <https://github.com/aa-blinov/lazy-to-text/issues>.

## Fonts (SIL Open Font License 1.1)

The interface bundles Inter, JetBrains Mono and Source Serif 4 as web fonts
(through `@monos/ui`). Each is licensed under the SIL Open Font License,
version 1.1, with the copyright notice that heads each file:

- Inter: `licenses/OFL-Inter.txt`
- JetBrains Mono: `licenses/OFL-JetBrains-Mono.txt`
- Source Serif 4: `licenses/OFL-Source-Serif-4.txt`

## JavaScript libraries in the interface

Bundled into the renderer by Vite:

| Package | Licence |
| --- | --- |
| svelte | MIT |
| lucide-svelte (and the Lucide icons) | ISC |
| @monos/ui | MIT |

Electron, Vite, Tailwind CSS and the other build and test tools are not part of
what is installed, apart from Electron itself.

## Heroicons (MIT)

The microphone glyph in the application icon and the tray images
(`scripts/make_icons.py`) is the Heroicons `microphone-solid` icon by Tailwind
Labs, MIT licence, <https://heroicons.com>.

> MIT License. Copyright (c) Tailwind Labs, Inc. Permission is hereby granted,
> free of charge, to any person obtaining a copy of this software and
> associated documentation files, to deal in the software without restriction,
> including without limitation the rights to use, copy, modify, merge, publish,
> distribute, sublicense, and/or sell copies, subject to the above copyright
> notice and this permission notice being included in all copies. The software
> is provided "as is", without warranty of any kind.

## Python runtime

The speech engine is a Python program frozen with PyInstaller. Every package
it contains keeps its own licence files in its `*.dist-info` folder inside
`backend/_internal/`. A summary, from each package's metadata as installed on
the build machine (platform-specific packages that are not installed on a given
platform are not in that platform's build):

| Package | Version | Licence |
| --- | --- | --- |
| annotated-doc | 0.0.4 | MIT |
| anyio | 4.13.0 | MIT |
| certifi | 2026.10.23 | MPL-2.0 |
| cffi | 2.0.0 | MIT |
| click | 8.3.3 | BSD-3-Clause |
| filelock | 3.29.0 | MIT |
| flatbuffers | 25.12.19 | Apache-2.0 |
| fsspec | 2026.4.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| hf-xet | 1.4.3 | Apache-2.0 |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| huggingface-hub | 1.13.0 | Apache-2.0 |
| idna | 3.13 | BSD-3-Clause |
| imageio-ffmpeg | 0.6.0 | BSD-2-Clause (its ffmpeg binary: GPL, see above) |
| markdown-it-py | 4.0.0 | MIT |
| mdurl | 0.1.2 | MIT |
| numpy | 2.4.4 | BSD-3-Clause and others, listed in its package |
| onnx-asr | 0.12.0 | MIT |
| onnxruntime | 1.30.0 | MIT |
| packaging | 24.2 | Apache-2.0 or BSD-2-Clause |
| platformdirs | 4.9.6 | MIT |
| playsound3 | 3.3.1 | MIT |
| protobuf | 7.34.1 | BSD-3-Clause |
| psutil | 7.2.2 | BSD-3-Clause |
| pyautogui | 0.9.54 | BSD-3-Clause |
| pycparser | 3.0 | BSD-3-Clause |
| pygetwindow | 0.0.9 | BSD-3-Clause |
| pygments | 2.20.0 | BSD-2-Clause |
| pymsgbox | 2.0.1 | BSD-3-Clause |
| pynput | 1.8.1 | LGPL-3.0 (see below) |
| pyobjc (core and frameworks) | 12.1 | MIT |
| pyperclip | 1.11.0 | BSD-3-Clause |
| pyrect | 0.2.0 | BSD-3-Clause |
| pyscreeze | 1.0.1 | MIT |
| pytweening | 1.2.0 | MIT |
| pyyaml | 6.0.3 | MIT |
| rich | 15.0.0 | MIT |
| rubicon-objc | 0.5.3 | BSD-3-Clause |
| scipy | 1.17.1 | BSD-3-Clause, with bundled libraries listed in its package |
| shellingham | 1.5.4 | ISC |
| six | 1.17.0 | MIT |
| sounddevice | 0.5.5 | MIT |
| soundfile | 0.13.1 | BSD-3-Clause |
| tqdm | 4.67.3 | MPL-2.0 and MIT |
| typer | 0.25.1 | MIT |
| typing-extensions | 4.15.0 | PSF-2.0 |

Windows and Linux builds also contain colorama, global-hotkeys, keyboard,
nvidia-ml-py, pywin32 (Windows) and evdev, python-xlib, python3-xlib (Linux);
their licences are in their own `*.dist-info` folders.

- **pynput** is LGPL-3.0. The runtime is frozen with its Python source kept
  beside the bytecode (`noarchive`), so the library can be read and replaced in
  `backend/_internal/pynput/`. Its source is at
  <https://github.com/moses-palmer/pynput>.
- **PortAudio** (MIT) is loaded through sounddevice: the macOS runtime carries
  a build with a patch for a deadlock on stop (`vendor/portaudio/`), and the
  Linux runtime carries the build machine's `libportaudio` so that the
  AppImage does not depend on the system's.
- **certifi** (MPL-2.0) is the certificate bundle httpx and huggingface-hub use for TLS
  when they download models.
- `mouseinfo` (GPL-3.0-or-later, a dependency of pyautogui) is deliberately
  excluded from the runtime; `scripts/build_server.py` fails the build if it
  appears.
