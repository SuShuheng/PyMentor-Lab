# PyMentor Lab 部署文档（v1.1）

- **版本**：v1.1
- **代码签名**：未签名（EXE 由 SmartScreen 拦截，需用户手动放行；BE-030 标记为
  WONTFIX，等待外部 Authenticode 证书）
- **文档语言**：简体中文（本项目的用户面向语言）
- **更新日期**：2026-07-19

本目录覆盖 PyMentor Lab v1.1 的完整部署生命周期，面向两类受众：

1. **学生端用户**：在自己 Windows 电脑上安装桌面应用，连接学校提供的后端。
2. **后端运维 / IT 管理员**：在学校服务器或本机部署后端服务栈（API + Worker +
   沙箱 + Web + Admin + PostgreSQL + Redis + MinIO）。

---

## 一、两种部署模式

### 模式 1：学生 Windows 安装（bootstrapper exe）

学生下载 `PyMentorLab-Bootstrapper.exe`，双击运行，按需选择是否也部署后端：

- **不部署后端**：学生只装桌面 App，启动后填入学校 IT 给出的 API 地址（"设置服务器
  地址"功能）。
- **部署后端**：本机既当学生机又当服务器（适合单机演示、小型班级、教师预览）。需要
  先装好 Docker Desktop。

详见 [windows-student-install.md](./windows-student-install.md)。

### 模式 2：后端独立部署（`dist/backend-deploy/` zip）

在学校服务器上独立部署后端服务栈，对外提供 API + 学生 Web + 管理 Web。打包产物为
`pymentor-backend-v1.1.zip`，解压后通过 `deploy.sh`（Linux/macOS）或 `deploy.ps1`
（Windows）拉起。这是正式生产环境的推荐模式。

详见 [backend-deploy-windows.md](./backend-deploy-windows.md) 和
[backend-deploy-linux.md](./backend-deploy-linux.md)。

---

## 二、先决条件矩阵

| 受众 | 平台 | 最低要求 | 部署产物 |
|---|---|---|---|
| 学生（仅桌面 App） | Windows 10/11 x64 | 4 GB 内存 / 2 GB 磁盘 | `PyMentorLab-Bootstrapper.exe` |
| 学生（自带后端） | Windows 10/11 x64 | 8 GB 内存 / 20 GB 磁盘 + Docker Desktop | bootstrapper exe（自动拉起后端） |
| 后端运维（Windows） | Windows Server 2019+ / Windows 10/11 | 8 GB 内存 / 20 GB 磁盘 + Docker Desktop | `pymentor-backend-v1.1.zip` |
| 后端运维（Linux） | Ubuntu 22.04+ / Debian 12+ / RHEL 9+ | 2 vCPU / 8 GB 内存 / 20 GB 磁盘 + Docker Engine + compose 插件 | `pymentor-backend-v1.1.zip` |
| 后端运维（macOS） | 仅开发/测试，无生产支持 | Docker Desktop | `pymentor-backend-v1.1.zip` |
| 学生（macOS / Linux 桌面） | — | — | **暂不支持**（v1.1 仅提供 Windows 桌面包；macOS/Linux 学生请使用浏览器访问 Web 端 `4173`） |

> 桌面 App 当前仅 Windows。macOS/Linux 用户通过浏览器访问后端的 `4173` 学生 Web
> 端口获得完整功能；离线场景不在 v1.1 支持范围。

---

## 三、文档索引

| 文档 | 适用对象 | 内容 |
|---|---|---|
| [windows-student-install.md](./windows-student-install.md) | 学生 / 教师 | 下载 exe、SmartScreen 放行、是否自部署后端、首次登录、连接学校后端 |
| [backend-deploy-windows.md](./backend-deploy-windows.md) | Windows IT / 教师 | 两条路径（bootstrapper / zip）、`.env` 必填项、`deploy.ps1`、Provider 预设 |
| [backend-deploy-linux.md](./backend-deploy-linux.md) | Linux 运维 | Docker Engine 安装、`deploy.sh`、systemd 守护、nginx 反代 |
| [upgrade.md](./upgrade.md) | 所有运维 | `upgrade.sh` / `upgrade.ps1`、备份前置、迁移 `0011 → 0012` |
| [rollback.md](./rollback.md) | 所有运维 | 本地构建回滚语义（=数据库还原）、未来 tag 版本回滚 |
| [backup-restore.md](./backup-restore.md) | 所有运维 | `backup.sh` / `restore.sh`、cron / 任务计划、MinIO 卷备份 |
| [troubleshooting.md](./troubleshooting.md) | 所有用户 | 端口冲突、Docker 未运行、登录失败、Provider 测试失败、SmartScreen 等 |

---

## 四、关键脚本与产物对照

部署脚本位于 Stage C 产物 `dist/backend-deploy/` 与 Stage D 产物 `dist/installer/`：

| 脚本 / 文件 | 平台 | 作用 |
|---|---|---|
| `PyMentorLab-Bootstrapper.exe` | Windows | 学生安装入口；可选链式部署后端 |
| `pymentor-backend-v1.1.zip` | 跨平台 | 后端独立部署归档（含 `dist/backend-deploy/` 内容 + 完整 `code/` 源副本） |
| `./deploy.sh` | Linux / macOS | 构建镜像 + 启动 compose 服务栈 |
| `.\deploy.ps1` | Windows | 同上（PowerShell） |
| `./upgrade.sh` / `.\upgrade.ps1` | 跨平台 | 重新构建并滚动重启 |
| `./backup.sh` / `.\backup.ps1` | 跨平台 | pg_dump 全库备份到 `backups/` |
| `./restore.sh` / `.\restore.ps1` | 跨平台 | 从 `backups/<file>.sql.gz` 恢复 |
| `./rollback.sh` / `.\rollback.ps1` | 跨平台 | 卸栈 + 提示数据库还原（见 rollback.md） |
| `./healthcheck.sh` / `.\healthcheck.ps1` | 跨平台 | 检查 API/Worker/Sandbox/Web/Admin 健康 |

---

## 五、安全与已知限制（诚实声明）

- **EXE 未签名**：Windows SmartScreen 会拦截首次运行，需手动 "更多信息 → 仍要运行"
  （BE-030 WONTFIX，等待 Authenticode 证书）。详见 [troubleshooting.md](./troubleshooting.md)。
- **本地构建无镜像 tag**：本部署模式由 `deploy.sh` 现场构建镜像，没有版本化 tag，因此
  回滚语义 = 数据库还原（详见 [rollback.md](./rollback.md)）。未来若切换到带 tag 的
  镜像仓库，回滚可指定旧版本号。
- **无 macOS / Linux 桌面包**：学生桌面 App 仅 Windows；其余平台请用浏览器访问
  学生 Web（端口 `4173`）。
- **生产强密码 / 密钥**：`.env.example` 中的所有 `dev-only-insecure-*` 默认值在生产
  环境 **必须** 替换，部署脚本在缺少 `[REQUIRED]` 项时会主动退出。
