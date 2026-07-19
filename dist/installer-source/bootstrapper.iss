; ===========================================================================
;  PyMentor Lab - Bootstrapper (Stage D)
;  --------------------------------------------------------------------------
;  Single Inno Setup wrapper that:
;    1. Runs the Electron student app installer (PyMentorLab-Setup.exe,
;       Squirrel.Windows /SILENT)            -- component `main`
;    2. Unpacks the backend deployment kit to Documents\PyMentorLab-Backend
;       after verifying Docker Desktop is available
;                                            -- component `backend`
;
;  The backend is NEVER auto-started and NEVER auto-configured. The user must
;  edit .env (PROVIDER_MASTER_KEY, ADMIN_*) before running deploy.ps1.
;
;  Build:
;    "F:/Tools/Inno-Setup6/ISCC.exe" dist/installer-source/bootstrapper.iss
;  Output:
;    dist/installer/PyMentorLab-Bootstrapper.exe
; ===========================================================================

#define MyAppName      "PyMentor Lab 引导安装程序"
#define MyAppVersion   "1.1.0"
#define MyAppPublisher "PyMentor Lab"

[Setup]
AppId={#MyAppName}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={commonpf}\PyMentorLab
DefaultGroupName={#MyAppPublisher}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
DisableReadyMemo=no
; Program Files install; requires admin for the unpack-to-{app} step too.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=..\installer
OutputBaseFilename=PyMentorLab-Bootstrapper

Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

WizardStyle=modern
ShowLanguageDialog=no

SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico

; The bootstrapper itself only lays down a marker + (optionally) the backend
; kit; there is no "application" icon group worth showing. We still create a
; minimal entry so Add/Remove Programs is informative.
UninstallDisplayName={#MyAppName} {#MyAppVersion}

; Note: ChineseSimplified.isl is not bundled with Inno Setup 6.7.3, so the
; wizard chrome falls back to the built-in English (Default.isl). Our custom
; PascalScript MsgBox / StatusMsg strings are still rendered in Simplified
; Chinese for end-user clarity.

[Types]
Name: "full"; Description: "完整安装（学生端 + 后端部署包）"
Name: "custom"; Description: "自定义安装"; Flags: iscustom

[Components]
; `main` is fixed: the student app is the primary deliverable.
Name: "main";    Description: "学生端主程序（PyMentor Lab 桌面应用）";                   Types: full custom; Flags: fixed
Name: "backend"; Description: "后端服务部署包（需要 Docker Desktop，仅解压不启动）";  Types: full

[Files]
; --- main: the Electron installer. Copied to {tmp} and run from there. ---
Source: "installer-assets\PyMentorLab-Setup.exe"; DestDir: "{tmp}"; Components: main;    Flags: nocompression deleteafterinstall
; --- backend: deployment kit + the docker checker. ---
Source: "installer-assets\backend-deploy.zip";    DestDir: "{app}\backend"; Components: backend; Flags: nocompression ignoreversion
Source: "check-docker.ps1";                       DestDir: "{tmp}";        Components: backend; Flags: nocompression deleteafterinstall
; --- keep the brand icon alongside {app} for the uninstall display icon. ---
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Run]
; --- main: silent Squirrel install of the student app. ---
Filename: "{tmp}\PyMentorLab-Setup.exe"; Parameters: "/SILENT /NORESTART"; \
  Components: main; StatusMsg: "正在安装学生端主程序…"; \
  Flags: waituntilterminated runhidden

; --- backend: the heavy lifting lives in [Code] so we can react to the
;     docker-check exit code (warn-and-skip rather than fail). Steps here
;     and in CurStepChanged below. ---

[Code]
const
  DOCKER_DOWNLOAD_URL = 'https://www.docker.com/products/docker-desktop/';
  BACKEND_DOCS_URL    = 'docs/deployment/backend-deploy-windows.md';

var
  // Set by PrepareToInstall when the user selected the backend component.
  BackendSelected: Boolean;

function IsBackendSelected: Boolean;
begin
  Result := BackendSelected;
end;

// ---------------------------------------------------------------------------
// Pre-install gate: probe Docker once, before file extraction. If the backend
// component is selected we warn (but do NOT abort) when Docker is missing,
// so the user can still finish installing the student app.
// ---------------------------------------------------------------------------
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Msg: String;
begin
  Result := '';

  if WizardIsComponentSelected('backend') then begin
    BackendSelected := True;

    // Run check-docker.ps1; {tmp}\check-docker.ps1 was copied in [Files].
    if Exec(ExpandConstant('{cmd}'),
            ExpandConstant('/c powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{tmp}\check-docker.ps1"'),
            '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then begin

      case ResultCode of
        0: ; // Docker OK - proceed.

        1: begin
             // Docker not installed. Warn, then skip backend deploy.
             Msg := '未检测到 Docker Desktop。' + #13#10 + #13#10
                  + '后端部署包仍会解压到 Documents\PyMentorLab-Backend，' + #13#10
                  + '但需要先安装 Docker Desktop 才能运行 deploy.ps1。' + #13#10 + #13#10
                  + '下载地址：' + DOCKER_DOWNLOAD_URL;
             MsgBox(Msg, mbInformation, MB_OK);
             // Continue the install; backend deploy step will be skipped.
           end;

        2: begin
             // Daemon not running.
             Msg := 'Docker Desktop 已安装，但守护进程未运行。' + #13#10 + #13#10
                  + '请启动 Docker Desktop，等待其变为运行状态后，' + #13#10
                  + '再双击 Documents\PyMentorLab-Backend\deploy.ps1 部署后端。';
             MsgBox(Msg, mbInformation, MB_OK);
           end;

        3: begin
             // compose plugin missing.
             Msg := '未检测到 docker compose 插件。' + #13#10 + #13#10
                  + '请在 Docker Desktop 中启用 Compose，或更新到最新版本：' + #13#10
                  + DOCKER_DOWNLOAD_URL;
             MsgBox(Msg, mbInformation, MB_OK);
           end;
      else
        // Unexpected exit code (4 or otherwise): warn but don't block.
        MsgBox('Docker 检查返回异常代码 (' + IntToStr(ResultCode) + ')，已跳过后端部署。',
               mbInformation, MB_OK);
      end;
    end;
  end else begin
    BackendSelected := False;
  end;
end;

// ---------------------------------------------------------------------------
// Post-install: unpack the backend kit and surface clear next-step guidance.
// Runs after all [Files] have been copied and after the [Run] student-app step.
// ---------------------------------------------------------------------------
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  BackendDir: String;
  ExpandCmd: String;
  Msg: String;
  OpenFolder: Integer;
begin
  if CurStep <> ssPostInstall then Exit;
  if not BackendSelected then Exit;

  BackendDir := ExpandConstant('{userdocs}\PyMentorLab-Backend');

  // Expand-Archive will create BackendDir as needed; -Force overwrites prior
  // extracts so re-runs are clean.
  ExpandCmd := '-NoProfile -ExecutionPolicy Bypass -Command "'
             + 'Expand-Archive -Path ''' + ExpandConstant('{app}\backend\backend-deploy.zip') + ''''
             + ' -DestinationPath ''' + BackendDir + ''' -Force'
             + '"';

  if not Exec(ExpandConstant('{cmd}'), '/c powershell.exe ' + ExpandCmd,
              '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then begin
    MsgBox('解压后端部署包失败 (ExitCode=' + IntToStr(ResultCode) + ')。' + #13#10
         + '请稍后手动解压 {app}\backend\backend-deploy.zip。',
           mbError, MB_OK);
    Exit;
  end;

  // Stage C design: never auto-start the backend. Always require the user to
  // edit .env (admin email/password + PROVIDER_MASTER_KEY) first.
  Msg := '后端部署包已解压到：' + #13#10
       + BackendDir + #13#10 + #13#10
       + '部署步骤：' + #13#10
       + '  1. 复制 .env.example 为 .env 并编辑' + #13#10
       + '     （设置管理员邮箱/密码与 PROVIDER_MASTER_KEY）' + #13#10
       + '  2. 双击 deploy.ps1 启动后端' + #13#10 + #13#10
       + '详细说明见 ' + BACKEND_DOCS_URL;
  MsgBox(Msg, mbInformation, MB_OK);

  // Offer to open the unpacked folder.
  OpenFolder := MsgBox('是否打开后端部署目录？', mbConfirmation, MB_YESNO or MB_DEFBUTTON1);
  if OpenFolder = IDYES then begin
    ShellExec('open', BackendDir, '', '', SW_SHOW, ewNoWait, ResultCode);
  end;
end;
