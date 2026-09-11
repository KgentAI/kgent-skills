# 0006 — 本地后端家族，local-fs 执行经 integration skill + shell 原语

本地后端（local backend）是一个家族：存储在本机的后端，成员以 `local-` 前缀命名（首个成员 **local-fs**：纯文件系统知识库；为未来的 local-obsidian 等留位）。家族成员与 lark / dingtalk / wecom 平台后端并列，是 config/router 层的一等 backend（`trust_zone: internal`）。

local-fs 的一切 search / read / write / undo 补偿执行，统一经 `local-fs-integration` skill（0004 的 `<backend>-integration` 形态不变），但委派对象不是平台 CLI——本地没有平台 CLI——而是 **shell 原语**：检索用 `rg`/`grep` + 目录遍历（`find`/`ls`），内容用文件直写。kgent CLI 只保留与三平台相同的角色：`route --dry-run`（只读裁决）、`journal begin/end`（台账）、`undo`（补偿计划）；台账与补偿纪律（0005）原样继承。

config 复用现有 schema，零改动：`backends.local-fs.type: skill`、`skill_name: local-fs-integration`、`trust_zone: internal`。

## Considered Options

- **kgent CLI 内建 LocalFsAdapter（执行收编进 Python）**：被否——三平台的 route/journal/undo 纪律都在 skill 层、由 eval 强制（0004 Consequences），本地若走 CLI 内建会分裂执行形态，且 grep 式检索的 agent 原生灵活性（模糊、上下文、跨文件联想）会退化为固定 ranking。
- **与 kgent hosted backend 合并（本地盘即 hosted backend 的首个实现）**：被否——hosted 是云端托管，trust/部署故事不同；合并会把两个未来耦合在一起。本地家族与 hosted 并列互斥命名（见 CONTEXT.md）。

## Consequences

- 执行纪律是 skill 层约定（route-first、journal begin/end、CAS 校验），由 eval 强制而非 kgent 结构强制——与三平台同一信任级别。
- shell 原语跨平台差异（Windows Git Bash 的 `rg` 可用性、引号、CRLF）进 local-fs-integration 已知限制；写入一律临时文件 + `mv` 保证原子，frontmatter 解析容忍 CRLF、落盘统一 LF。
- 检索 ranking 在 agent 侧，跨 agent 非确定——接受；`kgent search` fanout 的 local 贡献同样经 skill 说明产出。
- eval/gauntlet 获得无租户污染的实写目标：`KGENT_LOCAL_FS_ROOT` 指向临时目录即整体可弃。
