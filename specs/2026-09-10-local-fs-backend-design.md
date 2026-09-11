# Design Spec: local-fs backend — 本地文件系统知识库（本地后端家族首个成员）

- **Date:** 2026-09-10
- **Status:** draft（design 已逐节过审；实现未开始）
- **Priority:** medium-high — eval/gauntlet 目前实写真实 Lark 租户（租户污染 + 配额 + 凭据依赖）；本地后端提供一等可弃实写目标，同时是零凭据 onboarding 路径与不出本机的隐私存储
- **ADRs:** 0006（本地后端家族 + 执行层）、0007（存储格式）
- **语言:** CONTEXT.md 新增 本地后端 (local backend) / local-fs backend（本地文件后端）；「后端」「integration skill」条目已同步

## 背景与目标

kgent 目前仅有三个 SaaS 平台后端。新增 **local-fs**：存储在本机文件系统的知识库，
与 lark / dingtalk / wecom 并列的一等 backend（`trust_zone: internal`）。四个目的
（用户确认全选）：

1. eval/gauntlet 的安全实写目标（`KGENT_LOCAL_FS_ROOT` 指向临时目录，零租户污染）
2. 零凭据零管理的 onboarding 默认选项（setup 向导提供，不静默启用）
3. 不出本机的隐私敏感知识存储
4. 未来平台同步的本地暂存区（publish 到 lark/wecom/dingtalk 后续 spec）

## 决策摘要

- **命名与家族**：本地后端是家族（`local-` 前缀），local-fs 是首个成员；与 kgent
  hosted backend（云端托管）互斥命名（ADR 0006）。
- **执行层**：一切 local-fs search / read / write / undo 补偿经
  `local-fs-integration` skill，委派 **shell 原语**（`rg`/`grep` + `find`/`ls` +
  文件直写），无平台 CLI。kgent CLI 角色与三平台一致：`route --dry-run` /
  `journal begin,end` / `undo`（ADR 0006）。
- **存储**：md + YAML frontmatter；wiki 形目录树（空间=顶层目录、节点=嵌套目录、
  文档=.md）；路径即 id；归档=frontmatter 标志；删除=`.trash/`（ADR 0007）。
- **config 零 schema 改动**：`backends.local-fs.type: skill`、
  `skill_name: local-fs-integration`、`trust_zone: internal`、`root`（可选，
  默认 `~/.kgent/local-fs/`；`KGENT_LOCAL_FS_ROOT` 覆盖一切）。

## 存储模型

```yaml
---
id: engineering-wiki/onboarding/first-year-tasks.md   # = 相对路径 = native id
title: 第一年末任务
version: 7            # skill 每次写 +1（CAS 字段）
hash: sha256:…        # 正文 sha256，skill 每次写刷新（undo 新鲜度字段）
created: 2026-09-10T09:30:00Z
updated: 2026-09-10T14:05:00Z
archived: false
---
<markdown 正文>
```

- URI：`kgent://local-fs/<相对路径>`；拒绝绝对路径与 `..` 段（URI 永不逃出 root）。
- 归档：`archived: true`，路径稳定；search/list 排除。
- 删除：`mv` 到 `<root>/.trash/<原相对路径>`（镜像原树）；不 unlink。
- 外来文件（无 frontmatter / 非 UTF-8 / 解析失败）：search 跳过、write 拒绝。
- 编码：frontmatter 解析容忍 CRLF，落盘统一 LF，UTF-8。

## 操作流（local-fs-integration skill 承载）

**检索**：`rg -n --glob '*.md' --glob '!/.trash/**'`（缺 rg 退 `grep -rn
--include='*.md' --exclude-dir=.trash`）；frontmatter 行不计入命中；结构问题
（列空间/列文档）走 `find`/`ls` 遍历；命中 → `kgent://local-fs/<relpath>` URI +
摘要；ranking：标题/路径命中 > 正文多命中 > `updated` 新者；缩量必须显式声明。

**写入**（create/update/delete/archive/unarchive 同一序列）：

```
kgent route --dry-run            # 只读裁决
kgent journal begin              # op_id(uuid) + target URI + 写前内容快照
读 frontmatter                    # version + hash
CAS：当前 version == expected_version（update/delete）否则 FAIL
写：临时文件 + mv 原子落盘；frontmatter bump（version+1、hash、updated、archived）
kgent journal end                # status ok/failed + 写后 version + hash
读回校验                          # 正文 hash 比对
```

- create：version=1 起；父目录自动创建（建节点=`mkdir -p`，建空间=顶层 `mkdir`）；
  `--wiki-space`/`--parent-node-token` → `<root>/<space>/`、`<root>/<space>/<path>/`。
- 引用：原生「URL」= 绝对路径（正斜杠形式，如
  `C:/Users/…/local-fs/engineering-wiki/onboarding/auth.md`）；不向用户引用
  `kgent://` URI（与三平台同规）。

## 台账与 undo（0005 的本地形态）

新鲜度检查按 op 定形（「写后」= 台账记录的该 op 写后状态）：

| Op | 补偿 | 新鲜度检查（执行前） |
|---|---|---|
| update | 快照写回（写前快照 + 恢复旧 version） | 文件在位，当前 hash == 写后 hash 且 version == 写后 version |
| create | 移入 `.trash`（非 unlink） | 文件在位且 hash == 写后 hash |
| delete | `.trash/<relpath>` 恢复；退化取台账快照 | 原路径仍缺位，且 `.trash` 副本或快照至少一项可得 |
| archive/unarchive | 标志位翻转 | 文件在位且 hash == 写后 hash |

任一不符 → 补偿计划为「拒绝」，fail closed（手工编辑不改 version 但改 hash，仍被
拦截）。已知限制：补偿非原子；快照受 `journal.retention_days`（默认 30）约束；
`.trash` 无自动清理。

## kgent CLI 侧改动（Python 足迹，刻意最小）

1. **setup**（`capabilities/detect.py` `detect_setup`）：检测序列加 local-fs 腿——
   无凭据、恒可用（`rg` 存在性一并报告）；backend 条目按现有 merge-on-rerun 写入
   （0001/0003 ADR 语义不变），并幂等创建 `<root>`。
2. **doctor**（`config/validate.py` `doctor`）：`backends.local-fs.enabled` 时只读
   检查 root——缺失/非目录/不可写 → finding（不自动建，创建归 setup）。
3. **config 示例**：setup 产出与 README 的示例 config 增 local-fs 条目（注释掉或
   `enabled: false`，不静默启用）。

除此之外 **零 CLI 新增**。检索完全在 skill 层：local-fs 无 adapter，
`kgent search` 的 CLI fanout **不**含 local-fs 腿（与平台检索同规——ADR 0004 后
三平台检索也一律改走各自 integration skill）；kgent skills（question-answering /
knowledge-storage / wiki-setup）的编排里，local 腿与其他平台腿一样经 integration
skill 承担。`kgent route --dry-run` 对 local-fs 可用：config 声明的
`capabilities` 直达 router，无需 adapter。

## Tier 与失败模型

**Tier: high（数据丢失面）。** local-fs 直接承载覆盖性写与删除，失败模型逐项：

| 失败 | 机制性防御 | 残余风险 |
|---|---|---|
| 覆盖他人/他进程写入 | frontmatter version CAS（skill 执行） | 同刻外部编辑且 version 未动——hash 在 undo 兜底，写时不可查 |
| 半截文件（崩溃/断电） | 临时文件 + `mv` 原子落盘 | `.trash` 内 mv 跨目录失败（罕见）→ journal end failed 显式落账 |
| undo 埋掉并发/手工编辑 | hash+version 双重新鲜度检查，fail closed | retention 过期后无快照——`.trash` 独立于留存期兜底删除类 |
| URI 逃逸 root | id 校验拒绝绝对路径/`..` | —（负向约束，无残余） |
| 用户手放文件被破坏 | 外来文件写入拒绝 | 检索仍可读（只读无害） |
| 静默启用改变既有 fanout | setup 不自动 enable；示例注释态 | — |

## 验收标准（可执行）

**A1 config/schema（pytest）**：含 `backends.local-fs`（type: skill,
skill_name: local-fs-integration, trust_zone: internal, root:
`~/.kgent/local-fs`）的 config 经 `load_config_dict` 通过；故意把 type 写成
`local`（新类型）→ ConfigError（证明零 schema 改动的负向约束）。

**A2 setup（pytest + tmp home）**：`detect_setup` 后 local-fs 条目存在且
`enabled` 取用户选择；root 目录已创建；重跑 setup 不覆盖用户已改的
`backends.local-fs`（merge-on-rerun，ADR 0001）；备份文件生成（ADR 0002/0003
语义不回归）。

**A3 doctor（pytest + tmp home）**：root 缺失 → finding 含路径；root 存在但
只读 → finding；`enabled: false` → 无 local-fs finding。doctor 保持只读（运行后
root 未被创建）。

**A4 skill 流（gauntlet flow 腿，`KGENT_LOCAL_FS_ROOT=<tmp>`）**：真实启用
backend 上的端到端——(a) create space/node/doc → frontmatter 断言（version:1、
hash==正文 sha256、LF 落盘）；(b) 检索（rg→grep 退化链任一）命中并产出正确 `kgent://local-fs/…`
URI 与绝对路径引用；(c) update 带 `--expected-version` 正确版本 → version 递增；
带过期版本 → 拒绝且文件未动、journal 落 failed；(d) archive 后检索不再命中，
unarchive 恢复；(e) delete → 文件位于 `.trash/<relpath>`；undo → 恢复且
frontmatter version 恢复写前值；(f) update→undo：undo 前手工改文件（不 bump
version）→ 补偿计划为「拒绝」；(g) 全程 journal begin/end 成对、op_id 含 uuid。

**A5 幂等与隔离（负向）**：URI `kgent://local-fs/../etc/passwd` 与
`kgent://local-fs/C:/x.md` → 拒绝；无 frontmatter 文件植入 root → search 跳过、
write 拒绝；`.trash` 内文档任何检索路径不可见。

**A6 表面**：`tools/surface-manifest.txt` 与安装后工件含 local-fs-integration；
`kgent skills list` 类检查（artifact-smoke）可见该 skill。

## Setup plan（依赖逐项论证）

| 依赖 | 论证 |
|---|---|
| 无新 Python 依赖 | frontmatter 解析用 repo 既有 YAML 解析（`config/_yaml`）+ 标准库 hashlib/pathlib/shutil；sha256 标准库即可 |
| `rg` 可选 | skill 说明 rg→grep 退化链；gauntlet 只断言退化链存在，不硬依赖 rg |
| pytest 套件扩展 | A1-A3 纯 Python 层进既有 tests/；A4-A6 进 `tools/gauntlet.sh`（流程一致性腿，真实启用 backend 语义） |
| agent evals（发布门，非本 spec 门） | eval config 用 `KGENT_LOCAL_FS_ROOT` 指向临时目录——实写 evals 首次可完全离真实租户（evals/README 分区规则不变） |

## Out of scope（后续 spec）

平台 publish/同步（目的 4）、local-obsidian 等家族成员、语义检索、`.trash` 自动
清理、多机同步、frontmatter 之外的内容类型映射。
