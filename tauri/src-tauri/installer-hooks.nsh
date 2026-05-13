; NSIS installer hooks for Drevalis Creator Studio.
;
; Tauri's NSIS template calls these macros at well-defined points. We use
; them to kill any running Drevalis processes BEFORE the installer starts
; writing files, so re-installing (manually or via the in-app updater)
; doesn't fail with "Error opening file for writing" on locked DLLs and
; the bundled redis-server.exe.
;
; The in-app updater path is handled belt-and-braces: the Tauri shell
; already tree-kills the backend subtree via `taskkill /F /T` before
; spawning the installer (see src/main.rs::kill_backend). These hooks
; cover the *manual* path where a user double-clicks the .exe while
; Drevalis is still running.

!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping any running Drevalis processes..."
  ; Tauri front-end shell. /T kills its children too, but the children may
  ; have already escaped the parent's job, so explicitly /IM each one.
  nsExec::Exec 'taskkill /F /T /IM "drevalis-shell.exe"'
  Pop $0
  nsExec::Exec 'taskkill /F /T /IM "Drevalis Creator Studio.exe"'
  Pop $0
  ; Python launcher + spawned children (api/worker/redis).
  nsExec::Exec 'taskkill /F /T /IM "drevalis.exe"'
  Pop $0
  ; Bundled Redis sidecar — survives if its parent escaped tree-kill.
  nsExec::Exec 'taskkill /F /IM "redis-server.exe"'
  Pop $0
  ; Brief settle so the OS releases file handles before WriteFile begins.
  Sleep 500
!macroend
