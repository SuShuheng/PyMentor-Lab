# Windows 学生端安装指南

- **受众**：在 Windows 10 / 11 x64 个人电脑上使用 PyMentor Lab 的学生 / 教师
- **版本**：v1.1（未签名）
- **预计耗时**：5 分钟（仅学生 App）/ 20–40 分钟（附带部署后端，含 Docker 镜像构建）
- **相关文档**：[README](./README.md) · [backend-deploy-windows](./backend-deploy-windows.md) ·
  [troubleshooting](./troubleshooting.md)

---

## 一、安装前检查

| 项目 | 最低要求 |
|---|---|
| 操作系统 | Windows 10 1809+ / Windows 11，x64 |
| 内存 | 4 GB（仅学生 App） / 8 GB（附带后端） |
| 磁盘 | 2 GB（仅学生 App） / 20 GB（附带后端，含 Docker 镜像） |
| 浏览器（备用） | Edge / Chrome 最新版（访问学生 Web 时） |

> macOS / Linux 桌面暂不支持（v1.1 范围）。这两个平台的学生请通过浏览器访问学校
> 后端的学生 Web 端口（默认 `4173`）。

---

## 二、下载 bootstrapper

从发布渠道（学校 IT 提供的下载链接或 U 盘）获取：

```
PyMentorLab-Bootstrapper.exe
```

文件大小约 80–150 MB（bootstrapper 本体）。建议校验 SHA-256（学校 IT 会同时提供
哈希值），确认未被篡改后再运行。

---

## 三、运行（处理 SmartScreen 警告）

v1.1 的 EXE **未签名**（BE-030 WONTFIX，等待外部 Authenticode 证书）。首次双击运行
时，Windows Defender SmartScreen 会显示蓝色拦截页：

> "Windows 已保护你的电脑 / Microsoft Defender SmartScreen 阻止启动未识别的应用。
> 运行此应用可能会导致你的电脑面临风险。"

处理步骤：

1. 点击 **「更多信息」**（隐藏链接，就在"不运行"按钮上方）。
2. 此时出现 **「仍要运行」** 按钮，点击即可继续。
3. 如弹出 UAC 提权提示，请允许。

> **风险接受声明**：未签名的 EXE 无法证明发布者身份。仅当你确认文件来自可信渠道
> （学校官方分发、SHA-256 哈希匹配）时才放行。详见
> [troubleshooting.md](./troubleshooting.md) 的"未签名 EXE"章节。

---

## 四、bootstrapper 安装向导

向导启动后，按提示操作：

1. **选择安装目录**：默认 `C:\Program Files\PyMentorLab`，可改。
2. **开始菜单快捷方式**：默认创建。
3. **桌面图标**：可选。
4. **关键决策——是否同时部署后端**：
   - 选择 **「仅安装学生端 App」**（默认，适合绝大多数学生）→ 进入第五节。
   - 选择 **「同时在本机部署后端」** → 进入第六节。该选项需要 Docker Desktop 已
     安装并运行；若未装，向导会提示你去
     [Docker 官网](https://www.docker.com/products/docker-desktop/) 下载。
5. 点击 **「安装」** → 等待文件复制完成（约 1–3 分钟）。

---

## 五、不部署后端（默认）：连接学校后端

学校 IT 已在学校服务器上跑好了后端，你只需要把桌面 App 指向学校的 API 地址。

1. 安装完成后，从开始菜单启动 **PyMentor Lab**。
2. 首次启动会弹出 **「设置服务器地址」** 对话框。
3. 填入学校 IT 给你的地址，例如：
   ```
   https://pymentor.school.edu.cn
   ```
   或学校内网 IP + 端口：
   ```
   http://10.0.0.5:8000
   ```
   > 请填 **API 服务地址**（默认端口 `8000`）。如果你的学校用反向代理统一入口，
   > 请填代理后域名。
4. 点击 **「测试连接」**，提示"连接成功"后保存。
5. 使用学校分配的账号密码登录即可。

> 如果之后需要切换服务器（例如换学校），在 App 的 "设置 → 服务器地址" 里重新填入
> 并保存即可。

如果连接失败，请检查：
- 学校 IT 提供的地址是否正确（端口、http/https）
- 你是否在学校内网 / VPN 内
- 防火墙是否放行了目标端口
- 详见 [troubleshooting.md](./troubleshooting.md)

---

## 六、同时部署后端（自带后端模式）

适合教师预览、单机演示、小型班级（10 人以内）。**前提**：已安装
[Docker Desktop](https://www.docker.com/products/docker-desktop/) 并已启动（系统
托盘有 Docker 图标且显示 "running"）。

向导选 "同时部署后端" 后：

1. bootstrapper 会解压后端归档（`pymentor-backend-v1.1.zip` 内容）到
   `C:\Program Files\PyMentorLab\backend\`。
2. 提示你编辑 `.env` 文件，填入三个 **[REQUIRED]** 项（详见
   [backend-deploy-windows.md](./backend-deploy-windows.md) 的"必填环境变量"章节）：
   - `PYMENTOR_INITIAL_ADMIN_EMAIL`（管理员邮箱）
   - `PYMENTOR_INITIAL_ADMIN_PASSWORD`（管理员初始密码）
   - `PYMENTOR_PROVIDER_MASTER_KEY`（Provider 凭据加密密钥）
3. 保存 `.env` 后点击向导的 **「启动后端」**，向导调用 `.\deploy.ps1` 构建并启动
   Docker 服务栈。首次构建耗时 15–30 分钟（取决于网速和 CPU）。
4. 向导轮询 `http://localhost:8000/ready` 健康检查，绿了之后告知完成。

### 获取管理端地址 + 首次登录

- **管理端（Admin Web）**：浏览器打开 http://localhost:4174
- **学生 Web**：http://localhost:4173（桌面 App 也会自动用这个地址）
- **API 文档**：http://localhost:8000/docs

首次登录管理端：

1. 用 `.env` 里填的 `PYMENTOR_INITIAL_ADMIN_EMAIL` 和
   `PYMENTOR_INITIAL_ADMIN_PASSWORD` 登录。
2. 登录后必须 **立即修改密码** 并配置至少一个 Provider（详见
   [backend-deploy-windows.md](./backend-deploy-windows.md) "Provider 凭据配置"）。

---

## 七、卸载

- 通过 Windows「设置 → 应用 → PyMentor Lab → 卸载」卸载学生 App。
- 如果之前部署了后端，先在 PowerShell 中执行：
  ```powershell
  cd "C:\Program Files\PyMentorLab\backend"
  docker compose --env-file .env down -v
  ```
  （`-v` 会一并删除 PostgreSQL / Redis / MinIO 数据卷，**不可恢复**；如需保留数据
  请去掉 `-v`。）

---

## 八、下一步

- 后端运维细节：[backend-deploy-windows.md](./backend-deploy-windows.md)
- 升级流程：[upgrade.md](./upgrade.md)
- 遇到问题：[troubleshooting.md](./troubleshooting.md)
