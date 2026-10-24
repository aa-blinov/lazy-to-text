'use strict';
// electron-builder's afterPack hook (runs before signing).
//
// Electron's Info.plist ships usage strings and a transport-security
// exception the app has no use for: this app uses no camera, no Bluetooth and
// no audio capture API of the system (the runtime records through PortAudio),
// and the page talks to a loopback server through Chromium's own network
// stack, which App Transport Security does not govern. A usage string for a
// capability the app never asks for is a prompt text a reviewer has to
// explain, and `NSAllowsArbitraryLoads` is a switch that is simply on.
// NSMicrophoneUsageDescription, which the app does use, is set in
// electron-builder.yml.

const { execFileSync } = require('node:child_process');
const path = require('node:path');

const UNUSED = [
  'NSCameraUsageDescription',
  'NSBluetoothAlwaysUsageDescription',
  'NSBluetoothPeripheralUsageDescription',
  'NSAudioCaptureUsageDescription',
  'NSAppTransportSecurity',
];

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  const plist = path.join(app, 'Contents', 'Info.plist');
  for (const key of UNUSED) {
    try {
      execFileSync('plutil', ['-remove', key, plist], { stdio: 'ignore' });
    } catch {
      // not present in this Electron's plist
    }
  }
};

exports.UNUSED = UNUSED;
