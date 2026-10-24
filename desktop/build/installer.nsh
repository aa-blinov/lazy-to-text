; Included by electron-builder's NSIS installer (build/installer.nsh).
;
; Registers Lazy to Text as a program Windows may offer for audio and video
; files ("Open with"), which is what spec 007 asks of the Qt build too, for
; every extension the runtime accepts (app/audio_formats.py: a test compares
; the list below with it). The extension's own default class is left alone: electron-builder's
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

; The one list of extensions: each macro above is run for every entry.
!macro l2tEachExtension ACTION
  !insertmacro ${ACTION} "wav"
  !insertmacro ${ACTION} "flac"
  !insertmacro ${ACTION} "ogg"
  !insertmacro ${ACTION} "oga"
  !insertmacro ${ACTION} "opus"
  !insertmacro ${ACTION} "aiff"
  !insertmacro ${ACTION} "aif"
  !insertmacro ${ACTION} "mp3"
  !insertmacro ${ACTION} "m4a"
  !insertmacro ${ACTION} "aac"
  !insertmacro ${ACTION} "wma"
  !insertmacro ${ACTION} "amr"
  !insertmacro ${ACTION} "ac3"
  !insertmacro ${ACTION} "alac"
  !insertmacro ${ACTION} "mp4"
  !insertmacro ${ACTION} "mov"
  !insertmacro ${ACTION} "webm"
  !insertmacro ${ACTION} "mkv"
  !insertmacro ${ACTION} "avi"
  !insertmacro ${ACTION} "flv"
  !insertmacro ${ACTION} "3gp"
  !insertmacro ${ACTION} "m4v"
  !insertmacro ${ACTION} "wmv"
  !insertmacro ${ACTION} "ts"
!macroend

; ---- the Qt build this one replaces -------------------------------------------
;
; The Qt application was installed by an Inno Setup installer whose AppId is
; below (installer/lazy_to_text.iss); Inno records an uninstaller under
; that id with "_is1" appended. Left in place it would sit next to this
; app, and its optional "start with Windows" shortcut would start it at login
; and win the single-instance lock this app shares with it. So the installer
; offers to remove it first. Settings, history and models are not in the
; Qt install folder (they are in the per-user data folders both share), and
; the Inno uninstaller leaves them alone.
;
; Best effort: nothing here may stop the installation. The uninstaller is run
; in place (_?=), because without it Inno copies itself to a temporary folder
; and the first process exits at once, which would let this installer carry on
; while the old one is still deleting. This path has not been run on Windows.

!define L2T_QT_UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\{D7B4F3A2-8C5E-4D9F-9A1B-3F2E1D8C7B6A}_is1"

!macro l2tRemoveQtBuild ROOT
  ReadRegStr $R0 ${ROOT} "${L2T_QT_UNINSTALL_KEY}" "UninstallString"
  ReadRegStr $R1 ${ROOT} "${L2T_QT_UNINSTALL_KEY}" "InstallLocation"
  ${If} $R0 != ""
  ${AndIf} $R1 != ""
    ; Inno writes the folder with a trailing backslash; _?= wants it without.
    StrCpy $R2 $R1 1 -1
    ${If} $R2 == "\"
      StrCpy $R1 $R1 -1
    ${EndIf}
    ; /SD: a silent installation answers yes, which is the upgrade it was asked for.
    MessageBox MB_YESNO|MB_ICONQUESTION "An earlier version of Lazy to Text (the Qt build) is installed. It has to be removed so that this one can replace it. Your settings, history and downloaded models are kept.$\r$\n$\r$\nRemove it now?" /SD IDYES IDNO l2t_keep_qt_${ROOT}
    ClearErrors
    ExecWait '$R0 /SILENT /SUPPRESSMSGBOXES /NORESTART _?=$R1' $R3
    ${IfNot} ${Errors}
    ${AndIf} $R3 == 0
      ; With _?= the uninstaller does not delete itself.
      Delete "$R1\unins000.exe"
      Delete "$R1\unins000.dat"
      RMDir "$R1"
    ${EndIf}
    l2t_keep_qt_${ROOT}:
  ${EndIf}
!macroend

!macro customInit
  Push $R0
  Push $R1
  Push $R2
  Push $R3
  !insertmacro l2tRemoveQtBuild HKCU
  ; An all-users Inno install (the wizard lets an administrator choose it).
  SetRegView 64
  !insertmacro l2tRemoveQtBuild HKLM
  Pop $R3
  Pop $R2
  Pop $R1
  Pop $R0
!macroend

!macro customInstall
  WriteRegStr SHELL_CONTEXT "Software\Classes\LazyToText.Desktop.Media" "" "Audio or video (Lazy to Text)"
  WriteRegStr SHELL_CONTEXT "Software\Classes\LazyToText.Desktop.Media\DefaultIcon" "" "$INSTDIR\${APP_EXECUTABLE_FILENAME},0"
  WriteRegStr SHELL_CONTEXT "Software\Classes\LazyToText.Desktop.Media\shell\open" "" "Transcribe with Lazy to Text"
  WriteRegStr SHELL_CONTEXT "Software\Classes\LazyToText.Desktop.Media\shell\open\command" "" '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" "%1"'
  !insertmacro l2tEachExtension l2tRegisterExtension
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
!macroend

!macro customUnInstall
  !insertmacro l2tEachExtension l2tUnregisterExtension
  DeleteRegKey SHELL_CONTEXT "Software\Classes\LazyToText.Desktop.Media"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
!macroend
