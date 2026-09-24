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
Name: "{group}\Install ReEzSynth prerequisites and dependencies"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_reezsynth.ps1"""; WorkingDir: "{app}"
Name: "{group}\Windows setup guide"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\INSTALL_WINDOWS.md"""
Name: "{group}\Third-party notices"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\THIRD_PARTY_NOTICES.md"""
Name: "{group}\Clean-machine test guide"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\CLEAN_MACHINE_TEST.md"""
Name: "{group}\Uninstall ReEzSynth"; Filename: "{uninstallexe}"
Name: "{userdesktop}\ReEzSynth"; Filename: "{app}\run_reezsynth.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "prerequisites\git"; Description: "Git for Windows (required to obtain the FuouM engine source)"; GroupDescription: "Optional prerequisites - keep selected to install only when a compatible version is missing:"
Name: "prerequisites\conda"; Description: "Miniforge/Conda (required for the ReEzSynth Python environment)"; GroupDescription: "Optional prerequisites - keep selected to install only when a compatible version is missing:"
Name: "prerequisites\visualstudio"; Description: "Visual Studio 2022 C++ Build Tools, MSVC x64 toolchain, and Windows SDK (required to build native extensions)"; GroupDescription: "Optional prerequisites - keep selected to install only when a compatible version is missing:"
Name: "prerequisites\cuda"; Description: "NVIDIA CUDA Toolkit 12.8 (required for GPU engines and native CUDA extensions)"; GroupDescription: "Optional prerequisites - keep selected to install only when a compatible version is missing:"

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "{code:GetBootstrapParameters}"; WorkingDir: "{app}"; Description: "Set up and validate the ReEzSynth engine environment now (selected prerequisites run first; large download; administrator approval may be required)"; Flags: postinstall skipifsilent
Filename: "{sys}\notepad.exe"; Parameters: """{app}\INSTALL_WINDOWS.md"""; Description: "Open the Windows setup guide"; Flags: postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\ReEzSynth"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\ReEzSynth"; ValueType: string; ValueName: "Commit"; ValueData: "{#Commit}"

[UninstallDelete]
; Remove app-local runtime state created by setup/Python. The ezsynth tree is also
; installer-owned source; its entry removes generated nested caches after Inno
; removes the registered source files.
; Shared Git/Miniforge/Visual Studio/CUDA installations, named Conda environments,
; and projects/renders outside {app} are intentionally retained.
Type: filesandordirs; Name: "{app}\.engine_envs"
Type: filesandordirs; Name: "{app}\engine_sources"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\ezsynth"
Type: filesandordirs; Name: "{app}\.reezsynth-cache"
Type: files; Name: "{app}\.reezsynth-conda-path.txt"
Type: files; Name: "{app}\.reezsynth-env-name.txt"
Type: files; Name: "{app}\.reezsynth-setup-resume.json"

[Code]
function GetBootstrapParameters(Param: String): String;
begin
  Result := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\install_reezsynth.ps1') + '"';
  if not WizardIsTaskSelected('prerequisites\git') then
    Result := Result + ' -SkipGit';
  if not WizardIsTaskSelected('prerequisites\conda') then
    Result := Result + ' -SkipConda';
  if not WizardIsTaskSelected('prerequisites\visualstudio') then
    Result := Result + ' -SkipVisualStudio';
  if not WizardIsTaskSelected('prerequisites\cuda') then
    Result := Result + ' -SkipCuda';
end;
