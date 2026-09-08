# Phase 2 / Phase 3 验收记录

验收日期：2026-09-08（Asia/Shanghai）

## 标准入口

直接读取 TaskSpec，并选择 Agent 框架：

```bash
.venv/bin/python -m tracetotest run \
  --framework agentlab \
  --task tasks/admin/filter_low_inventory.json

.venv/bin/python -m tracetotest run \
  --framework browser-use \
  --task tasks/admin/filter_low_inventory.json
```

`--task` 是任务 ID、目标、起始路径、fixture、步数预算和 Verifier 的唯一来源。两个框架完成后才调用确定性 Verifier；Verifier 不提前终止 Agent。结果默认写入 `.env` 配置的 PostgreSQL，可用 `--database-url` 覆盖。

## Phase 2

执行：

```bash
.venv/bin/python -m tracetotest acceptance
```

结果：通过。10/10 个 TaskSpec 的真实无头 Chromium 人工路径全部通过，范围覆盖有效/无效登录、退出、库存筛选与更新、订单筛选/搜索/状态更新、库存导出和订单导出。每个任务均从同一版本化 fixture 重置，并由确定性 Verifier 判定。

四种故障注入均通过行为检查且保存真值：

- `response-delay`：可测量的响应延迟；
- `inventory-500`：库存端点返回注入的 HTTP 500；
- `missing-export`：导出控件缺失；
- `corrupt-export`：CSV 行内容不完整。

正式报告保存在被 Git 忽略的 `artifacts/acceptance/<timestamp>/phase2.json`。本次报告目录为 `artifacts/acceptance/20260908_083810_086085/`，运行代码版本为 `1d7bf85eb6d53e3a03a493179620a60954892c73`，所有任务 manifest 均记录 `dirty=false`。

## Phase 3

同一个 `filter-low-inventory` TaskSpec 已由两套真实框架和 Qwen `qwen3.7-plus` 分别完成：

| 框架 | Run ID | Steps | Agent 完成动作 | Verifier |
|---|---|---:|---|---|
| AgentLab Vision | `run_cc82d70bea57d126` | 6 | `finish_task` | 通过 |
| Browser Use | `run_2337984af7e792bd` | 3 | 原生 `done` | 通过 |

两条运行进入同一结果数据库，均保存原始轨迹、canonical trace，并且每个 step 都有关联 screenshot 和 action。复验入口：

```bash
.venv/bin/python -m tracetotest phase3-acceptance \
  --task-id filter-low-inventory
```

本次报告目录为 `artifacts/acceptance/20260908_083635_864428/`，运行代码版本为 `1d7bf85eb6d53e3a03a493179620a60954892c73`，报告记录 `dirty=false`。

## 自动化测试与限制

```bash
.venv/bin/python -m pytest -q
# 58 passed
```

本机已安装 Docker Desktop 4.90.0（Engine 29.7.2）并开启 Ubuntu 22.04
WSL integration。PostgreSQL 16.15 和后台容器均已实际启动并通过 healthcheck：

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8080/health
docker compose down
```

结果库已迁移到 PostgreSQL。历史 SQLite 库中 34 条 Run 已全部迁移，
迁移后比对 `(run_id, task_id, framework, status, steps)` 集合完全一致；
AgentLab 和 Browser Use 的 Phase 3 关键 Run 均可从 PostgreSQL 查询。
