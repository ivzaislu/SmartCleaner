[Setup]
AppId=SmartCleaner
AppName=SmartCleaner
AppVersion=2.0.2
DefaultDirName={localappdata}\Programs\SmartCleaner
DefaultGroupName=SmartCleaner
AllowNoIcons=yes
OutputDir=output
OutputBaseFilename=SmartCleaner-2.0.2-Setup
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
UninstallDisplayIcon={app}\SmartCleaner.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "contextmenu"; Description: "{cm:ExplorerQuarantine}"; Flags: unchecked

[CustomMessages]
english.ExplorerQuarantine=Add a file quarantine command to Explorer
russian.ExplorerQuarantine=Добавить команду карантина в контекстное меню Проводника
english.QuarantineVerb=Move to SmartCleaner quarantine
russian.QuarantineVerb=Переместить в карантин SmartCleaner

[Files]
Source: "..\..\dist\SmartCleaner.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SmartCleaner"; Filename: "{app}\SmartCleaner.exe"

Name: "{userdesktop}\SmartCleaner"; Filename: "{app}\SmartCleaner.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SmartCleaner.exe"; Description: "{cm:LaunchProgram,SmartCleaner}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Registry]
Root: HKCU; Subkey: "Software\Classes\*\shell\SmartCleanerDelete"; ValueType: string; ValueData: "{cm:QuarantineVerb}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\SmartCleanerDelete"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Single"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\SmartCleanerDelete\command"; ValueType: string; ValueData: """{app}\SmartCleaner.exe"" --delete ""%1"""; Tasks: contextmenu
