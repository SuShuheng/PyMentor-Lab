# 备份与恢复指南

- **受众**：所有后端运维
- **版本**：v1.1
- **相关文档**：[upgrade](./upgrade.md) · [rollback](./rollback.md) ·
  [troubleshooting](./troubleshooting.md)

本指南覆盖 PostgreSQL 数据库的备份/恢复，以及对象存储（MinIO）的卷级备份建议。

---

## 一、备份范围与策略

PyMentor Lab 后端有两类持久化数据：

| 数据类型 | 存放位置 | 备份方式 |
|---|---|---|
| 业务数据（学生、画像、任务、Provider 凭据、prompt 模板、审计日志等） | PostgreSQL（`pgdata` 卷） | `backup.sh` → `pg_dump` 压缩 SQL |
| 学生上传文件 + Worker 生成的资源（PDF / 图片 / 音频） | MinIO（`miniodata` 卷），bucket `pymentor-resources` | **Docker 卷快照**（见第四节） |
| Redis（事件流、缓存） | `redisdata` 卷 | **无需备份**（仅为缓存与流，丢失可重建） |

> 单独 `backup.sh` **只覆盖 PostgreSQL**。要完整备份系统，必须额外做 MinIO 卷快照
> （第四节）。否则恢复后学生上传的历史附件会丢失。

---

## 二、PostgreSQL 备份

### 2.1 手动备份

```bash
# Linux
./backup.sh
```

```powershell
# Windows
.\backup.ps1
```

输出文件：

```
backups/pymentor-YYYYMMDD-HHMMSS.sql.gz
```

脚本内部使用 `pg_dump`（PostgreSQL 16 的 `pg_dump`，与 `api.Dockerfile` 里安装的
`postgresql-client-16` 版本对齐），生成压缩归档。

### 2.2 验证备份

每次备份后建议快速验证（抽查备份能列出表）：

```bash
# 不真正还原，只列出 SQL 内容的 CREATE TABLE 语句
zcat backups/pymentor-YYYYMMDD-HHMMSS.sql.gz | grep -c "CREATE TABLE"
# 期望返回 >= 几十（具体取决于版本，v1.1 约 30+）
```

> 备份文件大小应 > 1 MB（空库的备份约几十 KB；有真实数据后通常几 MB 起步）。异常
> 小的备份很可能是失败备份。

### 2.3 保留策略（建议）

| 类型 | 频率 | 保留 |
|---|---|---|
| 每日 | 凌晨 2:00 自动 | 14 天 |
| 每周（周一） | 自动 | 8 周 |
| 升级前 | 手动 | 永久（或至少 90 天） |

可写个简单 cron / 任务计划清理过期文件：

```bash
# Linux：在 backup.sh 后追加
find backups/ -name "pymentor-*.sql.gz" -mtime +14 -delete
```

---

## 三、定时备份

### 3.1 Linux（cron）

```bash
crontab -e
```

加入（假设部署目录为 `/opt/pymentor`）：

```cron
# 每天 02:00 备份 PyMentor 数据库
0 2 * * * cd /opt/pymentor && ./backup.sh >> /var/log/pymentor-backup.log 2>&1
# 每周一 03:00 做一次周备份（保留更久，靠文件名后缀区分）
0 3 * * 1 cd /opt/pymentor && ./backup.sh >> /var/log/pymentor-backup-weekly.log 2>&1
```

> cron 用户必须对 `/opt/pymentor` 和 `docker` 有权限。如果以 `pymentor` 用户跑，
> 把它加入 `docker` 组（见 [backend-deploy-linux.md](./backend-deploy-linux.md)
> 第二节）。

### 3.2 Windows（任务计划程序）

PowerShell（管理员）创建任务：

```powershell
$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\PyMentorLab\backup.ps1"

$trigger = New-ScheduledTaskTrigger -Daily -At 2am

Register-ScheduledTask `
  -TaskName "PyMentor-Daily-Backup" `
  -Action $action `
  -Trigger $trigger `
  -RunLevel Highest `
  -User "SYSTEM"
```

查看 / 手动触发：

```powershell
Get-ScheduledTask -TaskName "PyMentor-Daily-Backup"
Start-ScheduledTask -TaskName "PyMentor-Daily-Backup"
```

---

## 四、MinIO 对象存储备份（卷快照）

学生上传的 PDF / 图片 / 录音，以及 Worker 生成的五类资源（讲义、讲解视频、知识图
谱、自适应题目等）都存在 MinIO 的 `pymentor-resources` bucket 里，对应 Docker 命名卷
`miniodata`。`backup.sh` **不会** 备份这部分。

### 4.1 推荐：Docker 卷级备份

```bash
# 把 miniodata 卷打包到一个 tar.gz
docker run --rm -v miniodata:/data:ro -v $(pwd)/backups:/backup ubuntu \
  tar czf /backup/minio-$(date +%Y%m%d-%H%M%S).tar.gz -C /data .
```

> 假设 compose 项目名是 `pymentor-prod`（`dist/backend-deploy/docker-compose.yml`
> 顶部的 `name:` 字段），卷全名为 `pymentor-prod_miniodata`。先 `docker volume ls`
> 确认实际名字。

### 4.2 还原

```bash
docker compose --env-file .env stop minio
docker run --rm -v miniodata:/data -v $(pwd)/backups:/backup ubuntu \
  tar xzf /backup/minio-YYYYMMDD-HHMMSS.tar.gz -C /data
docker compose --env-file .env start minio
```

### 4.3 跟数据库备份配对

MinIO 卷快照应与 PostgreSQL 备份**配对**做（同一时间点）。否则可能出现 "数据库里有
一行 resource 指向 minio 里的对象，但 minio 备份里没那个对象" 的不一致。

建议：把 4.1 的卷快照命令也加进 cron / 任务计划，紧接 `backup.sh` 之后执行。

---

## 五、PostgreSQL 恢复

### 5.1 完整恢复流程

```bash
# Linux
# 1. 停 API（避免恢复期间有写入）
docker compose --env-file .env stop api worker

# 2. 还原
./restore.sh backups/pymentor-YYYYMMDD-HHMMSS.sql.gz

# 3. 重启
docker compose --env-file .env start api worker
```

```powershell
# Windows
docker compose --env-file .env stop api worker
.\restore.ps1 backups\pymentor-YYYYMMDD-HHMMSS.sql.gz
docker compose --env-file .env start api worker
```

`restore.sh` 内部做的事：

1. 用 compose 的 postgres 服务（或临时容器）连到数据库。
2. `DROP DATABASE` + `CREATE DATABASE`（破坏性！确保你真的要还原）。
3. `gunzip -c <file>.sql.gz | psql ...` 导入。
4. 打印 `alembic_version.version_num` 供你确认 schema 版本。

### 5.2 验证

```bash
./healthcheck.sh
# 然后管理员登录管理端，抽查：
#   - 学生数对得上
#   - Provider 列表完整
#   - 最近一次审计日志时间戳合理
```

### 5.3 风险与注意

- 恢复会**覆盖**当前数据库。如果你只是想看历史数据，先把它恢复到一个独立的数据库
  名（例如 `pymentor_inspect`），别覆盖生产库。
- 如果备份的 schema 版本比当前代码旧（例如备份是 v1.0，代码是 v1.1），API 启动时
  alembic 会自动 `upgrade head`，把 schema 升到当前版本——数据不会丢，新增表/列会
  被创建为空。
- 如果备份版本比代码新（例如备份是 v1.1，代码是 v1.0），需要先手动
  `alembic downgrade 0011`，否则 v1.0 代码遇到未知列会报错。

---

## 六、检查清单

定期（每周）演练一次：

- [ ] 从最新备份还原到测试环境
- [ ] 管理员能登录，Provider 凭据显示正常
- [ ] 抽查一名学生能进入学习页
- [ ] MinIO 卷快照能解出至少一个最近上传的文件
- [ ] cron / 任务计划任务状态为 "上次运行成功"

---

## 七、下一步

- 升级前置备份：[upgrade.md](./upgrade.md)
- 升级失败回滚：[rollback.md](./rollback.md)
