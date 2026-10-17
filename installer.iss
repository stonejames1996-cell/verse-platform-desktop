; Inno Setup script: wraps the built app into "Verse Platform Setup x.y.z.exe"
#define AppName "Verse Platform"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "Verse Platform.exe"

[Setup]
AppId={{B3A1F6C2-5D47-4E8A-9F10-7C2E8D4B6A55}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Verse Platform
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; installs for just this user without needing admin, but lets people pick "all users" if they want
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=Verse Platform Setup {#AppVersion}
SetupIconFile=assets\logo.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardImageFile=assets\wizard_large.bmp
WizardSmallImageFile=assets\wizard_small.bmp
WizardStyle=modern
Compression=lzma2/ultra
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start Verse Platform when Windows starts (recommended)"; GroupDescription: "Startup:"

[Files]
Source: "dist\Verse Platform\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; same value the app's "Start with Windows" tray toggle uses
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --background"; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent
; auto updates run this installer silently with /RELAUNCH, so the app reopens by itself afterwards
Filename: "{app}\{#AppExe}"; Parameters: "{code:RelaunchArgs}"; Flags: nowait runasoriginaluser; Check: ShouldRelaunch

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ""{#AppExe}"""; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
; clean up the temporary clip buffer
Type: filesandordirs; Name: "{localappdata}\Temp\VersePlatform"

[Code]
// The app window needs Microsoft Edge WebView2. Windows 11 always has it, most Windows 10 PCs do too.
function HasWebView2: Boolean;
var v: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) and (v <> '') and (v <> '0.0.0.0'));
end;

// Auto update: "/RELAUNCH" reopens the app after a silent install, "/RELAUNCH=background" reopens it in the tray
function RelaunchParam: String;
var i: Integer;
begin
  Result := '';
  for i := 1 to ParamCount do
    if Pos('/RELAUNCH', Uppercase(ParamStr(i))) = 1 then Result := Uppercase(ParamStr(i));
end;

function ShouldRelaunch: Boolean;
begin
  Result := WizardSilent and (RelaunchParam <> '');
end;

function RelaunchArgs(Param: String): String;
begin
  if RelaunchParam = '/RELAUNCH=BACKGROUND' then Result := '--background' else Result := '';
end;

// The app used to be called "Verse Rewind". Remove that version quietly so there aren't two.
procedure RemoveOldVerseRewind;
var cmd: String; code: Integer;
begin
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6E1C2A4B-8F3D-4B7A-9C51-2D7E0F4A9B13}_is1', 'UninstallString', cmd) or
     RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6E1C2A4B-8F3D-4B7A-9C51-2D7E0F4A9B13}_is1', 'UninstallString', cmd) then
    Exec(RemoveQuotes(cmd), '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, code);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var code: Integer;
begin
  if CurStep = ssInstall then
    RemoveOldVerseRewind;
  if (CurStep = ssPostInstall) and (not HasWebView2) and (not WizardSilent) then
    if MsgBox('Verse Platform needs Microsoft Edge WebView2 (a free Microsoft component) to show its window.' + #13#10#13#10 +
              'Click OK to download it from Microsoft, run it, then open Verse Platform.', mbInformation, MB_OKCANCEL) = IDOK then
      ShellExec('open', 'https://go.microsoft.com/fwlink/p/?LinkId=2124703', '', '', SW_SHOWNORMAL, ewNoWait, code);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
end;
