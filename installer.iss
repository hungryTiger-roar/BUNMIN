; Aunion AI - Inno Setup 스크립트
; ISCC installer.iss 로 빌드 → setup/Aunion-AI-Setup-0.1.0.exe 생성

#define MyAppName "Aunion AI"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Aunion Team"
#define MyAppExeName "Aunion AI.exe"
#define MyAppId "{{C8A2E4B6-3F8D-4A1B-9C7E-1D2F3A4B5C6D}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=setup
OutputBaseFilename=Aunion-AI-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
; 17GB+ 동봉이라 디스크 여유 체크
DiskSpanning=no
; 설치 종료 후 곧바로 실행 가능하게
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"

[Files]
; win-unpacked 전체 복사 — 단 VLM Base 17GB는 제외 (첫 실행 시 HF에서 다운로드)
Source: "setup\win-unpacked\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: "resources\backend\models\qwen2.5-vl-7b-instruct\*"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; per-user 설치 + asInvoker manifest이므로 별도 권한 플래그 불필요
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
  Flags: nowait postinstall skipifsilent
