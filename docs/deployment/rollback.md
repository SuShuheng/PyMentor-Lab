# 回滚指南

- **受众**：所有后端运维
- **版本**：v1.1
- **相关文档**：[backup-restore](./backup-restore.md) · [upgrade](./upgrade.md) ·
  [troubleshooting](./troubleshooting.md)

---

## 一、范围与限制（诚实声明）

### 当前部署模式：本地现场构建

v1.1 的 `dist/backend-deploy/` 部署模式由 `deploy.sh` / `deploy.ps1` 在用户机器上
**现场构建 Docker 镜像**。这些镜像被 compose 内部以服务名（`api`、`worker`、...）
引用，**没有打版本化 tag**，也没有推到任何镜像仓库。

后果：

- **没有"回滚到旧版镜像"这回事**——重启后跑的还是 `code/` 目录当前源码构建出的镜像。
- **回滚 = 把 `code/` 目录换回旧版源码 + 把数据库还原到升级前的备份**。

由于 alembic 迁移会改 schema（例如 v1.1 的 `0012_agent_prompt_templates` 新增了
表），仅换源码不还原数据库是不够的：旧版代码遇到未知表会出错，新版 alembic 看到
`version_num=0012` 又会跳过 downgrade。

### 未来：带 tag 的镜像仓库部署

当切换到 "从镜像仓库 pull 版本化镜像" 模式后，回滚可以是真正的 "切回旧 tag"，无需
数据库还原（前提是 schema 兼容）。`rollback.sh` / `rollback.ps1` 已为该模式预留了
`v1.0` 位置参数，详见本文第四节。

---

## 二、当前模式回滚流程

适用于：升级后服务异常，需要立刻恢复到升级前状态。

### 2.1 停止整栈

```bash
# Linux
./rollback.sh
# 脚本内部会执行 docker compose down（不删卷），然后提示你执行 restore
```

```powershell
# Windows
.\rollback.ps1
```

或手动：

```bash
docker compose --env-file .env down
```

> 不要加 `-v`——`-v` 会删数据卷，那真的就没救了。

### 2.2 还原数据库

```bash
# Linux
./restore.sh backups/pymentor-YYYYMMDD-HHMMSS.sql.gz
# YYYYMMDD-HHMMSS 是你升级前那次 backup.sh 的时间戳
```

```powershell
# Windows
.\restore.ps1 backups\pymentor-YYYYMMDD-HHMMSS.sql.gz
```

脚本会：

1. 启动一个临时 postgres 容器（或直接用 compose 的 postgres），drop 当前数据库并
   重建。
2. `gunzip | pg_restore`（或 `psql <`，取决于备份格式）导入。
3. 校验 `alembic_version.version_num` 是否回到旧版。

详见 [backup-restore.md](./backup-restore.md)。

### 2.3 换回旧版源码

如果你保留了升级前的 zip（强烈建议）：

```bash
# Linux：解压旧版 zip 到一个临时目录，把 code/ 覆盖回去
unzip pymentor-backend-v1.0.zip -d /tmp/old
rm -rf /opt/pymentor/code
cp -r /tmp/old/code /opt/pymentor/code
```

```powershell
# Windows
Expand-Archive .\pymentor-backend-v1.0.zip -DestinationPath C:\temp\old
Remove-Item -Recurse -Force "C:\PyMentorLab\code"
Copy-Item -Recurse C:\temp\old\code "C:\PyMentorLab\code"
```

> 如果没保留旧 zip，从学校的发布存档里重新取；或从 git 标签 checkout（开发模式下）。

### 2.4 重启

```bash
./deploy.sh    # Linux
```

```powershell
.\deploy.ps1   # Windows
```

### 2.5 健康检查 + 抽查

```bash
./healthcheck.sh
```

- 全部 `[OK]`。
- 管理员登录一次，确认 Provider 凭据显示正常（前提：`PYMENTOR_PROVIDER_MASTER_KEY`
  跟升级前一致——这个值通常不会跨版本变，但你最好确认 `.env` 没被改）。
- 抽查一名学生账号能学习。

---

## 三、部分回滚（仅数据，不换源码）

场景：误删了学生数据，想从昨天的备份恢复——但不想换源码版本。

步骤同上 **2.1 → 2.2 → 2.4**，**跳过 2.3**。

> 注意：如果当前代码版本比备份时的版本新（例如备份时是 v1.0，现在跑 v1.1），还原
> 数据库后 alembic 会把 schema 又升到 v1.1（因为 API 启动时自动 `upgrade head`）。
> v1.0 的数据行会被保留；v1.1 新增的列 / 表会被创建为空。这是安全的（向前兼容）。
> 反向（v1.1 备份恢复到 v1.0 代码）**不安全**，需要先单独执行
> `alembic downgrade 0011`。

---

## 四、未来模式：tag 化镜像回滚

当部署切换为 "从镜像仓库 pull 版本化镜像" 后，`docker-compose.yml` 会改为引用
`pymentor/api:v1.1.0` 这样的 tag，`rollback.sh` 接受版本号参数：

```bash
./rollback.sh v1.0
```

语义：

1. 把 `docker-compose.yml` 里所有服务的 `image:` tag 改回 `v1.0`（或读取预设的
   override 文件）。
2. `docker compose pull && docker compose up -d`。
3. 如果 v1.1 → v1.0 schema 不兼容，提示并执行 `alembic downgrade <old_rev>`。

> v1.1 不支持此模式。本节是为未来文档化而预留。

---

## 五、检查清单

- [ ] 升级前备份的 `.sql.gz` 文件存在且可用
- [ ] 旧版 zip（或 git 标签）就绪
- [ ] `PYMENTOR_PROVIDER_MASTER_KEY` 未被改动（否则 Provider 凭据无法解密）
- [ ] 已通知学生短暂离线窗口
- [ ] 回滚后 `healthcheck.sh` 全 OK + 抽查一个学生 + 一个 Provider 测试连接

---

## 六、下一步

- 备份细节：[backup-restore.md](./backup-restore.md)
- 升级流程：[upgrade.md](./upgrade.md)
