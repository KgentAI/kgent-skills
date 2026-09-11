# 0007 — local-fs 存储格式：markdown + frontmatter，wiki 形目录树，路径即 id

local-fs 的存储模型三件套：

1. **每篇文档一个 `.md`，YAML frontmatter 承载全部元数据**：`id`（= 相对路径 = native id）、`title`、`version`（CAS 字段，skill 每次写 +1）、`hash`（正文的 sha256，skill 每次写刷新）、`created`/`updated`、`archived`。文件保持人类可直编。
2. **wiki 形目录树**：空间 = `<root>` 顶层目录，节点 = 嵌套目录，文档 = `.md`；目录遍历即导航。
3. **路径即 id**：`kgent://local-fs/<相对路径>`；拒绝绝对路径与 `..` 段——URI 永不逃出 `<root>`。改名/移动 = 新 URI（与平台侧移动 wiki 节点同语义）。归档 = frontmatter `archived: true`（路径稳定；检索与 list 排除）。

frontmatter 的 `version` 行兼任 git revert 的冲突哨兵：任何后续 skill 写都会改动该行，使对旧写 commit 的 revert 必然冲突——这是 0008 freshness 的结构性一层。

删除与 undo 属于 store 的版本化机制，按有效模式两档：**ADR 0008**（git-backed：store 是 git 仓库，undo 是 revert）与 **ADR 0009**（snapshot：git 不可用时的快照兜底，`.trash` 回归）。

## Considered Options

- **纯 markdown 无元数据**：被否——无 version 则无 CAS，无 hash 则 undo 新鲜度检查失效，并发/手工编辑静默丢失。
- **markdown + sidecar 元数据（`.meta.json` 或中心索引）**：被否——文件数翻倍且 sidecar 与正文易漂移；中心索引引入锁竞争与单点损坏。
- **UUID 作 id + 路径反查**：被否——grep/遍历天然产出路径而非 UUID，path-as-id 让检索结果零转换即成 URI。
- **归档走 `_archive/` 目录**：被否——路径不稳定，URI 与引用随归档失效；frontmatter 标志位保路径。

## Consequences

- 手工编辑不 bump `version`，写路径 CAS 会放行（skill 层无法察觉同刻外部修改）；hash 校验与 git 的 dirty-tree 检查（0008）在 undo 处兜底——已知限制，记入 skill。
- 外来文件（无 frontmatter / 非 UTF-8）检索跳过、写入拒绝——skill 不碰它没创建的东西，保护用户手放文件；skill 提交只 stage 触碰路径，外来文件永不入库。
- frontmatter 是元数据唯一来源：解析失败按外来文件处理，不猜测。
