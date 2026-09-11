# 0007 — local-fs 存储格式：markdown + frontmatter，wiki 形目录树，路径即 id

local-fs 的存储模型三件套：

1. **每篇文档一个 `.md`，YAML frontmatter 承载全部元数据**：`id`（= 相对路径 = native id）、`title`、`version`（CAS 字段，skill 每次写 +1）、`hash`（正文的 sha256，skill 每次写刷新）、`created`/`updated`、`archived`。文件保持人类可直编。
2. **wiki 形目录树**：空间 = `<root>` 顶层目录，节点 = 嵌套目录，文档 = `.md`；目录遍历即导航。删除移入 `<root>/.trash/<原相对路径>`（镜像原树，恢复即路径还原）。
3. **路径即 id**：`kgent://local-fs/<相对路径>`；拒绝绝对路径与 `..` 段——URI 永不逃出 `<root>`。改名/移动 = 新 URI（与平台侧移动 wiki 节点同语义）。归档 = frontmatter `archived: true`（路径稳定；检索与 list 排除）。

undo/新鲜度语义（0005 的本地形态）：补偿前按 op 定形校验——update/archive 类要求文件在位且当前 `hash` == 台账写后 hash、`version` == 写后 version；create 类要求文件在位且 hash 匹配；delete 类要求原路径仍缺位且 `.trash` 副本或台账快照至少一项可得。任一不符即计划为「拒绝」，fail closed。hash 校验使绕过 skill 的手工编辑也能被察觉——比平台侧仅比 revision 更强。删除的补偿优先从 `.trash` 恢复，退而取台账快照。

## Considered Options

- **纯 markdown 无元数据**：被否——无 version 则无 CAS，无 hash 则 undo 新鲜度检查失效，并发/手工编辑静默丢失。
- **markdown + sidecar 元数据（`.meta.json` 或中心索引）**：被否——文件数翻倍且 sidecar 与正文易漂移；中心索引引入锁竞争与单点损坏。
- **UUID 作 id + 路径反查**：被否——grep/遍历天然产出路径而非 UUID，path-as-id 让检索结果零转换即成 URI。
- **归档走 `_archive/` 目录**：被否——路径不稳定，URI 与引用随归档失效；frontmatter 标志位保路径。
- **删除即 unlink**：被否——undo 将完全依赖台账快照且受 `retention_days` 约束；`.trash` 使恢复独立于台账留存期。

## Consequences

- 手工编辑不 bump `version`，写路径 CAS 会放行（skill 层无法察觉同刻外部修改）；hash 校验在 undo 处兜底——已知限制，记入 skill。
- 外来文件（无 frontmatter / 非 UTF-8）检索跳过、写入拒绝——skill 不碰它没创建的东西，保护用户手放文件。
- frontmatter 是元数据唯一来源：解析失败按外来文件处理，不猜测。
- `.trash` 无自动清理；台账 `retention_days`（默认 30）只约束快照可得性，已记入 skill 已知限制。
