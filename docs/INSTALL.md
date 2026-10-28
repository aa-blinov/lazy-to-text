# Installing Lazy to Text

[Русская версия](INSTALL.ru.md)

If your system warned you before it would open the app, nothing is wrong with
the download. This page says why the warning appears, how to open the app
anyway, and how to check that the file is the one this project built.

## The short version

- Lazy to Text is open source (MIT). The installers on the
  [release page](https://github.com/aa-blinov/lazy-to-text/releases) are built
  by GitHub, from the tagged source, by the workflow in
  [`.github/workflows`](../.github/workflows). Nobody builds them by hand.
- macOS and Windows show a warning because the installers are **not signed with
  a paid certificate**. Apple charges $99 a year for the certificate and the
  notarization that silence its warning; Windows asks for a code-signing
  certificate, and trusts a new file only after enough people have run it. This
  project is free and has neither yet. Linux has no such gate.
- Your audio never leaves the computer. The network is used to download a model
  the first time you pick it, and, only if you turn on post-processing with a
  cloud provider, to send the text to that provider.
- You can check a download in a minute: see [Check what you downloaded](#check-what-you-downloaded).

## Check what you downloaded

Every release has a `SHA256SUMS.txt` with the SHA-256 of each file. Compare the
one for your file with what your computer computes.

macOS (Terminal), in the folder with the download:

```bash
shasum -a 256 LazyToText-Desktop-<version>-mac-arm64.dmg
```

Windows (PowerShell):

```powershell
Get-FileHash .\LazyToText-Desktop-<version>-setup-x64.exe -Algorithm SHA256
```

Linux:

```bash
sha256sum -c --ignore-missing SHA256SUMS.txt
```

The long hexadecimal strings must be identical. If they are not, download the
file again, and do not run it.

A checksum shows the file arrived intact. To show it was built **by this
repository's workflow, from this tag**, use the build attestation (needs the
[GitHub CLI](https://cli.github.com/)):

```bash
gh attestation verify LazyToText-Desktop-<version>-mac-arm64.dmg --repo aa-blinov/lazy-to-text
```

On success the command ends without an error (in a terminal it also prints a
"Verification succeeded" line); a file that was changed after the build, or
built elsewhere, fails with an error. To see where the file came from, ask for
the details: add `--format json` and read `sourceRepositoryURI`,
`sourceRepositoryRef` (the tag) and `buildSignerURI` (the workflow).

## macOS

Apple silicon (M1 and later) only.

### What you will see, and why

On the first launch macOS says that **Apple could not verify "Lazy to Text" is
free of malware**, or that the app **"is damaged and can't be opened"**. The
app is not damaged. macOS checks every downloaded app for a developer signature
that Apple has notarized. This build is signed *ad hoc* (it proves the file is
unchanged, not who made it) and is not notarized, because notarizing needs the
paid Apple Developer Program.

### Open it anyway

1. Open the `.dmg` and drag **Lazy to Text** to **Applications**.
2. Open it once from Applications. macOS will refuse; click **Done**.
3. Open **System Settings → Privacy & Security**, scroll to **Security**, and
   click **Open Anyway** beside the message about Lazy to Text. Confirm with
   your password or Touch ID, then click **Open**.

On macOS 14 and earlier you can instead right-click the app and choose
**Open**. From macOS 15 that shortcut is gone and the steps above are the way.

If macOS still says the app is damaged, and you have checked the SHA-256, remove
the download flag from the app:

```bash
xattr -dr com.apple.quarantine "/Applications/Lazy to Text.app"
```

Only do this for a file you have verified. It tells macOS to stop treating the
app as a download.

### The two permissions

The app asks for them; macOS does not remind you.

| Permission | Why |
| --- | --- |
| Microphone | To record you. |
| Accessibility | For the global hotkeys and for the paste keystroke (Cmd+V) into the window you were typing in. |

**Settings** inside the app shows a banner that opens the right System Settings
pane.

Because the signature is ad hoc, macOS treats each release as a new app and asks
for both permissions again after an update. If the hotkeys stop working after an
update, open **System Settings → Privacy & Security → Accessibility**, remove
Lazy to Text with the minus button, and add it again (or switch it off and on).
A build you make yourself with `scripts/setup-signing.sh` keeps its permissions.

## Windows

### What you will see, and why

The installer and the portable build show **"Windows protected your PC —
Microsoft Defender SmartScreen prevented an unrecognized app from starting"**,
with the publisher shown as **Unknown publisher**. Your browser may add
**"isn't commonly downloaded"**.

SmartScreen judges a file by its publisher's certificate and by how many people
have already run it. These installers have no certificate yet, and a new file
has no history, so it is called unrecognized. It is not a verdict that the file
is harmful.

### Open it anyway

1. If the browser blocks the download, choose **Keep** (in Edge, the three dots
   beside the file, then **Keep**, then **Keep anyway**).
2. Run the installer. On the blue SmartScreen window click **More info**, then
   **Run anyway**.

The **portable** build is one `.exe` that unpacks to a temporary folder every
time it starts; it shows the same window. Use it where you cannot run an
installer. The installer starts faster.

If Microsoft Defender removes a file, check its SHA-256 against
`SHA256SUMS.txt` first. A match means it is the file this project built; you can
restore it from **Protection history** and report the false positive to Microsoft
at [microsoft.com/wdsi/filesubmission](https://www.microsoft.com/en-us/wdsi/filesubmission).

Windows also keeps its own switch for microphones: if recording is silent, open
**Settings → Privacy & security → Microphone** and allow desktop apps.

## Linux

There is no signing gate on Linux, so there are no warnings about the publisher.
The messages you may meet are technical.

**AppImage** (`…-linux-x86_64.AppImage`):

```bash
chmod +x LazyToText-Desktop-<version>-linux-x86_64.AppImage
./LazyToText-Desktop-<version>-linux-x86_64.AppImage
```

AppImages need FUSE 2. If it stops with a message about `libfuse.so.2`, install
it: `sudo apt install libfuse2` (on Ubuntu 24.04 the package is `libfuse2t64`).

**Debian and Ubuntu package** (`…-linux-amd64.deb`):

```bash
sudo apt install ./LazyToText-Desktop-<version>-linux-amd64.deb
```

If `apt` prints a note that the download was "performed unsandboxed as root",
the file was in your home folder. The note is harmless; the install continues.

Global hotkeys and the paste keystroke may behave differently on Wayland than on
X11, because Wayland limits what an application may listen to and send. If they
do not work, try an X11 session.

If the app does not start, run it from a terminal to see the message, and
[open an issue](https://github.com/aa-blinov/lazy-to-text/issues) with it.

## Why these installers are not signed, and what would change that

- **macOS notarization** needs an Apple Developer ID, from the $99-a-year Apple
  Developer Program (free for nonprofits, educational institutions and
  governments). The build pipeline is already prepared for it; see
  [Notarizing the Mac build](../README.md#notarizing-the-mac-build). It is a
  decision about money, not about the code.
- **Windows signing** needs a code-signing certificate. Open-source projects can
  apply to the [SignPath Foundation](https://signpath.org/terms) for a free one;
  its publisher name is then SignPath Foundation, and it takes an application.
- Until then, the checksum and the attestation above are how to know a file is
  genuine, and this page is why the warnings are expected.

## Questions

[Open an issue](https://github.com/aa-blinov/lazy-to-text/issues), or, for a
security problem, report it privately as described in
[SECURITY.md](../SECURITY.md).
