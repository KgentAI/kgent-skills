# 0009 — git 可选：快照兜底模式（snapshot mode）

local-fs 不把 git 当硬依赖（修订 0008 的 enable fail-closed）。setup/enable 时按环境自动定档：

- **git-backed**（git 在 PATH，且 root 不嵌于他人仓库）：0008 全量语义——store 即仓库、每写恰一 commit、undo = `git revert`、恢复窗口无限、frontmatter `version` 行兼冲突哨兵。
- **snapshot**（git 缺失，或 root 嵌于既有仓库——为不污染用户仓库，拒绝就地 git）：删除移入 `<root>/.trash/<原相对路径>`；undo = 台账快照写回（update 恢复写前快照与 version、create 移入 `.trash`、delete 从 `.trash` 恢复——退化取台账快照、archive 翻标志）；新鲜度 = 当前 frontmatter `version`/`hash` vs 台账写后值（0005 的「revision」即 version 字符串）；fail closed 不变；快照恢复窗口受 `journal.retention_days` 约束（`.trash` 不受限）。

两模式共用同一 skill、同一 frontmatter、同一写路径 CAS 与检索；差异只在提交与补偿机制。有效模式由 doctor 报告；配置了 `remote` 但处于 snapshot 模式 → doctor finding（remote 仅 git-backed 有效）。

## Considered Options

- **git 硬依赖（0008 初稿）**：被否——与「零凭据零管理 onboarding」目的相抵；git 缺失环境（无 git 的 Windows、受限容器）里 local-fs 将完全不可用，而快照兜底语义本就存在且被 wecom 验证（同一补偿家族）。
- **用户显式选模式（config 开关）**：暂不做——环境唯一决定模式，auto 足够确定；显式开关待真实需求。

## Consequences

- undo 保证分级：git-backed 无限窗口 + 结构性冲突哨兵；snapshot 受 retention 约束、仅 hash 兜底——skill 文档必须按有效模式如实陈述，不得夸大恢复能力。
- gauntlet 的 undo 腿双模式各跑一遍：git-backed 原生；snapshot 经 PATH 屏蔽 git 复现（机制等同「git 缺失」，CI 可复制）。
- root 嵌于用户既有仓库时拒绝就地 git 是**安全规则**而非降级惩罚——kgent 的 commit 不得混入用户仓库。
