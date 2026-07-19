# 故障排查

- **受众**：学生 / 教师 / 后端运维
- **版本**：v1.1
- **相关文档**：[README](./README.md) · [backend-deploy-windows](./backend-deploy-windows.md) ·
  [backend-deploy-linux](./backend-deploy-linux.md)

按症状索引。每节给出常见原因与处置。

---

## 1. 端口冲突（5432 / 6379 / 9000 / 8000 / 4173 / 4174）

### 症状

- `docker compose up` 时报 `Bind for 127.0.0.1:5432 failed: port is already allocated`。
- 或浏览器访问 `http://localhost:4173` 打开的是另一个程序。

### 原因

本机已有别的程序占用相同端口。常见冲突：

| 端口 | 服务 | 常见占用方 |
|---|---|---|
| 5432 | PostgreSQL | 本机另装的 PostgreSQL 服务 |
| 6379 | Redis | 本机另装的 Redis |
| 9000 | MinIO S3 | PHP-FPM（默认 9000） |
| 8000 | API | 本机另跑的 dev server |
| 4173 / 4174 | 学生 / 管理 Web | Vite dev server 默认端口 |

### 处置

#### 方案 A：停掉占用方

```bash
# Linux：找占用进程
sudo lsof -i :5432
sudo ss -lptn 'sport = :5432'
# 然后停掉对应 systemd 服务，例如
sudo systemctl stop postgresql
```

```powershell
# Windows
netstat -ano | findstr :5432
# 拿到 PID 后
Stop-Process -Id <PID> -Force
# 或停服务
Stop-Service postgresql-x64-16
```

#### 方案 B：改 PyMentor 用的端口

需要同时改 **`docker-compose.yml`** 和 **`.env`**。以改 PostgreSQL 5432 → 15432 为例：

1. `docker-compose.yml`：

   ```yaml
   postgres:
     ports:
       - "127.0.0.1:15432:5432"   # 改前 127.0.0.1:5432:5432
   ```

2. `.env`：

   ```
   # 注意只改 host 侧端口；in-Compose 的 URL 不用动
   PYMENTOR_DATABASE_URL=postgresql+psycopg://pymentor:pymentor_dev@localhost:15432/pymentor
   ```

3. 重建：`docker compose --env-file .env up -d`

> 改 API（8000）/ Web（4173）/ Admin（4174）端口时，还要同步改
> `PYMENTOR_CORS_ALLOWED_ORIGINS`（CORS 白名单按 origin 校验，含端口）。
> 改 MinIO 端口要同步改 `PYMENTOR_OBJECT_STORE_ENDPOINT`。

---

## 2. Docker Desktop / Docker Engine 未运行

### 症状

- `docker compose up` 报 `Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?`
- Windows：`docker info` 报 `error during connect: This error may indicate that the docker daemon is not running`

### 处置

- **Windows**：从开始菜单启动 Docker Desktop，等系统托盘图标变成绿色 "running"
  （通常 30–60 秒）。
- **Linux**：`sudo systemctl start docker`，并 `sudo systemctl enable docker` 设
  开机自启。
- 仍失败：`sudo systemctl status docker` / Windows 看 Docker Desktop 故障日志。
  WSL2 后端故障时重启 WSL：`wsl --shutdown`，再启动 Docker Desktop。

---

## 3. `.env` 缺失必填项

### 症状

`deploy.sh` / `deploy.ps1` 退出并打印类似：

```
[ERROR] PYMENTOR_INITIAL_ADMIN_EMAIL is not set. Copy .env.example to .env and
        fill the three [REQUIRED] values, then re-run deploy.
```

### 原因

- 没有 `.env`（只有 `.env.example`），或
- `.env` 里三项 [REQUIRED] 没填，或填了空字符串：
  - `PYMENTOR_INITIAL_ADMIN_EMAIL`
  - `PYMENTOR_INITIAL_ADMIN_PASSWORD`
  - `PYMENTOR_PROVIDER_MASTER_KEY`

### 处置

```bash
# Linux
cp .env.example .env
nano .env   # 填好三项
```

```powershell
# Windows
Copy-Item .\.env.example .\.env
notepad .\.env
```

生成 master key：

```bash
python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

详见 [backend-deploy-windows 第三节](./backend-deploy-windows.md#三路径-b-详细步骤)。

---

## 4. 管理员登录失败（BE-029）

### 症状

- 启动时 API 日志报：
  ```
  pydantic_core._pydantic_core.ValidationError: ... value is not a valid email address
  ```
- 或：bootstrap 跳过（没创建管理员），登录时返回 401。

### 原因（BE-029）

`PYMENTOR_INITIAL_ADMIN_EMAIL` 的值不是合法邮箱。BE-029 在 bootstrap 时跑与
`/api/v1/auth/login` 一致的 Pydantic `EmailStr` 校验，避免产生 "能写入但永远登不进"
的幽灵管理员账号。常见无效值：

- `admin`（没有 `@`）
- `admin@school.local`（`.local` 是保留 TLD，EmailStr 拒绝）
- `admin@localhost`（同上）

### 处置

把 `.env` 里的 `PYMENTOR_INITIAL_ADMIN_EMAIL` 改成可投递邮箱，例如
`admin@school.edu.cn` 或 `admin@example.com`，然后：

```bash
docker compose --env-file .env down
docker volume rm pymentor-prod_pgdata    # 注意：会清空已建数据
docker compose --env-file .env up -d
```

> 如果数据库里已有不能丢的数据，**不要** 删卷——而是用管理端已能登录的另一个账号
> 在 "用户管理" 里手动建管理员；或直接修改 `users` 表的 email 字段（需 SQL 操作）。

---

## 5. Provider 测试连接失败

### 症状

管理端 → Providers → 新建/编辑 Provider → 点 "测试连接" → 提示失败。

### 排查顺序

1. **`PYMENTOR_PROVIDER_MASTER_KEY` 是否设置**？
   - `.env` 里此项为空时，保存的 Provider 凭据无法加密/解密。
   - 检查：`docker compose exec api env | grep PROVIDER_MASTER_KEY`
   - 若为空，生成并填入（见 [backend-deploy-windows](./backend-deploy-windows.md)），
     然后 `docker compose up -d --force-recreate api`。

2. **端点 URL 是否正确**？
   - 讯飞 TTS/ASR/OCR 各自有不同 host（参照讯飞官方文档）；填错会 404 或超时。
   - OpenAI 默认 `https://api.openai.com`；国内代理需要填代理域名。

3. **API Key / Secret 是否正确**？
   - 多余空格、漏字符都会 401。
   - 粘贴时注意某些 console 会把 `sk-...` 自动加换行。

4. **网络出口是否可达**？
   - 服务器是否能 `curl https://api.openai.com` / 讯飞端点？
   - 校园网防火墙是否拦截了出境 HTTPS？

5. **额度 / 套餐**？
   - 余额耗尽、QPS 超限也会表现为 "测试失败"。

### 调试

```bash
docker compose logs api | grep -i provider
docker compose logs worker | grep -i provider
```

---

## 6. 沙箱超时（学生代码运行无响应）

### 症状

学生在代码实验页执行代码后，长时间转圈最终报 "执行超时"。

### 原因与处置

沙箱 Supervisor 默认请求超时由 `PYMENTOR_SANDBOX_REQUEST_TIMEOUT_SECONDS` 控制
（默认 `30` 秒）。学生写了死循环、网络阻塞、或大量计算时会触发。

- **临时**：让学生优化代码（沙箱超时是设计的安全护栏，**不要**无脑调高）。
- **必要**（例如课程需要跑较长的训练任务）：在 `.env` 调高：

  ```
  PYMENTOR_SANDBOX_REQUEST_TIMEOUT_SECONDS=120
  ```

  然后 `docker compose up -d --force-recreate sandbox api`。

> 调高会让一个沙箱容器占用资源更久，影响并发。如果班级规模大，更好的方案是扩
> Worker / Sandbox 副本数（需要修改 `docker-compose.yml`，超出本指南范围）。

---

## 7. 未签名 EXE 被 SmartScreen 拦截

### 症状

学生双击 `PyMentorLab-Bootstrapper.exe` 看到：

> "Microsoft Defender SmartScreen 阻止启动未识别的应用。"

### 处置

1. 点击蓝色窗口里不起眼的 **「更多信息」** 文字链接。
2. 此时出现 **「仍要运行」** 按钮，点击即可。

### 风险接受声明

v1.1 的 EXE **未签名**（BE-030 WONTFIX：等待外部 Authenticode 证书，v1.1 范围内
无法解决）。未签名意味着：

- Windows 无法验证发布者身份，因此对所有用户显示 SmartScreen 警告。
- 用户必须主动放行；这构成供应链信任的薄弱点。

**强烈建议**：

- 仅从学校官方渠道获取 exe（学校 IT 内网 / 官方下载页 / 加密 U 盘）。
- 学校 IT 同时发布 SHA-256 哈希，学生装机前用 `certutil -hashfile <file> SHA256`
  校验。
- 一旦 BE-030 解决（拿到证书并签名），此节会更新为 "正常安装"。

详见 [windows-student-install 第三节](./windows-student-install.md#三运行处理-smartscreen-警告)。

---

## 8. 学生端打不开 / 白屏

### 症状

学生启动 App 后白屏，或浏览器访问 `http://localhost:4173` 报 502。

### 排查

1. **后端是否启动**？
   ```bash
   curl http://localhost:8000/ready
   # 期望返回 200 + {"status":"ready"} 或类似
   ```
2. **Web 容器是否健康**？
   ```bash
   docker compose ps web admin
   # 期望 State: Up (healthy)
   ```
3. **CORS 配置是否包含你访问的 origin**？
   - 如果你通过 IP 而非 localhost 访问（例如 `http://10.0.0.5:4173`），需在
     `.env` 的 `PYMENTOR_CORS_ALLOWED_ORIGINS` 加入 `http://10.0.0.5:4173`。

---

## 9. 升级后服务起不来

### 处置

1. `docker compose logs api | tail -100` 找启动异常。
2. 若是 alembic 报错（例如 `relation "xxx" already exists`），可能是版本号错乱。
   先备份（`./backup.sh`），再尝试 `docker compose exec api alembic -c
   backend/migrations/alembic.ini current` 看当前版本。
3. 若 5 分钟内无法恢复，按 [rollback.md](./rollback.md) 还原数据库。

---

## 10. 其它

| 症状 | 排查 |
|---|---|
| 容器反复重启 | `docker compose logs <svc>`；常见是依赖服务（postgres/redis/minio）未 healthy 就被依赖 |
| 磁盘满 | `docker system prune -a --volumes`（注意会删未用卷）；清 `backups/` 旧文件 |
| 镜像拉不下来 | 网络问题；国内可配 Docker Hub 镜像加速器 |
| 时间不对导致 JWT / TLS 报错 | 同步系统时间：`sudo chronyc makestep` / Windows 时间设置 |

---

## 求助前请准备

向学校 IT 或上游支持求助时，附上以下信息能大幅缩短定位时间：

- 操作系统与版本（`winver` / `cat /etc/os-release`）
- `docker --version` + `docker compose version`
- `docker compose ps` 输出
- `docker compose logs <出问题服务> --tail 200` 输出
- `.env` 中 **去掉敏感值后** 的内容（密码 / 密钥打码）
- 触发问题的具体操作步骤
