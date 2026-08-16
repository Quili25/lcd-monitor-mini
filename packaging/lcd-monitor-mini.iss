; Inno Setup script for lcd-monitor-mini
; Requires: Inno Setup 6+ (ISCC.exe)
; Build PyInstaller output first: dist\lcd-monitor-mini\

#define MyAppName "lcd-monitor-mini"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "lcd-monitor-mini"
#define MyAppExeName "lcd-monitor-mini.exe"
#define SourceDir "..\dist\lcd-monitor-mini\"

[Setup]
AppId={{A8F3C2E1-7B4D-4E9A-9C1F-2D6E8B0A5F33}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=lcd-monitor-mini-Setup-{#MyAppVersion}
SetupIconFile=icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked
Name: "autostart"; Description: "Start {#MyAppName} when I log in"; GroupDescription: "Startup:"; Flags: unchecked
Name: "disableusbmonitor"; Description: "Stop other LCD monitor utilities holding the COM port"; GroupDescription: "COM port:"; Flags: checkedonce

[Files]
Source: "{#SourceDir}*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "scripts\disable-usbmonitor.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "scripts\reset-display.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\disable-usbmonitor.ps1"""; StatusMsg: "Freeing COM port..."; Flags: runhidden waituntilterminated; Tasks: disableusbmonitor
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Keep LocalAppData themes/config — do not wipe user data
Type: files; Name: "{app}\*.log"
