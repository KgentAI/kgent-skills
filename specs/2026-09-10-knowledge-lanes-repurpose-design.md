# 知识双车道改名与组合：query-knowledge ← question-answering、ingest-knowledge ← knowledge-storage（设计 spec）

日期：2026-09-10 · 裁决：ADR 0006、ADR 0007 · 语言：CONTEXT.md「知识依赖」

## 1. 背景

`question-answering`（读车道）的触发面只覆盖"用户提问"，而知识库的价值不止答问：起草 PRD 要先拉既往需求与决策，设计营销活动要对品牌规范和历史战役，处理客诉要对已知问题和 runbook，制作季报要对上季报告与指标口径。这些任务的共同点是**任务带知识依赖**（CONTEXT.md）——读车道应作为前置步骤被任何任务调用，而不是等用户换个方式"提问"。

`knowledge-storage`（写车道）的 update-first 偏置要求写前检索既有内容，但它在 skill 内自带一套简化检索步骤——与读车道并存两套检索纪律。写前语境收集改走读车道，检索纪律归一。

两车道同步改为裸名（目录 = skill 名）：`query-knowledge`、`ingest-knowledge`。

## 2. 裁决（grilling 2026-09-10，ADR 0006 + 0007）

| 决策点 | 裁决 | 被否方案 |
|---|---|---|
| 读车道名称 | `query-knowledge`（裸名） | `kgent:` 冒号（NTFS 目录名非法）、`kgent-` 前缀 |
| 读车道触发 | 知识依赖判据：任务需要只有本组织掌握的事实即调用；直接提问是特例 | 每个任务都 grounding；不确定时反问用户 |
| 输出 | 单一形态：grounded 答案 + 原生 URL 引用；冲突（S55）与缺口（N11）在两种触发下都强制指出 | answer + knowledge brief 双形态；brief-only |
| 写车道名称 | `ingest-knowledge`（裸名） | 保留 knowledge-storage |
| 写前发现 | update-first 内容发现改调 query-knowledge（匹配候选：URI、node_type、标题、新近度、内容类型）作为提案输入；update-first 偏置本身（N18/S61）不变 | ingest 自带检索；Python 层跨 skill 调用 |
| Python | 两模块干净改名 `question_answering.answer` → `query_knowledge.query_knowledge`、`knowledge_storage.store_workflow` → `ingest_knowledge.ingest_knowledge`，无别名 | 兼容别名；Python 不动 |

## 3. 变更面（live surfaces 全清单）

**读车道（query-knowledge）**
- `skills/question-answering/` → `skills/query-knowledge/`（git mv）
- `skills/query-knowledge/SKILL.md`：
  - frontmatter `name: query-knowledge`；`description` 改写为知识依赖触发面（保留"即使自以为知道也调用以 grounding"条款）
  - "When to Use"：知识依赖判据 + 任务语境触发示例 ≥3（PRD、营销活动、客诉、季报、业务洞察中取）+ 跳过示例 ≥3（纯代码任务、通用知识、无知识依赖的创作）
  - "Workflow" 步骤 1 从"Analyze the Question"改为"Analyze the Knowledge Need"——直接提问照旧；任务语境则从驱动任务推导检索计划（S57 复合分解的推广），驱动任务即消费方
  - 步骤 4/5（综合、引用）不变，但显式声明：任务语境下冲突与缺口必须带回给驱动任务，不得静默吸收
  - 新增小节"Called by other skills"：被 ingest-knowledge 等调用时同一流程照走，调用方消费匹配候选（URI、node_type、标题、新近度、内容类型），不要求面向用户的答案稿
  - 与 ingest-knowledge 的读写分界句同步改名
- `src/kgent/skills/question_answering.py` → `src/kgent/skills/query_knowledge.py`（git mv）；`answer()` → `query_knowledge()`；docstring 同步。`Answer`/`Claim`/`question` 字段不改名（§7）

**写车道（ingest-knowledge）**
- `skills/knowledge-storage/` → `skills/ingest-knowledge/`（git mv）
- `skills/ingest-knowledge/SKILL.md`：
  - frontmatter `name: ingest-knowledge`；触发面措辞随"摄入"更新（写意图触发不变：save/store/persist/add to wiki…）
  - 步骤 2 "Check for Existing Content" 改为**调用 query-knowledge 收集写前语境**：匹配候选契约（URI、node_type、标题、新近度、内容类型）喂给提案；skill 内自带的检索步骤文字删除，update-first bias（N18/S61）与 per-copy 选项（S62）表述保留
  - 写序列（route → journal begin → integration 委派写 → journal end → 读回）与 wiki 定位、wiki-vs-doc 询问、non-docx 记录写委派**全部不变**；读回仍走 integration skill（写验证段，非内容发现）
- `src/kgent/skills/knowledge_storage.py` → `src/kgent/skills/ingest_knowledge.py`（git mv）；`store_workflow()` → `ingest_knowledge()`；docstring 同步；内部 `_search_matches` 等 router 级原语不动（S65）

**交叉引用**
- `skills/{lark,dingtalk,wecom}-integration/SKILL.md` 第 8 行服务对象枚举：→ `query-knowledge, ingest-knowledge, wiki-setup`
- `skills/wiki-setup/SKILL.md`：不改为走 query-knowledge（ADR 0007 裁决），但若正文指称 knowledge-storage 则同步改名（实现时核对）

**测试**
- `tests/test_docs_conformance.py`：`DOC_FILES` 两个条目改名
- `tests/test_install_skills.py`：`EXPECTED_SKILLS` → `("ingest-knowledge", "query-knowledge", "wiki-setup")`
- `tests/test_skill_docs_integration_routing.py`：`SKILLS` 列表两个条目改名
- `tests/test_negative_constraints.py`：N11 import/调用改名（query 侧）；`:427` 的 store_workflow import 改名（ingest 侧）
- `tests/test_wiki_operations.py`：`question_answering.answer`、`store_workflow` import/调用改名
- `tests/test_skill_qa_wiki.py`：import/调用改名
- `tests/e2e/test_skill_happy_paths.py`：import 改名；`test_e2e_question_answering_cites_sources` → `test_e2e_query_knowledge_cites_sources`

**Evals**
- `evals/skills/question-answering-evals.json` → `evals/skills/query-knowledge-evals.json`；`skill_name` 同步；新增任务语境触发用例 ≥1、跳过用例 ≥1（跳过用例按 evals/README 标 `manual review`）
- `evals/skills/knowledge-storage-evals.json` → `evals/skills/ingest-knowledge-evals.json`；`skill_name` 同步；新增"update-first 发现走 query-knowledge 流"期望用例 ≥1
- `evals/README.md`：并行分区段两车道改名（只读组 = query-knowledge、写组 = ingest-knowledge 不变）
- 旧 `evals/transcripts/*.md` 不动（历史记录；新 id 前缀天然重跑）

**文档与安装**
- `README.md`：手动 `ln -s` 示例、自然语言调用示例（读车道加任务语境示例，如 "Draft a PRD — pull what we have on X" → `query-knowledge`；写车道 "Save this to the knowledge base" → `ingest-knowledge`）、Python API §1 §2 改名
- `docs/install/codex.md`：skill 名 grep 行改名
- `tools/install-skills.sh`：新增悬挂自有条目回收（A8）
- `CONTEXT.md`：「知识依赖」词条（已落地）
- `docs/adr/0006-*`、`docs/adr/0007-*`（已落地）

**不改（历史记录，负向约束 N-a）**：`specs/2026-08-26-*`、`specs/2026-09-*` 既有 spec、`docs/superpowers/plans/*`、`EVIDENCE.md` 既有条目、`docs/adr/0001-0005`、`evals/transcripts/*.md` 旧文件。

## 4. 可执行验收标准

**A1 — 读车道改名与自洽**
`skills/query-knowledge/SKILL.md` frontmatter `name: query-knowledge`；live 面 `grep -ri "question-answering" skills/ tools/ src/ tests/ README.md docs/install/ evals/skills/ evals/README.md` 零命中（ADR 0006/0007 引用旧名属裁决记录，豁免）。

**A2 — 读车道触发面**
"When to Use" 含知识依赖判据；任务语境触发示例 ≥3 且每条指明检索对象；跳过示例 ≥3；frontmatter description 覆盖 "any task that needs knowledge-base facts" 语义 + grounding 条款。

**A3 — 输出单一形态**
query-knowledge SKILL.md 不定义第二套输出骨架；冲突（S55）与缺口（N11）条目显式覆盖任务语境（"bring conflicts and gaps back to the driving task" 语义 ≥1 次）；"Called by other skills" 小节存在且不引入面向用户的第二形态。

**A4 — 写车道改名与组合**
`skills/ingest-knowledge/SKILL.md` frontmatter `name: ingest-knowledge`；步骤 2 为调用 query-knowledge 的委派表述（含匹配候选契约五要素），skill 内不再有自带检索步骤文字；`grep -n "update-first\|N18" skills/ingest-knowledge/SKILL.md` 仍有命中（偏置表述保留）；写序列六步（config → 提案 → route → journal → integration 写 → journal end + 读回）文字未被削弱。

**A5 — Python 改名**
`python -c "from kgent.skills.query_knowledge import query_knowledge; from kgent.skills.ingest_knowledge import ingest_knowledge"` 成功；`grep -rn "question_answering\|knowledge_storage\|store_workflow" src/` 零命中；pytest / ruff / mypy 绿。

**A6 — 测试同步**
`pytest` 全绿（量级不变，净增仅改名与 import 路径）。

**A7 — Evals fixture**
两个 fixture 的 `skill_name` 分别为 `query-knowledge` / `ingest-knowledge`；`python tools/run-agent-evals.py`（dry）列出全部新 id（前缀 `query-knowledge-` / `ingest-knowledge-`）。真实执行为 release gate，per-commit 不跑（evals/README）。

**A8 — 安装器悬挂回收**
前置：存在旧安装链接（如 `~/.agents/skills/question-answering`，指向本仓已不存在目录）。跑 `bash tools/install-skills.sh` 后：
- 悬挂自有条目被移除；`query-knowledge`、`ingest-knowledge` 链接存在且解析到 `$REPO_ROOT/skills/` 下对应目录；
- 归属三条件缺一不删：条目是 link/junction、`readlink` 目标位于 `$REPO_ROOT/skills/` 之下、目标不存在性为真。真实目录（`--copy` 遗留）与外部条目一律不动；
- 可执行验证：安装 → 手工制造悬挂条目 + 一个无关外部条目 → 重跑 → 断言删除/保留各就位。

**A9 — 车道纪律不变**
query-knowledge 文档化流程零台账写入（`kgent journal` 不出现）；ingest-knowledge 写序列的 route/journal/read-back 文字完整。evals/README 并行分区表述（只读组 vs 写组）保持成立。

**A10 — 文档一致**
README、`docs/install/codex.md`、三个 integration skill 头部枚举更新；`test_docs_conformance.py` 对两份新 SKILL.md 的 CLI 示例全解析通过（layer D，需已装 kgent + lark-cli）。

**A11 — 收尾证据**
实现完成后：`tools/gauntlet.sh` 绿；`specs/2026-09-10-knowledge-lanes-repurpose-evidence.md` 落盘（一次全新终跑、分层 gauntlet 数字、行为→测试映射、跳过层与理由、可复现入口），根 `EVIDENCE.md` 追加小节。Agent evals（含新触发/组合用例）为独立 release gate，EVIDENCE 中声明 deferred 或已跑。

## 5. 不变量与负向约束

- **N-a 历史不可变**：§3 "不改" 清单零编辑；`git diff --name-only` 不含它们。
- **N-b 单形态**：query-knowledge 不引入第二种输出模板（negative of 被否方案）。
- **N-c 车道只读/写序完整**：query 零台账写；ingest 的 route → journal → 写 → journal → 读回序列不减步。
- **N-d S/N 编号引用保真**：S55/S57/S61/S62/S67/S68/S74/N1/N4/N11/N18 等引用继续指向未改动的验收 spec，语义不漂移。
- **N-e hub 归属安全**：安装器回收仅限三条件全满足的条目；unrelated hub entry must survive re-install。
- **N-f 别名禁止**：不保留 `question_answering`/`knowledge_storage` 模块、`answer`/`store_workflow` 函数或任何转发 shim。
- **N-g 组合不越层**：Python 原语不跨 skill 调用（S65）；组合只存在于 SKILL.md agent 流程层；两条车道对 integration skill 的委派格局不变（ADR 0004）。

## 6. Tier 声明与失败模型

**Tier 1**（非数据丢失 / 非鉴权 / 非并发域）：不改写路径语义、路由裁决、台账语义；读车道行为不变（触发面与名称变化），写车道只改"谁来搜"。

失败模型：
1. **安装器回收越权**（唯一外部可见变异）：误删共享 hub 其他工具条目。缓解：N-e 三条件。恢复：重装/重链即愈（link 无独立内容）。
2. **悬挂链接窗口**：已装机器更新后未重跑安装器 → 旧名条目悬挂，agent 发现机制跳过不可解析条目（表现为"找不到 skill"）。缓解：README 说明 + A8。
3. **文档-CLI 漂移**：两份 SKILL.md 改写引入不可解析示例。缓解：layer D（A10）。
4. **组合断链**：ingest 文档若仍留自带检索措辞，agent 可能跳过 query-knowledge 直搜。缓解：A4 的 grep 断言 + agent eval 新期望用例。
5. **触发面过扩**（行为性）：无关任务频繁空搜。缓解：知识依赖判据 + 跳过示例；观测噪音 → ADR 0006 fallback。
6. **eval fixture 断供**：fixture 改名 → 旧 transcript 失配 → 全量重跑代价。预期行为（新 id 前缀）；release gate 时声明。

## 7. Non-goals

- `Answer`/`Claim`/`question` 字段不改名（产物命名 ≠ 触发命名）。
- 不新增输出形态（knowledge brief 被否，ADR 0006）。
- **wiki-setup 的碰撞检索不改走 query-knowledge**（ADR 0007：作用域窄、与建页提案紧耦合；漂移再收编）。
- Python 原语不跨 skill 调用；`ingest_knowledge()` 内部检索原语保持 router 级。
- 不动三个 integration skill 与 wiki-setup 的行为语义（指称改名除外）。
- 不在本变更内跑真实 agent evals（release gate 单独排程）。
- 不清洗 `~/.agents/skills` 下无法安全归属的遗留真实目录。

## 8. Setup Plan（依赖逐项论证）

| 依赖 | 用途 | 论证 |
|---|---|---|
| `git mv` ×4 | 目录/模块改名保历史 | 无新依赖；链接以目录名为 key，改名必须原子 |
| pytest / ruff / mypy（既有 dev 工具链） | A5/A6 验收 | 既有；无新增 |
| 已安装 `kgent` + `lark-cli` | A10 layer D | 既有 gauntlet 前提；缺失时 `test_docs_conformance` 自带 skipif，按 EVIDENCE 声明 |
| `tools/install-skills.sh` 内嵌 python（stdlib：os/stat/shutil/_winapi） | A8 回收逻辑 | 脚本既有模式（remove_entry/link_entry 同款）；不引入第三方依赖 |
| `tools/run-agent-evals.py`（dry 模式） | A7 fixture 自检 | 既有；dry 不写平台不花钱 |
| `tools/gauntlet.sh` | A11 终验 | 既有 per-commit 门；无新增层 |
