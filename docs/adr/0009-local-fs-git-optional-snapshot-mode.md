# 0009 — git 可选：快照兜底模式（snapshot mode），模式可由 config 显式固定

local-fs 不把 git 当硬依赖（修订 0008 的 enable fail-closed）。**store 模式经 `backends.local-fs.mode` 显式可配**（`auto | git-backed | snapshot`，默认 `auto`）：

- `auto`（默认）：按环境定档——git 在 PATH 且 root 不嵌于他人仓库 → git-backed；否则 snapshot（降档不拒启）。
- `git-backed`（显式）：**要求** git 可得且 root 不嵌于他人仓库；不满足 → enable 时 fail closed（setup 命名报错、doctor error finding）——显式意图不静默降档（有意回归 0008 初稿行为，但仅限用户显式选择时）。
- `snapshot`（显式）：git 在也不 init、不使用 git——用户明确不要 git 机制。

「remote-synced git-backed」不是独立档位，而是 git-backed + `backends.local-fs.remote` 的有效状态（每次 commit 后尽力 push，0008 rev 3）；doctor 报告有效模式三值：`snapshot` / `git-backed` / `git-backed+remote`。安全规则绝对优先：`mode: git-backed` 但 root 嵌于他人仓库 → 拒绝并报错，不降档（kgent 不 commit 进用户仓库）。

两模式（三种有效状态）共用同一 skill、同一 frontmatter、同一写路径 CAS 与检索；差异只在提交与补偿机制：

- **git-backed**：0008 全量语义——store 即仓库、每写恰一 commit、undo = `git revert`、恢复窗口无限、frontmatter `version` 行兼冲突哨兵。
- **snapshot**：删除移入 `<root>/.trash/<原相对路径>`；undo = 台账快照写回（update 恢复写前快照与 version、create 移入 `.trash`、delete 从 `.trash` 恢复——退化取台账快照、archive 翻标志）；新鲜度 = 当前 frontmatter `version`/`hash` vs 台账写后值（0005 的「revision」即 version 字符串）；fail closed 不变；快照恢复窗口受 `journal.retention_days` 约束（`.trash` 不受限）。

## Considered Options

- **git 硬依赖（0008 初稿）**：被否——与「零凭据零管理 onboarding」目的相抵；git 缺失环境（无 git 的 Windows、受限容器）里 local-fs 将完全不可用，而快照兜底语义本就存在且被 wecom 验证（同一补偿家族）。
- **模式仅环境自动定档，无 config 开关（本 ADR 初稿）**：被 2026-09-11 修订推翻——模式即运维承诺（恢复窗口大小、是否上 remote），应显式可审计；`mode` 键进入 config，`auto` 仍为默认。

## Consequences

- schema 最小扩展：backend defaults 增 `mode`（默认 `"auto"`）与 `remote`（默认 `None`）两键并做枚举校验；既有后端与既有校验路径零改动。
- undo 保证分级：git-backed 无限窗口 + 结构性冲突哨兵；snapshot 受 retention 约束、仅 hash 兜底——skill 文档必须按有效模式如实陈述，不得夸大恢复能力。
- 显式 `git-backed` 在 git 缺失时 fail closed 是有意设计：配置即承诺，承诺不满足即拒绝。
- gauntlet 的 undo 腿按 config 固定模式各跑一遍（git-backed / snapshot 各一），另以 `auto` + 隐藏 git 复现降档路径。
- root 嵌于用户既有仓库时拒绝就地 git 是**安全规则**而非降级惩罚——任何模式下 kgent 的 commit 不得混入用户仓库。
