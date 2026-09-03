# 项目 3：Trace2Test

## Web/GUI Agent 轨迹回放、故障聚类与回归测试平台构建说明

> 定位：Agent Evaluation / GUI Agent / Observability / Testing Infrastructure / Reliability 方向项目
> 推荐周期：MVP 6～8 周，论文实验版 10～14 周，OSWorld 扩展另计 2～4 周
> 开发环境：Windows 11 + WSL2 + Docker Desktop；主要代码在 Linux/WSL2 环境运行
> 核心原则：先完成“轨迹采集—诊断—聚类—回归”的闭环，再增加 UI-TARS 和 OSWorld；不要从训练 GUI 模型开始。

---

# 1. 项目一句话

构建一个面向 Web/GUI Agent 的持续质量平台，统一接入 BrowserGym、AgentLab 和 Browser Use，记录每次任务的截图、DOM/A11y Tree、动作、模型调用、页面变化和最终结果；支持逐步回放、首个关键错误定位、跨运行故障聚类，并把历史失败自动沉淀为可复现的回归测试，在模型、Prompt 或 Agent 版本升级时给出质量、成本、延迟和安全回归结论。

# 2. 最终要做出的东西

最终交付不是一个单独的 GUI Agent，而是一套测试和调试 GUI Agent 的平台，包含五个用户可见组件。

## 2.1 Trace SDK / Adapter

负责接入不同 Agent 框架并采集统一轨迹：

- AgentLab adapter；
- Browser Use adapter；
- 后期增加 UI-TARS adapter；
- 最后增加 OSWorld adapter；
- 通用 OpenTelemetry/JSONL exporter；
- 截图、DOM、A11y Tree、网络和文件事件采集。

## 2.2 Benchmark Runner

通过统一命令运行任务：

```bash
tracetotest run \
  --suite miniwob-smoke \
  --agent agentlab-generic-dom \
  --repeat 5
```

Runner 负责：

- 创建和重置环境；
- 加载任务及 fixture；
- 启动 Agent；
- 设置步数、时间和费用预算；
- 采集轨迹；
- 调用结果验证器；
- 生成 run manifest；
- 把失败提交给诊断与聚类流程。

## 2.3 Replay Web Console

提供四个核心页面：

- Runs：所有运行、状态、版本、成本和失败类型；
- Replay：逐步查看截图、点击位置、Agent 决策和页面变化；
- Clusters：查看重复故障簇、趋势、影响版本和代表性轨迹；
- Regression：比较 baseline 与 candidate 版本，判断是否允许发布。

## 2.4 Diagnose & Cluster Engine

负责：

- 规则检测；
- 轨迹分段；
- 步骤级错误诊断；
- 首个关键错误定位；
- 故障 embedding；
- HDBSCAN/层次聚类；
- 故障簇命名和摘要；
- 关联相似历史案例。

## 2.5 Regression & Release Gate

把代表性失败转成可重复运行的测试，并在版本升级时检查：

- 任务成功率是否退化；
- 历史 P0/P1 故障是否复发；
- 是否出现新致命故障簇；
- 成本和延迟是否明显上升；
- 是否发生危险或越权动作。

---

# 3. 项目范围和非目标

## 3.1 MVP 必做范围

- BrowserGym 作为统一 Web 环境接口；
- AgentLab GenericAgent adapter；
- Browser Use adapter；
- 一个自建、可完全重置的电商/运营后台；
- 20～30 个 MiniWoB++ 任务；
- Run/Step/Event/Artifact 统一轨迹协议；
- 截图、动作、DOM/A11y Tree、模型调用和验证结果采集；
- 单条轨迹逐步回放；
- 至少 6 类规则型错误检测；
- 多模态或文本 Judge 的结构化诊断；
- 故障 embedding 与聚类；
- 从失败运行生成回归用例；
- baseline/candidate 版本对比；
- 基础 CI release gate。

## 3.2 论文实验版

- WebArena-Verified 30～50 个任务；
- UI-TARS-1.5-7B 视觉/坐标 Agent；
- 200～300 条人工标注失败轨迹；
- UI 扰动和故障注入；
- 首个关键错误定位实验；
- 聚类纯度、同根因召回率和回归检测率实验；
- 规则、单次 Judge、分段 Judge、规则+Judge 等消融实验。

## 3.3 最后扩展

- OSWorld-Verified 或 OSWorld 2.0；
- Agent-S 等桌面 Agent；
- Windows/Linux 桌面截图和 PyAutoGUI 动作；
- VM checkpoint 或环境快照；
- 跨 Chrome、LibreOffice、VS Code 等多应用任务。

## 3.4 明确不做

- 不从头训练通用 GUI 大模型；
- 不自行实现浏览器或虚拟机；
- 不在第一版支持 Web、Windows、Android、macOS 全平台；
- 不把所有判断都交给 LLM-as-a-Judge；
- 不在实时互联网网站上建立主要实验结论；
- 不以 Dashboard 美观程度作为项目核心；
- 不把采集到的私有思维链作为必要数据；
- 不承诺生产级多租户、计费、全球容灾和完整 IAM。

---

# 4. 总体架构

```text
Task/Suite YAML
      │
      ▼
Benchmark Runner ───── Environment Manager
      │                       │
      │                       ├── BrowserGym / MiniWoB++
      │                       ├── Custom Admin App
      │                       ├── WebArena-Verified
      │                       └── OSWorld (later)
      │
      ├── AgentLab Adapter ─────── Research Agent
      ├── Browser Use Adapter ──── Production-style Agent
      ├── UI-TARS Adapter ──────── Vision/Coordinate Agent
      └── OSWorld Adapter ──────── Desktop Agent
      │
      ▼
Trace Collector
      ├── Run / Step / Event metadata
      ├── Screenshot / DOM / A11y
      ├── Model & tool calls
      ├── Network / console / files
      └── Verifier results
      │
      ▼
Trace Store
      ├── PostgreSQL: structured metadata
      ├── Object Store: screenshots/traces/files
      └── pgvector: embeddings
      │
      ├───────────────┬──────────────────┐
      ▼               ▼                  ▼
Replay Console   Diagnose Engine    Metrics/Reports
                      │
                      ▼
               Failure Clustering
                      │
                      ▼
               Regression Registry
                      │
                      ▼
               Version Comparator
                      │
                      ▼
                 Release Gate
```

# 5. 接下来首先需要准备什么

## 5.1 硬件

### MVP 最低配置

- Windows 11；
- 16GB 内存，建议 32GB；
- 4 核以上 CPU，建议 8 核以上；
- 至少 40GB 可用磁盘，建议预留 80～120GB；
- 不要求本地 NVIDIA GPU；
- Agent 推理先使用模型 API 或小型本地模型。

### UI-TARS 阶段

- 推荐使用云端推理 Endpoint 或短租 GPU；
- UI-TARS 官方文档明确提供 Hugging Face Endpoint 和 vLLM 接入方式；
- 7B 模型可以单卡服务，但实际显存需求受精度、上下文长度和服务配置影响；
- 不要在 MVP 阶段因 GPU 部署阻塞主项目。

### OSWorld 阶段

- 本地桌面建议 VMware Workstation Pro 或 VirtualBox；
- OSWorld 官方要求 Python 3.10+；
- 如果走 Docker，Linux 服务器最好支持 KVM；
- Windows + Docker Desktop 不等同于 Linux 主机上的 KVM，是否支持完整 OSWorld 桌面环境需要单独验证；
- 首次下载 VM 镜像和任务资源需要较大磁盘空间与稳定网络。

## 5.2 软件

建议安装：

- Git；
- WSL2 Ubuntu 22.04/24.04；
- Docker Desktop，启用 WSL2 backend；
- Python 3.11；
- `uv` 或 Conda，建议使用 `uv` 管理本项目；
- Node.js 20 LTS；
- pnpm；
- PostgreSQL 16；
- MinIO，可后置；
- Chromium，由 Playwright 安装；
- VS Code 或其他 IDE。

为什么主环境选 Python 3.11：当前 AgentLab 的 `pyproject.toml` 要求 Python `>=3.11,<3.13`，而 OSWorld 要求 Python 3.10+；Python 3.11 可以覆盖两者，但建议 OSWorld 后期仍使用独立虚拟环境。

## 5.3 账号和凭证

至少准备一个支持视觉输入和 tool calling 的模型 API。将凭证放入未提交 Git 的 `.env`：

```dotenv
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=

DATABASE_URL=postgresql://tracetotest:change-me@localhost:5432/tracetotest
ARTIFACT_STORE_PATH=./data/artifacts
```

原则：

- 首期只配置一种模型供应商；
- `.env` 加入 `.gitignore`；
- 轨迹中不要保存 Authorization header；
- 对网页输入、截图、DOM 和模型消息做脱敏；
- 每次实验记录实际模型 ID，不能只写“GPT”或“Claude”。

WebArena、WorkArena 和 OSWorld 后期可能需要额外账号、镜像或 gated dataset 权限，到对应阶段再申请。

## 5.4 需要掌握的知识

开始编码前应能解释：

- GUI Agent 的 observation-action loop；
- DOM、Accessibility Tree 与 Screenshot 的差异；
- Playwright/CDP 的基本工作方式；
- task、environment、reward/verifier 的区别；
- Agent trajectory 和普通应用日志的区别；
- LLM-as-a-Judge 的偏差与不确定性；
- embedding、余弦相似度、HDBSCAN；
- 回归测试、fixture、测试隔离和幂等；
- p50/p95、成功率置信区间和重复运行；
- Docker、PostgreSQL 和基本 Web API。

---

# 6. 推荐仓库结构

```text
tracetotest/
├── README.md
├── pyproject.toml
├── uv.lock
├── package.json
├── docker-compose.yml
├── .env.example
├── configs/
│   ├── agents/
│   │   ├── agentlab_generic_dom.yaml
│   │   ├── agentlab_generic_vision.yaml
│   │   ├── browser_use.yaml
│   │   └── ui_tars.yaml
│   ├── suites/
│   │   ├── smoke.yaml
│   │   ├── miniwob.yaml
│   │   ├── custom_admin.yaml
│   │   └── webarena_verified.yaml
│   └── release_gates/
│       └── default.yaml
├── src/tracetotest/
│   ├── cli/
│   ├── runner/
│   ├── environments/
│   ├── adapters/
│   │   ├── base.py
│   │   ├── agentlab.py
│   │   ├── browser_use.py
│   │   ├── ui_tars.py
│   │   └── osworld.py
│   ├── trace/
│   │   ├── schema.py
│   │   ├── collector.py
│   │   ├── redaction.py
│   │   └── exporter.py
│   ├── verifier/
│   ├── diagnosis/
│   ├── clustering/
│   ├── regression/
│   ├── storage/
│   └── api/
├── web/
│   └── replay-console/
├── apps/
│   └── admin-demo/
├── tasks/
│   ├── custom_admin/
│   ├── miniwob/
│   └── webarena/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── regression/
├── scripts/
├── data/
│   ├── artifacts/
│   └── exports/
├── experiments/
│   ├── manifests/
│   ├── results/
│   └── notebooks/
└── docs/
    ├── trace-schema.md
    ├── adapter-guide.md
    ├── benchmark-manifest.md
    └── experiment-protocol.md
```

仓库可以采用 monorepo，但 Python runner 与前端应保持清晰边界。

---

# 7. 版本和可复现策略

GUI Agent 实验最容易因为环境漂移失去可信度，因此从第一天就要记录版本。

## 7.1 每次运行必须记录

- Git commit；
- Agent adapter 版本；
- Agent Prompt hash；
- 模型精确 ID；
- 模型推理参数；
- BrowserGym/AgentLab/Browser Use 版本；
- benchmark 名称和版本；
- 自建后台镜像 digest；
- Chromium/Playwright 版本；
- viewport、device scale factor；
- locale、timezone；
- seed；
- 最大步骤、超时和费用预算；
- Judge 模型与 Prompt 版本；
- verifier 版本。

## 7.2 Manifest 示例

```yaml
run_id: run_20260903_0001
git_commit: abc1234
agent:
  framework: agentlab
  adapter_version: 0.1.0
  config: generic_dom
  prompt_sha256: 7b1d...
model:
  provider: openai-compatible
  id: exact-model-id
  temperature: 0
environment:
  framework: browsergym
  benchmark: miniwob
  benchmark_version: pinned-version
  task: click-test
  viewport: [1280, 720]
  locale: en-US
limits:
  max_steps: 25
  timeout_seconds: 120
```

## 7.3 依赖策略

- 使用 `uv.lock` 固定 Python 依赖；
- 使用 `pnpm-lock.yaml` 固定前端依赖；
- Docker 镜像正式实验使用 digest 或固定 tag；
- benchmark 代码使用 Git tag/commit；
- 不在同一份最终实验中混用 `main` 和固定 release；
- 升级依赖单独作为一次实验版本。

---

# 8. 统一轨迹协议

不要直接把 AgentLab 或 Browser Use 的原始日志当成平台内部格式。平台需要自有、稳定的 canonical schema。

## 8.1 Run

```json
{
  "run_id": "run_20260903_0001",
  "task_id": "export-low-inventory",
  "suite_id": "custom-admin-v1",
  "agent_id": "agentlab-generic-dom",
  "status": "failed",
  "reward": 0,
  "started_at": "2026-09-03T10:00:00+08:00",
  "duration_ms": 91320,
  "steps": 18,
  "input_tokens": 28000,
  "output_tokens": 4740,
  "estimated_cost": 0.19,
  "manifest_ref": "artifact://manifests/run_20260903_0001.yaml"
}
```

## 8.2 Step

```json
{
  "run_id": "run_20260903_0001",
  "step_index": 7,
  "timestamp": "2026-09-03T10:00:23.412+08:00",
  "observation": {
    "url": "http://admin.local/inventory",
    "screenshot_ref": "artifact://screenshots/step-7-before.png",
    "dom_ref": "artifact://dom/step-7.json",
    "a11y_ref": "artifact://a11y/step-7.json"
  },
  "decision": {
    "current_goal": "导出筛选结果",
    "action_reason": "页面右上角存在导出按钮",
    "expected_effect": "显示导出格式菜单",
    "confidence": 0.81
  },
  "action": {
    "type": "click",
    "coordinates": [1042, 183],
    "target_text": "导出",
    "target_element_id": "button-export"
  },
  "after": {
    "screenshot_ref": "artifact://screenshots/step-7-after.png",
    "observed_effect": "筛选条件被清除"
  }
}
```

## 8.3 Event

用于对齐异步事件：

```json
{
  "event_id": "evt_789",
  "run_id": "run_20260903_0001",
  "step_index": 7,
  "timestamp_ns": 1788400823620000000,
  "event_type": "network_request",
  "payload": {
    "method": "POST",
    "path": "/api/inventory/reset",
    "status": 200
  }
}
```

## 8.4 Artifact

```json
{
  "artifact_id": "art_001",
  "run_id": "run_20260903_0001",
  "type": "screenshot",
  "uri": "file:///data/artifacts/run_20260903_0001/step-7-before.png",
  "sha256": "...",
  "content_type": "image/png",
  "redacted": true
}
```

## 8.5 必须遵守的采集原则

- 每个 action 必须有动作前状态；
- 尽可能保存动作后稳定状态；
- 保存 Agent 的结构化决策摘要，不要求私有思维链；
- 原始日志保留，canonical trace 单独生成；
- 所有 artifact 使用 hash 校验；
- 时间统一使用 UTC 存储，前端按本地时区展示；
- screenshot、DOM、network body 必须先脱敏；
- action schema 不能只保存自然语言。

---

# 9. 自建后台设计

## 9.1 为什么必须自建

公开 benchmark 用来证明通用性，自建后台用来获得诊断真值和可重复环境。没有自建环境，就很难知道失败到底由哪个预设变化造成，也难做精确回放。

## 9.2 推荐业务域

构建一个简化的运营后台，包含：

- 登录与权限；
- 商品列表；
- 库存筛选；
- CSV 导出；
- 订单搜索；
- 订单状态修改；
- 退款工单；
- 用户信息；
- 文件上传/下载；
- 审计日志。

推荐栈：

- 前端：React + TypeScript；
- 后端：FastAPI；
- 数据库：PostgreSQL；
- 测试环境：Docker Compose；
- 数据初始化：固定 SQL/JSON fixture；
- E2E 验证器：Playwright + 后端查询。

## 9.3 第一批 15 个任务

1. 登录后台；
2. 搜索指定商品；
3. 筛选库存低于 10 的商品；
4. 导出筛选结果为 CSV；
5. 查询指定订单；
6. 将测试订单标为已审核；
7. 创建退款工单；
8. 给订单添加备注；
9. 批量选择三条记录；
10. 修改每页显示数量；
11. 上传测试附件；
12. 下载订单发票；
13. 查看某用户最近操作；
14. 在两个页面之间复制字段；
15. 完成一个跨库存和订单页面的组合任务。

## 9.4 故障和扰动注入

所有扰动必须通过配置开启，而不是手工临时修改页面。

```yaml
faults:
  modal_occlusion: true
  delayed_loading_ms: 2500
  first_click_dropped: false
  button_text_variant: export-data
  sticky_header_offset_px: 64
  duplicate_action_button: true
```

第一批故障类型：

- 弹窗遮挡；
- 第一次点击不生效；
- 页面延迟加载；
- 按钮位置变化；
- 按钮文案同义改写；
- 插入相似干扰按钮；
- DOM 层级变化；
- 滚动后 sticky header；
- 下载延迟；
- 后端返回可恢复的 5xx；
- 表单提交后提示位置变化；
- 未保存离开页面确认框。

每种故障都要带真值：

```json
{
  "fault_id": "modal_occlusion_v1",
  "expected_failure_family": "execution",
  "affected_control": "button-export",
  "recovery": "close-modal-then-retry",
  "active_from": "page-load"
}
```

## 9.5 成功验证器

优先使用确定性验证：

- 数据库记录；
- 下载文件存在性、内容和行数；
- 后端事件；
- DOM 状态；
- URL；
- 测试 outbox；
- 不允许出现的副作用。

示例：

```yaml
task_id: export-low-inventory
instruction: 导出所有库存低于 10 的商品为 CSV
setup:
  fixture: inventory_v1
success:
  downloaded_file: inventory.csv
  csv_row_count: 15
  every_row:
    stock_lt: 10
safety:
  database_mutations: 0
  external_uploads: 0
budget:
  max_steps: 25
  timeout_seconds: 120
```

---

# 10. BrowserGym 接入

BrowserGym 是统一 Web 环境接口，不是我们的产品 UI。

## 10.1 第一阶段安装验证

在独立 Python 3.11 环境完成：

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install browsergym
playwright install chromium
```

先执行官方 demo 的 MiniWoB 任务，确认：

- 浏览器能启动；
- `env.reset()` 返回 observation；
- `env.step(action)` 能执行；
- reward、terminated、truncated、info 可读取；
- screenshot 和 A11y Tree 可获得。

具体命令以 BrowserGym 当前官方 README 为准：

- https://github.com/ServiceNow/BrowserGym

## 10.2 我们的 Environment 接口

```python
class EnvironmentAdapter(Protocol):
    async def reset(self, task_spec: TaskSpec) -> Observation: ...
    async def step(self, action: AgentAction) -> StepResult: ...
    async def verify(self) -> VerificationResult: ...
    async def snapshot(self) -> EnvironmentSnapshot: ...
    async def close(self) -> None: ...
```

不要让 diagnosis 或 replay 模块直接依赖 Gymnasium 的原始对象。

## 10.3 需要采集的 BrowserGym 信息

- task name；
- goal；
- current URL；
- screenshot；
- A11y Tree；
- open tabs；
- action string；
- reward；
- termination reason；
- error；
- task-specific verifier output。

---

# 11. AgentLab 接入

AgentLab 是第一套标准研究 Agent。

## 11.1 为什么先接 AgentLab

- 原生适配 BrowserGym；
- GenericAgent 可作为稳定 baseline；
- 方便切换模型；
- 可以比较 DOM/A11y 与 Vision 输入；
- 支持批量实验和轨迹分析；
- 论文复现更容易。

官方仓库：

- https://github.com/ServiceNow/AgentLab

当前官方 `pyproject.toml` 要求 Python `>=3.11,<3.13`。

## 11.2 两个首要配置

### 配置 A：DOM/A11y Agent

- 输入 A11y Tree；
- 不提供 screenshot；
- 固定模型；
- temperature 设为 0 或官方可复现设置；
- 用于建立低成本 baseline。

### 配置 B：Vision Agent

- 与 A 使用相同模型；
- 加入 screenshot；
- 其他 Prompt、预算尽量一致；
- 用于研究视觉信息对失败类型的影响。

## 11.3 Adapter 要完成的事情

- 把 AgentLab task/run ID 映射为平台 run ID；
- 将 Agent action 规范化；
- 提取 observation；
- 记录模型调用和 token；
- 关联 screenshot/A11y artifact；
- 保留原始 AgentLab trace；
- 转换为 canonical trace；
- 不修改 Agent 的核心策略。

## 11.4 第一阶段验收

- 同一任务连续运行 5 次；
- 每次都能生成完整 manifest；
- Run/Step/Event 数量一致且可解释；
- 成功任务可通过 verifier；
- 失败任务可在 Replay 页面定位到最后一步；
- 原始 trace 和 canonical trace 可相互关联。

---

# 12. Browser Use 接入

Browser Use 是生产型 Agent baseline。

官方仓库：

- https://github.com/browser-use/browser-use

## 12.1 为什么需要第二套框架

只支持 AgentLab 容易变成 benchmark 内部工具。Browser Use 可以验证：

- 平台是否能处理非 BrowserGym 原生 Agent；
- 能否适配真实 CDP/browser session；
- 能否处理不同动作协议；
- 能否捕捉生产型 Agent 的重试、工具和文件事件；
- 统一轨迹协议是否真的跨框架。

## 12.2 建议接入方式

优先在 Browser Use 的事件/回调边界做 adapter，而不是修改其内部逻辑。需要采集：

- task；
- browser session；
- 每轮 model input/output 摘要；
- selected element/index；
- action；
- screenshot；
- 页面 URL/title；
- tool result；
- final result/error；
- usage/cost。

## 12.3 与 AgentLab 的公平对比

尽可能固定：

- 相同模型；
- 相同 task instruction；
- 相同环境 fixture；
- 相同最大步骤；
- 相同 timeout；
- 相同 viewport；
- 相同 verifier。

不能完全相同时，manifest 中明确记录差异，不要强行声称严格公平。

---

# 13. MiniWoB++ 数据积累计划

## 13.1 任务选择

先选 20～30 个，覆盖：

- click；
- type；
- form filling；
- select/dropdown；
- menu；
- checkbox/radio；
- scroll；
- drag and drop；
- date/time；
- multi-step interaction。

## 13.2 轨迹规模

第一轮建议：

```text
25 个任务
× 2 个 Agent 框架/配置
× 5 次重复
= 250 条轨迹
```

加入 DOM/Vision 对照后：

```text
25 个任务
× 4 个 Agent 配置
× 5 次重复
= 500 条轨迹
```

## 13.3 MiniWoB 的作用

- 快速验证 pipeline；
- 积累成功与失败轨迹；
- 测试 schema 稳定性；
- 测试聚类工程流程；
- 测试模型/Prompt版本对比。

不要用 MiniWoB 单独支撑“生产级 GUI Agent”结论，因为其页面和任务较短、较合成。

---

# 14. Replay 实现

## 14.1 MVP 回放

每个步骤展示：

- step index 和时间；
- 动作前 screenshot；
- 点击坐标/输入区域覆盖；
- action JSON；
- Agent 当前目标和预期效果；
- 动作后 screenshot；
- URL/DOM/A11y 变化摘要；
- verifier 和诊断结果。

## 14.2 三类 replay

### Visual Replay

只读取保存的 artifact，不重新执行。MVP 必做。

### Action Replay

重置环境后重新执行原动作序列。MVP 后期或论文版做。

### Branch/Counterfactual Replay

在可疑步骤替换动作再继续执行，例如：

- 坐标点击改为 DOM click；
- 等待 2 秒后点击；
- 先关闭弹窗；
- 改用另一个目标元素。

这是首个关键错误定位的重要研究增强，不要求 MVP 首周完成。

## 14.3 回放一致性指标

- replay 到相同步骤时 URL 一致率；
- DOM/A11y 相似度；
- screenshot perceptual similarity；
- verifier 状态一致率；
- 原失败重现率；
- 重放耗时和失败原因。

---

# 15. 故障诊断

## 15.1 第一版 taxonomy

```text
perception
grounding
planning
execution
state_tracking
recovery
termination
environment
verifier
safety
unknown
```

## 15.2 规则检测器

第一批至少实现：

1. 重复相同动作；
2. 页面无变化但 Agent 判断成功；
3. 点击坐标没有对应可交互元素；
4. 目标元素不在 viewport；
5. 导航/下载/数据库目标未发生；
6. 达到 max steps；
7. 状态在两个页面间循环；
8. 任务完成后继续操作；
9. 错误页面仍继续执行；
10. 高风险动作未获得确认。

## 15.3 分段诊断

借鉴 GUIDE 的思路：

```text
完整轨迹
  ↓
按子任务/页面状态分段
  ↓
逐段诊断 success / partial / fail
  ↓
定位候选错误步骤
  ↓
整合为 run 级结论
```

Judge 必须输出 JSON Schema：

```json
{
  "root_step": 7,
  "error_type": "grounding",
  "severity": "fatal",
  "confidence": 0.91,
  "evidence": [
    "计划目标为导出按钮",
    "点击坐标落在重置按钮区域",
    "动作后筛选条件消失"
  ],
  "recoverable": true,
  "suggested_fix": "使用元素定位或重新计算滚动后的坐标"
}
```

## 15.4 Judge 不是 ground truth

必须人工标注一部分数据，至少包括：

- 是否存在 Agent 错误；
- 首个关键错误步骤；
- error type；
- 是否可恢复；
- 证据；
- 是否属于环境/verifier错误。

评估：

- Error detection Precision/Recall/F1；
- Root-step exact accuracy；
- Root-step ±1 accuracy；
- Error type Macro-F1；
- 与人工标注一致性；
- 重复调用稳定性；
- 不同轨迹长度下的性能。

---

# 16. 故障聚类

## 16.1 聚类对象

聚类单位不是整条 run，也不是单个 action，而是一个标准化 `FailureCase`：

```json
{
  "run_id": "...",
  "root_step": 7,
  "task_family": "data_export",
  "page_state": "filtered_inventory",
  "error_type": "grounding",
  "intended_action": "click export",
  "executed_action": "click reset",
  "expected_effect": "open export menu",
  "actual_effect": "clear filter",
  "visual_context_ref": "...",
  "dom_context_ref": "...",
  "diagnosis": "..."
}
```

## 16.2 特征

### 结构化特征

- error type；
- action type；
- target element role；
- task family；
- page family；
- 是否发生导航；
- DOM变化率；
- screenshot变化率；
- 是否重复；
- 是否有弹窗；
- failure step percentile。

### 文本 embedding

拼接：

```text
task family
+ intended action
+ expected effect
+ actual effect
+ diagnosis
+ recovery suggestion
```

### 可选视觉 embedding

- 根因步骤前截图；
- 目标元素局部截图；
- 动作前后差异图。

## 16.3 第一版算法

```text
先按 error_type / action_type 粗分桶
              ↓
标准化文本生成 embedding
              ↓
HDBSCAN 聚类
              ↓
规则检查簇内一致性
              ↓
LLM 生成簇名称、共同根因和修复建议
              ↓
人工审核 merge / split / accept
```

## 16.4 评价指标

如果有故障注入真值：

- Adjusted Rand Index；
- Normalized Mutual Information；
- cluster purity；
- same-root-cause recall；
- noise ratio；
- 每个簇的可行动性人工评分。

平台指标：

- 一个簇覆盖多少失败；
- top-K 簇覆盖率；
- 修复一个簇后成功率提升；
- 新版本出现的新簇数量；
- 已解决簇的复发率。

---

# 17. 回归测试

## 17.1 从失败转测试

```bash
tracetotest promote run_20260903_0001 \
  --suite critical-regression \
  --name scroll-offset-export
```

生成内容：

- task instruction；
- 初始 fixture；
- fault/variant 配置；
- success verifier；
- safety constraints；
- budget；
- 原始失败轨迹引用；
- failure cluster ID；
- 参考成功运行，可选。

## 17.2 测试集分层

### Smoke

- 10～20 个任务；
- 每次提交运行；
- 低成本、短任务。

### Critical Regression

- 所有 P0/P1 历史故障；
- 发布前运行；
- 每个任务至少 3 次。

### Full Regression

- 全部代表性历史故障；
- 每日或每周运行。

### Robustness

- UI 文案、布局、弹窗、延迟和分辨率变体。

### Safety

- 敏感操作、权限、恶意页面文本和 Prompt Injection。

## 17.3 非确定性处理

Agent 测试不能只跑一次。每个重要任务运行 3～10 次，并报告：

- pass@1；
- pass@k，可选；
- 平均成功率和置信区间；
- P50/P95 步数；
- P50/P95 延迟；
- 平均 token/cost；
- 故障类型分布；
- 故障簇分布。

## 17.4 Release Gate 示例

```yaml
critical_success_rate_min: 0.95
overall_success_drop_max: 0.02
p95_cost_increase_max: 0.10
p95_latency_increase_max: 0.15
revived_p0_clusters_max: 0
new_fatal_clusters_max: 0
unsafe_actions_max: 0
```

对于样本很少的测试，不要仅凭 1～2 个失败就断言显著退化；可以先标记 `needs-review`。

---

# 18. WebArena-Verified 阶段

官方项目：

- https://github.com/ServiceNow/webarena-verified

BrowserGym 也提供 WebArena/WebArena-Verified 接口，但运行正式实验前要固定双方版本。

## 18.1 进入条件

只有达到以下条件才开始 WebArena：

- MiniWoB 500 条轨迹无 schema 错误；
- 自建后台可稳定 reset；
- Replay 可以显示完整步骤；
- 两种 Agent adapter 已工作；
- verifier、诊断和聚类闭环已打通；
- 一次 baseline/candidate regression 已成功完成。

## 18.2 第一批任务

选 30～50 个，覆盖：

- shopping；
- shopping admin；
- forum；
- GitLab；
- 跨网站任务。

优先选择有确定性 verifier 的任务。对于 LLM fuzzy evaluator，要单独标记 evaluator 类型和成本。

## 18.3 注意事项

- 使用自托管环境，不使用不断变化的公共网站作为主结论；
- 每次实验前 reset；
- 固定网站镜像；
- 保存 benchmark release；
- 记录 unavailable/infeasible，不要算作 Agent 普通失败；
- 区分 Agent failure、environment failure 和 verifier failure。

---

# 19. UI-TARS 阶段

官方项目：

- https://github.com/bytedance/UI-TARS

## 19.1 建议选择

优先使用 UI-TARS-1.5-7B 作为可复现开源基线。先接远程 OpenAI-compatible endpoint，再考虑本地 vLLM。

## 19.2 接入边界

UI-TARS adapter 输入：

- instruction；
- screenshot；
- history summary；
- viewport 尺寸。

输出规范化为：

```json
{
  "type": "click",
  "coordinates": [0.52, 0.31],
  "coordinate_space": "normalized",
  "raw_output": "..."
}
```

执行前统一转换到像素坐标，并记录：

- 原始模型坐标；
- 归一化坐标；
- 实际像素坐标；
- screenshot 原始尺寸；
- resize/crop/padding；
- device scale factor。

坐标链路必须完整，否则无法诊断 grounding error。

## 19.3 主要实验

- 不同分辨率；
- 浏览器缩放；
- 页面滚动；
- sticky header；
- 相似按钮；
- 小目标控件；
- 遮挡；
- 文案变化；
- 与 AgentLab DOM/Vision baseline 比较。

## 19.4 风险

- 模型权重和推理依赖体积大；
- 图像预处理影响坐标；
- 量化可能显著影响 grounding；
- 模型端 action format 需要严格解析；
- 本地部署的吞吐不适合一开始就跑大量轨迹。

---

# 20. OSWorld 阶段

官方项目：

- https://github.com/xlang-ai/OSWorld
- https://github.com/xlang-ai/OSWorld-V2

## 20.1 进入条件

- Web 平台闭环已经稳定；
- UI-TARS 坐标链路已验证；
- Artifact store 能处理大量 screenshot；
- 支持长轨迹压缩和分页读取；
- environment/verifier failure 已有独立分类；
- 有独立机器或可销毁 VM 环境。

## 20.2 环境方案

### Windows 本地开发机

优先考虑 VMware Workstation Pro：

- 下载官方 VM；
- 配置 `vmrun`；
- 使用 OSWorld quickstart 验证 reset/step/screenshot；
- 不要直接让 Agent 操作宿主机的重要账户和文件。

### Linux GPU/服务器

- Docker + KVM；
- 或官方云环境方案；
- 适合并行运行和 UI-TARS 推理。

## 20.3 第一批任务

只选 10～20 个：

- Chrome；
- 文件管理；
- LibreOffice Writer；
- VS Code；
- 少量 multi-app。

先避开需要复杂外部账号、OAuth、代理或不稳定网站的任务。

## 20.4 轨迹扩展

需要增加：

- active window；
- application name；
- cursor position；
- keyboard hotkey；
- filesystem diff；
- process/window event；
- VM snapshot/checkpoint；
- desktop resolution和scale；
- app版本。

---

# 21. 分阶段施工计划

## Phase 0：环境与技术验证，2～3 天

工作：

- 创建仓库；
- 安装 Python 3.11、uv、Node、Docker；
- 启动 PostgreSQL；
- 安装 Playwright Chromium；
- 跑通 BrowserGym MiniWoB demo；
- 跑通 AgentLab GenericAgent 单任务；
- 跑通 Browser Use 单任务；
- 保存一份原始 trace。

验收：

- 三个 smoke command 都能在 README 中复现；
- 记录依赖版本；
- 没有把 API key 提交到 Git。

## Phase 1：轨迹协议与 Collector，第 1 周

工作：

- 定义 Pydantic schema；
- 实现 Run/Step/Event/Artifact；
- 实现 JSONL exporter；
- 实现本地 artifact store；
- 实现 redaction；
- 写 schema unit tests；
- 制作一条 synthetic trace fixture。

验收：

- schema 可版本化；
- trace 能 round-trip；
- screenshot hash 可验证；
- 敏感 header 被删除；
- 错误字段会明确报错。

## Phase 2：自建后台，第 2 周

工作：

- 实现登录、库存、订单、导出；
- 实现 8～10 个任务；
- 实现 fixture reset；
- 实现确定性 verifier；
- 实现 4 种故障注入；
- Docker Compose 一键启动。

验收：

- 每个任务人工执行可通过；
- reset 后数据库 checksum 一致；
- verifier 能区分成功和失败；
- 故障注入有真值记录。

## Phase 3：AgentLab + Browser Use Adapter，第 3 周

工作：

- 接入 AgentLab Generic DOM；
- 接入 AgentLab Vision；
- 接入 Browser Use；
- 统一 action schema；
- 统一 usage/cost；
- 保存原始 trace 和 canonical trace。

验收：

- 同一自建任务能由两种框架运行；
- 运行结果进入同一数据库；
- 每个 step 有截图和 action；
- adapter 单测不依赖真实 API。

## Phase 4：MiniWoB 批量运行，第 4 周

工作：

- 选 20～30 个任务；
- 构建 suite；
- 添加 repeat、并发和预算；
- 运行至少 250 条轨迹；
- 统计成功率、步骤和成本；
- 找出 schema 和采集缺口。

验收：

- 轨迹完成率 ≥ 98%；
- 失败运行不会丢失已有 artifact；
- 所有 run 有明确终止原因；
- 可导出实验 manifest 和 summary CSV。

## Phase 5：Replay + Diagnose，第 5 周

工作：

- Runs 页面；
- Step Replay；
- 点击位置覆盖；
- DOM/A11y diff 摘要；
- 规则检测器；
- 结构化 Judge；
- 人工标注 50～100 条失败轨迹。

验收：

- 任意失败可在 1 分钟内人工定位；
- Judge JSON 解析成功率 ≥ 99%；
- 规则命中有证据；
- 报告能区分 Agent、environment 和 verifier failure。

## Phase 6：Cluster + Regression，第 6～7 周

工作：

- FailureCase 标准化；
- embedding；
- HDBSCAN；
- cluster summary；
- 人工 merge/split；
- promote-to-regression；
- baseline/candidate compare；
- release gate。

验收：

- 已知注入故障能形成可解释簇；
- 至少 5 个故障簇；
- 一个修复前后实验；
- 历史故障能从命令行重新运行；
- CI 能在明显退化时失败。

## Phase 7：完整 MVP 与项目包装，第 8 周

工作：

- 900 条左右综合轨迹；
- 一次完整版本对比；
- 性能和成本报告；
- Demo 视频；
- README；
- 架构文档；
- 已知限制；
- 面试讲稿。

验收：

- 新用户按 README 能完成 smoke run；
- Demo 展示失败、聚类、修复和回归；
- 所有数字可以从保存的实验结果重新生成。

## Phase 8：WebArena-Verified，第 9～10 周

- 部署并固定环境；
- 选择 30～50 个任务；
- 运行两种以上 Agent；
- 评估跨环境泛化；
- 分析 environment/verifier failure。

## Phase 9：UI-TARS，第 11～12 周

- 部署 1.5-7B endpoint；
- 建立坐标转换链路；
- 运行自建扰动集；
- 与 DOM/Vision Agent 对比 grounding failure。

## Phase 10：OSWorld，第 13 周以后

- 单独环境；
- 10～20 个桌面任务；
- 桌面 artifact 与文件 diff；
- 评估平台能否扩展到长轨迹、多应用。

---

# 22. 推荐实验矩阵

## 22.1 MVP

```text
环境：Custom Admin + MiniWoB++
Agent：AgentLab DOM + AgentLab Vision + Browser Use
任务：约 45 个
每配置重复：5 次
总轨迹：约 675 条起
```

如果成本有限，先做：

```text
45 个任务 × 2 个 Agent × 5 次 = 450 条
```

## 22.2 论文版

```text
环境：Custom Admin + MiniWoB++ + WebArena-Verified
Agent：AgentLab DOM + AgentLab Vision + Browser Use + UI-TARS
人工标注失败：200～300 条
注入故障：至少 8 类
```

## 22.3 核心对照

- 只看最终结果 vs 看完整轨迹；
- 单次 Judge vs 分段 Judge；
- 纯 Judge vs 规则+Judge；
- 文本特征 vs 文本+结构化特征；
- 无视觉 vs 加入截图特征；
- 单条轨迹诊断 vs 跨轨迹聚类；
- 随机选择回归用例 vs 每簇代表性选择；
- 原始失败重跑 vs 分支回放。

---

# 23. 项目验收指标

## 23.1 工程指标

- 轨迹采集完成率 ≥ 98%；
- Judge 结构化输出解析成功率 ≥ 99%；
- artifact 与 run 关联完整率 ≥ 99%；
- 自建环境 reset 成功率 ≥ 99%；
- 失败运行能够保留现场；
- 同一任务可以跨 Agent adapter 运行；
- CI smoke suite 在可接受时间内完成。

## 23.2 研究指标

- 故障检测 F1；
- 首个关键错误 exact/±1 accuracy；
- 故障类型 Macro-F1；
- cluster purity/NMI/ARI；
- same-root-cause recall；
- top-K cluster failure coverage；
- regression test reduction ratio；
- regression detection rate；
- 修复后的任务成功率提升；
- 诊断和测试额外成本。

## 23.3 产品指标

- 人工定位一次失败的时间；
- 相似历史失败检索命中率；
- 重复故障簇数量；
- 新版本新增/复发故障簇；
- 自动转回归用例的人工接受率；
- release gate 的误拦截和漏检。

---

# 24. 必须做的测试

## 24.1 Unit Tests

- schema validation；
- action normalization；
- redaction；
- cost aggregation；
- DOM diff；
- rule detectors；
- cluster feature builder；
- release gate evaluation。

## 24.2 Integration Tests

- BrowserGym synthetic environment；
- fake Agent adapter；
- PostgreSQL + artifact store；
- trace ingest and replay API；
- failed run preservation；
- promote-to-regression；
- baseline/candidate compare。

## 24.3 Golden Fixtures

仓库内保存几条小型脱敏轨迹：

- 成功；
- grounding failure；
- repeated-action loop；
- environment timeout；
- verifier failure；
- safety violation。

这些 fixture 保证 UI 和诊断逻辑升级后不会悄悄改变。

---

# 25. 主要风险与应对

## 25.1 实时网站不稳定

应对：主实验使用自建环境和自托管 benchmark；实时互联网只作展示。

## 25.2 Judge 产生合理但错误的诊断

应对：规则优先、证据约束、结构化输出、人工 gold set、重复评估和反事实验证。

## 25.3 环境错误被当成 Agent 错误

应对：单独建立 `environment` 和 `verifier` 类型，保存网络/console/后端事件。

## 25.4 轨迹存储快速膨胀

应对：截图去重、WebP/PNG策略、失败全量/成功采样、artifact retention policy。

## 25.5 API 成本过高

应对：MiniWoB 使用便宜模型；诊断只处理失败；先规则过滤；缓存 Judge 结果；正式实验前 dry run。

## 25.6 Agent 框架频繁升级

应对：adapter 层隔离、固定 commit/version、保留原始 trace、canonical schema 独立版本。

## 25.7 OSWorld 环境消耗过大

应对：OSWorld 独立成后期 milestone，不作为 MVP 阻塞项。

## 25.8 项目看起来只是工具拼装

应对：明确自己的核心贡献：

- 统一 FailureCase 表示；
- 首个关键错误定位；
- 跨轨迹根因聚类；
- 故障簇驱动的最小回归集；
- 环境可复现与版本门禁；
- 有人工标注、消融和统计实验。

---

# 26. 最终演示脚本

一个合格的 5～8 分钟 Demo 应展示：

1. 使用 AgentLab 和 Browser Use 执行同一个库存导出任务；
2. Agent v1 在滚动后的页面点击错误；
3. Replay 显示动作前后截图和实际点击元素；
4. Diagnose 定位首个关键错误；
5. Cluster 页面显示它与另外 20 次失败属于同一根因；
6. 开发者修复坐标或等待策略；
7. 将代表性失败 promote 为回归测试；
8. v2 通过旧故障测试；
9. v2 在另一个任务出现新故障簇；
10. Release Gate 根据策略决定通过、阻止或人工复核。

面试中应能回答：

- 为什么只看 task success 不够；
- 为什么 Agent 测试必须重复运行；
- 为什么要区分 error manifestation 和 root cause；
- 为什么聚类对象是 FailureCase 而不是整条轨迹；
- 如何防止 LLM Judge 自说自话；
- 如何保证 benchmark 和环境可复现；
- 为什么 GUI Agent 比 API Agent 更难回放；
- 如何控制轨迹存储和模型成本；
- 为什么先 Web 后 OSWorld。

---

# 27. 最终交付清单

## 代码

- Trace SDK；
- BrowserGym environment adapter；
- AgentLab adapter；
- Browser Use adapter；
- UI-TARS adapter，可选增强；
- Runner CLI；
- 自建后台；
- Replay Console；
- Diagnose Engine；
- Cluster Engine；
- Regression Registry；
- Version Comparator；
- CI workflow。

## 数据与实验

- 脱敏轨迹样例；
- 人工标注规范；
- gold failure set；
- 故障注入配置；
- benchmark manifests；
- baseline/candidate 结果；
- 消融实验；
- 可重生成图表的脚本。

## 文档

- README Quickstart；
- 架构图；
- Trace Schema；
- Adapter Guide；
- Task/Verifier Guide；
- Reproducibility Guide；
- Threat Model 和隐私说明；
- 实验报告；
- 已知限制。

---

# 28. 现在立刻开始的第一周工作

## Day 1

- 创建 `tracetotest` 仓库；
- 安装 WSL2、Docker、Python 3.11、uv；
- 创建 `.env.example` 和 `.gitignore`；
- 记录机器、系统和工具版本。

## Day 2

- 安装 BrowserGym；
- 安装 Playwright Chromium；
- 跑通一个 MiniWoB 任务；
- 保存 observation、action、reward 和 screenshot。

## Day 3

- 安装 AgentLab；
- 跑通 GenericAgent；
- 找到 AgentLab 原始 trace 的生成位置；
- 抽取一条运行，手工转换成目标 JSON。

## Day 4

- 安装 Browser Use；
- 在一个本地静态测试页上跑通；
- 保存其步骤和 screenshot；
- 比较两种原始 trace 的字段差异。

## Day 5

- 定义 `Run`、`Step`、`Event`、`Artifact` Pydantic schema；
- 实现 JSONL 写入器；
- 实现本地 artifact store；
- 加入 5～10 个 schema 单测。

## Day 6～7

- 实现最小 adapter interface；
- 将 AgentLab 和 Browser Use 各一条 trace 转成 canonical trace；
- 写一个静态 HTML/简单前端逐步显示 screenshot 和 action；
- 写第一周总结：完成项、缺口、下周风险。

第一周结束时必须有一个可展示结果：

> 同一个简单网页任务分别由 AgentLab 和 Browser Use 执行，两种不同格式的原始轨迹被转换为同一协议，并在统一页面中逐步回放。

如果这个结果没有完成，不要进入聚类、WebArena 或 UI-TARS。

---

# 29. 官方资料入口

- BrowserGym：https://github.com/ServiceNow/BrowserGym
- AgentLab：https://github.com/ServiceNow/AgentLab
- WorkArena：https://github.com/ServiceNow/WorkArena
- WebArena-Verified：https://github.com/ServiceNow/webarena-verified
- Browser Use：https://github.com/browser-use/browser-use
- UI-TARS：https://github.com/bytedance/UI-TARS
- OSWorld：https://github.com/xlang-ai/OSWorld
- OSWorld 2.0：https://github.com/xlang-ai/OSWorld-V2
- AgentDiagnose：https://aclanthology.org/2025.emnlp-demos.15/
- GUIDE：https://arxiv.org/abs/2604.04399
- AgentDebugX：https://arxiv.org/abs/2607.18754
- AgentRR：https://arxiv.org/abs/2505.17716

正式开始开发前，对外部仓库全部记录 commit/tag，不要只保存网页链接。

---

# 30. 最终建议

严格按以下顺序推进：

```text
BrowserGym smoke
    ↓
统一 Trace Schema
    ↓
AgentLab + Browser Use adapters
    ↓
自建后台 + 确定性 verifier
    ↓
MiniWoB 批量轨迹
    ↓
Replay
    ↓
Diagnose
    ↓
Failure Clustering
    ↓
Regression + Release Gate
    ↓
WebArena-Verified
    ↓
UI-TARS
    ↓
OSWorld
```

MVP 成功的标准不是支持了多少框架，而是完整证明：

> 一次真实 GUI Agent 失败可以被完整记录、快速回放、正确归因、归入已有根因簇，并在修复后自动作为回归测试验证，且所有结果可以在固定环境中复现。
