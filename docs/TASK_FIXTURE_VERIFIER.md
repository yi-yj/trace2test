# Task、Fixture、Collector 与 Verifier

## 已实现组件

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| `TaskSpec` | `tracetotest/tasks/schema.py` | 版本化描述 instruction、环境、fixture、预算、verifier 和安全约束 |
| `JsonFixture` | `tracetotest/fixtures/base.py` | 从固定 JSON 建立可重置状态，并计算确定性 SHA-256 |
| `TraceCollector` | `tracetotest/trace/collector.py` | 增量记录 Step/Event/Artifact/VerificationResult，每次变更后写可恢复检查点 |
| `Verifier` | `tracetotest/verification/base.py` | 所有确定性验证器遵守的 Protocol |
| `VerificationResult` | `tracetotest/verification/schema.py` | 保存逐项检查、证据、分数及 agent/environment/verifier failure 分类 |
| `InventoryExportVerifier` | `tracetotest/verification/inventory.py` | 验证低库存 CSV、页面筛选对应的后端状态和禁止的数据库副作用 |

Trace Schema 当前为 `1.1.0`，仍可读取 `1.0.0`；新版本增加可选的第一类
`verification` 和 `RunRecord.termination_reason`。

## 运行库存端到端验证

```bash
.venv/bin/python -m tracetotest inventory-e2e
```

显示浏览器：

```bash
.venv/bin/python -m tracetotest inventory-e2e --headed --slow-mo 500
```

可视化模式默认使用共享虚拟鼠标显示 `MOVE`、`CLICK` 和 `IDLE` 状态；任务验证完成后，
按 Enter 或点击页面底部按钮关闭 Chromium。仅调试时可用 `--no-virtual-cursor` 关闭覆盖层。

该命令执行：

```text
加载 TaskSpec 和 inventory-v1 fixture
→ 在 127.0.0.1 随机端口启动库存应用
→ 启动 TraceCollector
→ Playwright 填写 stock < 10 并提交筛选
→ 下载 low-inventory.csv
→ InventoryExportVerifier 独立读取 CSV 和 /api/state
→ VerificationResult 写入 canonical trace
→ 保存最终 manifest
→ 关闭浏览器和本地服务
```

这是 verifier/collector 的确定性 E2E 测试驱动，不是 Agent 成绩。它不调用 Qwen，也不把固定
Playwright 操作标记成 AgentLab 或 Browser Use。下一阶段将在相同 TaskSpec、fixture 和 verifier
上分别运行两种 Agent。

## 库存任务真值

任务定义：`tasks/inventory/export_low_inventory.json`

初始数据：`fixtures/inventory/inventory_v1.json`

目标是筛选 `stock < 10` 并导出 CSV，正确 SKU 为：

```text
P100, P300, P400
```

验证器不会相信页面提示或执行者的“成功”声明，而是检查：

1. `low-inventory.csv` 确实存在；
2. 文件是可解析的 UTF-8 CSV；
3. 表头严格为 `sku,name,stock`；
4. SKU 顺序和集合与版本化 fixture 完全一致；
5. 每行所有字段与 fixture 一致；
6. 每行 `stock < 10`；
7. 后端记录的筛选阈值为 10；
8. 只发生一次导出；
9. 后端导出 SKU 与 CSV 一致；
10. fixture checksum 没有变化；
11. 数据库修改次数为 0。

任一业务检查不通过时分类为 `agent` failure；无法访问本地应用分类为 `environment` failure；
任务配置、fixture 或验证器自身无效时分类为 `verifier` failure。

## Fixture 重置

`InventoryDemoServer.start()` 每次都会调用 `InventoryStore.reset()`。重置会：

- 从只读的 pristine JSON 深拷贝商品数据；
- 清空当前筛选条件；
- 清空导出次数和上次导出 SKU；
- 清零数据库修改计数；
- 恢复与 pristine fixture 相同的 checksum。

重置没有暴露为网页 HTTP 接口，避免浏览器 Agent 意外调用 reset 改写真值。Fixture 文件的版本和
SHA-256 会写入每次 run 的 manifest。

## TraceCollector 行为

Collector 初始化后立即写出一个 `status=running` 的 canonical checkpoint。之后每次增加 artifact、
step、event 或 verification 都原子替换 JSON/JSONL 检查点；正常结束时由 `finish()` 写入：

- `succeeded`、`failed`、`error` 或 `truncated`；
- reward；
- `termination_reason`；
- 实际 step 数和耗时；
- 可选 token/cost。

Collector 强制 step 从 0 连续递增，所有 Step/Event 必须引用相同 run ID，verification 必须引用
相同 task/run。文本和 JSON artifact 通过现有脱敏器保存，所有 artifact 均带 SHA-256。

## 测试 Fixture

`tests/fixtures/traces/synthetic_v1/` 是提交到仓库的 canonical golden fixture，用于验证：

- Schema 1.1.0 可加载；
- model dump/load round-trip 一致；
- artifact SHA-256 正确；
- VerificationResult 可作为 canonical trace 的第一类记录。

## 当前边界

- 库存应用当前是最小本机 HTTP 服务和内存状态，用于先证明确定性闭环；尚未扩展为计划中的
  React/FastAPI/PostgreSQL 完整运营后台。
- 目前只有库存导出一项自建任务；Phase 2 最终仍需扩展登录、订单等 8～10 个任务及故障注入。
- `TraceCollector` 已用于库存 E2E；AgentLab/Browser Use Adapter 当前仍支持运行结束后的批量转换，
  后续应让框架回调直接写入 Collector。
- Verifier 判断最终结果及失败归属，不负责定位首次关键错误；该能力属于后续 Replay + Diagnose。
