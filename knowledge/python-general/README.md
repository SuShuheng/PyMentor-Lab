# 高校通识 Python 课程资产

`v1/course-bundle.json` 是 BE-009 的可发布课程种子，包含 14 章、93 个
知识节点，以及逐节点的误区、诊断题、练习题、测试、掌握策略和官方来源。

四个深度单元为循环边界、作用域与 `UnboundLocalError`、可变默认参数、递归
调用栈。`v1/validation-report.json` 是同一资产的确定性校验结果；其摘要必须与
当前 bundle 一致。

从仓库根目录运行下列命令可重新生成 bundle、报告和 `knowledge/schemas/v1`
下的 JSON Schema：

```powershell
.\.venv\Scripts\python.exe scripts\generate_knowledge_assets.py
```

生成器使用 UUIDv5 派生稳定标识；内容键不变时，重复运行不会产生 diff。

`v1/material-coverage-review.md` 记录了仓库原始教材/题库如何用于覆盖面审查，
以及哪些第三方或高风险主题未进入 V1 正式来源。
