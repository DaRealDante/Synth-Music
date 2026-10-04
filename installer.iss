#define MyAppName "Synth Music"
#define MyAppVersion GetEnv("KM_VERSION")
#define MyAppExe "SynthMusic.exe"

[Setup]
AppId={{5B1E9D44-2C7A-4F8B-A3E6-9D0C17F2B835}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Ken [HD]
DefaultDirName={localappdata}\Programs\Synth Music
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=SynthMusic_Setup_v{#MyAppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea un'icona sul desktop"; GroupDescription: "Icone:"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\SynthMusic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon
Name: "{autoprograms}\Synth Music - Aggiorna"; Filename: "{localappdata}\SynthMusic\Sorgente\INSTALLA_E_AGGIORNA.bat"; WorkingDir: "{localappdata}\SynthMusic\Sorgente"; IconFilename: "{app}\{#MyAppExe}"; Check: SourceExists

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Avvia Synth Music"; Flags: nowait postinstall

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  OldUninstaller: String;
begin
  if CurStep = ssInstall then
  begin
    OldUninstaller := ExpandConstant('{localappdata}\Programs\Ken Music\unins000.exe');
    if FileExists(OldUninstaller) then
      Exec(OldUninstaller, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

function SourceExists: Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\SynthMusic\Sorgente\synth_build.py'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    if MsgBox('Vuoi eliminare anche playlist, canzoni scaricate, testi, video e impostazioni?' + #13#10 + 'Se scegli No restano per una futura reinstallazione.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{userappdata}\SynthMusic'), True, True, True);
      DelTree(ExpandConstant('{userappdata}\KenMusic'), True, True, True);
    end;
end;
