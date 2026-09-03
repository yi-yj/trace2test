# Trace2Test 开发指南

## 1. 指导原则

本项目构建面向 Web/GUI Agent 的持续评测平台。开发时以本文件为执行准则，以 [`docs/PROJECT_BUILD_GUIDE.md`](docs/PROJECT_BUILD_GUIDE.md) 为完整技术依据；涉及架构、数据协议、接口、任务、实验或验收细节时，必须先查阅该文档，不得凭空补全。

优先完成“轨迹采集 → 诊断 → 聚类 → 回归”的可复现闭环，不以界面美观、框架数量或模型训练代替核心能力。

## 2. 最终交付

最终内容必须完整包含：

1. **Trace SDK / Adapter**：统一接入 AgentLab、Browser Use，并可扩展 UI-TARS、OSWorld；采集截图、DOM/A11y Tree、动作、模型调用、页面变化、网络/文件事件和验证结果。
2. **Benchmark Runner**：管理任务、环境、fixture、预算、重复运行、结果验证、run manifest 和失败处理。
3. **Replay Web Console**：提供 Runs、Replay、Clusters、Regression 页面，支持步骤级回放和版本比较。
4. **Diagnose & Cluster Engine**：完成规则检测、轨迹分段、首个关键错误定位、结构化诊断、故障 embedding、聚类及历史案例关联。
5. **Regression & Release Gate**：把历史失败转成可复现测试，对比 baseline/candidate 的质量、成本、延迟和安全性，并阻止不合格版本发布。

最终必须证明：一次真实 GUI Agent 失败能够被完整记录、快速回放、正确归因、归入根因簇，并在修复后自动作为回归测试验证，且结果能在固定环境中复现。

## 3. 范围与顺序

MVP 必须覆盖 BrowserGym、AgentLab、Browser Use、自建可重置后台、20～30 个 MiniWoB++ 任务、统一轨迹协议、Replay、至少 6 类规则诊断、结构化 Judge、故障聚类、回归用例、版本对比和基础 CI release gate。

严格按以下顺序推进：

```text
BrowserGym smoke → 统一 Trace Schema → AgentLab + Browser Use adapters
→ 自建后台 + 确定性 verifier → MiniWoB 批量轨迹 → Replay
→ Diagnose → Failure Clustering → Regression + Release Gate
→ WebArena-Verified → UI-TARS → OSWorld
```

当前阶段验收未通过，不得提前进入后续阶段。WebArena、UI-TARS 和 OSWorld 均不得阻塞 MVP。

不从头训练通用 GUI 模型，不自行实现浏览器或虚拟机，不把 LLM Judge 当作 ground truth，不以实时网站作为主要实验环境，不采集或依赖私有思维链。

## 4. 工程约束

- 主要代码运行于 WSL2/Linux；使用 Python 3.11 与 `uv`，前端使用 Node.js 20 LTS 与 pnpm。
- 外部框架通过 adapter 隔离，并固定版本或 commit；统一轨迹 schema 独立版本化。
- 成功判定优先使用确定性 verifier；Judge 必须结构化输出并引用可核验的轨迹证据。
- 功能实现必须附带与风险相称的测试，包括 schema 单元测试、adapter/runner 集成测试和关键失败类型的 golden fixtures。
- 修改架构、schema、依赖或 release gate 时，同步更新文档、fixture 和可复现记录。
- 只提交必要的小范围变更；保留用户已有修改，不擅自覆盖、回滚或删除无关内容。

## 5. 安全、实验与版本门禁

以下要求不可跳过：

1. 密钥只存放于被 Git 忽略的 `.env`；仓库只提交脱敏的 `.env.example`。
2. 不提交 API 密钥、账号凭证、Cookie、个人数据、未脱敏轨迹、私有思维链或不必要的大体积 artifact。
3. 日志、截图、DOM、网络和文件事件在保存或共享前必须脱敏；危险动作和越权动作必须进入安全检测与 release gate。
4. 执行删除、覆盖、数据库重置、环境清理等破坏性操作前，必须确认目标范围并优先选择可恢复方案。
5. 依赖和外部仓库必须记录精确版本、tag 或 commit；不得仅记录网页链接或使用未固定的浮动版本完成正式实验。
6. 每次运行必须生成 manifest，至少记录代码 commit、Agent/模型/Prompt/环境/任务版本、随机种子、预算、依赖锁文件摘要、开始结束时间及结果。
7. 每次正式实验必须保存完整版本信息、配置、数据集与 fixture 版本、原始结果和可重生成报告的脚本；同一配置应能重复运行并解释波动。
8. 提交前必须运行受影响范围的格式检查、静态检查和测试；若某项无法运行，必须说明原因、风险和未验证范围。
9. 推送远端前必须先获取远端最新状态，解决所有合并或变基冲突，再重新运行相关测试；禁止使用强制推送覆盖他人历史，除非用户明确授权。
10. 合并或发布前必须通过适用的 CI 与 release gate；P0/P1 历史故障复发、新致命故障簇或安全违规默认阻止发布。

## 6. 完成定义

任务只有在实现、测试、文档和可复现信息一致时才算完成。交付说明必须列出：完成内容、测试命令与结果、已知限制、未验证项，以及对质量、成本、延迟或安全指标的影响。

阶段计划、目录结构、Trace Schema、FailureCase 表示、诊断 taxonomy、实验矩阵、指标阈值和完整交付清单见 [`docs/PROJECT_BUILD_GUIDE.md`](docs/PROJECT_BUILD_GUIDE.md)。
