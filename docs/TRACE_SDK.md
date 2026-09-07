# Trace SDK / Adapter

## 当前范围

- Schema `1.0.0`：`RunRecord`/`StepRecord`/`EventRecord`/`ArtifactRecord`。
- Adapter：AgentLab 可读 `trace.json + manifest.json`；Browser Use 在模型决策回调和每步结束回调采集。
- 导出：`canonical_trace.json`、`run.jsonl`、`steps.jsonl`、`events.jsonl`、`artifacts.jsonl`。
- Artifact 按 SHA-256 校验；URL 凭证、API key、Cookie、token 和密码字段会脱敏。

```text
AgentLab raw files ---- AgentLabAdapter ----\
                                          +--> canonical schema --> JSON + JSONL
Browser Use callbacks - BrowserUseAdapter-/
```

Browser Use 保存动作前的 URL/title/DOM+A11y/截图、结构化决策摘要、元素
index/动作参数、动作结果与动作后截图；同时记录可见的浏览器事件摘要、未完成
network request 和文件 attachment。不保存模型私有思维链。

## 安全边界

JSON/文本 artifact 会在 canonical 目录内脱敏。截图不能靠通用规则可靠判定个人
信息，因此 Artifact 中如实标记 `redacted=false`，在共享、上传或进入数据集前必须人工
审查或经过后续图像脱敏器。`.env`、`.auth/` 和 `artifacts/` 都被 Git 忽略。

Browser Use 原始文件是回调边界的安全子集，而不是其完整 history 序列化；这是为了避免
持久化私有思维链、Cookie 或不必要的模型上下文。

## 扩展新框架

新 Adapter 实现 `tracetotest.adapters.base.TraceAdapter`，输出 `CanonicalTrace`，并由
`LocalArtifactStore` 保存 artifact。可视化运行必须复用 `tracetotest.cursor_overlay`，不在
Adapter 内另做一套鼠标样式。每次实验 manifest 需保留 Git commit、dirty 状态、两份
lockfile 摘要、模型、任务、seed、预算和验证结果。

## 已知限制

- Browser Use 与 AgentLab 必须分开 Python 环境；统一 Runner 负责跨进程调度。
- 当前统一在线 Runner 先覆盖 HTTPS web task；MiniWoB 仍可使用
  `scripts.run_agentlab_miniwob`，其产物也会自动转为 canonical trace。
- 网络采集是 Browser Use 回调当时的可见请求，不是完整 HAR；如需审计级网络回放，应在
  Benchmark Runner 阶段增加脱敏 HAR collector。
