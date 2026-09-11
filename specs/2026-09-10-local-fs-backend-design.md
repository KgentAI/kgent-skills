# Design Spec: local-fs backend — 本地文件系统知识库（本地后端家族首个成员，git 使能）

- **Date:** 2026-09-10（同日 rev 2：store 改为 git 仓库，undo 改为 revert，`.trash` 废弃）
- **Status:** draft（design 已逐节过审 + git 修订；实现未开始）
- **Priority:** medium-high — eval/gauntlet 目前实写真实 Lark 租户（租户污染 + 配额 + 凭据依赖）；本地后端提供一等可弃实写目标，同时是零凭据 onboarding 路径与不出本机的隐私存储
- **ADRs:** 0006（本地后端家族 + 执行层）、0007（存储格式）、0008（git 使能 store + revert undo）
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
  文件直写 + `git`），无平台 CLI。kgent CLI 角色与三平台一致：`route --dry-run` /
  `journal begin,end` / 台账读取（ADR 0006、0008）。
- **存储**：md + YAML frontmatter；wiki 形目录树（空间=顶层目录、节点=嵌套目录、
  文档=.md）；路径即 id；归档=frontmatter 标志（ADR 0007）。
- **git 使能**：`<root>` 是 git 仓库；每次写一个 commit；undo = `git revert`；
  台账 revision 字段存 commit SHA；无 `.trash`（ADR 0008）。
- **config 零 schema 改动**：`backends.local-fs.type: skill`、
  `skill_name: local-fs-integration`、`trust_zone: internal`、`root`（可选，
  默认 `~/.kgent/local-fs/`；`KGENT_LOCAL_FS_ROOT` 覆盖一切）。

## 存储模型

`<root>` 布局：

```
<root>/                      # git 仓库（setup 幂等 init + 种子提交）
  .gitattributes             # `* -text`：git 永不改写换行
  engineering-wiki/          # 空间（顶层目录）= wiki space
    onboarding/              # 节点（嵌套目录）
      first-year-tasks.md    # 文档
    api-reference/
      auth.md
  product-wiki/
    q4-planning.md
```

每篇文档一个 `.md`，frontmatter 承载全部元数据：

```yaml
---
id: engineering-wiki/onboarding/first-year-tasks.md   # = 相对路径 = native id
title: 第一年末任务
version: 7            # skill 每次写 +1（CAS 字段；兼任 revert 冲突哨兵，ADR 0008）
hash: sha256:…        # 正文 sha256，skill 每次写刷新
created: 2026-09-10T09:30:00Z
updated: 2026-09-10T14:05:00Z
archived: false
---
<markdown 正文>
```

- URI：`kgent://local-fs/<相对路径>`；拒绝绝对路径与 `..` 段（URI 永不逃出 root）。
- 归档：`archived: true`，路径稳定；search/list 排除。
- 删除：`git rm` + commit（内容永存于历史，undo = revert；无 `.trash`）。
- 外来文件（无 frontmatter / 非 UTF-8 / 解析失败）：search 跳过、write 拒绝；
  skill 提交只 stage 触碰路径，外来文件**永不入库**。
- 编码：frontmatter 解析容忍 CRLF，落盘统一 LF，UTF-8；`.gitattributes`
  `* -text` 保证 git 侧同样不转换。

## 操作流（local-fs-integration skill 承载）

**检索**：`rg -n --glob '*.md' --glob '!/.git/**'`（缺 rg 退 `grep -rn
--include='*.md' --exclude-dir=.git`）；frontmatter 行不计入命中；结构问题
（列空间/列文档）走 `find`/`ls` 遍历；命中 → `kgent://local-fs/<relpath>` URI +
摘要；ranking：标题/路径命中 > 正文多命中 > `updated` 新者；缩量必须显式声明。

**写入**（create/update/delete/archive/unarchive 同一序列）：

```
kgent route --dry-run            # 只读裁决
kgent journal begin              # op_id(uuid) + target URI + --revision-before=<HEAD SHA> + 写前内容快照
读 frontmatter                    # version + hash
CAS：当前 version == expected_version（update/delete）否则 FAIL
写：临时文件 + mv 原子落盘（delete = git rm；archive = 标志位翻转）
frontmatter bump：version+1、hash、updated、archived
git add <仅触碰路径> && git commit -m "kgent(<op_id>): <op> <uri> (vN→vM)"
kgent journal end                # status ok/failed + --revision-after=<写后 SHA>
读回校验                          # 正文 hash 比对
```

- create：version=1 起；父目录自动创建（建节点=`mkdir -p`，建空间=顶层 `mkdir`）；
  `--wiki-space`/`--parent-node-token` → `<root>/<space>/`、`<root>/<space>/<path>/`。
- commit 恰好一个/写；index.lock 获取失败即退出并显式报错，不清理他人锁。
- 引用：原生「URL」= 绝对路径（正斜杠形式，如
  `C:/Users/…/local-fs/engineering-wiki/onboarding/auth.md`）；不向用户引用
  `kgent://` URI（与三平台同规）。

## 台账与 undo（0005 + 0008 的本地形态）

台账零 schema 改动：local-fs 的 `--revision-before/after` 存 **git commit SHA**；
0005 的「当前 revision ≠ 写后 revision → 拒绝」对 local-fs 原生成立为
**HEAD == 写后 SHA**。

undo 由 skill 执行（`kgent undo` 的 adapter 路径不适用——local-fs 无 adapter，
与三平台同形）：**`git revert <写后 commit>`**。新鲜度双层，任一不过即拒绝
（fail closed）：

| 层 | 检查 | 拦截什么 |
|---|---|---|
| 显式 | 当前 HEAD == 台账写后 SHA；目标路径 `git status --porcelain` 干净 | 后续已提交写；未提交手工编辑 |
| 结构性 | revert 冲突检测（后续写必改 frontmatter `version` 行 → 逆向补丁必冲突） | 一切绕过显式检查的已提交漂移 |

| Op | 补偿 | 恢复窗口 |
|---|---|---|
| update | `git revert` 写后 commit | 无限（commit 可达即恢复） |
| create | `git revert`（文件消失） | 同上 |
| delete | `git revert`（文件回来） | 同上 |
| archive/unarchive | `git revert`（标志位还原） | 同上 |

已知限制：用户自己的 commit 会令显式检查拒绝——正确行为；`git gc --prune=now`
可毁历史断掉 revert（skill 明示勿做）；补偿非原子（与 0005 同立场）。

## kgent CLI 侧改动（Python 足迹，刻意最小）

1. **setup**（`capabilities/detect.py` `detect_setup`）：检测序列加 local-fs 腿——
   无凭据、恒可用（`git`/`rg` 存在性一并报告）；backend 条目按现有 merge-on-rerun
   写入（0001/0003 ADR 语义不变）；`<root>` 幂等创建 + `git init` + 种子提交 +
   `.gitattributes`（已是仓库则跳过全部三步）。
2. **doctor**（`config/validate.py` `doctor`）：`backends.local-fs.enabled` 时只读
   检查——root 缺失/非目录/不可写、git 缺失、root 非 git 仓库、工作树脏（信息级）
   → finding（不自动建，创建归 setup）。

除此之外 **零 CLI 新增**：local-fs 无 adapter，`kgent search` 的 CLI fanout **不**
含 local-fs 腿（与平台检索同规——ADR 0004 后三平台检索也一律改走各自 integration
skill）；`kgent undo` 的 adapter 执行路径不适用 local-fs（补偿由 skill 执行，
ADR 0008）；`kgent route --dry-run` 对 local-fs 可用：config 声明的 `capabilities`
直达 router，无需 adapter。台账 begin/end 的 revision 字段原样承载 SHA，
**schema 与 undo 模块均不动**。

## Tier 与失败模型

**Tier: high（数据丢失面）。** local-fs 直接承载覆盖性写与删除，失败模型逐项：

| 失败 | 机制性防御 | 残余风险 |
|---|---|---|
| 覆盖他人/他进程写入 | frontmatter version CAS（skill 执行） | 同刻外部编辑且 version 未动——undo 双层新鲜度兜底，写时不可查 |
| 半截文件（崩溃/断电） | 临时文件 + `mv` 原子落盘；未 commit 的半截状态被显式检查拦截 | mv 失败 → journal end failed 显式落账 |
| undo 埋掉并发/手工编辑 | 双层新鲜度（HEAD==SHA + 干净树）+ revert 冲突哨兵 | gc prune 毁历史（skill 明示勿做） |
| git 缺失/仓库损坏 | enable 时检查（setup/doctor），fail closed | 用户运行中删 `.git`——doctor 可发现，写流程 git 失败即 journal failed |
| 并发 agent 写竞争 | index.lock 获取失败即退出，不清理他人锁 | 无（退避重试属实现细节） |
| URI 逃逸 root | id 校验拒绝绝对路径/`..` | —（负向约束，无残余） |
| 用户手放文件被破坏 | 外来文件写入拒绝 + 永不 stage | 检索仍可读（只读无害） |
| 静默启用改变既有 fanout | setup 不自动 enable；示例注释态 | — |
| 隐私外泄 | 永不配置 remote、永不 push | 用户自行加 remote 属其决定，skill 文档警示 |

## 验收标准（可执行）

**A1 config/schema（pytest）**：含 `backends.local-fs`（type: skill,
skill_name: local-fs-integration, trust_zone: internal, root:
`~/.kgent/local-fs`）的 config 经 `load_config_dict` 通过；故意把 type 写成
`local`（新类型）→ ConfigError（证明零 schema 改动的负向约束）。

**A2 setup（pytest + tmp home + tmp root）**：`detect_setup` 后 local-fs 条目存在
且 `enabled` 取用户选择；root 已创建、已是 git 仓库（`.git` 在）、
`.gitattributes` 内容为 `* -text`、存在种子提交；重跑 setup 幂等（不重复 init、
不覆盖用户已改的 `backends.local-fs`——merge-on-rerun，ADR 0001）；备份文件生成
（ADR 0002/0003 语义不回归）。

**A3 doctor（pytest + tmp home）**：root 缺失 → finding 含路径；git 不在 PATH →
finding；root 非 git 仓库 → finding；工作树脏 → 信息级 finding；`enabled: false`
→ 无 local-fs finding。doctor 保持只读（运行后 root 未被创建/初始化）。

**A4 skill 流（gauntlet flow 腿，`KGENT_LOCAL_FS_ROOT=<tmp>`）**：真实启用
backend 上的端到端——(a) create space/node/doc → frontmatter 断言（version:1、
hash==正文 sha256、LF 落盘）且 git log 恰一 commit（message 含 op_id）；(b) 检索
（rg→grep 退化链任一）命中并产出正确 `kgent://local-fs/…` URI 与绝对路径引用；
(c) update 带 `--expected-version` 正确版本 → version 递增、新 commit；带过期版本
→ 拒绝且文件未动、journal 落 failed；(d) archive 后检索不再命中，unarchive 恢复；
(e) delete → 文件消失且历史保留；undo（`git revert`）→ 文件恢复、frontmatter
version 恢复写前值；(f) update→undo 两类拒绝：undo 前手工改文件不提交（脏树）→
拒绝；undo 前经 skill 再写一笔（HEAD 前移）→ revert 冲突拒绝；(g) 全程 journal
begin/end 成对、op_id 含 uuid、revision-after 为有效 SHA。

**A5 幂等与隔离（负向）**：URI `kgent://local-fs/../etc/passwd` 与
`kgent://local-fs/C:/x.md` → 拒绝；无 frontmatter 文件植入 root → search 跳过、
write 拒绝、**git status 无该文件的任何 staged 痕迹**；`.git/` 不出现在任何检索
结果；store 仓库无 remote（`git remote` 空）。

**A6 表面**：`tools/surface-manifest.txt` 与安装后工件含 local-fs-integration；
`kgent skills list` 类检查（artifact-smoke）可见该 skill。

## Setup plan（依赖逐项论证）

| 依赖 | 论证 |
|---|---|
| git（**硬依赖**，新） | undo 主机制 + op 历史 + 删除恢复全押在 commit 可达上；enable 时检查 fail closed；评估环境（本机/CI）git 普遍存在，无替代品同时满足「结构化冲突检测 + 无限窗口」 |
| 无新 Python 依赖 | frontmatter 解析用 repo 既有 YAML 解析（`config/_yaml`）+ 标准库 hashlib/pathlib/shutil/subprocess（调 git 仅限 setup/doctor 两处） |
| `rg` 可选 | skill 说明 rg→grep 退化链；gauntlet 只断言退化链存在，不硬依赖 rg |
| pytest 套件扩展 | A1-A3 纯 Python 层进既有 tests/；A4-A6 进 `tools/gauntlet.sh`（流程一致性腿，真实启用 backend 语义） |
| agent evals（发布门，非本 spec 门） | eval config 用 `KGENT_LOCAL_FS_ROOT` 指向临时目录——实写 evals 首次可完全离真实租户（evals/README 分区规则不变） |

## Out of scope（后续 spec）

平台 publish/同步（目的 4）、local-obsidian 等家族成员、语义检索、git gc 策略与
远端（备份）同步、多机同步、frontmatter 之外的内容类型映射。
