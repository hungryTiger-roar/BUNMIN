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
; 비주얼 — placeholder 자산 (정식 디자인 나오면 같은 경로 파일 교체)
SetupIconFile=installer-assets\icon.ico
WizardImageFile=installer-assets\wizard-image.bmp
WizardSmallImageFile=installer-assets\wizard-small.bmp
WizardImageStretch=no
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

[Code]
{
  설치 후 첫 실행 시 VLM 모델(~14GB)을 HuggingFace에서 다운로드합니다.
  Windows symlink 우회 패치 때문에 cache 사용량이 ~2배가 되어 실제로 ~30GB 가 필요.
  설치 시점에 미리 안내 + 디스크 여유 부족하면 경고 (강제 차단은 안 함).
}
const
  RequiredFreeGB = 35;  { 모델 14GB + symlink → copy 패치로 인한 ~2배 사용 + 안전 마진 }

var
  DiskInfoPage: TOutputMsgWizardPage;

function GetFreeGB(Path: String): Double;
var
  FreeBytes, TotalBytes: Int64;
begin
  Result := -1.0;
  if GetSpaceOnDisk64(Path, FreeBytes, TotalBytes) then
    Result := FreeBytes / (1024.0 * 1024.0 * 1024.0);
end;

procedure InitializeWizard();
begin
  DiskInfoPage := CreateOutputMsgPage(
    wpWelcome,
    'AI 모델 추가 다운로드 안내',
    '첫 실행 시 인터넷에서 AI 모델이 자동으로 다운로드됩니다.',
    '이 설치 프로그램은 약 3.5 GB 의 앱 본체를 설치합니다.' + #13#10 +
    '처음 실행 시 슬라이드 번역용 AI 모델 약 14 GB 를 HuggingFace 에서 추가 다운로드합니다.' + #13#10 + #13#10 +
    'Windows 안전 모드 호환을 위해 모델은 ~2배 공간을 사용하므로,' + #13#10 +
    '쾌적한 사용을 위해 사용자 디스크에 약 35 GB 이상의 여유 공간을 확보해 주세요.' + #13#10 + #13#10 +
    '여유 공간이 부족하면 모델 다운로드가 실패할 수 있습니다 (앱은 정상 설치).');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  FreeGB: Double;
begin
  Result := True;
  if CurPageID = DiskInfoPage.ID then
  begin
    FreeGB := GetFreeGB(ExpandConstant('{autopf}'));
    if (FreeGB > 0) and (FreeGB < RequiredFreeGB) then
    begin
      if MsgBox(
        Format('현재 디스크 여유 공간: %.1f GB' + #13#10 +
               '권장 여유 공간: %d GB' + #13#10 + #13#10 +
               '여유 공간이 권장치보다 적습니다. 첫 실행 시 모델 다운로드가 실패할 수 있습니다.' + #13#10 + #13#10 +
               '그래도 설치를 계속하시겠습니까?', [FreeGB, RequiredFreeGB]),
        mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

{
  백엔드 (aunion_backend.exe) 는 부모 Electron 종료 후에도 5분 grace 동안 살아남아
  학생 자막 다운로드를 처리함 (757bd35 워치독 패턴). install / uninstall 진입 시점에
  이 백엔드가 살아있으면 .exe 파일 락 때문에 Inno Setup 이 파일을 못 지워 "수동 삭제"
  메시지를 표시. 진입 직전에 taskkill 로 정리해 매끄러운 install/uninstall 흐름 보장.
}
procedure KillAunionProcesses();
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM aunion_backend.exe /T',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM "Aunion AI.exe" /T',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  { 파일 락 해제 대기 — Windows 가 핸들 정리하는 데 잠시 걸릴 수 있음 }
  Sleep(500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillAunionProcesses();
  Result := '';  { 빈 문자열 = 진행 OK }
end;

function InitializeUninstall(): Boolean;
begin
  KillAunionProcesses();
  Result := True;
end;

{
  메인 uninstall 끝난 후 사용자 데이터(%LOCALAPPDATA%\Aunion AI\) 삭제 여부 묻기.
    - 내용: HF 모델 캐시(VLM ~14GB+), 다운받은 모델, error_log, 설정
    - 기본 권장 = "아니오" (재설치 시 14GB 재다운로드 회피)
    - silent uninstall (/VERYSILENT 등) 일 때는 안전하게 데이터 유지 (프롬프트 X, 삭제 X)
}
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataDir: String;
  Response: Integer;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  if UninstallSilent then Exit;

  UserDataDir := ExpandConstant('{localappdata}\Aunion AI');
  if not DirExists(UserDataDir) then Exit;

  Response := MsgBox(
    '사용자 데이터를 함께 삭제하시겠습니까?' + #13#10 + #13#10 +
    '위치: ' + UserDataDir + #13#10 +
    '내용: 다운받은 AI 모델 캐시(~14GB+), 로그, 설정' + #13#10 + #13#10 +
    '[예] 함께 삭제 — 디스크 공간 회복' + #13#10 +
    '[아니오] 데이터 유지 — 재설치 시 모델 재다운로드 안 받음 (권장)',
    mbConfirmation, MB_YESNO);

  if Response = IDYES then
  begin
    if not DelTree(UserDataDir, True, True, True) then
      MsgBox(
        '일부 파일 삭제에 실패했습니다 (앱이 아직 살아있거나 권한 문제).' + #13#10 + #13#10 +
        '수동 삭제 경로: ' + UserDataDir,
        mbInformation, MB_OK);
  end;
end;
