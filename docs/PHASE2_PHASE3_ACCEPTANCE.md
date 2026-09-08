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

`--task` 是任务 ID、目标、起始路径、fixture、步数预算和 Verifier 的唯一来源。两个框架完成后才调用确定性 Verifier；Verifier 不提前终止 Agent。结果默认写入 `sqlite:///./data/results.sqlite3`，可用 `DATABASE_URL` 或 `--database-url` 更改。

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
# 56 passed
```

当前 WSL 发行版没有 `docker` 命令，因此 `docker-compose.yml` 已通过 YAML/契约测试，但本机容器启动和 healthcheck 尚未实测。装有 Docker Desktop WSL integration 的环境应再执行：

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8080/health
docker compose down
```

结果库当前采用本地 SQLite，足以满足 Phase 3 的统一存储验收；迁移到总体架构目标中的 PostgreSQL 应在多进程批量 Runner 开始前完成。
