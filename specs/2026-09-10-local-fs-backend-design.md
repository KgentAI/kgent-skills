# Design Spec: local-fs backend — 本地文件系统知识库（本地后端家族首个成员，git 使能）

- **Date:** 2026-09-10（同日 rev 2：store 改为 git 仓库，undo 改为 revert，`.trash` 废弃；rev 3：remote 可选；rev 4：git 可选，快照兜底模式；rev 5：模式进 config；rev 6：删 `auto` 档，默认 `git-backed`）
- **Status:** draft（design 已逐节过审 + 三轮修订；实现未开始）
- **Priority:** medium-high — eval/gauntlet 目前实写真实 Lark 租户（租户污染 + 配额 + 凭据依赖）；本地后端提供一等可弃实写目标，同时是零凭据 onboarding 路径与不出本机的隐私存储
- **ADRs:** 0006（本地后端家族 + 执行层）、0007（存储格式）、0008（git-backed 模式：revert undo + 可选 remote）、0009（git 可选：snapshot 兜底模式）
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
- **git 使能且可选（store 模式）**：**模式可配**——`backends.local-fs.mode:
  git-backed | snapshot`，**默认 `git-backed`**（git 缺失或 root 嵌于他人仓库 →
  enable fail closed，命名报错——配置即承诺，无静默降档；`auto` 档已删）。显式
  `snapshot` = git 在也不用，git 缺失环境的降档选择。git-backed：每次写一个
  commit、undo = `git revert`、台账 revision 字段存 commit SHA；snapshot：删除入
  `.trash`、undo = 台账快照写回、revision 存 version 字符串。两档同一 skill /
  frontmatter / CAS，fail closed 不变；**remote 仅 git-backed 有效**，配置后尽力
  而为 push = remote-synced 有效状态（doctor 报告三值：`snapshot` / `git-backed` /
  `git-backed+remote`）（ADR 0008、0009）。
- **config 最小 schema 扩展（rev 5，rev 6 默认值定档）**：backend defaults 新增
  `mode`（**默认 `"git-backed"`**）与 `remote`（默认 `None`）两键 + 枚举校验
  （`git-backed | snapshot`）；既有后端与既有校验路径零改动。local-fs 条目：

  ```yaml
  backends:
    local-fs:
      enabled: true
      type: skill
      skill_name: local-fs-integration
      trust_zone: internal
      mode: git-backed      # git-backed | snapshot（默认 git-backed）
      remote: null          # git URL；git-backed 有效时每次 commit 后尽力 push
      root: ~/.kgent/local-fs   # 可选；KGENT_LOCAL_FS_ROOT 覆盖一切
  ```

## 存储模型

`<root>` 布局（git-backed 模式；snapshot 模式无 `.git*` 项，其余同）：

```
<root>/                      # git-backed：git 仓库（setup 幂等 init + 种子提交）
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
- 删除：git-backed = `git rm` + commit（内容永存于历史，undo = revert）；
  snapshot = `mv` 入 `<root>/.trash/<原相对路径>`（恢复窗口不受 retention 约束）。
- 外来文件（无 frontmatter / 非 UTF-8 / 解析失败）：search 跳过、write 拒绝；
  git-backed 下 skill 提交只 stage 触碰路径，外来文件**永不入库**。
- 编码：frontmatter 解析容忍 CRLF，落盘统一 LF，UTF-8；git-backed 下
  `.gitattributes` `* -text` 保证 git 侧同样不转换。

## 操作流（local-fs-integration skill 承载）

**检索**：`rg -n --glob '*.md' --glob '!/.git/**'`（缺 rg 退 `grep -rn
--include='*.md' --exclude-dir=.git`；排除项在 snapshot 模式无害）；frontmatter
行不计入命中；结构问题（列空间/列文档）走 `find`/`ls` 遍历；命中 →
`kgent://local-fs/<relpath>` URI + 摘要；ranking：标题/路径命中 > 正文多命中 >
`updated` 新者；缩量必须显式声明。

**写入**（create/update/delete/archive/unarchive 同一序列）：

```
kgent route --dry-run            # 只读裁决
kgent journal begin              # op_id(uuid) + target URI + 写前内容快照
                                 #   --revision-before=<HEAD SHA | 写前 version>
读 frontmatter                    # version + hash
CAS：当前 version == expected_version（update/delete）否则 FAIL
写：临时文件 + mv 原子落盘（delete：git-backed = git rm / snapshot = mv 入 .trash；
                                 archive = 标志位翻转）
frontmatter bump：version+1、hash、updated、archived
git-backed 才有：git add <仅触碰路径> && git commit -m "kgent(<op_id>): <op> <uri> (vN→vM)"
kgent journal end                # status ok/failed + --revision-after=<写后 SHA | 写后 version>
读回校验                          # 正文 hash 比对
push（可选，仅 git-backed）       # 仅当 backends.local-fs.remote 已配置；尽力而为：
                                 # 失败只申报，不影响 journal 结论；undo 的 revert
                                 # commit 同样走此步
```

- create：version=1 起；父目录自动创建（建节点=`mkdir -p`，建空间=顶层 `mkdir`）；
  `--wiki-space`/`--parent-node-token` → `<root>/<space>/`、`<root>/<space>/<path>/`。
- commit 恰好一个/写；index.lock 获取失败即退出并显式报错，不清理他人锁。
- 引用：原生「URL」= 绝对路径（正斜杠形式，如
  `C:/Users/…/local-fs/engineering-wiki/onboarding/auth.md`）；不向用户引用
  `kgent://` URI（与三平台同规）。

## 台账与 undo（0005 + 0008/0009 的本地形态）

台账零 schema 改动：`--revision-before/after` 是后端无关字符串——git-backed 存
**git commit SHA**，snapshot 存 **version 字符串**。0005 的「当前 revision ≠
写后 revision → 拒绝」对两模式原生成立（HEAD == 写后 SHA / 当前 version ==
写后 version）。

undo 由 skill 执行（`kgent undo` 的 adapter 路径不适用——local-fs 无 adapter，
与三平台同形）。补偿机制按有效模式：

**git-backed**：`git revert <写后 commit>`。新鲜度双层，任一不过即拒绝（fail
closed）：

| 层 | 检查 | 拦截什么 |
|---|---|---|
| 显式 | 当前 HEAD == 台账写后 SHA；目标路径 `git status --porcelain` 干净 | 后续已提交写；未提交手工编辑 |
| 结构性 | revert 冲突检测（后续写必改 frontmatter `version` 行 → 逆向补丁必冲突） | 一切绕过显式检查的已提交漂移 |

**snapshot**：新鲜度单层（fail closed）——当前 `version` == 台账写后 version
**且** 当前 `hash` == 写后 hash（手工编辑不 bump version 但必改 hash，仍被拦截）：

| Op | 补偿 | 恢复窗口 |
|---|---|---|
| update | 台账写前快照写回 + 恢复写前 version | 受 `retention_days`（默认 30）约束 |
| create | 移入 `.trash` | 无限（`.trash` 不受 retention） |
| delete | `.trash/<relpath>` 恢复；退化取台账快照 | `.trash` 无限 / 快照受 retention |
| archive/unarchive | 标志位翻转 | 随快照 |

已知限制：git-backed 下用户自己的 commit 会令显式检查拒绝——正确行为；
`git gc --prune=now` 可毁历史断掉 revert（skill 明示勿做）；snapshot 模式 skill
文档必须如实陈述较窄的恢复窗口，不得夸大；补偿均非原子（与 0005 同立场）。

## kgent CLI 侧改动（Python 足迹，刻意最小）

1. **config schema**（`config/schema.py`）：backend defaults 增 `mode`（默认
   `"git-backed"`）与 `remote`（默认 `None`）；`_validate_backend` 增 mode 枚举校验
   （`git-backed | snapshot`，`auto` 等违例值 → ConfigError）与 remote 类型校验
   （str 或 None）。既有后端与既有校验路径零改动。
2. **setup**（`capabilities/detect.py` `detect_setup`）：检测序列加 local-fs 腿——
   无凭据（`git`/`rg` 存在性一并报告）；`mode` 裁决：`git-backed`（含默认）→ git
   缺失或 root 嵌于他人仓库 → **命名报错**（enable fail closed）；`snapshot` →
   跳过一切 git 步骤。git-backed 有效时：`<root>` 幂等创建 + `git init` + 种子提交
   + `.gitattributes`（已是仓库则跳过全部三步）。backend 条目按现有 merge-on-rerun
   写入（0001/0003 ADR 语义不变）。
3. **doctor**（`config/validate.py` `doctor`）：`backends.local-fs.enabled` 时只读
   检查——root 缺失/非目录/不可写；有效模式报告（`snapshot` / `git-backed` /
   `git-backed+remote`）；git-backed 下加 root 非 git 仓库、工作树脏（信息级）；
   snapshot 下 `remote` 已配置 → finding「remote 仅 git-backed 有效」；显式
   `git-backed` 但 git 缺失/嵌套仓库 → error 级 finding（不自动建，创建归 setup）。

除此之外 **零执行面新增**：local-fs 无 adapter，`kgent search` 的 CLI fanout **不**
含 local-fs 腿（与平台检索同规——ADR 0004 后三平台检索也一律改走各自 integration
skill）；`kgent undo` 的 adapter 执行路径不适用 local-fs（补偿由 skill 执行，
ADR 0008）；`kgent route --dry-run` 对 local-fs 可用：config 声明的 `capabilities`
直达 router，无需 adapter。台账 begin/end 的 revision 字段原样承载 SHA 或
version，**journal 与 undo 模块均不动**；search/read/write 路径无任何新 CLI 面。

## Tier 与失败模型

**Tier: high（数据丢失面）。** local-fs 直接承载覆盖性写与删除，失败模型逐项：

| 失败 | 机制性防御 | 残余风险 |
|---|---|---|
| 覆盖他人/他进程写入 | frontmatter version CAS（skill 执行） | 同刻外部编辑且 version 未动——undo 新鲜度兜底（按模式：双层/单层），写时不可查 |
| 半截文件（崩溃/断电） | 临时文件 + `mv` 原子落盘；git-backed 下未 commit 的半截状态被显式检查拦截 | mv 失败 → journal end failed 显式落账 |
| undo 埋掉并发/手工编辑 | git-backed：双层新鲜度 + revert 冲突哨兵；snapshot：version+hash 单层，均 fail closed | git-backed 下 gc prune 毁历史（skill 明示勿做）；snapshot 下 retention 过期后快照不可得（`.trash` 类不受限） |
| git 缺失 / root 嵌于他人仓库 / 运行中删 `.git` | 默认与显式 `git-backed` 均 enable fail closed（命名报错，配置即承诺）；doctor 报告有效模式；降档需显式 `mode: snapshot` | git 缺失环境默认不可启用——响亮且可操作；非安全削弱 |
| 并发 agent 写竞争 | git-backed：index.lock 获取失败即退出，不清理他人锁；snapshot：version CAS | 无（退避重试属实现细节） |
| URI 逃逸 root | id 校验拒绝绝对路径/`..` | —（负向约束，无残余） |
| 用户手放文件被破坏 | 外来文件写入拒绝 + 永不 stage | 检索仍可读（只读无害） |
| 静默启用改变既有 fanout | setup 不自动 enable；示例注释态 | — |
| 隐私外泄 | remote 默认无；配置后 push 复制全部已提交内容 = 用户明示同意（skill 文档警示） | push 目标主机被攻破——超出 local-fs 威胁模型，属用户所选 git 服务的安全域 |
| push 失败/非快进 | 尽力而为：不判写失败、不回滚、journal 照常；非快进只申报 | 长期不解决的分叉会累积——申报可见，解决属多机同步 spec |

## 验收标准（可执行）

**A1 config/schema（pytest）**：含 `backends.local-fs`（type: skill,
skill_name: local-fs-integration, trust_zone: internal, mode/remote 缺省）的
config 经 `load_config_dict` 通过，且 defaults 补全 `mode: "git-backed"`、
`remote: None`；`mode: "auto"` 与 `mode: "git-synced"`（非法值）→ ConfigError；
`remote: "https://git.example.com/team/store.git"` 与 `mode: "snapshot"` /
`mode: "git-backed"` 均通过；故意把 type 写成 `local`（新类型）→ ConfigError
（type 枚举零扩动的负向约束）；既有后端条目（无 mode/remote 键）行为与本 PR 前
完全一致。

**A2 setup（pytest + tmp home + tmp root，按 mode 分变体）**：`detect_setup` 后
local-fs 条目存在且 `enabled` 取用户选择；root 已创建。变体：mode 缺省（默认
git-backed）+ git 可得 → git-backed（root 已是 git 仓库、`.gitattributes` 为
`* -text`、存在种子提交）；git 缺失（PATH 屏蔽）→ **命名报错**、不建 `.git`；
`mode: git-backed` 显式 → 与缺省同；`mode: snapshot` + git 可得 → 无 `.git`、
不调 git、不报错。重跑 setup 幂等（git-backed 不重复 init；各变体均不覆盖用户
已改的 `backends.local-fs`——merge-on-rerun，ADR 0001）；备份文件生成
（ADR 0002/0003 语义不回归）。

**A3 doctor（pytest + tmp home）**：root 缺失 → finding 含路径；doctor 输出有效
模式三值（`snapshot` / `git-backed` / `git-backed+remote`）；git-backed（含默认）
下：root 非 git 仓库 → finding、工作树脏 → 信息级、git 缺失 → error 级 finding；
snapshot 下配置了 remote → finding「remote 仅 git-backed 有效」；`enabled: false`
→ 无 local-fs finding。doctor 保持只读（运行后 root 未被创建/初始化）。

**A4 skill 流（gauntlet flow 腿，`KGENT_LOCAL_FS_ROOT=<tmp>`，按 config 固定
`mode: git-backed`（默认缺省同）与 `mode: snapshot` 各跑一遍）**：真实启用
backend 上的端到端——(a) create space/node/doc → frontmatter 断言（version:1、
hash==正文 sha256、LF 落盘）；git-backed 变体另断言 git log 恰一 commit（message
含 op_id）；(b) 检索（rg→grep 退化链任一）命中并产出正确 `kgent://local-fs/…`
URI 与绝对路径引用；(c) update 带 `--expected-version` 正确版本 → version 递增
（git-backed 另有新 commit）；带过期版本 → 拒绝且文件未动、journal 落 failed；
(d) archive 后检索不再命中，unarchive 恢复；(e) delete → 文件消失（git-backed
且历史保留）→ undo → 文件恢复（git-backed 经 `git revert`；snapshot 自
`.trash` 归位）、frontmatter version 恢复写前值；(f) update→undo 拒绝：
git-backed 两类——手工改文件不提交（脏树）→ 拒绝、经 skill 再写一笔（HEAD 前移）
→ revert 冲突拒绝；snapshot 一类——手工改文件（hash 漂移）→ 拒绝；(g) 全程
journal begin/end 成对、op_id 含 uuid、revision-after 为有效 SHA（git-backed）
或写后 version（snapshot）。

**A5 幂等与隔离（负向）**：URI `kgent://local-fs/../etc/passwd` 与
`kgent://local-fs/C:/x.md` → 拒绝；无 frontmatter 文件植入 root → search 跳过、
write 拒绝；git-backed 下 **git status 无该文件的任何 staged 痕迹**且 `.git/`
不出现在任何检索结果；git-backed 默认配置 store 无 remote（`git remote` 空）。

**A5b remote push（可选路径，pytest/gauntlet，remote fixture = 本地 bare 仓库）**：
配置 remote 后写一笔 → push 到位（bare 仓库含该 commit）；remote 不可写 → 写仍
成功、journal ok、push 失败显式申报；人为制造非快进 → 申报且不产生自动合并提交。

**A6 表面**：`tools/surface-manifest.txt` 与安装后工件含 local-fs-integration；
`kgent skills list` 类检查（artifact-smoke）可见该 skill。

## Setup plan（依赖逐项论证）

| 依赖 | 论证 |
|---|---|
| git（**默认档所需**，新） | 默认 `git-backed` 依赖它：结构化冲突检测 + 无限恢复窗口 + op 历史，无替代品兼得；git 缺失 → 命名报错（显式 `mode: snapshot` 显式降档后可无 git 运行，wecom 同款补偿家族） |
| 无新 Python 依赖 | frontmatter 解析用 repo 既有 YAML 解析（`config/_yaml`）+ 标准库 hashlib/pathlib/shutil/subprocess（调 git 仅限 setup/doctor 两处） |
| `rg` 可选 | skill 说明 rg→grep 退化链；gauntlet 只断言退化链存在，不硬依赖 rg |
| pytest 套件扩展 | A1-A3 纯 Python 层进既有 tests/；A4-A6 进 `tools/gauntlet.sh`（流程一致性腿，真实启用 backend 语义） |
| agent evals（发布门，非本 spec 门） | eval config 用 `KGENT_LOCAL_FS_ROOT` 指向临时目录——实写 evals 首次可完全离真实租户（evals/README 分区规则不变） |

## Out of scope（后续 spec）

平台 publish/同步（目的 4）、local-obsidian 等家族成员、语义检索、git gc 策略、
多机同步语义（pull/rebase/冲突解决——remote 现为纯尽力而为备份）、敏感级门控的
push（按内容级别拒绝上行的策略路由）、frontmatter 之外的内容类型映射。
