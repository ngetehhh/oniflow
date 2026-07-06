#define MyAppName "Oniflow"
#define MyAppVersion "0.9.4-beta"
#define MyAppPublisher "Oniven"
#define MyAppExeName "Oniflow.exe"
#define MyAppURL "https://www.instagram.com/oniven.tt/"

[Setup]
AppId={{B12F8238-E924-4FE2-AC37-01F10A000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf64}\Oniflow
DefaultGroupName=Oniflow
DisableProgramGroupPage=yes
OutputDir=installer-output
OutputBaseFilename=Oniflow-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
Uninstallable=yes
CreateUninstallRegKey=yes
UninstallDisplayName={#MyAppName}
LicenseFile=EULA.md
SetupIconFile=assets\oniflow.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
MinVersion=10.0
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Files]
Source: "release\Oniflow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Oniflow"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Oniflow"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Oniflow"; Flags: nowait postinstall skipifsilent
