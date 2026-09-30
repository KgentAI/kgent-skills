# 0017 — confluence 传输收敛为 Atlassian MCP 唯一传输（替代 0015 阶梯）

ADR 0015 的「acli 主 / MCP 兜底」阶梯在 2026-09-25 的首次真机实测中被证伪，用户裁决收敛为
**Atlassian Remote MCP 唯一传输**（单认证 = 宿主 OAuth，不持有 CLI 令牌）。实测证据：

- 官方 `acli` 1.3.39（当时最新）的 Confluence 面只有 `page view` + space 族——**无搜索、
  无页面写**（`confluence page` 仅 `view`；博客组反而有 `create`）。阶梯的「acli 主传输」
  对 search/write 两车道根本不成立；Atlassian 文档所述的写能力领先于实际发布的二进制。
- 阶梯的「MCP 兜底」腿实测完整覆盖全部车道：CQL 搜索（`searchConfluence`）、页面读
  （`getConfluenceContent`，带 `version.number` 与 snapshotToken）、页面写
  （`createConfluenceContent` / `updateConfluenceContent`）、版本历史族
  （`listConfluenceContentVersions` / `getConfluenceContentVersion` /
  `restoreConfluenceContentVersion`——undo 的 version-revert 补偿可全机械化）、页面级
  archive/unarchive（**修订 spec 2026-09-22 的「无页面级 archive」结论**——那是 acli
  时代的观察；MCP 目录含 `archiveConfluenceContent`/`unarchiveConfluenceContent`）。
- acli 车道不只是窄，而且是死车道：`kgent undo` 的新鲜度检查走 acli adapter 直接报
  `unknown command`，fail-closed 拒绝产计划——留在注册表里只会产生假阴性行。
- 真机 e2e（KKB 空间，2026-09-25）经 MCP 全绿：搜索/读/格式桥/journal 守护的
  create→update(v1→v2，op_id 进 Atlassian 版本历史)/undo 计划/清理。

唯一传输意味着：无阶梯、无逐环境降级裁决——`kgent setup`/`doctor` 探测**宿主是否连接
Atlassian MCP**（`mcpServers` 含 atlassian），Gate 每次运行复核；未连接 → 优雅禁用。

## Considered Options

- **保留阶梯（acli 读 + MCP 写）**：被否——acli 的读车道与 MCP 读车道能力重叠且更窄
  （无 `--include-version` 之外的元数据），双车道双认证违背用户「只认证一种方式」的裁决；
  acli adapter 车道的 undo 新鲜度检查实测死亡。
- **社区 atlassian-cli（omar16100，Rust）补搜索/写**：被否——无 Windows 发布产物
  （v0.9.2 仅 darwin/linux），WSL 包装给每次调用加平台壳；第三方依赖换来的能力 MCP 原生就有。
- **curl 直打 Cloud REST v2**：被否——需要 kgent 侧持有 API token（违背单认证），
  且把平台 HTTP 面引入 skill 层，绕开传输抽象。

## Consequences

- `ConfluenceAdapter` 与其 acli argv/payload 锚点、wire fake、adapter 测试**整体删除**；
  confluence 成为首个 **adapter-less 平台后端**（config-only route 参与，同 local-fs 形状），
  一切 I/O 经 `confluence-integration` skill 直调 MCP 工具（ADR 0004 同规）。
- `kgent wiki` CLI 车道不覆盖 confluence（无 adapter wiki 块）；知识空间操作经 MCP
  （`listConfluenceSpaces` 等）由 skill 承载。
- **页面删除（进回收站）MCP 目录暂缺**：删除车道 v1.1 = 不支持，skill 提供 archive
  （可逆）或显式申报人工删除；purge 永不执行。create 的 undo 补偿相应降级为
  archive（可逆）+ 人工删除提示，known limitations 如实陈述。
- 凭据面 = 宿主 OAuth 一处；`kgent` 不接触任何 token。
- acli 二进制本身与 `tools/confluence-probe.sh`（acli 探针）退役；探针使命已由
  2026-09-25 真机实测完成并留证。
