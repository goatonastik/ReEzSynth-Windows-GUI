#ifndef MyAppVersion
  #error MyAppVersion must be supplied by build_release.ps1
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by build_release.ps1
#endif
#ifndef MyNumericVersion
  #error MyNumericVersion must be supplied by build_release.ps1
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build_release.ps1
#endif
#ifndef Commit
  #error Commit must be supplied by build_release.ps1
#endif

[Setup]
AppId={{F3C28DA2-E335-4C39-8874-B745AF38337B}
AppName=ReEzSynth
AppVersion={#MyAppVersion}
AppVerName=ReEzSynth {#MyAppVersion}
AppPublisher=ReEzSynth contributors
AppPublisherURL=https://github.com/goatonastik/ReEzSynth-Windows-GUI
AppSupportURL=https://github.com/goatonastik/ReEzSynth-Windows-GUI/issues
AppUpdatesURL=https://github.com/goatonastik/ReEzSynth-Windows-GUI/releases
DefaultDirName={localappdata}\Programs\ReEzSynth
DefaultGroupName=ReEzSynth
DisableProgramGroupPage=yes
LicenseFile={#SourceDir}\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=ReEzSynth-Windows-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern
UninstallDisplayName=ReEzSynth {#MyAppVersion}
VersionInfoVersion={#MyNumericVersion}
VersionInfoDescription=ReEzSynth Windows installer
VersionInfoCompany=ReEzSynth contributors
VersionInfoCopyright=GNU AGPL v3; see installed LICENSE
VersionInfoProductName=ReEzSynth
VersionInfoProductVersion={#MyNumericVersion}

[Files]
; Keep the installer focused on the runnable application and user-facing support
; material. The complete repository, tests and maintainer records remain in the
; companion source ZIP and public Git repository.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: ".github\*,installer\*,test_*.py,test_progress.txt,build_release.ps1,requirements-ci.txt,run_maintained_tests.py"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ReEzSynth"; Filename: "{app}\run_reezsynth.bat"; WorkingDir: "{app}"
Name: "{group}\Install ReEzSynth dependencies"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup_reezsynth.ps1"""; WorkingDir: "{app}"
Name: "{group}\Windows setup guide"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\INSTALL_WINDOWS.md"""
Name: "{group}\Third-party notices"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\THIRD_PARTY_NOTICES.md"""
Name: "{group}\Clean-machine test guide"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\CLEAN_MACHINE_TEST.md"""
Name: "{group}\Uninstall ReEzSynth"; Filename: "{uninstallexe}"
Name: "{userdesktop}\ReEzSynth"; Filename: "{app}\run_reezsynth.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup_reezsynth.ps1"""; WorkingDir: "{app}"; Description: "Install engines and dependencies now (large download; requires Git, Conda, CUDA 12.8 and Visual Studio C++ tools)"; Flags: postinstall skipifsilent unchecked
Filename: "{sys}\notepad.exe"; Parameters: """{app}\INSTALL_WINDOWS.md"""; Description: "Open the Windows setup guide"; Flags: postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\ReEzSynth"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\ReEzSynth"; ValueType: string; ValueName: "Commit"; ValueData: "{#Commit}"
