# Agent Evals — 运行手册

对 headless Claude（`claude -p`）真实执行本仓 skills，验证**文档化的编排流**被
agent 遵从：route → journal begin → integration 委派写入 → journal end → 读回
校验 → 原生 URL + op_id。这是 release gate（真实写平台、非确定、花钱），不进
per-commit gauntlet。

## 标准流程（2026-09-07 codify）

```bash
# 1. dry 看计划（不写任何东西）
python tools/run-agent-evals.py

# 2. 并行真跑（按 eval 文件分组派 worker；报告自动合并）
python tools/run-agent-evals.py --execute --parallel 3 --timeout 600

# 3. 中断后续跑：直接重发同命令——transcript 已存在即跳过（resume 幂等）
python tools/run-agent-evals.py --execute --parallel 3

# 4. 单条重跑
python tools/run-agent-evals.py --execute --ids 1 --force

# 5. 抽样人工复核 transcripts 后才算 sign-off（启发式评分只是初筛）
```

### Agent（本 harness）长跑模式

后台任务有 ~10 分钟上限，长跑用脱离进程 + 轮询：

```bash
nohup python tools/run-agent-evals.py --execute --parallel 3 \
  --timeout 600 > evals/transcripts-runner.log 2>&1 &
# 轮询：tail evals/transcripts-runner.log；数 evals/transcripts/*.md
```

## 并行原则（为什么能并行、怎么切）

- **分区单位 = eval 文件**（`--parallel` 自动按文件分组）。写域不相交的概率
  最高：只读组（question-answering，零台账写入）与创建组（wiki-setup，新建
  独立页）可安全并行。
- **共享状态**：`~/.kgent/journal/journal.ndjson` 被 worker 追加共享——避免
  两个 worker 同时写**同一 target**（新鲜度检查会兜底，但别主动撞）。
- 同文件内多条 eval 撞同一 target 时（如多条 update 部门入职文档），它们留在
  同一 worker 内串行——分区单位天然保证。
- 报告按 pid 分文件（`report-<pid>.md`），跑完自动合并进 `report.md`。
- wecom 相关 eval 在 Phase 3（wecom-integration）落地前会低分——属预期而
  非回归；DingTalk eval 自 Phase 2 起按正常门槛验收。

## 已知限制

- **评分是启发式**（词面命中）：无词面证据的 prose 断言标 `manual review`，
  既不计过也不计败；sign-off 需人工读 transcript。
- **fixture 会腐烂**：指向具体文档的 eval 前提随租户漂移（2026-09-07 实测：
  "bare-metal 转 Docker" 前提在本租户不成立，agent 正确拒写）。fixture 低分
  时先核前提，再怀疑行为。
- **skill 规定写前批准**：runner 默认自动扮演批准者（proposal 后最多两轮
  `--continue` 批准回复）；`--no-followup` 只测 proposal 段。
