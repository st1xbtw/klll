; Установщик Harness Cloud (Inno Setup 6). Собирается в CI из dist\HarnessCloud.
; Ставит в профиль пользователя (без прав администратора), создаёт ярлык в меню «Пуск».

#define MyAppName "Harness Cloud"
#define MyAppVersion "1.0.0"
#define MyAppExe "HarnessCloud.exe"

[Setup]
AppId=HarnessCloud.Desktop
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Harness Cloud
DefaultDirName={localappdata}\Programs\HarnessCloud
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
SetupIconFile=..\ui\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
OutputDir=..\installer_out
OutputBaseFilename=HarnessCloud-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительно:"

[Files]
Source: "..\dist\HarnessCloud\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent
