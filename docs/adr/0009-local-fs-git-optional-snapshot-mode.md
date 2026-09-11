# 0009 — git 可选：快照兜底模式（snapshot mode），默认 git-backed，模式可配置

local-fs 不把 git 当硬性前置（snapshot 档位存在），但 **git-backed 是默认档**。store 模式经 `backends.local-fs.mode` 配置（`git-backed | snapshot`，默认 `git-backed`）：

- `git-backed`（默认，显式声明同义）：要求 git 可得且 root 不嵌于他人仓库；不满足 → enable 时 fail closed（setup 命名报错、doctor error finding）——配置即承诺，不静默降档。语义 = 0008 全量：store 即仓库、每写恰一 commit、undo = `git revert`、恢复窗口无限、frontmatter `version` 行兼冲突哨兵。
- `snapshot`（显式降档）：git 缺失环境的选择；git 在也不 init、不使用 git。删除移入 `<root>/.trash/<原相对路径>`；undo = 台账快照写回（update 恢复写前快照与 version、create 移入 `.trash`、delete 从 `.trash` 恢复——退化取台账快照、archive 翻标志）；新鲜度 = 当前 frontmatter `version`/`hash` vs 台账写后值（0005 的「revision」即 version 字符串）；fail closed 不变；快照窗口受 `journal.retention_days` 约束（`.trash` 不受限）。

「remote-synced git-backed」不是独立档位，而是 git-backed + `backends.local-fs.remote` 的有效状态（每次 commit 后尽力 push，0008 rev 3）；doctor 报告有效模式三值：`snapshot` / `git-backed` / `git-backed+remote`。安全规则绝对优先：root 嵌于他人仓库 → 拒绝并报错，不降档——任何模式下 kgent 不 commit 进用户仓库。

两档共用同一 skill、同一 frontmatter、同一写路径 CAS 与检索；差异只在提交与补偿机制。

## Considered Options

- **git 硬依赖且唯一模式（0008 初稿）**：被否——与「零凭据零管理 onboarding」目的相抵（无 git 环境完全不可用），且快照补偿家族现成（wecom 验证）。
- **`auto` 环境自动定档（本 ADR rev 4–5）**：被 2026-09-11 修订否——两档已足够表达，auto 使「默认承诺随环境漂移」不可审计；默认固定为强档 git-backed，降档必须显式。
- **snapshot 为默认**：被否——git-backed 是 undo 易用性（本 backend 的核心动机之一）与 op 历史审计的来源，默认档应给最强保证。

## Consequences

- schema：backend defaults `mode` 默认 `"git-backed"`、`remote` 默认 `None`；枚举校验（`git-backed | snapshot`，`auto` 等违例值 → ConfigError）；既有后端零改动。
- 无 git 机器上 local-fs **默认不可启用**（命名报错）——该环境下零 setup onboarding 需显式 `mode: snapshot`；失败响亮且可操作，不静默。
- undo 保证分级如实陈述：git-backed 无限窗口 + 结构性冲突哨兵；snapshot 受 retention 约束、仅 hash 兜底——skill 文档按有效模式陈述，不得夸大。
- gauntlet 的 undo 腿按 config 两档各跑一遍；无降档腿（`auto` 已删）。
- root 嵌于用户既有仓库 → 拒绝（安全规则），任何模式不例外。
