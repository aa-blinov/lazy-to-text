#!/usr/bin/env bash
# Start the Electron app on Linux in a container, under a virtual display,
# against the real runtime, and save what the window shows to /out.
#
#   docker run --rm --platform linux/arm64 -v "$PWD":/src:ro \
#     -v scripts/linux_container_electron.sh:/electron.sh:ro \
#     -v "$PWD/models/hub":/vosk:ro -v /tmp/out:/out ubuntu:24.04 bash /electron.sh
#
# It needs a hub cache holding vosk-ru-small. Node 22.12 or newer is required
# by Electron's installer. Under emulation the GPU process dies after the
# picture is taken; that is the container, and the screenshot is what counts.
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends xvfb xauth x11-utils libportaudio2 libsndfile1 curl ca-certificates git xz-utils python3 gcc libc6-dev linux-libc-dev python3-dev libasound2-plugins libasound2t64 libnss3 libgtk-3-0t64 libxss1 libgbm1 libxtst6 libxkbcommon0 libdrm2 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libpango-1.0-0 libcairo2 libxrandr2 libxcomposite1 libxdamage1 libxfixes3 libxcb-dri3-0 libdbus-1-3 libfontconfig1 fonts-dejavu-core > /tmp/apt.log 2>&1
curl -LsSf https://astral.sh/uv/install.sh | sh >> /tmp/setup.log 2>&1
curl -fsSL https://nodejs.org/dist/v22.14.0/node-v22.14.0-linux-arm64.tar.xz | tar -xJ -C /opt
export PATH=/opt/node-v22.14.0-linux-arm64/bin:/root/.local/bin:$PATH
mkdir -p /work && cd /work
tar -C /src -cf - --exclude=./.venv --exclude=./desktop/node_modules --exclude=./dist --exclude=./build --exclude=./desktop/release --exclude=./desktop/dist-renderer --exclude=./models --exclude=./.git --exclude=./logs . | tar -xf -
uv python install 3.12 >> /tmp/setup.log 2>&1
uv sync --frozen >> /tmp/setup.log 2>&1
mkdir -p /models/hub && cp -R /vosk/models--alphacep--vosk-model-small-ru /models/hub/
printf 'storage:\n  models_dir: /models\nwhisper:\n  model: vosk-ru-small\n  language: auto\nonboarding:\n  complete: true\n' > /work/config.yaml
cd /work/desktop
npm ci >> /tmp/npm.log 2>&1
node node_modules/electron/install.js >> /tmp/npm.log 2>&1
npm run build >> /tmp/npm.log 2>&1
export DISPLAY=:99
touch /root/.Xauthority
Xvfb :99 -ac -screen 0 1400x900x24 >/tmp/xvfb.log 2>&1 &
for i in 1 2 3 4 5 6 7 8 9 10; do xdpyinfo >/dev/null 2>&1 && break; sleep 1; done
L2T_SCREENSHOT=/out/linux-window.png L2T_SCREENSHOT_DELAY=25000 ./node_modules/.bin/electron . --l2t-selftest --no-sandbox --disable-gpu > /tmp/electron.out 2> /tmp/electron.err || true
echo ---ELECTRON-ERR---; tail -15 /tmp/electron.err
echo ---WINDOW-TEXT---; cat /out/linux-window.png.txt || true
ls -la /out
