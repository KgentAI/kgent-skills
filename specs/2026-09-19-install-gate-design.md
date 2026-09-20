# 安装门：平台 integration skill 按 config 门控安装 — design + acceptance

- 版本：v1.1（2026-09-20 — B3 值域修订：`--agents` 值域 = 镜像注册表，hub-native agent 为非法值；v1.0 2026-09-19）
- 决策依据：`docs/adr/0010-config-driven-install-gate.md`； Ubiquitous language：`CONTEXT.md` **安装门 (install gate)**、**skill 同步 (skill sync)**
- 状态：已批准（2026-09-20，含 v1.1 修订）

## 1. 背景与目标

`tools/install-skills.sh` 现在无条件把全部 `skills/*/` 装进 hub 与全部镜像目录。后果：未启用某平台的机器（如实例机 `~/.codebuddy/skills` 只有三个平台 integration skill、零原生 skill）的 agent skill 列表被永远用不上的 integration skill 占据——导航开销 + 误触发面。目标：integration skill 的安装由安装门（`backends.<platform>.enabled`）决定，`--sync` 双向收敛，发现回路三条腿（doctor finding / setup 尾注 / 车道 prose）。

## 2. 行为规格

### B1 门信号与映射（约定）
平台 integration skill 目录名匹配 `^(lark|dingtalk|wecom)-integration$`，按约定映射门键 `backends.<backend>.enabled`。`local-fs-integration` 与三条车道（query-knowledge / ingest-knowledge / wiki-setup）不匹配该模式 ⇒ 恒装。映射不得用第二来源（无 per-skill frontmatter、无安装器内清单）。

### B2 门读取链（fail-closed）
按序：
1. PATH 上有 `kgent` ⇒ `kgent config show-effective --json`，取 `.backends.<backend>.enabled`（JSON 布尔）。
2. 否则 grep 腿：读 `~/.kgent/config.yaml`，定位 `^  <backend>:` 两空格块，块内取 `^    enabled: <value>`；**仅字面 `true` 为开**；缺块/缺键/其他值/文件不存在 ⇒ 关。
3. 两腿皆不可得（无 CLI 且无 config 文件）⇒ 全部门关 + 恰一行提示（含 `kgent setup` 与 `--sync` 字样）。
`KGENT_HOME` 非空时 config 路径随其走（与 CLI 一致）。安装器全程不改写 config。

### B3 安装目标与 --agents（v1.1 修订）
目标集 = hub（恒装；镜像 hop 指向 hub 条目，hub 不可豁免）+ 各检测到的镜像 hop（目录存在性检测）。镜像 hop 来自脚本顶部的**镜像注册表**（数据表 `名字 → 自有 skill 目录`），当前成员 `claude → ~/.claude/skills`、`codebuddy → ~/.codebuddy/skills`；今后任何「自有目录型」标准兼容 agent 增一行注册表即入值域，不改逻辑。`--agents <name[,name...]>` 选 hop 子集：注册表未知名 ⇒ exit 2（同 unknown flag）；**hub-native 标准兼容 agent**（codex / opencode / openclaw / pi —— 原生扫描 `~/.agents/skills`）不是合法值 ⇒ exit 2，stderr 解释「hub 恒装、逐 agent 不可豁免」（agentskills 标准只定义 SKILL.md 格式，不定义发现目录；判型规则见根 EVIDENCE.md）。选择持久化到 `~/.kgent/skills-targets.txt`（内容 = 逗号分隔 hop 名或 `all`）；文件不存在 ⇒ 默认 all detected；`--agents all` 重置；文件内容非法 ⇒ 警告一行并按 all 处理（不 crash）。每次运行向 stdout 打印 active targets 一行。

### B4 --sync（双向收敛）
正常安装流程完成后：对选定 targets 中门关的平台 integration skill 执行移除——link 模式删 hub 条目及指向它的 hop，--copy 模式删副本；随后跑既有 `sweep_dangling_self`。每笔打印 `removed <skill> from <dir>`。`--keep` 抑制移除（门关的已装 skill 原样保留）。普通安装（无 --sync）只装不删：门关 ⇒ 跳过；已装 ⇒ 不动。

### B5 --force
全部门视为开 + 恰一行警告（列出被 force 的 skill 名单）。与 --sync 组合时 sync 的移除腿跳过（force 语义 = 只开不关）。

### B6 doctor finding
`src/kgent/config/validate.py`：对每个 enabled 的平台 backend（config ∩ adapter registry，即 lark/dingtalk/wecom），探测 `SKILL_DIRS` 中任一目录含 `<backend>-integration/SKILL.md`；皆无 ⇒ finding（文案含 backend 名与 `tools/install-skills.sh --sync` 指引）。`SKILL_DIRS = [~/.agents/skills, ~/.claude/skills, ~/.codebuddy/skills]` 常量落 `src/kgent/capabilities/detect.py`（skill 感知模块）并由 validate 复用。probe 抛错（目录不可读等）⇒ 报 finding（fail closed，不吞异常返回健康）。local-fs 不在探测范围。

### B7 setup 尾注
`kgent setup` 输出末尾恒追加一行 hint（含 `--sync` 字样），无论是否发现 backend（无状态、无分支）。

### B8 车道 prose
query-knowledge / ingest-knowledge / wiki-setup 三个 SKILL.md 的 degrade 条款各加一句：目标 backend 门开而对应 integration skill 未安装 ⇒ 跑 `kgent doctor` 确认，按 finding 指引 `tools/install-skills.sh --sync`。

### B9 文档
`docs/install/README.md` 表格与六个 agent guide 增「安装门」一节：门信号、fail-closed 缺省、`--sync/--keep/--force/--agents`、doctor finding；判型规则（hub-native vs mirror）与镜像注册表扩展方式（新自有目录 agent = 一行注册表）。

## 3. 验收场景（可执行）

Installer 场景跑在既有 hermetic sandbox（`tests/test_install_skills.py` 的隔离 `$HOME` seam）内：

- **I1 无 config ⇒ fail closed**：沙箱无 `~/.kgent/config.yaml`，`--no-cli` 安装 ⇒ hub 含 4 个恒装 skill（三车道 + local-fs-integration），不含三个平台 integration；stdout 恰一行提示含 `kgent setup` 与 `--sync`；exit 0。
- **I2 单平台门开**：config 仅 `backends.lark.enabled: true` ⇒ hub 额外含 lark-integration，不含 dingtalk/wecom；verify()（S7）按受门控的期望集通过；exit 0。
- **I3 门全关**：config 三平台皆 `enabled: false` ⇒ 同 I1 集合，无提示行（门可读、非缺失），exit 0。
- **I4 键残缺**：config 只有 lark 块无 enabled 键 ⇒ lark 视为关；其余视为关 ⇒ 同 I1 集合。
- **I5 门关 + 已装 + 普通安装** ⇒ 已装 skill 原样保留（不删不重装报错），exit 0。
- **I6 门关 + 已装 + --sync** ⇒ hub 条目移除、指向它的 claude/codebuddy hop 一并移除（无 dangling）；每笔打印 `removed …`；车道与 local-fs-integration 不被移除；exit 0。
- **I7 I6 + --keep** ⇒ 全部保留，无 removed 行。
- **I8 门开 + --sync** ⇒ 幂等（已装 ⇒ 无 removed、无重复链接），exit 0。
- **I9 --force + 无 config** ⇒ 三个平台 integration 全装 + 恰一行警告列出名单；exit 0。
- **I10 --agents codebuddy + 门全开** ⇒ hub + codebuddy hop 装 lark-integration；claude hop 不新增；`~/.kgent/skills-targets.txt` 内容 = `codebuddy`；stdout 打印 active targets；exit 0。
- **I11 I10 之后裸 --sync** ⇒ 沿用持久化 targets（codebuddy 更新、claude 仍不动）。
- **I12 --agents all** ⇒ targets 重置 all detected，持久化文件内容 = `all`。
- **I13 --agents 非法值**：未知名（`--agents nosuch`）⇒ exit 2，stderr 含该名；hub-native 名（`--agents codex`）⇒ exit 2，stderr 解释 hub 恒装。
- **I14 grep 腿契约（checker 负例）**：无 `kgent` CLI；config 为手写形状（含注释行、`# enabled: true` 陷阱行、`    enabled: true` 出现在 lark 块而 wecom 块无）⇒ lark 开、wecom 关；config 为不可解析形状（backend 块缩进异常）⇒ 该平台按关 + 一行警告，不 crash、不误开。
- **I15 prune 白名单**：`--sync` 且门全关 ⇒ 被移除名单恰为三个平台 integration；车道/local-fs-integration 的条目数前后不变。
- **I16 --uninstall 不变** ⇒ 全量拆除（含恒装 skill），既有断言原样通过。
- **I17 回归**：无 `~/.codebuddy` 目录的沙箱 ⇒ 安装照常（现有行为）；config mtime/内容在所有场景前后不变（只读承诺）。

Doctor 场景（pytest，`validate.py` 单元层）：

- **D1** lark enabled + lark-integration 在任一 SKILL_DIR ⇒ 无该 finding，doctor exit 0。
- **D2** lark enabled + 三目录皆无 ⇒ finding 消息含 `lark` 与 `--sync`；doctor exit 1。
- **D3** 仅在 codebuddy ⇒ 无 finding（any-dir 规则）。
- **D4** local-fs enabled + local-fs-integration 全缺 ⇒ 豁免，无 finding。
- **D5** SKILL_DIR 指向不可读路径 ⇒ 报 finding（fail closed），不异常退出。
- **D6** wecom enabled 但目录里只有 lark-integration ⇒ 正确报 wecom（不误报、不漏报）。

## 4. 不变量（负面约束）

- 安装器绝不写 `~/.kgent/config.yaml`（I17 mtime 断言）。
- 三车道 + local-fs-integration 在一切场景恒装（I1/I15）。
- 镜像 hop 恒指向 hub 条目，不直接指 repo（既有结构，I6 断言移除后无 dangling）。
- `--uninstall` 与既有 S1–S8 断言不削弱，只扩展（anti-gaming #1）。
- 布尔解析只认字面 `true`；一切歧义落「关」而非猜（B2、I14）。
- verify() 失败仍非零退出（S7 语义保持）。

## 5. Tier 与失败模型

**Tier 2（normal feature）**。不触 money/auth/数据丢失面：config 只读，被删对象仅为本仓库 skill 的 symlink/junction/副本，重跑安装器或 `--force` 即可恢复。失败模式与防线：

- F1 prune 误删非门控 skill ⇒ 白名单恰为约定匹配的三名（I15）。
- F2 hub 删而 hop 留 ⇒ I6 断言 + 既有 sweep 兜底。
- F3 grep 跨块误读 ⇒ I14 负例锚定缩进契约；不可解析 ⇒ 落关不落开。
- F4 targets 文件损坏 ⇒ 警告 + 按 all（B3），不 crash。
- F5 doctor probe 异常被吞 ⇒ D5 fail-closed 断言。

## 6. Setup plan

- **零新依赖**：bash + POSIX 工具（脚本现状）+ Python stdlib（tests）；grep 腿为纯 bash/awk，无 PyYAML、无新包。
- **git checkpoint**：SPEC 批准后 commit 一次；其后每个 GREEN checkpoint commit 一次；mutant restore 以 `git diff` 验证。
- **新增文件**：`tests/` 内 installer 场景扩展（既有文件）+ doctor 场景新测试文件；`specs/2026-09-19-install-gate-evidence.md`；根 `EVIDENCE.md` 摘要节。无 tools/ 变更。
- **gauntlet**：收尾跑全量 `bash tools/gauntlet.sh`（含 artifact-smoke 对已装 CLI、local-fs flow 腿）；bash 门逻辑另做手动 mutation（3–5 个，逐个观察被杀）；grep 腿负例（I14）兼作 checker 的 fail-closed 负控制。
- **不触发平台 real 测试**（本次非平台 integration 内容变更，AGENTS.md 2026-09-11 ruling）；agent evals 属独立 release gate，不在本次。

## 7. Out of scope

`kgent skills sync` CLI 子命令（ADR 0010 否决）；车道门控；presence/原生 skill 家族检测；per-agent 原生能力感知（已知代价，`--agents` 兜底）。
