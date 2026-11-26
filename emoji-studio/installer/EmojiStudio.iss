; Inno Setup 6. Сборка: ISCC.exe installer\EmojiStudio.iss (после PyInstaller, см. dist\EmojiStudio).
#define AppVersion "1.0.0"

[Setup]
AppId={{6B1E0C2A-8F3D-4C55-9A21-7E5D0C0FFEE1}
AppName=Emoji Studio
AppVersion={#AppVersion}
AppPublisher=Emoji Studio
DefaultDirName={autopf}\EmojiStudio
DefaultGroupName=Emoji Studio
DisableProgramGroupPage=yes
OutputDir=..\installer_out
OutputBaseFilename=EmojiStudio-Setup-{#AppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\EmojiStudio.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Установка без прав администратора: в профиль пользователя
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"

[Files]
Source: "..\dist\EmojiStudio\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Emoji Studio"; Filename: "{app}\EmojiStudio.exe"
Name: "{group}\Удалить Emoji Studio"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Emoji Studio"; Filename: "{app}\EmojiStudio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\EmojiStudio.exe"; Description: "Запустить Emoji Studio"; Flags: nowait postinstall skipifsilent
