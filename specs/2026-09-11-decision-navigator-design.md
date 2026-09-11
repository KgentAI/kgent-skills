# Design Spec: decision-navigator 决策导航 skill（编排型决策支持）

- **Date:** 2026-09-11
- **Status:** proposed（grill-with-docs 已收敛；实现与验收未开始）
- **Priority:** medium — 新能力，无事故驱动；价值主张是「把 kgent 已有的联邦检索变成可选方案的决策支持」
- **Discovered while:** 维护者提出 Decision-Guidance Agent Skill Architecture 设计稿
  （2026-09-10），经 grill-with-docs 四轮 stress-test 收敛为本 spec；统一语言落
  `CONTEXT.md`，检索层裁决落 `docs/adr/0010`，流程裁决落 `docs/adr/0011`

> **修订（2026-09-11，merge origin/main #12/#13）**：知识两车道更名
> question-answering → **query-knowledge**、knowledge-storage → **ingest-knowledge**，
> 本文与 SKILL.md/evals 相应更新；本 spec 原编号 ADR 0006/0007 与 #12/#13 落下的
> 新 ADR 撞号，改编号为 **0010/0011**（正文引用已同步）。⚠️ 上游遗留：main 的
> #12 与 #13 各自落了 0006 与 0007（`0006-query-knowledge-*` vs
> `0006-local-backend-family-*`、`0007-ingest-knowledge-*` vs
> `0007-local-fs-storage-format`），编号重复属 main 自身问题，本分支不代为重编。
>
> **修订 2（2026-09-11，实现期）**：runner 增加可选 `answers` 字段（见组件改动），
> 支持 B2/B8 澄清场景的真实多轮回放。

## 设计稿 → 本 spec 的修正（grill 记录）

原设计稿按「企业级 AI 通用件」写就，与本仓现实的差距全部在 grill 中逐条裁决：

| 原设计稿 | 本 spec | 依据 |
|---|---|---|
| 向量库 + 知识图谱 + 内部数据库连接器 | 检索级联：kgent 联邦知识库 → 能力盘点发现的内部源 → 宿主 web（机会性）；向量库否决，知识图谱**延后**（经能力盘点接入） | ADR 0010 |
| 线性四阶段（检索→分解） | 分解⇄检索收敛循环（分解先行、定点收敛） | ADR 0011 |
| 「非阻塞」澄清 | 批间合并澄清：每轮至多一批、每批 ≤5 问、每问带推荐答案；「非阻塞」重定义为「合并批、不逐问串行」 | grill R1-Q3 / R2-Q10 |
| 产出未定义 | 决策简报：聊天内唯一交付物，v1 不落盘 | grill R1-Q4 |
| 「历史案例相似检索」 | 先例 = kgent 原生 search + 「可能相关」纪律；决策日志随写回能力延后 | grill R1-Q6 |
| 「动态更新权重」 | 节点重开 + 下游传播；澄清批轮界合并 | ADR 0011 Consequences |

## 决策

**decision-navigator 是本仓第 7 个 agent skill（`skills/decision-navigator/`），
纯编排、全程只读：在用户面临决策意图时，驱动 澄清 → 分解⇄检索收敛循环 →
准则提议 → 加权排序，产出一份聊天内决策简报。平台 I/O 统一经 integration
skill（ADR 0004）；skill 自身无写路径，故不触台账 / undo / 路由裁决。**

关键裁决（grill R1–R4 全部与维护者逐条确认）：

1. **身份**：kgent skill，kebab-case 目录名，"DecisionNavigator" 仅作显示名
2. **检索**：级联 = kgent KB（经 integration skill）→ 能力盘点内部源（只读）→
   宿主 web（宿主没有就跳过）；每 run 盘点一次；简报列「已检数据源」
3. **分解⇄检索**：收敛循环——strawman 子问题图 → 按开放节点信息需求定向检索 →
   检索成果推进分解 → 直至某轮零新增/零重开/零新增引用解算；硬上限 3 轮，
   达限征询用户延长（N 用户定，默认 3）；假设级变化不计为进展（ADR 0011）
4. **解算归一**：每个开放节点恰一路由——用户（→澄清批）/ 来源（→检索）/
   假设（→标注）；只有用户路由节点可构成澄清批
5. **评价准则**：skill 提议准则集 + 权重，用户确认/修改；用户显式权重优先
6. **触发**：决策意图（必须在候选间抉择/承诺行动方向）触发本 skill；纯查询走
   query-knowledge；SKILL.md 带双向示例
7. **简报语言跟随请求**（沿 query-knowledge 语言规则）；仓内文档中文为主
8. **高风险域**（法律/财务/医疗/人身安全/人事）：不拒绝；强制注记
   「本简报是决策支持，不构成专业意见」+ 材料性主张必须引用
9. **零证据降级**：级联全空 → 不拒绝；纯假设推演，置信度钉
   「低——纯假设推演」，「先补数据」列为推荐下一步
10. **evals 分期**：结构断言（本期）→ rubric LLM-judge（后续 harness 能力）

## 操作流

```
决策意图触发
  ├─ 0. kgent config validate / setup（沿 query-knowledge §0；配置读取先征同意）
  ├─ 1. 澄清：从请求找缺口 → 澄清批（≤5 问、每问带推荐答案）
  ├─ 2. strawman 子问题图（仅凭澄清后的请求；节点 = 子问题，边 = 解算依赖）
  └─ 3. 收敛循环（≤3 轮；达限征询延长，默认再 3 轮）
       每轮：
       a. 靶向声明：本轮追逐的开放节点 + 信息需求
       b. 能力盘点（仅第 1 轮）：环境内可用 skill / MCP / 工具 → 内部数据源候选
       c. 定向检索（级联，每信息需求独立走级联）：
          kgent KB（integration skill search/read，沿用 QA 纪律）
          → 盘点发现的内部源（只读）
          → 宿主 web（有则用）
       d. 解算节点：每个 touched 节点落恰一状态
          用户已给 / 引用来源（附原生 URL）/ 假设 / 依前未解
       e. 变更报告：新增 / 重开 / 新增引用解算；三者全零 → 收敛
       f. 新增用户路由节点 → 并入本轮澄清批（至多一批），有依赖被阻则等待
  ├─ 4. 评价准则提议：准则集 + 权重 ← 已解算节点；用户确认/修改（用户权重优先）
  ├─ 5. 方案生成：2–4 个方案 + status-quo 基线（成立时）；加权评价 → 排序
  └─ 6. 决策简报（唯一交付物，聊天内，不落盘）：
       决策分解（mermaid flowchart TD 仅结构 + 编号节点表正典：状态 + 「依：#n」）
       → 评价准则与权重表（标注来源：用户给出/用户确认/提议被接受）
       → 排序方案与逐项权衡 → 先例（「可能相关」，必附引用）
       → 假设与证据缺口 → 置信度 + 「何者会改变排序」
       → 高风险域注记（如适用）→ 已检数据源（含盘点发现未用项；含收敛申报）
```

## SKILL.md 触发面（description 草案，随实现评审）

> 触发：用户必须在多个候选方案间做选择或承诺行动方向——「该选 A 还是 B」
> 「要不要迁到 X」「该裁掉哪条产品线」「帮我在这些 offer 里挑」。会在回复里给
> 出带权衡的排序建议。不触发：纯查询/找文档（query-knowledge）；写入/保存
> （ingest-knowledge）；建空间（wiki-setup）。灰色地带：决策中的事实子问题
> （「X 的续约价是多少」）按 query-knowledge 纪律检索后作为本 skill 的节点
> 解算，不整体移交。

## 组件改动

| 位置 | 内容 |
|---|---|
| `skills/decision-navigator/SKILL.md`（新） | 唯一实现物：上述操作流 + 触发面 + 检索纪律沿用（S33 缺失覆盖声明 / S55 冲突浮出 / S56 快照重叠 / N6 不可信内容 / config-consent / 语言跟随请求）+ mermaid 方言限定（裸 `flowchart TD`，节点不塞状态文本）+ 高风险域规则 + 零证据降级脚本 |
| `tools/dn_brief_check.py`（新） | 结构断言器：吃 transcript/简报 markdown，校验 B5/B6/B7（节点状态恰一、mermaid 可解析且与节点表交叉一致（边一致/无环/节点覆盖）、收敛申报在场、轮次 ≤ 上限）；非零退出即违规 |
| `tests/test_dn_brief_check.py`（新） | 断言器自身的单元测试：合规简报通过；图-表分叉、环、状态缺失、伪 mermaid、轮次超限 各负控必败 |
| `evals/skills/decision-navigator-evals.json`（新） | 只读 eval 腿：B1/B2/B8/B10/B11/B14 场景；澄清行为用 canned answers（eval 新增可选 `answers` 字段，runner `user_turns()` 读取并沿 `--continue` 节奏回放；缺省仍用固定 APPROVALS），免批路径用 `--no-followup` |
| `tools/run-agent-evals.py`（小改） | 新增 `user_turns(entry, followup)`：`answers` 字段优先，否则默认 APPROVALS——澄清类 eval 需要真实回答而非批准语 |
| `README.md` | 技能清单两处补 decision-navigator（手动 `ln -s` 示例 + 触发示例） |
| `evals/README.md` | 并行分区说明补：decision-navigator 属只读组（零台账写入，与 query-knowledge 同组可并行） |
| `tools/surface-manifest.txt` | **不改**——无新 kgent CLI 子命令 |
| `tools/install-skills.sh` | **不改**——按 `skills/*/SKILL.md` 自动发现 |

## 非目标（明确不做）

- **无写路径**：不写 KB、不建决策日志、不触台账/undo/路由裁决（写回是后续
  phase，依赖 ingest-knowledge 复用，届时单独立 spec）
- 不自建向量库/嵌入/索引；不接企业知识图谱（延后接入点 = 能力盘点，ADR 0010）
- 不接行业行情数据源（宿主 web 机会性覆盖）
- 不新增 kgent CLI 子命令、不改 MCP 面
- 不做 rubric LLM-judge（分期后续）
- 不做领域硬排除（高风险域走注记 + 引用严纪律，不拒绝）

## old-coder 充实（Tier 2：常规新功能）

**Tier 声明：Tier 2。** 全程只读编排，无数据丢失 / 认证 / 并发面（不入
Tier 3）；但产出影响真实决策，主要风险是**证据完整性**而非数据完整性。

### 失败模型

| # | 失败模式 | 抓住它的层 |
|---|---|---|
| FM1 | 引用幻觉：编造文档/URL，或引用不支持结论 | 引用只能来自本会话真实检索；eval 断言简报 URL ⊆ transcript 检索结果；高风险域材料性主张必引用 |
| FM2 | mermaid 与节点表分叉（图好看但与正典不符） | `dn_brief_check.py` 交叉校验（边一致/无环/覆盖）+ SKILL.md 方言限定 + 负控单测 |
| FM3 | 循环不收敛 / 成本失控 | 每轮靶向声明 + 变更报告；三条零收敛判据；硬上限 3 + 达限征询；eval 断言轮次与收敛申报 |
| FM4 | 触发误射（查询走决策流，或反之） | SKILL.md 双向触发/反触发示例；B1 判别 eval |
| FM5 | 权重凭空捏造（不来自用户确认） | 权重表强制 + 来源标注（用户给出/用户确认/提议被接受）；B8 场景 |
| FM6 | 零证据仍高置信 | 零证据降级路径（置信度钉「低——纯假设推演」+ 先补数据）；B10 场景 |
| FM7 | 高风险域过度自信 | 强制注记 + 材料性主张引用纪律；B11 场景 |
| FM8 | 无提示缩量（某后端超时被静默跳过） | S33 缺失覆盖声明沿用 + 已检数据源行 |
| FM9 | 越权写：盘点发现的写工具被调用 | 只读卫兵写进 SKILL.md 硬性步骤；B12 断言全部 transcript 无写调用 |
| FM10 | 配置静默读取 | config-consent guardrail 沿用（QA 同款文字） |

### 可执行验收标准

每条 = 一个具名行为；实现期 RED 阶段逐条见到失败。

- **B1 触发判别**（eval）：决策意图 prompt（「A 还是 B」）触发本 skill；
  查询 prompt（「X 的政策是什么」）不触发（走 query-knowledge）。
- **B2 澄清批纪律**（eval，canned answers）：每批 ≤5 问、每问带推荐答案；
  每轮至多一批；批内问题可追溯到用户路由节点。
- **B3 strawman 先行**（transcript 顺序断言）：子问题图初版出现在任何检索
  调用之前。
- **B4 级联顺序**（transcript 顺序断言）：同一信息需求内 KB → 盘点内部源 →
  web；web 腿缺席时简报明示（宿主无 web 能力属合法降级，不是违规）。
- **B5 节点状态完备**（`dn_brief_check.py`）：每节点恰一状态；引用来源节点
  带原生平台 URL（禁 `kgent://`）。
- **B6 图表交叉一致**（`dn_brief_check.py`）：mermaid 可解析；解析边 == 节点
  表「依：」引用；无环；节点表全覆盖 mermaid 节点。
- **B7 收敛申报**（`dn_brief_check.py`）：收敛声明在场（「第 N 轮收敛」或
  「达限 + 用户批准延长」或「达限，余下按假设」）；轮次 ≤ 上限（含批准延长）。
- **B8 权重提议-确认**（eval，canned answers）：准则 + 权重先提议后使用；
  场景中用户改权重 → 简报权重与用户改后一致。
- **B9 排序呈现**（结构 + 人工复核）：排序 + 逐方案权衡在场；与权重表一致
  性入 rubric-judge 待办（本期人工复核）。
- **B10 零证据降级**（eval）：构造级联全空场景 → 简报含「低——纯假设推演」
  置信度 + 「先补数据」推荐。
- **B11 高风险域注记**（eval）：医疗/法律场景 → 注记在场 + 材料性主张带引用。
- **B12 只读卫兵**（全部场景结构断言）：transcript 无任何写调用（无 journal
  begin、无 update/create/store、无平台写命令）。
- **B13 基线不变量**：现有套件零新增失败（baseline 已录：623 passed /
  2 failed / 4 skipped，2 failed 为 dingtalk 真机凭据门既有项，与本 spec 无关）。
- **B14 语言跟随**（eval）：英文请求 → 英文简报；中文请求 → 中文简报。

### Setup 计划

- **依赖（新增）**：无。运行前置沿 query-knowledge：`kgent` CLI 已装 +
  ≥1 backend `enabled: true`（KB 腿）；能力盘点与宿主 web 为机会性，缺席合法
  （B4 明示即可）。`dn_brief_check.py` 仅用标准库（mermaid 子集自写解析，
  不引入依赖——理由：断言器必须先于简报可信，依赖越少越不可被绕过）。
- **git**：检查点提交按 GREEN/REFACTOR 节奏；本 spec + ADR 已先期落盘。
- **真机授权**：无需写授权——eval 只读打真租户（沿用 evals README 纪律：
  跑前核 prompt 目标存在、跑后无残留清理项——只读腿无残留）。
- **gauntlet**：不新增腿（无新 CLI 面；skill 安装面由 install-skills.sh 幂等
  重跑覆盖）。本 skill 的行为门 = agent evals 只读腿（release gate，非
  per-commit）+ `dn_brief_check.py` 单测（per-commit）。

### EVIDENCE 要求（close 时）

`specs/2026-09-11-decision-navigator-design-evidence.md`：一次性 fresh eval
run（`python tools/run-agent-evals.py --execute --parallel 3`，decision-navigator
腿）；`dn_brief_check.py` 对全部 transcript 的判定记录；B1 判别通过/失败计数；
B13 基线对照；负控记录（B6 各负控目睹失败）；skip 层带理由（如宿主 web 缺席
场景）；可复现入口 = eval 命令 + 断言器调用行。根 `EVIDENCE.md` 加摘要小节。

## 测试

- **单元**（per-commit）：`dn_brief_check.py` 合规简报通过 + 五类负控
  （图表分叉 / 环 / 状态缺失 / 伪 mermaid / 轮次超限）必败
- **结构**（eval 后处理）：B3/B4/B5/B6/B7/B12 对每条 transcript 跑断言器
- **eval**（release gate，只读真租户）：B1/B2/B8/B10/B11/B14；启发式评分 +
  人工读 transcript（evals README 沿例）
- **人工复核**：B9 排序质量；高风险域措辞

## 风险与开放问题

- **排序智慧不可机检**：本期只能断言呈现完整性；行为质量依赖 rubric-judge
  分期 + 人工复核。简报的「何者会改变排序」是给人工复核者的抓手。
- **能力盘点依赖宿主自省**：不同 harness 暴露工具清单的方式不同，盘点是
  best-effort；已检数据源行让缺口可见而非静默。
- **mermaid 方言漂移**：SKILL.md 限定裸 `flowchart TD`；断言器只认子集，
  超子集按违规处理（fail closed）。
- **与 query-knowledge 的灰色复合请求**（「该续约吗？顺便查下现价」）：
  本 skill 内嵌 QA 纪律做节点解算，不整体移交；若实测触发抖动，反例入
  SKILL.md 触发面。
- **循环轮次的 token 成本**：3 轮硬上限 + 靶向声明约束单轮宽度；超预算
  场景（如超大型采购决策）依赖达限征询机制，不另设规模分档。
