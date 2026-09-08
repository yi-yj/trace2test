# Trace2Test

Web/GUI Agent 轨迹回放、故障聚类与回归测试平台。

## 统一 Runner 与 Trace SDK

同一条命令可选择 AgentLab 或 Browser Use，两者都会产生 `canonical/canonical_trace.json`
及 Run/Step/Event/Artifact JSONL：

```bash
.venv/bin/python -m tracetotest run --framework agentlab --headed
.venv/bin/python -m tracetotest run --framework browser-use --headed
```

正式自建任务直接读取 TaskSpec；无需重复手写 URL、目标、fixture、预算和验证条件：

```bash
.venv/bin/python -m tracetotest run \
  --framework agentlab \
  --task tasks/admin/filter_low_inventory.json \
  --headed
```

运行结果统一写入 `.env` 的 `DATABASE_URL`（默认 `sqlite:///./data/results.sqlite3`）。

传入同一组任务、预算和验证条件：

```bash
.venv/bin/python -m tracetotest run \
  --framework browser-use \
  --task-id example-link \
  --start-url https://example.com \
  --goal "Click the 'More information...' link once." \
  --expected-url-contains iana.org \
  --max-steps 5 \
  --headed --record-video
```

Browser Use 0.13.10 使用独立环境，避免其新版 `anthropic` 与 AgentLab 0.4.2 冲突：

```bash
cd integrations/browser_use
UV_CACHE_DIR=../../.cache/uv UV_PYTHON_INSTALL_DIR=../../.tools/python \
  ../../.tools/uv sync --python ../../.venv/bin/python
cd ../..
```

统一 Runner 读取现有 `.env` 中的 Qwen 配置。headed 模式默认有共享虚拟鼠标；
`--storage-state .auth/<name>.json` 可加载登录状态，`--no-virtual-cursor` 可显式关闭鼠标。

也可将历史原始轨迹单独转换：

```bash
.venv/bin/python -m tracetotest adapt --framework agentlab --run-dir artifacts/agentlab/<run>
.venv/bin/python -m tracetotest adapt --framework browser-use --run-dir artifacts/browser-use/<run>
```

完整操作方式见 [统一 Runner 与轨迹采集指南](docs/RUNNER_TRACE_OPERATIONS.md)，
协议和脱敏边界见 [Trace SDK 说明](docs/TRACE_SDK.md)。

## 可重置库存任务

运行不消耗模型 API 的完整“fixture 重置—浏览器操作—轨迹采集—确定性验证”闭环：

```bash
.venv/bin/python -m tracetotest inventory-e2e
```

当前验证器检查 CSV 文件、精确行内容、筛选阈值、导出次数、fixture checksum
和禁止的数据库副作用。实现与 Schema 见
[Task、Fixture、Collector 与 Verifier](docs/TASK_FIXTURE_VERIFIER.md)。

## 自建后台与 Phase 2/3 验收

后台包含登录、库存、订单和 CSV 导出，共 10 个 TaskSpec，并支持响应延迟、HTTP 500、控件缺失和错误导出四种带真值的故障注入。

```bash
docker compose up --build -d
.venv/bin/python -m tracetotest acceptance
.venv/bin/python -m tracetotest phase3-acceptance --task-id filter-low-inventory
```

验收范围、真实跨框架 Run ID 和当前限制见 [Phase 2 / Phase 3 验收记录](docs/PHASE2_PHASE3_ACCEPTANCE.md)。

## AgentLab + Qwen

默认使用 AgentLab `ToolUseAgent`、Qwen 原生 tool call 与视觉 + A11y Tree 观察：

```bash
.tools/uv run python -m scripts.run_agentlab_miniwob
```

更换任务、使用纯 DOM/A11y 模式，或显示浏览器：

```bash
.tools/uv run python -m scripts.run_agentlab_miniwob --task click-checkboxes
.tools/uv run python -m scripts.run_agentlab_miniwob --config configs/agents/agentlab_qwen_a11y.yaml
.tools/uv run python -m scripts.run_agentlab_miniwob --headed --slow-mo 500 --record-video
```

原始 AgentLab 轨迹、可读 `trace.json`、每步截图、reward、版本清单和 manifest 保存在 `artifacts/agentlab/<experiment>/`。配置见 `configs/agents/`。
headed 模式默认启用共享虚拟鼠标：黄色 `MOVE`、红色 `CLICK`、蓝色 `IDLE`。可用 `--cursor-move-ms`、`--click-display-ms` 调整演示速度，或用 `--no-virtual-cursor` 关闭。后续 Agent 框架统一通过 `tracetotest.visualization.wrap_env_with_virtual_cursor` 接入。

LiteLLM 价格表未收录的 Qwen 型号只输出一条简短 warning，保留 token 用量并将 `effective_cost` 记为 `0`，不影响动作执行。

### 受控的真实站点演示

真实站点只用于只读演示，不作为正式 benchmark。默认在 `example.com` 点击一个公开链接，并用最终 URL 而不是 openended 的固定零 reward 验证结果：

```bash
.venv/bin/python -m scripts.run_agentlab_web --headed --record-video
```

初始页面导航默认超时为 30 秒，可用 `--navigation-timeout-ms` 调整。导航失败会作为
`environment` failure 写入 canonical `VerificationResult`，不计为 Agent 任务失败。

产物保存在 `artifacts/agentlab-web/<experiment>/`。不要将该入口用于登录、下单、发布、删除或其他会改变外部状态的操作。

### 中文字体与登录状态

WSL headed Chromium 会自动通过 `configs/fontconfig-wsl.conf` 使用 Windows 已安装的微软雅黑/宋体，不复制字体文件。

首次手动登录并保存 Playwright `storageState`：

```bash
.venv/bin/python -m scripts.capture_browser_state \
  --url https://login.taobao.com/ \
  --name taobao
```

登录成功后回到终端按 Enter，状态保存在被 Git 忽略的 `.auth/taobao.json`。后续演示加载它：

```bash
.venv/bin/python -m scripts.run_agentlab_web \
  --start-url https://www.taobao.com/ \
  --goal '在搜索框输入“无线鼠标”并搜索，不要点击商品或修改账户数据。' \
  --expected-url-contains s.taobao.com \
  --max-steps 2 \
  --storage-state .auth/taobao.json \
  --headed --slow-mo 800 --record-video
```

`storageState` 包含可能用于冒充账号的 Cookie 和本地存储，禁止提交或分享。它不包含 `sessionStorage`，且不保证消除站点的 CAPTCHA/风控。

## MiniWoB smoke test

项目使用 Python 3.11、AgentLab 0.4.2、BrowserGym 0.14.2 和固定版本的 MiniWoB++：

```bash
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.tools/python"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright"
.tools/uv sync --python 3.11
.tools/uv run playwright install chromium

git clone https://github.com/Farama-Foundation/miniwob-plusplus.git .benchmarks/miniwob-plusplus
git -C .benchmarks/miniwob-plusplus checkout 7fd85d71a4b60325c6585396ec4f48377d049838

cp .env.example .env
# 设置 .env 中的 MINIWOB_ROOT 和可选的 DASHSCOPE_API_KEY
.tools/uv run python scripts/run_miniwob_smoke.py
```

运行结果保存在 `artifacts/smoke/<run-id>/`，包括 observation、action、reward、执行前后截图和 manifest。`artifacts/` 与 `.env` 均不会被 Git 提交。

## Qwen visual tool-call test

在 `.env` 中设置 `DASHSCOPE_API_KEY` 后运行：

```bash
.tools/uv run python -m scripts.run_qwen_miniwob
```

Qwen 将同时读取任务文本、A11y Tree 和截图，并通过受约束的 `click(bid)` tool call 操作页面。脱敏后的模型请求、响应、token usage、动作、reward、截图及 manifest 保存在 `artifacts/qwen/<run-id>/`。

通过 WSLg 实时显示 Chromium，并将操作放慢到每步 1 秒：

```bash
.tools/uv run python -m scripts.run_qwen_miniwob --headed
```

可视化模式会显示虚拟鼠标：蓝色 `IDLE` 表示未点击，黄色 `MOVE` 表示移动，红色 `CLICK` 与脉冲圈表示点击状态。成功或失败后，页面底部会显示并自动聚焦英文 `CLOSE CHROMIUM` 按钮（避免最小 Chromium 环境缺少中文字体）；可在浏览器内按 Enter、直接点击该按钮，或在启动脚本的终端按 Enter 来关闭 Chromium。这个脚本只运行一个场景，Enter 不会启动下一个场景。

可用 `--slow-mo 2000` 让虚拟鼠标到达目标后停留 2 秒再点击；它不会再延迟 Enter 检测。红色点击状态默认显示 450ms，可通过 `--click-display-ms` 调整。自动化场景可加 `--no-pause` 禁止等待，也可用 `--no-virtual-cursor` 隐藏虚拟鼠标：

```bash
.tools/uv run python -m scripts.run_qwen_miniwob --headed --slow-mo 2000
.tools/uv run python -m scripts.run_qwen_miniwob --headed --click-display-ms 800
.tools/uv run python -m scripts.run_qwen_miniwob --headed --no-pause
.tools/uv run python -m scripts.run_qwen_miniwob --headed --no-virtual-cursor
```

默认固定使用 `qwen3-vl-plus-2025-12-19`。模型流量默认绕过系统代理，
浏览器流量默认使用 `BROWSER_PROXY_SERVER` 或现有 `HTTPS_PROXY/HTTP_PROXY`；
两者可独立配置。如果返回 `AllocationQuota.FreeTierOnly`，需要在百炼控制台增加余额或关闭“仅使用免费额度”后重试。

## Inspect the MiniWoB dataset

查看当前 BrowserGym 版本实际注册的全部任务及描述：

```bash
.tools/uv run python scripts/list_miniwob_tasks.py
.tools/uv run python scripts/list_miniwob_tasks.py --search click
.tools/uv run python scripts/list_miniwob_tasks.py --json
```

完整项目要求见 [AGENTS.md](AGENTS.md)，技术构建说明见 [docs/PROJECT_BUILD_GUIDE.md](docs/PROJECT_BUILD_GUIDE.md)。
