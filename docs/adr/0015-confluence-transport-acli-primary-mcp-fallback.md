# 0015 — confluence 传输：官方 acli 为主，Atlassian MCP 按环境兜底

本组织在 Confluence 集成立项时没有任何 Confluence CLI（与 lark-cli / dws / wecom-cli 的既有格局不同），可用传输有二：Atlassian 官方 CLI（`acli`，2025-05 发布，email + API token 认证，Windows/macOS/Linux）与 Atlassian 官方 Remote MCP Server（`mcp.atlassian.com`，OAuth 2.1，含 Confluence 站点搜索与页面读写工具）。决定采用**传输阶梯（transport ladder）**：`acli` 为主传输；`acli` 不可用且环境可检测到 Atlassian MCP 时降级 MCP 工具；两者皆不可得 → 优雅禁用（Gate 显式申报，不静默）。阶梯在 `kgent setup` 阶段探测并报告有效传输，`confluence-integration` skill 的 Gate 每次运行复核；同一环境内不逐调用切换。

acli 为主的原因：kgent 平台后端的全部测试与一致性基建都是 CLI 形状（subprocess wire fake、skill CLI 示例的 docs-conformance 校验、artifact smoke），API token 认证与其余三平台同构，且不依赖宿主 MCP 客户端准入。MCP 兜底保留的原因：零安装、官方维护，acli 缺失环境不应因此整体不可用；其代价（宿主须为 Atlassian 准入的 MCP 客户端、gauntlet 无法密闭测试 MCP 调用）由已知限制如实陈述。

## Considered Options

- **MCP 唯一传输**：被否——自定义 OAuth 客户端注册不被允许（仅 Atlassian 准入客户端可连），产品化受限；密闭测试面坍缩为 prose-pin + agent evals。
- **acli 硬性唯一传输**：被否——安装摩擦直接变为可用性门槛，与「MCP 可得即用」的裁决相抵。
- **逐调用运行时切换**：被否——同一操作中途换传输使审计与测试矩阵不可确定；阶梯按环境一次性裁决。

## Consequences

- confluence 不新增 transport 类 config 键：有效传输是环境事实，由 setup/doctor 探测报告（`acli` / `mcp` / `unavailable` 三值），skill Gate 运行时复核。
- adapter 仅走 acli 路径；MCP 路径只存在于 skill 层，密闭测试只覆盖 acli 腿与格式桥，MCP 腿的纪律靠 docs-pin + agent evals（发布门）。
- acli 的 Confluence 面宽度（CQL 搜索 / 页面 CRUD / 版本 / JSON 输出 / 回收站恢复）未经本机实证——实现前置一道 gated 探针（spec A1），未过探针不得宣称 e2e 可用。
- 未装 acli 且无 MCP 的环境：backend 可配置 enabled 但 skill 优雅禁用；doctor 报 `unavailable`，不报 error（配置存在 ≠ 承诺可用，与 local-fs 的 fail-closed 定档语义不同，后者是本地状态承诺）。
