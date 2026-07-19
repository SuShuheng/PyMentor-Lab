# 升级指南

- **受众**：所有后端运维（Windows / Linux）
- **版本**：v1.1
- **典型耗时**：30–60 秒滚动重启（不含镜像构建）；首次构建 5–15 分钟
- **相关文档**：[backup-restore](./backup-restore.md) · [rollback](./rollback.md) ·
  [troubleshooting](./troubleshooting.md)

本指南覆盖 PyMentor Lab 后端从一个版本升级到下一个版本的完整流程。

---

## 一、核心流程（两平台通用）

```
[1] 备份      [2] 替换 code/ 目录    [3] 重新构建镜像    [4] 滚动重启    [5] 健康检查
```

`upgrade.sh` / `upgrade.ps1` 把 [2][3][4] 串起来；[1] 与 [5] 需手动执行。

---

## 二、前置：备份（每次升级必做）

```bash
# Linux
./backup.sh
# 输出：backups/pymentor-YYYYMMDD-HHMMSS.sql.gz
```

```powershell
# Windows
.\backup.ps1
```

> 即使升级很小，**永远先备份**。一旦 alembic 迁移把 schema 改了，回滚只能靠数据库
> 还原（详见 [rollback.md](./rollback.md)）。备份细节见
> [backup-restore.md](./backup-restore.md)。

---

## 三、执行升级

### Linux / macOS

```bash
# 假设你已把新版 pymentor-backend-v1.X.zip 解压后，把里面的 code/ 目录覆盖到
# /opt/pymentor/code/  （或直接重新解压整个 zip 到一个新目录，再 cd 进去）
./upgrade.sh
```

### Windows

```powershell
.\upgrade.ps1
```

`upgrade.sh` / `upgrade.ps1` 内部执行：

1. `docker compose --env-file .env build`（增量构建，仅当源码变化层会重做）。
2. `docker compose --env-file .env up -d`（compose 会智能滚动：先创建新容器再停旧
   容器，依赖 `depends_on` + `healthcheck` 保证顺序）。

通常整栈从 "重建完成" 到 "全部 healthy" 约需 **30–60 秒**。期间：

- 学生 Web / API 可能短暂 502（取决于反向代理），刷新即可。
- 长连接的 SSE（tutoring 流式）会被切断，前端会自动重连。

---

## 四、后置：健康检查

```bash
# Linux
./healthcheck.sh
```

```powershell
# Windows
.\healthcheck.ps1
```

期望全部 `[OK]`。如有 `[FAIL]`：

1. 看 `docker compose logs api | tail -100` 找启动报错。
2. 看本指南第六节"迁移"是否报错。
3. 参考 [troubleshooting](./troubleshooting.md)。
4. 若无法快速恢复，按 [rollback.md](./rollback.md) 还原数据库。

---

## 五、数据库迁移（自动）

### 设计 §M0：API 容器启动时自动跑 alembic

`infra/api.Dockerfile` 的 CMD 是：

```
alembic -c backend/migrations/alembic.ini upgrade head && exec uvicorn ...
```

也就是说：**每次 API 容器启动都会自动 `alembic upgrade head`**。你不需要手动跑
迁移。alembic 自己有版本表（`alembic_version.version_num`），已应用的迁移会跳过。

### v1.0 → v1.1 升级路径：`0011 → 0012`

v1.1 引入了一个新迁移（详见 `backend/migrations/versions/`）：

| 迁移 | 关联工单 | 内容 |
|---|---|---|
| `0011_system_maintenance` | — | v1.0 终态 |
| `0012_agent_prompt_templates` | BE-020 | 新增 `agent_prompt_templates` 表，存储 LangGraph 节点级、版本化、带审计的 prompt 模板 |

升级时 alembic 会自动 `CREATE TABLE agent_prompt_templates`。该表初始为空——管理员
需要时通过管理端 Agent 调优 UI 创建；Worker 在运行时读取每个节点的 published 版本，
未配置则回退到 Worker 内置默认 prompt（向后兼容）。

> **降级（downgrade）**：`0012_agent_prompt_templates` 提供了 `downgrade()` 函数，
> 但 v1.1 部署模式（本地构建）的回滚策略是"整库还原"而非 alembic downgrade，详见
> [rollback.md](./rollback.md)。

### 多次升级

如果你的部署跳了多个版本（例如 v1.0 → v1.2），alembic 会按 `down_revision` 链
顺序应用所有未应用迁移。升级前请：

1. 备份（必须）。
2. 阅读 `backend/migrations/versions/` 下从当前版本号之后的所有迁移文件，理解
   schema 变化。
3. 如果有破坏性变更（drop column / rename table），先在测试环境演练。

---

## 六、回滚预案

如果升级后服务起不来或行为异常：

1. 立即按 [rollback.md](./rollback.md) 操作：停服务 → 还原数据库 → 重启旧版镜像。
2. 由于本地构建模式没有版本化镜像 tag，回滚 = 数据库还原 + 重新解压旧版 zip 覆盖
   `code/` 目录 + 重新 `deploy.sh`。

详见 [rollback.md](./rollback.md)。

---

## 七、配置变更（升级同时改 `.env`）

如果新版本要求新环境变量（例如某个 feature flag），通常 `.env.example` 顶部会有
`# NEW in v1.X` 注释。升级流程：

1. 对比新版 `.env.example` 与你的 `.env`。
2. 把新增项复制到你的 `.env` 并赋值。
3. 再跑 `upgrade.sh`。

不要直接用新版 `.env.example` 覆盖你的 `.env`——会丢失已设的密钥。

---

## 八、升级检查清单

- [ ] 阅读新版 `CHANGELOG`（或 PR 描述）
- [ ] 测试环境演练过一次
- [ ] `./backup.sh` 成功，且备份文件大小合理（>1 MB）
- [ ] 选择低峰期执行（学生端 502 影响 < 1 分钟）
- [ ] `./healthcheck.sh` 全部 OK
- [ ] 管理员手动登录一次，确认 Provider 列表与凭据未丢（Provider 行由
      `PYMENTOR_PROVIDER_MASTER_KEY` 加密，**密钥未变** 才能正常解密显示）
- [ ] 抽查一名学生账号能正常进入学习页

---

## 九、下一步

- 备份细节：[backup-restore.md](./backup-restore.md)
- 出问题回滚：[rollback.md](./rollback.md)
