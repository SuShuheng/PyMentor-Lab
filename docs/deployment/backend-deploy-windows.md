# 后端部署 — Windows（Docker Desktop）

- **受众**：Windows IT / 管理员，已具备 Docker Desktop
- **版本**：v1.1
- **预计耗时**：20–40 分钟（含首次镜像构建）
- **相关文档**：[README](./README.md) · [windows-student-install](./windows-student-install.md) ·
  [backend-deploy-linux](./backend-deploy-linux.md) · [troubleshooting](./troubleshooting.md)

本指南面向在学校 Windows 服务器（或本机）上独立部署 PyMentor Lab 后端服务栈的
运维人员。提供两条等价路径。

---

## 一、先决条件

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows Server 2019+ / Windows 10 1809+ / Windows 11 |
| Docker | [Docker Desktop](https://www.docker.com/products/docker-desktop/) 最新版，启用 WSL2 后端，已启动（托盘图标显示 running） |
| 内存 / 磁盘 | 8 GB / 20 GB 可用 |
| PowerShell | 5.1+（Windows 10 自带）或 PowerShell 7 |
| 网络 | 能访问 Docker Hub（`postgres:16-alpine`、`redis:7`、`minio/minio` 等） |

确认 Docker 可用：

```powershell
docker --version
docker compose version
docker info
```

三条都有输出且无报错即可。如果 `docker info` 报 "cannot connect to the Docker
daemon"，请先启动 Docker Desktop，详见 [troubleshooting](./troubleshooting.md)。

---

## 二、两条部署路径

### 路径 A：通过 bootstrapper exe（推荐首次部署者）

`PyMentorLab-Bootstrapper.exe` 内置了后端部署向导。优点：图形化、自动处理 SmartScreen
和 `.env` 模板。流程见 [windows-student-install.md 第六节](./windows-student-install.md#六同时部署后端自带后端模式)，
向导最终调用与本指南路径 B 完全相同的 `.\deploy.ps1`。

> 该路径本质上等于"路径 B + 图形壳"，因此下文的环境变量、Provider 配置、健康检查
> 步骤对两条路径都适用。

### 路径 B：通过独立 zip（推荐有经验的运维）

获取归档：

```
pymentor-backend-v1.1.zip
```

（Stage C 产物 `dist/backend-deploy/` 打包而成，内含 `docker-compose.yml`、
`.env.example`、`deploy.ps1` 等脚本和 `code/` 完整源副本。）

---

## 三、路径 B 详细步骤

### 3.1 解压 zip

```powershell
Expand-Archive .\pymentor-backend-v1.1.zip -DestinationPath C:\PyMentorLab
cd C:\PyMentorLab
```

解压后目录结构：

```
C:\PyMentorLab\
├── docker-compose.yml          # 生产变体（name: pymentor-prod，build.context=./code）
├── .env.example                # 环境模板
├── deploy.ps1                  # 构建并启动
├── upgrade.ps1                 # 升级（重建+滚动重启）
├── backup.ps1                  # pg_dump 备份
├── restore.ps1                 # 恢复
├── rollback.ps1                # 卸栈+提示数据库还原
├── healthcheck.ps1             # 服务健康检查
├── code\                       # 完整源副本（api/worker/sandbox/web/admin）
└── backups\                    # 备份输出目录（首次运行 backup 后生成）
```

### 3.2 编辑 `.env`

复制模板：

```powershell
Copy-Item .\.env.example .\.env
notepad .\.env
```

#### 必填环境变量（三项 [REQUIRED]）

部署脚本在缺这三项时会主动退出，不会带默认 dev secret 启动：

| 变量 | 说明 | 生成 / 设置方式 |
|---|---|---|
| `PYMENTOR_INITIAL_ADMIN_EMAIL` | 首位系统管理员的邮箱。**必须是可投递邮箱**（BE-029：会跑 Pydantic `EmailStr` 校验，类似 `admin` 这种没有 `@` 或 `.local` 顶级域的值会在启动期失败，避免产生永远登不进去的幽灵账号）。 | 用真实邮箱，例如 `admin@school.edu.cn` |
| `PYMENTOR_INITIAL_ADMIN_PASSWORD` | 首位管理员初始密码。 | 强密码（建议 16 位以上，含大小写数字符号）；首次登录后请立即改 |
| `PYMENTOR_PROVIDER_MASTER_KEY` | Provider 凭据（LLM / OCR / ASR / TTS 的 API key）的 AES-256 加密密钥。**必须保持稳定**：一旦 Provider 行被加密后写入，此值变更将导致历史凭据无法解密（轮换需重新加密所有 Provider）。 | PowerShell 生成： `python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"` |

> 如果本机没有 Python，可用 Docker 临时容器生成：
> ```powershell
> docker run --rm python:3.13-alpine python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
> ```

#### 建议修改（替换 dev 默认）

| 变量 | 默认（dev） | 建议生产值 |
|---|---|---|
| `POSTGRES_PASSWORD` | `pymentor_dev` | 强随机串 |
| `MINIO_ROOT_PASSWORD` | `pymentor_dev` | 强随机串 |
| `PYMENTOR_JWT_SECRET` | `dev-only-insecure-...` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `PYMENTOR_WORKER_INTERNAL_SECRET` | `dev-only-insecure-...` | 同上独立生成 |
| `PYMENTOR_SANDBOX_SECRET` | `dev-only-insecure-...` | 同上独立生成 |

生成命令（任选一种）：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
# 或
docker run --rm python:3.13-alpine python -c "import secrets; print(secrets.token_urlsafe(48))"
```

#### 端口表（如需修改）

`docker-compose.yml` 全部绑定到 `127.0.0.1`。如需对外暴露，请用反向代理（见
[backend-deploy-linux.md](./backend-deploy-linux.md) 的 nginx 示例；Windows 上推荐
IIS Application Request Routing 或 nginx for Windows）。

| 端口 | 服务 | 改端口需同时改的地方 |
|---|---|---|
| 5432 | PostgreSQL | `PYMENTOR_DATABASE_URL` 里的 `:5432` |
| 6379 | Redis | 通常无需改 |
| 9000 / 9001 | MinIO S3 / Console | `PYMENTOR_OBJECT_STORE_ENDPOINT` |
| 8000 | API（FastAPI） | CORS / 反向代理上游 |
| 4173 | 学生 Web | `PYMENTOR_CORS_ALLOWED_ORIGINS` |
| 4174 | 管理 Web | `PYMENTOR_CORS_ALLOWED_ORIGINS` |
| 8081 | Worker（内部健康） | 通常无需对外 |

详见 [troubleshooting.md](./troubleshooting.md) 的"端口冲突"。

### 3.3 运行 `.\deploy.ps1`

```powershell
.\deploy.ps1
```

脚本会：

1. 校验 `.env` 三项 [REQUIRED] 是否填好；缺则退出。
2. `docker compose --env-file .env build`（首次耗时 15–30 分钟）。
3. `docker compose --env-file .env up -d`。
4. 轮询各服务健康检查。

### 3.4 等待健康检查

```powershell
.\healthcheck.ps1
```

期望输出（全部 OK）：

```
[OK] postgres
[OK] redis
[OK] minio
[OK] api         http://localhost:8000/ready
[OK] worker      http://localhost:8081/ready
[OK] sandbox     http://localhost:8090/healthz（内部）
[OK] web         http://localhost:4173/healthz
[OK] admin       http://localhost:4174/healthz
```

如有 FAIL，参考 [troubleshooting.md](./troubleshooting.md)。

### 3.5 首次管理员登录

1. 浏览器打开 **管理端**： http://localhost:4174
2. 使用 `.env` 里的 `PYMENTOR_INITIAL_ADMIN_EMAIL` + `PYMENTOR_INITIAL_ADMIN_PASSWORD`
   登录。
3. **立即修改密码**（管理端 → 账户 → 修改密码）。

---

## 四、Provider 凭据配置（首次登录后必做）

学生端要使用任何 LLM / OCR / ASR / TTS 能力，都必须先在管理端配置 Provider 凭据。
未配置时学生调用 Agent 会拿到明确的"未配置 Provider"错误。

### 操作路径

1. 管理端 → **Providers**（FE-016 增强了 CRUD 表单 + 启用/禁用 + 凭据输入）。
2. 点击 **「新建 Provider」**。
3. 选择类型（FE-016 预设：讯飞星火 / OpenAI / Anthropic 等），表单会预填常见字段：
   - **讯飞**：TTS / ASR / OCR（BE-022 / BE-024 / BE-025 适配器）——填入 AppID、
     APIKey、APISecret
   - **OpenAI**：ChatGPT 系——填入 API Key、组织 ID（可选）
4. 填入凭据（写入数据库前会用 `PYMENTOR_PROVIDER_MASTER_KEY` 加密）。
5. 点击 **「测试连接」**：管理端会发一个最小探针请求验证凭据有效。
6. 测试通过后 **启用**。

> 凭据在管理端 UI 永远不会原样回显（只会显示掩码或最后 4 位），符合 BE-010 的加密
> 与展示规范。如果 "测试连接" 失败，请检查端点 URL、API Key 是否正确，以及
> `PYMENTOR_PROVIDER_MASTER_KEY` 是否在 `.env` 里设置（详见
> [troubleshooting](./troubleshooting.md)）。

---

## 五、对外发布（可选）

默认所有端口绑定 `127.0.0.1`，只有本机能访问。若要让校园网内学生访问：

**方案 A（简单）**：把 `docker-compose.yml` 里相关端口的 `127.0.0.1:` 前缀去掉，例如：

```yaml
ports:
  - "8000:8000"   # 改前 127.0.0.1:8000:8000
```

> 直接对外暴露会跳过 TLS。仅适合内网测试。

**方案 B（推荐生产）**：保留 `127.0.0.1` 绑定，在前端加 nginx / IIS 反向代理并配置
TLS 证书。配置示例见 [backend-deploy-linux.md](./backend-deploy-linux.md) 的 nginx
章节（Windows 上 nginx 配置语法相同）。

---

## 六、下一步

- 备份策略：[backup-restore.md](./backup-restore.md)
- 升级版本：[upgrade.md](./upgrade.md)
- 排错：[troubleshooting.md](./troubleshooting.md)
