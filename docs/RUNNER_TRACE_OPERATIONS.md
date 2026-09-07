# 统一 Runner 与轨迹采集指南

## 1. 标准入口

项目的标准入口是：

```bash
.venv/bin/python -m tracetotest <command> [options]
```

目前提供三个子命令：

| 子命令 | 作用 |
| --- | --- |
| `run` | 调度 AgentLab 或 Browser Use 执行新任务，保存原始轨迹并自动转换为 canonical trace |
| `adapt` | 不再次运行 Agent，将已有的 AgentLab/Browser Use 产物转换为 canonical trace |
| `inventory-e2e` | 重置库存 fixture，执行筛选/下载，并用页面、CSV 和后端状态端到端验证 Collector/Verifier |

查看命令参数：

```bash
.venv/bin/python -m tracetotest --help
.venv/bin/python -m tracetotest run --help
.venv/bin/python -m tracetotest adapt --help
.venv/bin/python -m tracetotest inventory-e2e --help
```

`scripts/run_agentlab_*.py` 等脚本保留为框架专用入口和调试工具；对外执行
HTTPS web task 时应优先使用 `python -m tracetotest run`。

## 2. 环境准备

### 2.1 主环境

主环境包含 Trace SDK、AgentLab 和 BrowserGym：

```bash
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.tools/python"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright"

.tools/uv sync --python 3.11
.tools/uv run playwright install chromium
```

### 2.2 Browser Use 隔离环境

Browser Use 0.13.10 需要的新版 `anthropic` 与 AgentLab 0.4.2 不兼容，因此它使用
`integrations/browser_use/.venv` 和独立 `uv.lock`：

```bash
cd integrations/browser_use
UV_CACHE_DIR=../../.cache/uv UV_PYTHON_INSTALL_DIR=../../.tools/python \
  ../../.tools/uv sync --python ../../.venv/bin/python
cd ../..
```

统一 Runner 会自动使用该解释器启动 Browser Use worker，无需手动激活隔离环境。

### 2.3 Qwen 配置

`.env` 至少需要：

```dotenv
DASHSCOPE_API_KEY=<local-secret>
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_VISION_MODEL=qwen3.7-plus
QWEN_TOOL_MODEL=qwen-plus
ARTIFACT_STORE_PATH=./artifacts
```

`.env` 不得提交。默认使用 `QWEN_VISION_MODEL`；传入 `--no-vision` 后改用
`QWEN_TOOL_MODEL`。

## 3. 运行任务

### 3.1 同一任务选择不同框架

AgentLab：

```bash
.venv/bin/python -m tracetotest run \
  --framework agentlab \
  --task-id example-link \
  --start-url https://example.com \
  --goal "Click the 'More information...' link once." \
  --expected-url-contains iana.org \
  --max-steps 5
```

Browser Use：

```bash
.venv/bin/python -m tracetotest run \
  --framework browser-use \
  --task-id example-link \
  --start-url https://example.com \
  --goal "Click the 'More information...' link once." \
  --expected-url-contains iana.org \
  --max-steps 5
```

`--expected-url-contains` 是当前 web task 的确定性 verifier：最终 URL 包含该字符串时
任务成功。对比两个框架时，应保持 task-id、URL、goal、max-steps、模型观察
模式和 verifier 一致；无法一致的项目必须记入 manifest。

### 3.2 可视化和录像

```bash
.venv/bin/python -m tracetotest run \
  --framework browser-use \
  --headed --record-video
```

- 默认为 headless；`--headed` 显示 Chromium。
- headed 时默认启用共享虚拟鼠标：黄色 `MOVE`、红色 `CLICK`、蓝色 `IDLE`。
- `--cursor-move-ms` 和 `--click-display-ms` 调整演示速度。
- `--no-virtual-cursor` 关闭虚拟鼠标。
- `--record-video` 把浏览器会话保存到当次 run 的 video 目录。

### 3.3 使用已登录状态

```bash
.venv/bin/python -m scripts.capture_browser_state \
  --url https://login.taobao.com/ \
  --name taobao

.venv/bin/python -m tracetotest run \
  --framework browser-use \
  --task-id taobao-search \
  --start-url https://www.taobao.com/ \
  --goal '搜索“无线鼠标”，不要点击商品或修改账户数据。' \
  --expected-url-contains s.taobao.com \
  --storage-state .auth/taobao.json \
  --headed
```

`.auth/` 中的文件包含 Cookie 和本地存储，只能本地使用，不得上传或分享。

### 3.4 MiniWoB

当前统一 `run` 优先覆盖 HTTPS web task。MiniWoB 使用 AgentLab 专用入口，结束后也会
自动输出 canonical trace：

```bash
.venv/bin/python -m scripts.run_agentlab_miniwob \
  --task login-user \
  --max-steps 15 \
  --headed --record-video
```

### 3.5 库存导出确定性 E2E

```bash
.venv/bin/python -m tracetotest inventory-e2e
.venv/bin/python -m tracetotest inventory-e2e --headed --slow-mo 500
```

该入口用固定 Playwright 驱动验证 fixture、Collector 和 Verifier 闭环，不调用模型；
详见 [`TASK_FIXTURE_VERIFIER.md`](TASK_FIXTURE_VERIFIER.md)。

## 4. 统一调度如何实现

```text
python -m tracetotest run
        |
        +-- AgentLab ------> scripts.run_agentlab_web
        |                     -> BrowserGym VisualEnvArgs / ExpArgs
        |                     -> trace.json + AgentLab raw files + manifest.json
        |
        +-- Browser Use ---> isolated worker subprocess
                              -> model-decision callback + step-end callback
                              -> raw_trace.json + screenshots + manifest.json
        |
        +-- framework Adapter
                -> redaction + artifact hashing + schema validation
                -> canonical_trace.json + JSONL
```

入口实现在 `tracetotest/cli.py`：

1. 验证 HTTPS URL、步数、可视化延迟和 storage state 路径。
2. 读取 `.env` 中的 Qwen 配置和 artifact 根目录。
3. AgentLab 在主环境运行；Browser Use 由隔离解释器启动 worker 子进程。
4. 框架结束后调用对应 Adapter。
5. Adapter 完成脱敏、artifact 复制与 SHA-256 计算、Pydantic Schema 验证和导出。
6. verifier 未通过或框架运行出错时，命令以非零状态结束，已生成的 run 产物保留。

Browser Use worker 还会：

- 自动复用 `.cache/ms-playwright` 内的 Chromium；
- 关闭默认扩展下载和匿名 telemetry，避免与任务无关的网络依赖；
- 使用 `ChatOpenAILike` 连接百炼 OpenAI-compatible API；
- 设置 `use_thinking=False`、`use_judge=False`、`max_actions_per_step=1`，不保存私有思维链，
  并保持步骤与结构化动作一一对齐。

## 5. 轨迹如何采集

### 5.1 AgentLab

AgentLab 先保存框架原始的 `step_*.pkl.gz`、每步截图、日志和参数，然后生成不依赖
pickle 的 `trace.json`。`AgentLabAdapter` 将当前 step 作为动作前状态，下一 step 作为
动作后状态，并把 `click(bid='20')`/`fill(...)` 等字符串解析为结构化动作。

### 5.2 Browser Use

Browser Use 不修改框架内部代码，在官方回调边界采集：

- model-decision callback：动作前 URL/title、DOM+A11y 表示、截图、决策摘要、动作及元素 index；
- step-end callback：工具结果、错误、动作后 URL/title 和截图；
- Browser state：可见的浏览器事件摘要和当时未完成的 network request；
- ActionResult：文件 attachment 事件；
- History usage：输入、输出和总 token，以及可用时的 cost。

Browser Use 的 `raw_trace.json` 是回调字段的安全子集，不是完整 history 序列化，因此不包含
私有思维链、Cookie 和完整模型上下文。

## 6. Canonical Trace

Schema 版本当前为 `1.1.0`，定义位于 `tracetotest/trace/schema.py`；仍可
加载 `1.0.0` 历史轨迹。

| 记录 | 主要内容 |
| --- | --- |
| Run | run/task/suite/agent/framework、status、reward、UTC 时间、耗时、步数、token、cost、manifest ref |
| Step | 动作前 observation、决策摘要、结构化 action、动作后 after state 和 error |
| Event | verification、browser event、network request、file artifact 等异步事件 |
| Artifact | 类型、`artifact://` URI、SHA-256、content type 和脱敏状态 |

Schema 会强制：

- 所有子记录引用同一 `run_id`；
- `run.steps` 等于 Step 数量；
- `step_index` 从 0 开始且连续；
- 时间必须带时区并统一转为 UTC；
- artifact 必须带合法 SHA-256。

## 7. 产物目录

AgentLab web task：

```text
artifacts/agentlab-web/<experiment>/
```

Browser Use：

```text
artifacts/browser-use/<UTC-timestamp>_<task-id>/
```

典型结构：

```text
<run>/
├── manifest.json
├── trace.json | raw_trace.json
├── screenshots/
├── video/                         # 仅 --record-video
└── canonical/
    ├── canonical_trace.json             # 完整聚合格式
    ├── run.jsonl
    ├── steps.jsonl
    ├── events.jsonl
    ├── artifacts.jsonl
    └── artifacts/
        ├── raw/manifest.json
        ├── raw/trace.json
        ├── screenshots/
        ├── dom/
        └── a11y/
```

`artifact://screenshots/step-0-before.png` 相对于 `<run>/canonical/artifacts/`。

## 8. 转换已有轨迹

```bash
.venv/bin/python -m tracetotest adapt \
  --framework agentlab \
  --run-dir artifacts/agentlab/<experiment>

.venv/bin/python -m tracetotest adapt \
  --framework browser-use \
  --run-dir artifacts/browser-use/<run>
```

指定其他输出目录：

```bash
.venv/bin/python -m tracetotest adapt \
  --framework browser-use \
  --run-dir artifacts/browser-use/<run> \
  --output-dir /tmp/canonical-browser-use
```

Adapter 输入要求：

| 框架 | 必需文件 |
| --- | --- |
| AgentLab | `trace.json` + `manifest.json` |
| Browser Use | `raw_trace.json` + `manifest.json` |

## 9. 脱敏与分享

- `.env`、`.auth/`、`artifacts/` 均被 Git 忽略。
- JSON/文本中的 API key、Authorization、Cookie、password、secret、凭证 token、URL
  userinfo/敏感 query 和常见 email 会脱敏。`input_tokens` 等用量指标不会被误删。
- 截图无法通过通用文本规则可靠脱敏，Artifact 因此标记 `redacted=false`。
- 截图、原始轨迹和 storage state 在分享、上传或进入数据集前必须额外审查。
- 实时站点只用于受控、低风险演示，不把下单、发布、删除等外部副作用任务作为默认测试。

## 10. 实验与版本规则

每次正式运行应在已提交、`dirty=false` 的代码版本上执行。manifest 记录：

- Git commit 和 dirty 状态；
- Agent/框架/模型版本；
- task-id、goal、seed、max-steps 和 verifier；
- 主环境与 Browser Use 的 lockfile SHA-256；
- 开始/结束时间、token、cost 和最终结果。

开发修改通过测试后可主动创建本地 commit，但不主动执行 `git push`。只有用户明确
要求推送时，才先 fetch 远端、解决冲突、重新运行相关测试并推送；禁止默认强制推送。

## 11. 排查清单

| 现象 | 检查 |
| --- | --- |
| Browser Use runtime missing | 重新执行 2.2 的隔离环境 `uv sync` |
| 找不到 Chromium | 确认 `.cache/ms-playwright` 存在，重新执行 Playwright Chromium 安装 |
| Qwen 调用失败 | 检查 `.env` 的 key/base URL/model；代理不可达时设 `DASHSCOPE_BYPASS_PROXY=true` |
| 任务做完但命令失败 | 检查 `manifest.json.result` 和 `expected-url-contains` 是否匹配真实最终 URL |
| Adapter 报缺少文件 | 根据第 8 节确认框架原始文件齐全 |
| 没有虚拟鼠标 | 确认使用 `--headed` 且未传入 `--no-virtual-cursor` |

## 12. 扩展新 Agent 框架

1. 在框架稳定的 callback/event 边界采集，不修改策略内部逻辑。
2. 保留框架原始轨迹或安全子集。
3. 实现 `tracetotest.adapters.base.TraceAdapter`。
4. 使用 `LocalArtifactStore`、脱敏器和 `CanonicalTrace`，不自定义另一套平台内部格式。
5. headed 时复用 `tracetotest.cursor_overlay`。
6. 在 `tracetotest/cli.py` 注册框架名和调度函数。
7. 增加 Schema、Adapter、失败路径和统一 CLI 合同测试。
8. 用相同任务/模型/预算/verifier 与现有框架各运行一次，确认 canonical 输出可比较。
