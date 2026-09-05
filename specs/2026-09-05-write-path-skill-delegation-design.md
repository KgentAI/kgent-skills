# Design Spec: Lark 写入路径下沉 skill 层 + kgent 台账（B+ 方案）

- **Date:** 2026-09-05
- **Status:** proposed — 设计已与维护者逐条对齐，待 spec 评审
- **Priority:** high — 现有 Lark 写入路径对多块内容是**确定性数据丢失**，且 undo 无法兜底
- **Discovered while:** 用 knowledge-storage 给「部门新人入职」wiki 追加"第一年末"任务行，`kgent update` 返回 ok 但整篇文档被清空为 `<callout emoji="💡"></callout>`

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
revision 50）完成，内容零损失 —— 该原语同时成为 B+ 方案里 undo 的补偿机制。

## 决策

**采用 B+：Lark 写入执行下沉到平台 skill，kgent 保留策略（route）、台账
（journal/undo/audit）、统一读面（search/read）与非 Lark 后端 adapter。**

与 C（kgent 适配器内下沉执行）的取舍，维护者逐条裁决：

| C 的反对理由 | 维护者裁决 |
|---|---|
| MCP 消费面只能经 kgent 写 Lark | 不成立 —— MCP 将直接用平台 API |
| fan-out 多后端写入要 kgent 编排 | 可由 skill 起并行 subagent 承担 |
| 写入逻辑在 skill 层分叉为多套（长期税） | 接受 |

B+ 的直接收益：lark-doc 的 DocxXML / 块级 / media / history 知识是现成的，
零重写；不依赖 kgent 发版；策略/执行分离的架构表达更清晰。

## 写入流（改造后）

```
extract → kgent search（update-first 不变）→ proposal → 用户批准
  → kgent route --dry-run      # 策略：敏感级 + 后端裁决；复用 kgent router，只读暴露
  → kgent journal begin        # 台账：op_id(uuid) + target + 写前 revision + 内容快照
  → 执行：
      Lark        → lark-doc skill（lark-integration 写委托矩阵；DocxXML/块级写）
      其它后端    → kgent update/create（各自 adapter；@file 内容通道修复见下）
  → kgent journal end          # 落账（status ok/failed）
  → 读回校验（kgent read 或 docs +fetch）→ 原生 URL 确认
```

journal begin 在用户批准之后、执行之前调用；审批交互仍由各层自洽
（lark-doc 侧沿用 lark-shared 的高风险写确认）。

## 组件改动

| 位置 | 内容 |
|---|---|
| `src/kgent/cli.py`（journal） | 新增 `journal begin/end`；op_id 改为 uuid 后缀；台账落 `~/.kgent/journal/`（entry：op_id、op 类型、target uri、backend、写前 revision_id、内容快照路径、时间戳） |
| `src/kgent/cli.py`（undo） | 按台账补偿：Lark 目标 → `docs +history-revert` 回写前 revision（内部包装，非用户命令）；create → delete target；其它后端 → 快照经本后端 adapter 写回。`kgent audit` 改读台账目录 |
| `src/kgent/cli.py`（route） | 新增只读 `route --dry-run --content X --backends Y`：暴露现有 router 的敏感级 + 后端裁决，不执行任何写 |
| `src/kgent/adapters/cli_adapter.py` | 非 Lark 通道保留并修复：内容含换行或非 ASCII 字符时一律改走 CLI 的 `@file`/stdin 通道（dingtalk-cli / wecom-cli 同款 `.cmd` 包装问题预防性覆盖） |
| `skills/knowledge-storage/SKILL.md` | 写流程按上图重写：Lark 分支委派 lark-doc（经 lark-integration 矩阵），前后包 journal begin/end；dingtalk/wecom 分支维持 `kgent update/create`；加"route-before-execute"为硬性步骤 |
| `skills/wiki-setup/SKILL.md` | 同构改造：Lark 节点创建/内容写入走委托路径；多目标 fan-out 用并行 subagent，分目标 journaling 保持 |
| `skills/lark-integration/SKILL.md` | 写委托矩阵从"非 docx 才委托"扩展为"**所有 Lark 内容写入都委托**"（docx → lark-doc；wiki 节点 → lark-wiki/lark-doc；记录类不变）；补"文档损坏 → `+history-list`/`+history-revert`"条目 |
| `evals/` | 新增两条：写流程必须先 route 再执行；写后读回校验（写入内容与读回一致） |

## 非目标（明确不做）

- kgent 不暴露块级编辑 CLI（`str_replace`/`block_*`）—— 外科手术归 lark-doc
- kgent 不实现独立 `restore` 命令 —— undo 补偿已覆盖，history 能力留在 lark-doc
- kgent 不复刻 DocxXML 知识 —— Lark 写入不再流经 kgent，往返契约（根因 3）对 Lark 自动消解；非 Lark 后端维持各 CLI 自己的内容格式
- MCP 侧 Lark 写能力 —— 由 MCP 直接接平台 API，不经 kgent/skill
- dingtalk/wecom 的 history 级 undo —— 先用快照写回，平台原生 history 后续再说

## 测试

- **单元**：journal begin/end/audit 的台账读写；op_id 唯一性；undo 补偿路由（按 backend × op 类型矩阵 mock）；route --dry-run 裁决；`@file` 通道对多行/CJK/emoji 的完整性
- **集成（真 lark-cli，探针文档模式 + teardown 删除）**：lark-doc 委派写入 → 读回 parity；undo → `history-revert` 恢复断言；create → undo → 删除断言
- **回归**：本次事故场景固化为用例——"多块中文内容经非 Lark adapter 写入不截断"
- **evals**：route-before-execute；写后读回校验

## 发布

1. `bash tools/install-skills.sh`（CLI + skills 链接刷新）
2. 更新项目记忆：first-block bug 条目改写为"已修复 + 根因（.cmd 包装层）+ 新写入流"
3. 本 spec 状态流转 proposed → implemented（附真机验收记录，沿仓库惯例）

## 风险与开放问题

- **route-before-execute 是守约不是执法**：skill 层理论上可绕过路由。缓解：
  eval 强制 + SKILL.md 硬性步骤。若未来出现真实泄漏场景，再评估把执行漏斗
  收回 kgent（本 spec 的 C 路线是现成 fallback）。
- **journal 落账依赖 skill 自觉调用**：与上一条同性质。begin/end 不调用时
  audit 出现空洞，可由 evals 的写后读回校验间接暴露。
- **lark-doc 侧审批与 kgent journal 的时序**：begin 在批准后调用（见写入流），
  若 lark-doc 侧二次确认被拒，journal end 记 failed，不产生脏账。
- **开放问题（维护者裁决）**：`LarkAdapter` 的写路径（`update_document`/
  `create_document`）是保留 + 标注 deprecated，还是对 `--backends lark` 硬禁
  （返回"改走 lark-doc 委托"错误）？硬禁更符合单一漏斗，但破坏向后兼容，
  需盘点 `test_archive_delete_undo.py` 等既有测试的语义。

---

## old-coder 充实（Tier 3：数据丢失域）

**Tier 声明：Tier 3。** 本变更的域就是本次事故的域——整篇文档数据丢失。
通用 gauntlet 之上叠加失败模型；每条失败模式绑定一个能真正抓住它的层。

### 失败模型

| # | 失败模式 | 抓住它的层 |
|---|---|---|
| FM1 | 部分写：journal begin 后执行崩溃，台账留 open 脏账 | journal end 走 finally 语义（异常也落账 failed）；单测注入执行异常 |
| FM2 | undo 打错版本：写入后他人又改，`history-revert` 到写前 revision 会埋掉他人编辑 | undo 前新鲜度检查：当前 revision ≠ 台账"写后 revision" → 拒绝（fail closed）；真机集成测试模拟写后第三方编辑 |
| FM3 | 快照陈旧：非 Lark 后端快照写回覆盖他人并发编辑 | 同 FM2：写回前比对当前版本 vs 台账版本，不匹配即拒 |
| FM4 | 路由绕过：confidential 内容进 external zone | `route --dry-run` 单测（拒绝语义沿用现有 router exit 3）+ eval 强制 route-before-execute |
| FM5 | 快照泄漏：`~/.kgent/journal/` 明文快照含敏感内容 | 快照文件权限收紧（POSIX 0600；Windows 记录 ACL 现状）；目录加入 .gitignore；**已知限制：本地明文快照写入 EVIDENCE** |
| FM6 | history 不可用：Lark 侧写前 revision 被清理/越界 | undo fail closed：`history-revert` 失败必须非零退出 + 明确错误，绝不静默成功 |
| FM7 | `.cmd` 通道再吃内容（非 Lark @file 修复回归） | hypothesis 属性测试（多行/CJK/emoji 往返）+ fake CLI 断言 argv 完整 + 手工 mutant |
| FM8 | 台账文件损坏/被篡改 | 读台账 fail closed：损坏 entry 硬失败，绝不跳过（checker 负控：喂损坏 JSON 看它失败） |
| FM9 | 并发 begin 同一 target | op_id 含 uuid 后缀（回归 B1）；台账 append-only |
| FM10 | lark-doc 写入半途失败但 skill 当成功 | 写后读回校验为流程硬步骤 + eval；journal end 前 fetch 比对 |

### 可执行验收标准

每条 = 一个具名行为；RED 阶段逐条见到失败（新测试先败，实现后绿）。

- **B1 op_id 唯一性**：同一秒内 `journal begin` 两次（同 target）→ 两个不同
  op_id，形如 `op-20260905-<8hex>`；回归本事故的 `op-20260905-01` 撞号。
- **B2 台账生命周期**：begin → entry 可被 `audit` 读到且标记 open；
  `journal end --op-id X --status ok` → 标记 finalized；`--status failed` →
  标记 failed；注入执行异常（FM1）→ entry 仍以 failed 落账。
- **B3 undo·Lark·update（真机）**：探针文档内容 A → begin → 写入内容 B →
  undo → 读回 == A 且 revision 递增。**变体（FM2）**：undo 前再写入 C →
  undo 拒绝，非零退出，错误含当前 revision 与台账期望。
- **B4 undo·Lark·create（真机）**：begin(create) → 建文档 → undo → 文档删除
  （`drive +delete` 已删/不存在 → 幂等成功）。
- **B5 undo·非 Lark（fake 后端）**：快照写回路径；当前版本 ≠ 台账版本 →
  拒绝（FM3）。
- **B6 route --dry-run**：confidential 内容 + external 后端 → 拒绝（沿用
  router exit 3 语义）；public 内容 → 放行；`--json` 输出结构化裁决
  （sensitivity、allowed_backends、reasons）。
- **B7 内容通道完整性**：fake CLI（回显收到的 argv）断言 content 含
  `"第一段\n\n第二段\n\n第三段"` 与 `❤️` 逐字节到达；hypothesis 属性
  （FM7）：任意 unicode 文本经通道往返无损；真机：三段中文 + emoji 经
  非 Lark adapter 写入 → 读回全量。
- **B8 skill 流程纪律（eval）**：knowledge-storage 写流程必须先 `route
  --dry-run` 后执行、journal begin/end 成对、写后读回一致；三缺一即 eval 失败。
- **B9 基线不变量**：现有测试套件零**新增**失败（先录 baseline，含
  `test_archive_delete_undo.py` 的 undo 语义现状）；search/read/node_type
  行为（2026-09-02 spec）不回归。
- **B10 checker 负控**：台账读虫（FM8）与 @file 门（FM7）各喂一次已知坏
  输入，目睹其失败后才信任其 pass。

### Setup 计划（批准即授权）

- **依赖：零新增。** pytest≥8 / pytest-randomly / mypy≥1.8 / ruff≥0.4 /
  coverage+diff-cover≥9 / mutmut≥3 / hypothesis≥6 均已在 `[dev]` extra。
- **git**：本 spec 已提交（094c0e6，分支 `feat/lark-integration-shared-doc`）；
  每个 GREEN/REFACTOR 检查点提交一次，mutant 恢复以 `git diff` 验证。
- **真机授权**：集成测试在租户 `hjpiui0m07o0.jp.larksuite.com` 创建/写入/
  撤销/删除探针文档（命名带 `-probe-`，teardown 必删）——批准本 spec 即授权。
- **gauntlet 新增文件**：`tests/test_journal.py`、`tests/test_undo_ledger.py`、
  `tests/test_route_command.py`、`tests/test_cli_adapter_content_channel.py`、
  `tests/properties/test_content_channel.py`、
  `evals/skills/knowledge-storage-write-flow/`。
- **环境改动登记**：除上述文件与检查点提交外无环境变更；安装类命令为零。

### EVIDENCE 要求

最终一次性 fresh run（最后一次代码编辑之后）：全套测试数（含随机序），
`diff-cover` changed-line %（目标：变更行 100%，分支覆盖处注明），mutmut
kill 数/等价存活分类，mypy/ruff 零新增，真机集成结果（含 B3/B4 撤销前后的
revision 读数），负控记录（B10），skip 层带理由。入口命令：一条脚本重跑全部层，
随仓库提交（`tools/gauntlet.sh` 若无现成等价物）。
