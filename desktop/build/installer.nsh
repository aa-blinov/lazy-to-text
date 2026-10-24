; Included by electron-builder's NSIS installer (build/installer.nsh).
;
; Registers Lazy to Text as a program Windows may offer for audio and video
; files ("Open with"), which is what spec 007 asks of the Qt build too. The
; extension's own default class is left alone: electron-builder's
; fileAssociations would write it, which makes a double-click on an .mp3 open
; this app instead of the user's player. OpenWithProgids only adds a choice.
;
; The paths are per-user or per-machine according to the install mode
; (SHELL_CONTEXT is HKCU or HKLM), like the rest of the installer.

!macro l2tRegisterExtension EXT
  WriteRegStr SHELL_CONTEXT "Software\Classes\.${EXT}\OpenWithProgids" "LazyToText.Desktop.Media" ""
!macroend

!macro l2tUnregisterExtension EXT
  DeleteRegValue SHELL_CONTEXT "Software\Classes\.${EXT}\OpenWithProgids" "LazyToText.Desktop.Media"
!macroend

!macro customInstall
  WriteRegStr SHELL_CONTEXT "Software\Classes\LazyToText.Desktop.Media" "" "Audio or video (Lazy to Text)"
  WriteRegStr SHELL_CONTEXT "Software\Classes\LazyToText.Desktop.Media\DefaultIcon" "" "$INSTDIR\${APP_EXECUTABLE_FILENAME},0"
  WriteRegStr SHELL_CONTEXT "Software\Classes\LazyToText.Desktop.Media\shell\open" "" "Transcribe with Lazy to Text"
  WriteRegStr SHELL_CONTEXT "Software\Classes\LazyToText.Desktop.Media\shell\open\command" "" '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" "%1"'
  !insertmacro l2tRegisterExtension "wav"
  !insertmacro l2tRegisterExtension "mp3"
  !insertmacro l2tRegisterExtension "m4a"
  !insertmacro l2tRegisterExtension "flac"
  !insertmacro l2tRegisterExtension "ogg"
  !insertmacro l2tRegisterExtension "aac"
  !insertmacro l2tRegisterExtension "aiff"
  !insertmacro l2tRegisterExtension "mp4"
  !insertmacro l2tRegisterExtension "mov"
  !insertmacro l2tRegisterExtension "webm"
  !insertmacro l2tRegisterExtension "mkv"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
!macroend

!macro customUnInstall
  !insertmacro l2tUnregisterExtension "wav"
  !insertmacro l2tUnregisterExtension "mp3"
  !insertmacro l2tUnregisterExtension "m4a"
  !insertmacro l2tUnregisterExtension "flac"
  !insertmacro l2tUnregisterExtension "ogg"
  !insertmacro l2tUnregisterExtension "aac"
  !insertmacro l2tUnregisterExtension "aiff"
  !insertmacro l2tUnregisterExtension "mp4"
  !insertmacro l2tUnregisterExtension "mov"
  !insertmacro l2tUnregisterExtension "webm"
  !insertmacro l2tUnregisterExtension "mkv"
  DeleteRegKey SHELL_CONTEXT "Software\Classes\LazyToText.Desktop.Media"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
!macroend
