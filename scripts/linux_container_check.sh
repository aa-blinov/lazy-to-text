#!/usr/bin/env bash
# Run the headless runtime on Linux in a container and dictate through it:
# Xvfb for the display, PulseAudio with a virtual microphone for the input,
# xdotool for the hotkeys, paplay to "speak" a recorded phrase into the
# microphone. Needs Docker, a repository checkout, a hub cache holding the
# vosk-ru-small model and a short Russian phrase as phrase.wav.
#
#   docker run --rm --platform linux/arm64 \
#     -v "$PWD":/src:ro -v scripts/linux_container_check.sh:/inside.sh:ro \
#     -v scripts/linux_container_driver.py:/driver.py:ro \
#     -v /path/phrase.wav:/phrase.wav:ro -v "$PWD/models/hub":/vosk:ro \
#     ubuntu:24.04 bash /inside.sh
#
# What it shows: the global hotkey on X11, recording from a PulseAudio source,
# transcription and the delivery outcome. It does not show the Electron
# window or the tray.
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends xvfb xdotool pulseaudio pulseaudio-utils libportaudio2 libsndfile1 xclip curl ca-certificates libegl1 libgl1 libglib2.0-0 libdbus-1-3 libfontconfig1 libxkbcommon-x11-0 python3 gcc libc6-dev linux-libc-dev python3-dev libasound2-plugins x11-xkb-utils x11-utils xauth
curl -LsSf https://astral.sh/uv/install.sh | sh >> /tmp/setup.log 2>&1
export PATH=/root/.local/bin:$PATH
mkdir -p /work && cd /work
tar -C /src -cf - --exclude=.venv --exclude=node_modules --exclude=dist --exclude=build --exclude=release --exclude=dist-renderer --exclude=models --exclude=.git --exclude=logs . | tar -xf -
uv python install 3.12 >> /tmp/setup.log 2>&1
uv sync --frozen >> /tmp/setup.log 2>&1
echo "deps installed"
mkdir -p /models/hub && cp -R /vosk/models--alphacep--vosk-model-small-ru /models/hub/
printf 'storage:\n  models_dir: /models\nwhisper:\n  model: vosk-ru-small\n  language: auto\nonboarding:\n  complete: true\nclipboard:\n  auto_paste: false\n' > /work/config.yaml
export DISPLAY=:99
touch /root/.Xauthority
Xvfb :99 -ac -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
for i in 1 2 3 4 5 6 7 8 9 10; do xdpyinfo >/dev/null 2>&1 && break; sleep 1; done
xdpyinfo | head -3
printf "pcm.!default { type pulse }\nctl.!default { type pulse }\n" > /etc/asound.conf
sleep 2
pulseaudio --start --exit-idle-time=-1 --system=false 2>/dev/null || pulseaudio -D --exit-idle-time=-1 2>/dev/null || true
sleep 2
pactl load-module module-null-sink sink_name=nullsink >/dev/null
pactl load-module module-virtual-source source_name=vmic master=nullsink.monitor >/dev/null
pactl set-default-source vmic
pactl list short sources
uv run --frozen python /driver.py || true
echo ---SERVER-LOG---; tail -25 /tmp/server.err; ls /models/hub
