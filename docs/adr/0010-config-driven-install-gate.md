# 0010 — 安装门：平台 integration skill 按 config 门控安装，sync 双向收敛

平台 integration skill 不再无条件安装。安装器以 `~/.kgent/config.yaml` 的 `backends.<platform>.enabled` 为唯一门信号：门开 ⇒ 安装对应 `<platform>-integration`，门关 ⇒ 不装；skill 同步（`tools/install-skills.sh --sync`）按同一门双向收敛——门关而已装的，从选定安装目标移除（`--keep` 豁免）。本地后端与知识车道 skill（query-knowledge / ingest-knowledge / wiki-setup）不设门，始终安装。

门读 config，不探测原生 skill 是否在盘。config 是平台操作的路由先决条件（无 enabled backend 则平台操作本就不可路由），且 schema 默认 `enabled: false`——门信号与运行期可用性天然一致，fail-closed（无 config / 无该键 ⇒ 视为门关）语义同源。安装器对 config 只读不改写：config 是 enablement 的唯一真源，安装期（本 ADR）与运行期（各 integration skill 的 Gate 章节）各消费一次；写 config 是 `kgent setup` 与用户的事。越门仅 `--force` 旗标级例外（dev / 冒烟确定性），打印警告。

发现回路靠三条腿把「门开而 skill 未装」暴露给用户：doctor finding（诊断面）、`kgent setup` 尾注、车道 skill degrade 条款一行。安装目标（agent skill 目录）默认全部检测到的；hub 恒装（镜像 hop 指向 hub 条目，不可豁免），镜像 hop 可用 `--agents` 选子集，选择持久化于 `~/.kgent/` 并每次运行打印。

## Considered Options

- **presence 检测（探测原生 skill 家族在盘）**：被否——安装器需内嵌各家族 required set 或脆弱前缀匹配，false positive（只装了 lark-okr 也算装了 lark）与双重信号漂移必居其一；config 已是路由先决条件，presence 是第二个必然漂移的信号。
- **安装器改写 `backends.*.enabled`（unify）**：被否——enablement 是用户/domain 决策，安装器是机制；机制写策略必然越权，且把 config 与 skill 目录耦合出漂移面。
- **runtime lazy install（任务中自动安装）**：被否——任务中装 skill permission-heavy 且不可审计；三条腿发现回路足够。
- **纯全局门，无 per-target 选择**：被否——config 全局而 skill 目录按 agent 分立；实况是机器 config 全开 ⇒ 无原生 skill 的 agent 目录（如本机 CodeBuddy）照收全部 integration skill，纯导航噪声。`--agents` 与门正交：管 where，不管 whether。

## Consequences

- fresh 机器（无 config / 无 platform 键）⇒ 只装车道 + local-fs-integration，打印提示；与 schema 默认（`enabled: false`）fail-closed 一致。
- 门读取链：`kgent config show-effective --json` 优先（PATH 已装的 CLI，既有脚本面），退化为 pinned grep（config 由 setup merge 写出、形状稳定）；两腿皆不可得 ⇒ 全部门关。`--no-cli` 机器走 grep 腿。
- doctor 新增 finding：enabled 平台 backend 的 `<platform>-integration` 未见于任何已知 agent skill 目录 ⇒ finding（doctor exit 1）；probe 失败按 fail-closed 报 finding。local-fs 豁免。
- 普通安装只装不删：门关不装、已装不动；移除仅发生于显式 `--sync`（打印每一笔）。
- 安装器测试契约（S1–S8）扩展：门开/关/无 config、sync 收敛、`--force`/`--keep`/`--agents` 持久化；六 agent 安装指南同步更新。
- 代价如实：某 agent 目录缺某平台原生 skill 而 config 开着该平台时，该 agent 仍会收到 integration skill（门不感知 per-agent 能力）——这是选择 config 驱动的已知代价，由 `--agents` 兜底而非门本身。
