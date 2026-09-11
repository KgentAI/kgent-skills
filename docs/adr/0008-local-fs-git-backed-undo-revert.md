# 0008 — local-fs store 是 git 仓库，undo 是 revert

local-fs 的 `<root>` 是一个 git 仓库：setup 幂等 `git init` + 种子提交 + `.gitattributes`（`* -text`，git 永不改写换行，落盘统一 LF）。skill 的每次写操作（create / update / delete / archive / unarchive）= **恰好一个 commit**：只 stage 触碰的路径（外来文件永不入库），message 固定格式 `kgent(<op_id>): <op> <uri> (vN→vM)`——`git log` 即人可读的全库 op 历史。

台账零 schema 改动：`journal begin/end` 的 `--revision-before/after` 本就是后端无关字符串，local-fs 存 **git commit SHA**。ADR 0005 的新鲜度规则（当前 revision ≠ 台账写后 revision → 拒绝）对 local-fs 原生成立：**HEAD == 写后 SHA**。

undo 与三平台同形（0004/0005）：`kgent undo` 的 adapter 执行路径不适用（local-fs 无 adapter），补偿由 `local-fs-integration` skill 执行——**`git revert <写后 commit>`**。删除的补偿同样是 revert（恢复即文件回来），不再需要独立的 `.trash/` 暂存区。

新鲜度检查双层，任一不过即拒绝（fail closed）：

1. **显式**：当前 HEAD == 台账写后 SHA，且目标路径 `git status --porcelain` 干净（未提交的手工编辑即拒绝）。
2. **结构性**：revert 自身的冲突检测——任何后续 skill 写都会改动 frontmatter `version` 行，对旧写 commit 的逆向补丁必然冲突，git 拒绝合并。`version` 行由此兼任冲突哨兵。

## Considered Options

- **台账快照写回为主（WeCom 模式）**：保留为台账既有行为与跨平台机制，但不作 local-fs 补偿主路径——快照受 `retention_days` 限制，手工编辑只能靠 hash 事后察觉；git 免费给出无限恢复窗口 + 结构性冲突拦截 + 全库 op 历史。
- **`git checkout <parent> -- path` + 手工提交**：被否——新鲜度要靠 skill 自查；`git revert` 让 git 的合并机制本身就是 fail-closed 的一道闸。
- **per-space 独立仓库**：被否——跨空间操作与 setup 复杂化；单仓库 `git log` 即全库 op 历史。

## Consequences

- git 是硬依赖：缺失时 local-fs 不可启用（enable 时 fail closed）；setup/doctor 检查。
- **remote 可选，默认无**（local-fs 的目的之一即不出本机）：`backends.local-fs.remote` 未配置时仓库仅本机、永不 push。用户显式配置 remote（如自建 git 服务，私密信息获准上行的场景）后，每次 skill 执行的 commit（写与 undo revert 同）之后**尽力而为 push**：push 失败不判定写失败、不回滚、journal 照常落账——失败显式申报；非快进拒绝（他机分叉）只申报，不自动 pull/rebase/merge（多机同步语义属后续 spec）。push 复制的是全部已提交内容，配置 remote 即用户对复制范围的明示同意。
- 用户自己的 commit 会令 undo 显式检查拒绝——正确行为（不可埋掉用户的提交），记入 skill 已知限制。
- `git gc --prune=now` 类操作可毁历史、断掉 revert：skill 文档明示勿做；正常 gc 不影响可达 commit。
- 每写一 commit 是预期形态，不 squash；`.git` 随文档量增长属可接受成本。
- index.lock 竞争（并发 agent）：锁获取失败即退出并显式报错，不清理他人锁。
