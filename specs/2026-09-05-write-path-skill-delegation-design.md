# Design Spec: 平台操作下沉集成 skill（integration skill 中心制）+ kgent 台账

- **Date:** 2026-09-05
- **Status:** implemented（Phase 1 — lark，2026-09-06 真机验收）。验收摘要：
  套件 515 passed / 1 failed（预先存在 `test_s5b_backend_none_fails_loudly`）/ 3 skipped，
  mypy strict 52 文件 0 错，diff-cover 变更行 85%（39 行缺口见 task-11-report），
  手工 mutant 5 中 4 杀（快照 0600→0644 在 Windows 存活：mode 断言 POSIX-only），
  B3/B4 真机 undo 探针 revision 3→5 → `docs +history-revert`(2048) → 读回 AAA-CONTENT（rev 6）。
  Phase 2/3（dingtalk / wecom）待凭据就绪后各自动实施计划
- **Priority:** high — 现有 Lark 写入路径对多块内容是**确定性数据丢失**，且 undo 无法兜底
- **Discovered while:** 用 knowledge-storage 给「部门新人入职」wiki 追加"第一年末"任务行，
  `kgent update` 返回 ok 但整篇文档被清空为 `<callout emoji="💡"></callout>`

## 事故与实证

对 ForDev产品部门「部门新人入职」（wiki node `EpMdwMpUViLscYkdBQOjNU8Cp2c`）的
update 把 v50 全文清空。同日以一次性探针文档完成三层对照实验：

| 实验 | 结果 |
|---|---|
| kgent update，三段纯文本（无任何富格式） | 仅第一段存活，status ok |
| lark-cli `docs +update --command overwrite` 内联多行（同一文档） | 三段全部存活 |
| Python `subprocess.run(['lark-cli', ...])` 裸名调用 | `WinError 2`（裸名不可执行 → kgent 实际经 `lark-cli.cmd` 批处理包装调用） |

**根因三个，相互独立：**

1. **数据丢失**：`LarkAdapter` 经 `lark-cli.cmd`（cmd 批处理包装）以内联 argv 传
   `--content`；cmd.exe 对参数重新求值时丢弃引号内首个换行后的全部内容、并搅碎
   多字节 UTF-8（❤️ → 占位 💡）。lark-cli 本身无此问题（对照实验 2）。
   注意：`run_cli` 本身是干净的（`shell=False` + argv 数组 + utf-8），问题在
   `.cmd` 包装层，不在 kgent 的 subprocess 用法。
2. **undo 失效**：op_id 为日期序号，同日全部操作撞号为 `op-20260905-01`，
   按 id 回滚不可能命中；且 undo 实测不恢复内容（v52 → undo "ok" → v54 仍空）。
3. **往返契约断裂（设计债）**：`kgent read` 产出富格式（`<callout>`/
   `<readonly-block>`/`<base_refer>`/`<table>`），而 write 只收 markdown ——
   "读出什么就写回什么"必然损坏。

事故恢复已用 `lark-cli docs +history-revert`（`history_version_id 20480` →
revision 50）完成，内容零损失 —— 该原语成为 undo 补偿矩阵的 Lark 项。

## 决策

**采用集成 skill 中心制（B+ 的最终形态）：kgent skills 只做编排；三大平台的
search / read / write / undo 补偿执行，统一经各平台的 integration skill
（lark-integration / dingtalk-integration / wecom-integration），由其委派原生
skill 或平台 CLI；kgent CLI 的平台操作仅保留给 kgent hosted backend。**

演进过程（三次裁决，全部与维护者逐条对齐）：

| 轮次 | 裁决 |
|---|---|
| B+ vs C | 执行走平台 skill；MCP 直连平台 API；fan-out 由 skill 并行 subagent 承担；契约分叉税接受 |
| v2 | search/read/write 全下沉（不只写入）；kgent skills 纯编排化；本 spec 落 lark-integration |
| v3 | **dingtalk-integration / wecom-integration 一并进入本 spec**（CLI 来源：`WecomTeam/wecom-cli`、`DingTalk-Real-AI/dingtalk-workspace-cli`）；kgent hosted backend 是与三平台**并列的另一种后端**（尚未实现、本 PR 不实现），为其保留 CLI 平台操作；分阶段落地 |

被否方案与理由沉淀于 `docs/adr/0004`；undo 设计沉淀于 `docs/adr/0005`；
统一语言见根目录 `CONTEXT.md`。

### 平台事实（2026-09-05 研究，影响设计）

| | lark-cli | wecom-cli | dws (dingtalk) |
|---|---|---|---|
| 搜索 | ✓ | ✓（doc/mail/盘/通讯录） | ✓（doc/chat/drive/mail/aitable/aisearch） |
| 读取 | ✓ | ✓ | ✓（Markdown + 无损 JSONML） |
| 写入 | ✓ DocxXML/块级 | ✓（doc/sheet/消息/邮件/todo/日历） | ✓（doc create/update/块级、wiki 节点、aitable） |
| history/undo | ✓ `history-revert` | ✗ 无 | ✓ `version-revert` + `--expected-revision` 乐观并发 |
| 身份 | user/bot | **仅 bot** | user（OAuth/device；需管理员开启 CLI Access Management） |
| 安装 | 已装 | `npm i -g @wecom/cli` + `npx skills add WeComTeam/wecom-cli` | `install.ps1` / npm 全局 |
| 自带 skill | 14+ | 14 个 `wecomcli-*` | 14 个 multi skill（`dws skill setup`） |

平台硬约束（记入各 integration skill 已知限制）：wecom 仅 bot 身份、消息只达
"bot 最近对话过"的会话、速率限制未文档化（自设退避）；dws 的
`docs/command-index.md` 已过期，以 README 表格 + 代码为准。

## 操作流（改造后）

```
kgent skill（纯编排：extract / update-first / proposal / 用户批准 / 引用规范）
  ├─ 检索与读取：三平台 → 各自 integration skill → 原生 skill / 平台 CLI
  │              kgent hosted backend → kgent search / read
  ├─ 策略        → kgent route --dry-run   # 敏感级 + 后端裁决；复用 kgent router，只读暴露
  ├─ 台账        → kgent journal begin     # op_id(uuid) + target + 写前 revision + 内容快照
  ├─ 执行写入    → 各自 integration skill → lark-cli / wecom-cli / dws
  │              kgent hosted backend → kgent update/create
  ├─ 台账        → kgent journal end       # 落账（status ok/failed）
  └─ 校验与确认  → 读回比对（经 integration skill）→ 原生 URL 引用

undo：kgent 查台账 → 产出补偿计划（含新鲜度检查）→ integration skill 执行
  lark     → docs +history-revert（history_version_id）
  dingtalk → dws +version-revert（+ expected-revision 条件）
  wecom    → 台账快照写回（平台无 history，唯一选项）
  新鲜度   → 当前 revision ≠ 台账写后 revision → 计划为"拒绝"，不产生可执行补偿
```

journal begin 在用户批准之后、执行之前调用；审批交互仍由各层自洽
（原生 skill 侧沿用各自的高风险写确认）。

### integration skill 最小能力契约（三平台公共模板）

| 能力 | 语义 | 失败语义 |
|---|---|---|
| search | 按关键词检索本平台内容，输出原生 URL + 类型 | 部分失败须声明（超时/降级），不静默缩量 |
| read | 按 URL/token 读取内容，标注类型与保真度 | 不支持类型显式报错，不猜测 |
| write | 创建/更新内容；审批由原生 skill 高风险确认 | 半途失败必须可被读回校验发现 |
| undo 补偿 | 按上表平台机制执行补偿计划 | 新鲜度不符 fail closed；机制缺失显式降级（wecom=快照） |
| 原生 URL | token → 平台原生链接（类型匹配路径） | 无法判定类型时不产链接 |
| 已知限制 | 平台身份/权限/速率约束文档化 | — |

## 组件改动

| 位置 | 内容 |
|---|---|
| `src/kgent/cli.py`（journal） | 新增 `journal begin/end`；op_id 改为 uuid 后缀；台账落 `~/.kgent/journal/`（entry：op_id、op 类型、target uri、backend、写前/写后 revision_id、内容快照路径、时间戳）；只记变更、逻辑操作粒度 |
| `src/kgent/cli.py`（undo） | 依台账产出补偿计划（JSON：平台机制参数、期望 revision、新鲜度检查结果）；新鲜度不符 → 计划为"拒绝"；`kgent audit` 改读台账目录。**kgent 不再直接执行对三平台的补偿**——计划由 integration skill 执行 |
| `src/kgent/cli.py`（route） | 新增只读 `route --dry-run --content X --backends Y`：暴露现有 router 的敏感级 + 后端裁决，不执行任何写。三平台 trust_zone 一律 `internal`（维护者裁决） |
| `src/kgent/adapters/lark.py` 等 | 平台 adapter 的 search/read/write 标注 deprecated（docstring 指明 skills 改走 integration skill；CLI 面保留供调试 + kgent hosted backend 车道），**不删代码**——2026-09-02 spec 的行为与测试原样保留为回归装甲 |
| `skills/lark-integration/SKILL.md` | 升格为 Lark 唯一接口：① 新增 search 章节（`docs +search` / `drive +search`；node_type 判定：URL 路径段 `/wiki/` vs `/docx/` 优先、`entity_type` 兜底；原生 URL 构造沿用 2026-09-02 规则）② read 矩阵扩展为**所有 Lark 内容** ③ 写矩阵：所有 Lark 内容写入 → lark-doc/lark-wiki ④ undo 补偿章节（`+history-list`/`+history-revert` + 新鲜度前提）⑤ 按能力契约自检 |
| `skills/dingtalk-integration/SKILL.md`（新） | DingTalk 唯一接口：dws 调用矩阵（doc/wiki/aitable/chat/mail）；补偿 = `+version-revert` + `expected-revision`；版本轴说明（revision vs version）；已知限制（管理员开启 CLI Access Management、command-index 过期） |
| `skills/wecom-integration/SKILL.md`（新） | WeCom 唯一接口：wecom-cli 调用矩阵（doc/sheet/消息/邮件/盘）；补偿 = **快照写回**（平台无 history）；已知限制（仅 bot 身份、消息只达近期会话、速率自设退避） |
| `skills/knowledge-storage/SKILL.md` | 纯编排化：三平台的 search/read/写执行/读回校验/undo 全部经各自 integration skill；journal begin/end 与 route 经 kgent CLI；route-before-execute 为硬性步骤；多目标 fan-out 用并行 subagent |
| `skills/question-answering/SKILL.md` | 检索步骤：三平台经各自 integration skill，kgent hosted backend 经 kgent search；结果按子查询分组、原生 URL 引用规则不变 |
| `skills/wiki-setup/SKILL.md` | 同 knowledge-storage；分目标 journaling 保持 |
| `evals/` | 新增：route-before-execute；写后读回校验；**平台操作必须经 integration skill**（skill 文档静态检查 + 流程 eval）；lark/dingtalk/wecom search 保真用例 |

## 非目标（明确不做）

- kgent 不暴露块级编辑 CLI —— 外科手术归原生 skill
- kgent 不实现独立 `restore` 命令 —— undo 补偿已覆盖
- kgent 不复刻各平台内容格式知识 —— 平台操作不再流经 kgent adapter
- `cli_adapter.py` 的 `@file` 内容通道修复**移出本 PR**：三大平台操作均不走
  kgent Python 子进程通道（skills 从 bash 调 CLI 经 node 垫片，无 `.cmd` 问题），
  adapter 进入 dormant；kgent hosted backend 车道启用时再议
- MCP 侧平台能力 —— 由 MCP 直连平台 API
- kgent hosted backend 的实现 —— 它是与三平台并列的另一种后端，**尚未实现、
  本 PR 不实现**；本 PR 仅确认 CLI 平台操作（store/wiki/update/create/read/
  search）为它保留，三平台操作不经这些命令

## old-coder 充实（Tier 3：数据丢失域）

**Tier 声明：Tier 3。** 本变更的域就是本次事故的域——整篇文档数据丢失。

### 失败模型

| # | 失败模式 | 抓住它的层 |
|---|---|---|
| FM1 | 部分写：journal begin 后执行崩溃，台账留 open 脏账 | journal end 走 finally 语义；单测注入执行异常 |
| FM2 | undo 打错版本：写入后他人又改，补偿回滚埋掉他人编辑 | 新鲜度检查按平台：lark revision / dws expected-revision / wecom 当前内容比对快照；不符即拒（fail closed）；真机集成测试模拟写后第三方编辑 |
| FM3 | 快照陈旧（wecom 专属：无平台 history） | 补偿前读当前内容与台账快照比对，不匹配即拒 |
| FM4 | 路由绕过：confidential 内容绕过 route 进敏感面 | `route --dry-run` 单测 + eval 强制 route-before-execute |
| FM5 | 快照泄漏：`~/.kgent/journal/` 明文快照含敏感内容 | 文件权限收紧（POSIX 0600；Windows 登记 ACL 现状）；目录加入 .gitignore；**已知限制：本地明文快照写入 EVIDENCE** |
| FM6 | 平台 history 不可用：写前 revision 被清理/越界 | 补偿 fail closed：非零退出 + 明确错误，绝不静默成功 |
| FM7 | integration skill 经 bash 调 CLI 的内容完整性回归 | Phase 各自的真机内容完整性用例（多行/CJK/emoji）；bash→node 垫片通道在事故实验中已证完好，此项为回归装甲 |
| FM8 | 台账文件损坏/被篡改 | 读台账 fail closed：损坏 entry 硬失败（checker 负控：喂损坏 JSON 看它失败） |
| FM9 | 并发 begin 同一 target | op_id 含 uuid 后缀（回归 B1）；台账 append-only |
| FM10 | integration skill 写入半途失败但编排当成功 | 写后读回校验为流程硬步骤 + eval |

### 可执行验收标准

每条 = 一个具名行为；RED 阶段逐条见到失败。

- **B1 op_id 唯一性**：同一秒内 `journal begin` 两次（同 target）→ 两个不同
  op_id，形如 `op-20260905-<8hex>`；回归本事故的 `op-20260905-01` 撞号。
- **B2 台账生命周期**：begin → `audit` 可见且标记 open；`journal end --status
  ok/failed` → 标记落账；注入执行异常（FM1）→ entry 以 failed 落账。
- **B3 undo·lark（真机）**：探针文档内容 A → begin → 写入 B → undo 产出补偿
  计划 → 经 lark-integration 执行 `history-revert` → 读回 == A 且 revision
  递增。**变体（FM2）**：undo 前再写入 C → 计划为"拒绝"，指明当前 revision。
- **B4 undo·lark·create（真机）**：begin(create) → 建文档 → 补偿计划 → 经
  lark-integration 删除（已删 → 幂等成功）。
- **B5 undo·wecom·快照写回**：fake CLI 验证计划生成 + 快照路径；真机（待
  凭据，见 Setup）：写 A → 写 B → 补偿 = 快照写回 → 读回 == A；内容被第三方
  改过 → 拒绝（FM3）。
- **B6 undo·dingtalk（真机，待凭据）**：写 A → 写 B → 计划 → `+version-revert`
  → 读回 == A；`expected-revision` 不符 → 拒绝。
- **B7 route --dry-run**：confidential 内容 + internal 后端 → 放行；路由裁决
  `--json` 结构化输出（sensitivity、allowed_backends、reasons）。三平台
  trust_zone 全 internal 后，zone 拒绝路径以单测保持（未来外部平台用）。
- **B8 内容完整性（各 Phase 真机）**：三段中文 + emoji 内容经对应平台
  写入 → 读回全量（FM7 回归装甲）。
- **B9 skill 流程纪律（eval）**：route-before-execute、journal 成对、写后读回
  一致、**平台操作必须经 integration skill**（三 skills 文档静态检查：
  不得出现对平台后端的 `kgent search/read/update/create/store/wiki` 直调）。
- **B10 checker 负控**：台账读虫（FM8）各喂已知坏输入，目睹失败后才信其 pass。
- **B11 search 保真迁移**：lark-integration search 步骤的 node_type 判定与
  原生 URL 输出与 2026-09-02 规则一致（fixture 沿用 `tests/test_lark_node_type.py`
  payload 形状）；dingtalk/wecom 的类型判定用例随 Phase 补充。
- **B12 基线不变量**：现有测试套件零**新增**失败（先录 baseline，含
  `test_archive_delete_undo.py` 的 undo 语义现状）；search/read/node_type
  行为不回归。

### Setup 计划（批准即授权）

- **依赖（新增，含理由）**：`@wecom/cli`（npm 全局）与
  `dingtalk-workspace-cli`（install.ps1 或 npm 全局）——Phase 2/3 的 integration
  skill 的平台 CLI，无替代物；均为官方仓库（MIT / Apache-2.0）。lark-cli 已在环境。
- **git**：检查点提交按 GREEN/REFACTOR 节奏；mutant 恢复以 `git diff` 验证。
- **真机授权**：各 Phase 在对应平台租户创建/写入/撤销/删除探针内容（命名带
  `-probe-`，teardown 必删）。**凭据阻塞项**：lark 已配；dingtalk 需组织管理员
  开启 CLI Access Management + OAuth 登录；wecom 需 `auth init`（扫码，交互式，
  需维护者本人操作）——Phase 2/3 的真机验收在凭据就绪前标记 blocked。
- **gauntlet 新增文件**：`tests/test_journal.py`、`tests/test_undo_ledger.py`、
  `tests/test_route_command.py`、`tests/properties/`（内容完整性属性）、
  `evals/skills/{knowledge-storage-write-flow,platform-via-integration}/`。

### EVIDENCE 要求

最终一次性 fresh run（最后一次代码编辑之后）：全套测试数（含随机序），
`diff-cover` changed-line %（目标：变更行 100%），mutmut kill 数/等价存活分类，
mypy/ruff 零新增，真机集成结果（含撤销前后 revision 读数；Phase 2/3 凭据阻塞
如实记录），负控记录（B10），skip 层带理由。入口脚本 `tools/gauntlet.sh`
随仓库提交。

## 测试

- **单元**：journal begin/end/audit 台账读写；op_id 唯一性；undo 补偿计划路由
  （backend × op 类型矩阵 mock：lark=history、dingtalk=version、wecom=snapshot、
  hosted=adapter）；route --dry-run 裁决；新鲜度检查拒绝路径
- **集成（真机，按 Phase）**：各平台 integration skill 委派写入 → 读回 parity；
  undo → 平台机制恢复断言；create → undo → 删除断言
- **回归**：本次事故场景固化为用例——多块中文内容经平台通道写入不截断
- **evals**：route-before-execute；写后读回；平台操作经 integration skill

## 发布（分阶段）

1. **Phase 1 — lark**：journal/undo/route + lark-integration 升格 + 三 skills
   编排化 + evals；`bash tools/install-skills.sh`
2. **Phase 2 — dingtalk**：dingtalk-integration + dws 依赖/凭据 + B6/B8 真机
3. **Phase 3 — wecom**：wecom-integration + wecom-cli 依赖/凭据 + B5 真机
4. 每阶段更新项目记忆与 spec 状态（proposed → implemented 附真机验收记录）
5. 项目记忆更新：first-block bug 条目改写为"已修复（架构性绕开）+ 根因
   （.cmd 包装层）+ 新操作流"

## 风险与开放问题

- **route-before-execute / journal 成对是守约不是执法**：eval 强制 + SKILL.md
  硬性步骤；真实泄漏的 fallback 是执行漏斗收回 kgent（C 路线，见 ADR 0004）。
- **Phase 2/3 真机验收阻塞于凭据**（dingtalk 管理员开关 + OAuth、wecom 扫码）：
  单元/fixture 测试不受阻，阻塞如实进入 EVIDENCE。
- **三平台 CLI 均为外部仓库依赖**：版本漂移风险由 integration skill 的
  `--version` 预检与已知限制章节吸收；不做 vendoring。
- **dws 文档过期**（command-index 缺 6 个服务）：以 README 表格 + 代码为准，
  integration skill 内注明。
