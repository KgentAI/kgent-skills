# Handoff Spec: Phase 2（dingtalk-integration）与 Phase 3（wecom-integration）

- **Date:** 2026-09-07
- **Status:** ready-to-implement —— 母 spec（`2026-09-05-write-path-skill-delegation-design.md`
  v3，approved）随 PR #7 合并入 main；Phase 1（lark）已 implemented 并真机验收
- **Priority:** high —— 平台一致性：三平台操作统一经 integration skill（ADR 0004）
- **Discovered while:** Phase 1 收尾后维护者要求产出 Phase 2/3 交接文档

## 交接基线（Phase 1 已落地，勿重做）

| 资产 | 位置 |
|---|---|
| 母 spec（能力契约/操作流/验收标准 B1–B12） | `specs/2026-09-05-write-path-skill-delegation-design.md` |
| 决策记录 | `docs/adr/0004`（集成 skill 中心制）、`0005`（台账驱动 undo） |
| 统一语言 | `CONTEXT.md`（integration skill / 原生 skill / 台账 / 补偿计划 / 路由裁决） |
| 台账 + undo 补偿计划 | `src/kgent/router/ledger.py`、`kgent journal begin/end`、`kgent undo` |
| 只读裁决 | `kgent route --dry-run`（zone 从 config 读，fail-closed） |
| gauntlet（绿 = 端到端） | `tools/gauntlet.sh`：artifact-smoke / 真实 config 冒烟 / 全流一致性 / 文档一致性 |
| agent evals（release gate） | `tools/run-agent-evals.py --execute --parallel 3`；运行手册 `evals/README.md` |

**新 skill 落地必做的接线**（Phase 1 的教训清单）：

1. `tests/test_docs_conformance.py` 的 `DOC_FILES` 列表**追加新 SKILL.md**——
   否则文档一致性层测不到它。
2. B9 静态检查对 `<platform>-integration` 命名自动生效，无需改。
3. 每阶段 close：`specs/` 增 phase evidence 文件 + 根 `EVIDENCE.md` addendum、
   项目记忆更新、`bash tools/install-skills.sh`（含 uv 缓存清障）。
4. 三平台 `trust_zone` 默认已 internal（T6，setup 侧）。

## Phase 2 — dingtalk-integration

### 平台事实（2026-09-05 研究，动手前建议重核 README + 代码）

| 项 | 值 |
|---|---|
| CLI | `dws`（Go 单二进制，Apache-2.0）；安装 `scripts/install.ps1` / npm 全局 / Homebrew；自带 14 个 multi skill（`dws skill setup` 装到 `~/.agents/skills/`） |
| 搜索 | doc / chat / drive / mail / aitable / `aisearch`（跨源） |
| 读取 | Markdown 默认；无损 JSONML 可得（`doc +fetch --scope/--detail`） |
| 写入 | doc create/update/**block 增删改**；wiki 节点（adoc/axls/able/appt/adraw/amind/folder）；aitable CRUD；chat 收发/recall；mail；drive |
| history/undo | `+version-save/+version-list/+version-revert`、`+checkpoint-update`、回收站；`--expected-revision` 乐观并发写 |
| 版本轴 | `revision` = 编辑号（条件写用）；`version` = 历史快照（回滚用）——补偿计划两者都要带 |
| 身份 | user：OAuth 浏览器 / `--device` 无头；**组织管理员须先开启 "CLI Access Management"**；Custom App 模式供 CI；多组织 profile（`corpId:userId`） |
| 已知坑 | `docs/command-index.md` 已过期（README 表格 + 代码为准）；回收站可作删除类补偿辅助 |

### 工作项

1. **`skills/dingtalk-integration/SKILL.md`**：按母 spec「integration skill 最小能力
   契约」六行写全。undo 补偿 = `doc +version-revert`；执行前新鲜度 = 当前
   `revision` 与台账 `revision_after` 比对（不一致即拒，可再加 `--expected-revision`
   条件写双保险）；已知限制章节收录管理员开关与 command-index 过期。
2. **DOC_FILES 追加**（见接线清单 1）。
3. **evals fixture 回装**：`knowledge-storage-evals.json` id3（现 Lark 占位 → 改回
   DingTalk 目标）、id4（恢复 Lark+DingTalk 双后端 fan-out，去掉 notes）、
   `wiki-setup-evals.json` id1/id2（恢复 DingTalk 腿，去掉 notes）。
4. **验收**：spec **B6**（真机 undo：写 A → 写 B → 计划 → `+version-revert` → 读回
   A；`expected-revision` 不符 → 拒绝）、**B8**（多行中文+emoji 完整性）、
   **B11**（dingtalk search 保真用例，fixture 沿用 `tests/test_lark_node_type.py`
   的 payload 形状）。
5. **EVIDENCE**：`specs/2026-09-07-…-phase2-evidence.md` + 根 `EVIDENCE.md`
   addendum；agent evals 跑 DingTalk 相关条目。

### 阻塞项（动手前完成）

- [ ] 组织管理员在钉钉后台开启 **CLI Access Management**
- [ ] `dws auth login`（OAuth，需浏览器）或 `--device` 无头流
- 建议分支：`feat/dingtalk-integration`（从 origin/main 切，如本 handoff 分支）

## Phase 3 — wecom-integration

### 平台事实

| 项 | 值 |
|---|---|
| CLI | `wecom-cli`（Rust 核心，npm `@wecom/cli` 分发，MIT，node≥18）；安装 `npm i -g @wecom/cli && npx skills add WeComTeam/wecom-cli -y -g`（README 标注必装，自带 14 个 `wecomcli-*` 原生 skill） |
| 搜索 | `doc search`（多类型）/ mail / WeDrive / 通讯录 |
| 写入 | doc create/import/append/overwrite/rename/permissions；sheet CSV/Excel 导入与编辑；smartsheet/smartpage；todo/calendar/meeting CRUD；消息推送；邮件收发 |
| history/undo | **无** → 补偿 = **台账快照写回**（唯一选项，ADR 0005 预留） |
| 身份 | **仅 bot**（`auth init` 交互式扫码 5min 或 `--manual`；`credentials.enc` AES-256-GCM 0600；token 只来自该文件） |
| 已知坑 | 消息只达"bot 最近对话过"的会话；速率限制未文档化（集成层自设退避）；文件 IO 有 Fs 沙箱（**当前目录内相对路径**——lark-cli `@file` 同款教训） |

### 工作项

1. **`skills/wecom-integration/SKILL.md`**：契约六行。**写流程强制先
   `kgent journal begin --snapshot-content <内容>`**——无平台 history，台账快照
   是补偿唯一依据（FM3：写回前读当前内容与快照比对，不符即拒）。已知限制
   章节收录 bot-only / 消息会话限制 / 速率自退避 / Fs 沙箱。
2. **DOC_FILES 追加**。
3. **evals fixture 回装**：同 Phase 2 对应条目。
4. **验收**：spec **B5**（真机快照写回：写 A → 写 B → 计划 → 快照写回 → 读回
   A；第三方改过 → 拒绝）、**B8**。
5. **EVIDENCE**：同 Phase 2 模式。

### 阻塞项

- [ ] `wecom-cli auth init`（**维护者本人扫码**，交互式；或 `--manual` 输 Bot ID/Secret）

## 两阶段通用约定

- 流程按 `AGENTS.md` § Spec workflow：母 spec 已 approved，无需再 grill；
  每阶段实现走 writing-plans → subagent-driven，close 必附 old-coder EVIDENCE。
- 真机探针命名带 `-probe-`，teardown 必删（删失败把 token 打进报告）；e2e 需
  凭据，CI 用 `-m "not real"` 屏蔽。
- **每阶段收尾跑一次 skill 层端到端**（agent evals `--execute --parallel 3`）——
  Phase 1 的教训：pytest 全绿 ≠ skill 层可用。
- Phase 1 遗留小债（顺手修，见 git 历史）：
  - `tools/run-agent-evals.py` 的 per-turn `TimeoutExpired` 防护（ws worker 实测
    批准轮超时裸崩，2026-09-07）
  - `platform-via-integration-evals.json` 的 `skill_name` 与文件名不一致（T10 遗留）
  - 本轮 agent evals 的 24 份 transcript 在 `evals/transcripts/`（已 gitignore）——
    是否留档由维护者定
