# Handoff Spec: `kgent setup` 整体覆写 config.yaml，静默丢失用户手改

- **Date:** 2026-09-02
- **Status:** open / not started
- **Priority:** high — 数据丢失类缺陷，且随着 `kgent config set-workspace-domain`
  落地（用户 config 里开始有更多手写内容）爆炸半径变大
- **Discovered while:** 为 set-workspace-domain 设计写入策略时审读 `detect.py`

## 问题陈述

`kgent setup`（`src/kgent/capabilities/detect.py`）在 `kgent config.yaml`
**已存在**时，仍以 `O_TRUNC` 整体重写该文件（`_write_config`，
`detect.py:317-327`），内容仅由本次 discovery report 生成。后果：

- 用户手动启用的后端（`enabled: true`）被静默重置为 `enabled: false`；
- 用户手写的 `defaults:`（含 `workspace_domain`、timeouts、sensitivity floors、
  `content_type_mapping` 等一切 discovery 不生成的键）全部丢失；
- 无备份、无提示、退出码 0 —— 用户通常在“搜索怎么又空了”时才会发现。

本机即真实案例：config 由 2026-08-31 的 setup 生成（见
`~/.kgent/capabilities.cache.yaml` 的 `detected_at`），2026-09-02 手动改为
`enabled: true` 才能搜索；此时重跑 setup 即会回滚该修改。

## 根因

`detect.py:324` `os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)`
—— 写入前不读现有文件，`_emit_config(report)` 也不接受现有内容作为输入。
模块 docstring 只声明“生成 config + cache”，未定义**重跑语义**（首次 vs 再次）。

## 建议方案（三选一，或组合）

| 方案 | 行为 | 取舍 |
|---|---|---|
| **A. 合并（推荐）** | setup 前解析现有 config；后端条目按“已有则保留用户的 enabled/扩展键，仅补缺失的 backend/键；新发现的 backend 以 `enabled: false` 追加”。`defaults:` 等非 backend 段原样保留 | 最符合用户预期；需要定义键级合并规则（浅合并 backend 顶层键即可，不深合并） |
| B. 拒绝 + 生成伴生文件 | 已有 config 时默认不改，写 `config.generated.yaml` 并提示 diff；`--force` 才允许覆写 | 实现最简单，但“setup 可重复执行”的体验差 |
| C. 备份后覆写 | 覆写前复制为 `config.yaml.bak-<ts>` 并打印警告 | 最差选择：用户仍会静默丢配置，只是可手工找回；仅当作为 A/B 的附加保险时采用 |

推荐 **A + C**：合并为主，写入前仍留一份时间戳备份（迁移类操作的对冲习惯，
成本一行）。`kgent doctor` 可顺带增加 finding：检测到 `config.yaml.bak-*`
时提示存在历史覆写痕迹（仅提示，不强求）。

## 验收标准

- [ ] 空目录跑 `setup` → 生成完整 config（现状行为，回归）。
- [ ] config 存在且含 `enabled: true` + 自定义 `defaults.workspace_domain`
      → 重跑 `setup` 后两者原样保留；新发现的 backend 以 `enabled: false` 追加。
- [ ] 现有 config 语法损坏 → setup 不覆写，报错并指引（绝不在解析失败时 TRUNC）。
- [ ] 覆写/合并写盘前生成 `config.yaml.bak-<ts>`。
- [ ] 单测覆盖上述四条（tmp_path fixture，不依赖真实环境探测 —— 用注入的
      discovery report 测 `_write_config`/合并层）。

## 范围外

- `kgent config migrate` 的迁移语义（只处理 version 升级，不碰本问题）。
- discovery 探测本身的只读约束（§2.2/S42/N12）不变 —— 本 spec 只改
  **写盘策略**，不新增任何探测。
