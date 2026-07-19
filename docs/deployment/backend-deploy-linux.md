# 后端部署 — Linux（Docker Engine + compose 插件）

- **受众**：Ubuntu / Debian / RHEL 系 Linux 服务器管理员
- **版本**：v1.1
- **预计耗时**：15–30 分钟（含首次镜像构建）
- **相关文档**：[README](./README.md) · [backend-deploy-windows](./backend-deploy-windows.md) ·
  [troubleshooting](./troubleshooting.md)

本指南面向在学校 Linux 服务器上部署 PyMentor Lab 后端的运维人员。Linux 是生产环境
推荐平台。

---

## 一、先决条件

| 项目 | 要求 |
|---|---|
| 操作系统 | Ubuntu 22.04+ / Debian 12+ / RHEL 9+（其它发行版理论可行但未测） |
| 资源 | 2 vCPU / 8 GB 内存 / 20 GB 磁盘 |
| 权限 | root 或具备 sudo 的账号 |
| 软件 | Docker Engine 24+ 与 docker compose 插件 v2+ |
| 网络 | 能访问 Docker Hub（拉 `postgres:16-alpine`、`redis:7`、`minio/minio`） |

---

## 二、安装 Docker Engine + compose 插件

> 以下命令来自 [Docker 官方文档](https://docs.docker.com/engine/install/)。
> 不要用发行版自带的 `docker.io` 包（版本旧且无 compose v2 插件）。

### Ubuntu / Debian（apt）

```bash
# 1. 安装依赖
sudo apt-get update
sudo apt-get install -y ca-certificates curl

# 2. 添加 Docker 官方 GPG key
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/$(. /etc/os-release; echo "$ID")/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# 3. 添加 apt 源
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/$(. /etc/os-release; echo "$ID") \
  $(. /etc/os-release; echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 4. 安装
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 5. 把当前用户加入 docker 组（避免每次 sudo）
sudo usermod -aG docker $USER
newgrp docker
```

### RHEL / CentOS Stream（dnf）

```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker
```

### 验证

```bash
docker --version
docker compose version
docker run --rm hello-world
```

三条都有正常输出即可。详见 [troubleshooting](./troubleshooting.md)。

---

## 三、解压部署归档

将 `pymentor-backend-v1.1.zip` 上传到服务器（例如 `/opt/`）：

```bash
sudo mkdir -p /opt/pymentor
sudo unzip pymentor-backend-v1.1.zip -d /opt/pymentor
cd /opt/pymentor
ls
# docker-compose.yml  .env.example  deploy.sh  upgrade.sh  backup.sh
# restore.sh  rollback.sh  healthcheck.sh  code/  ...
```

---

## 四、编辑 `.env`

```bash
cp .env.example .env
nano .env        # 或 vi / vim
```

### 必填三项 [REQUIRED]

| 变量 | 说明 | 生成 / 设置 |
|---|---|---|
| `PYMENTOR_INITIAL_ADMIN_EMAIL` | 首位管理员邮箱，必须可投递（BE-029 校验，无 `@` 或 `.local` 顶级域会在启动期失败）。 | 真实邮箱，如 `admin@school.edu.cn` |
| `PYMENTOR_INITIAL_ADMIN_PASSWORD` | 首位管理员初始密码。 | 强密码 |
| `PYMENTOR_PROVIDER_MASTER_KEY` | Provider 凭据 AES-256 加密密钥，**必须长期稳定**。 | `python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"` |

如果服务器没有 python3：

```bash
docker run --rm python:3.13-alpine python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

### 替换其它 dev 默认（建议）

| 变量 | 默认 | 生成命令 |
|---|---|---|
| `POSTGRES_PASSWORD` | `pymentor_dev` | `openssl rand -base64 24` |
| `MINIO_ROOT_PASSWORD` | `pymentor_dev` | `openssl rand -base64 24` |
| `PYMENTOR_JWT_SECRET` | `dev-only-insecure-...` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `PYMENTOR_WORKER_INTERNAL_SECRET` | `dev-only-insecure-...` | 同上独立生成 |
| `PYMENTOR_SANDBOX_SECRET` | `dev-only-insecure-...` | 同上独立生成 |

完整变量含义和端口表见 `dist/backend-deploy/.env.example` 内嵌注释，以及
[backend-deploy-windows.md 第三节](./backend-deploy-windows.md#三路径-b-详细步骤)。

---

## 五、运行 `./deploy.sh`

```bash
./deploy.sh
```

脚本会校验 `.env`、构建镜像、`docker compose up -d`、轮询健康检查。

### 验证健康

```bash
./healthcheck.sh
```

期望全部 `[OK]`。如某项 `[FAIL]`，参考 [troubleshooting](./troubleshooting.md)。

### 首次管理员登录

- **管理端**：http://localhost:4174 （本机）或 `http://<server-ip>:4174`（校园网内，
  需先开放防火墙或反向代理）
- 用 `.env` 里的 `PYMENTOR_INITIAL_ADMIN_EMAIL` + `PYMENTOR_INITIAL_ADMIN_PASSWORD`
  登录，立即改密码。
- 配置 Provider（FE-016 预设：讯飞 TTS/ASR/OCR、OpenAI 等），流程同
  [backend-deploy-windows 第四节](./backend-deploy-windows.md#四provider-凭据配置首次登录后必做)。

---

## 六、systemd 守护（可选但推荐）

Docker 自身的 `restart: unless-stopped` 已能在容器崩溃时自动重启；但服务器重启后
Docker daemon 的开机自启、磁盘/网络故障的看门狗由 systemd 兜底。

### 6.1 确保 Docker 开机自启

```bash
sudo systemctl enable --now docker
```

### 6.2 创建 pymentor.service 单元

```bash
sudo tee /etc/systemd/system/pymentor.service > /dev/null <<'UNIT'
[Unit]
Description=PyMentor Lab backend stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/pymentor
ExecStart=/usr/bin/docker compose --env-file /opt/pymentor/.env up -d
ExecStop=/usr/bin/docker compose --env-file /opt/pymentor/.env down
# 看门狗：每 60s 探一次 API /ready，挂了就视为失败
ExecStartPost=/bin/bash -c 'for i in {1..30}; do curl -fsS http://localhost:8000/ready && exit 0; sleep 5; done; exit 1'
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now pymentor.service
```

### 6.3 验证

```bash
sudo systemctl status pymentor
sudo systemctl restart pymentor    # 手动重启整栈
journalctl -u pymentor -f           # 跟踪日志
```

> systemd 这里管的是 "整栈 up/down"；容器内部崩溃由 Docker 的
> `restart: unless-stopped` 处理。两者互补。

---

## 七、防火墙与端口

### 直接开放（仅内网测试）

| 端口 | 服务 | 是否开放给学生 |
|---|---|---|
| 8000 | API | 是（学生 App / Web 都打这个） |
| 4173 | 学生 Web | 是 |
| 4174 | 管理 Web | 仅 IT |
| 5432 / 6379 / 9000 / 9001 / 8081 | 数据层 / 内部 | **不开放**（仅本机） |

```bash
# Ubuntu (ufw)
sudo ufw allow 8000/tcp
sudo ufw allow 4173/tcp
sudo ufw allow 4174/tcp
sudo ufw reload

# RHEL (firewalld)
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --permanent --add-port=4173/tcp
sudo firewall-cmd --permanent --add-port=4174/tcp
sudo firewall-cmd --reload
```

### nginx 反向代理（推荐生产 + TLS）

`docker-compose.yml` 保持 `127.0.0.1` 绑定，由 nginx 暴露 80/443 并终结 TLS。

```bash
sudo apt-get install -y nginx
```

`/etc/nginx/sites-available/pymentor.conf`（示意，把 `pymentor.school.edu.cn` 换成
你的域名；证书可用 [certbot](https://certbot.eff.org/) 自动签发）：

```nginx
# 学生 Web
server {
    listen 443 ssl http2;
    server_name pymentor.school.edu.cn;

    ssl_certificate     /etc/letsencrypt/live/pymentor.school.edu.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pymentor.school.edu.cn/privkey.pem;

    # 学生 Web SPA
    location / {
        proxy_pass http://127.0.0.1:4173;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # SSE 长连接（tutoring / agent 流式）
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }
}

# 管理 Web（可独立域名或路径）
server {
    listen 443 ssl http2;
    server_name admin.pymentor.school.edu.cn;

    ssl_certificate     /etc/letsencrypt/live/admin.pymentor.school.edu.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/admin.pymentor.school.edu.cn/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:4174;
        proxy_set_header Host $host;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
}

# 80 强制跳 443
server {
    listen 80;
    server_name pymentor.school.edu.cn admin.pymentor.school.edu.cn;
    return 301 https://$host$request_uri;
}
```

启用：

```bash
sudo ln -s /etc/nginx/sites-available/pymentor.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

> 用反向代理时，记得在 `.env` 的 `PYMENTOR_CORS_ALLOWED_ORIGINS` 加上你的
> `https://pymentor.school.edu.cn` 和 `https://admin.pymentor.school.edu.cn`，
> 否则浏览器 CORS 会拒绝。

---

## 八、下一步

- 备份：[backup-restore.md](./backup-restore.md)（含 cron 模板）
- 升级：[upgrade.md](./upgrade.md)
- 排错：[troubleshooting.md](./troubleshooting.md)
