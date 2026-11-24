; LiuliDNS per-user installer (NSIS 3.x / Unicode).
; Build after dist\LiuliDNS exists:
;   makensis /DAPP_VERSION=0.2.2 /DAPP_VERSION4=0.2.2.0 packaging\installer.nsi
; Then sign dist\LiuliDNS-Setup-0.1.0.exe on the signing machine.

Unicode true
!include "MUI2.nsh"

!ifndef APP_VERSION
  !define APP_VERSION "0.2.2"
!endif
!ifndef APP_VERSION4
  !define APP_VERSION4 "0.2.2.0"
!endif

!define APP_NAME "LiuliDNS"
!define APP_PUBLISHER "LiuliDNS"
!define APP_EXE "LiuliDNS.exe"
!ifndef DIST_DIR
  !define DIST_DIR "dist"
!endif
!ifndef ICON_PATH
  !define ICON_PATH "client\resources\app-icon.ico"
!endif
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\LiuliDNS"

Name "${APP_NAME}"
OutFile "${DIST_DIR}\LiuliDNS-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\LiuliDNS"
InstallDirRegKey HKCU "Software\LiuliDNS" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "${APP_NAME} ${APP_VERSION}"

VIProductVersion "${APP_VERSION4}"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "CompanyName" "${APP_PUBLISHER}"
VIAddVersionKey "FileDescription" "${APP_NAME} installer"
VIAddVersionKey "FileVersion" "${APP_VERSION4}"
VIAddVersionKey "ProductVersion" "${APP_VERSION4}"
VIAddVersionKey "LegalCopyright" "Copyright (c) 2026 LiuliDNS"

!define MUI_ABORTWARNING
!define MUI_ICON "${ICON_PATH}"
!define MUI_UNICON "${ICON_PATH}"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "启动 ${APP_NAME}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "${DIST_DIR}\LiuliDNS\*.*"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\LiuliDNS" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"

  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\LiuliDNS"

  ; User settings, crash logs and local lab certificates are intentionally
  ; left in place so an uninstall never destroys user data silently.
  RMDir /r "$INSTDIR"
SectionEnd
