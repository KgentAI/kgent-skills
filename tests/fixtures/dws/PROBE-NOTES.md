# PROBE-NOTES — dws 命令真值单（Phase 2 Task 1）

- 探测日期：2026-09-08（§0–§5）；**§2 payload 键位已 live-captured 回填：2026-09-09**（B6/B8 兑现轮修复半场，§7）
- CLI：`dws version v1.0.61 (50eb73a0, 2026-08-31T14:46:17Z)`，npm 包 `dingtalk-workspace-cli`（2026-09-09 复核同版本，无升级漂移）
- 环境：Windows 11 + Git Bash（win32）
- 探测方式标注：
  - **[help 实测]** = 在本机 `dws <path> --help` / `dws schema --cli-path ... --compact` 实际输出，逐字核对过
  - **[PENDING-凭据]** = 需要登录后真机捕获（**2026-09-09 起全部定谳，见 §7**）
  - **[live-captured 2026-09-09]** = 真机捕获原样定谳（payload 全文见
    `FIXTURES-NOTE.md` 与 `.superpowers/sdd/2026-09-08-phase3-wecom-integration/dingtalk-closure-report.md`、同目录 `dingtalk-closure-fix-report.md`）

## 0. 登录状态（本任务写入时的阻塞点）

`dws auth status -f json` 实测两次登录窗口（各 5 分钟）均超时，未完成人工扫码授权：

```json
{ "success": true, "authenticated": false, "message": "未登录" }
```

`dws doctor` 实测：网络可达（`https://mcp.dingtalk.com`，延迟 ~2145ms）、凭据后端正常、仅 1 fail = 未登录。**不是组织「CLI Access Management」被关**（那会在授权页报错，而不是等满 5 分钟超时）——纯粹是无人完成浏览器扫码。

**维护者需要执行（补捕前置步骤）**：

1. 在本机终端运行 `dws auth login`（OAuth Loopback 流，默认）。它会：
   - 自动打开默认浏览器到 `https://login.dingtalk.com/oauth2/auth?...redirect_uri=http://127.0.0.1:<port>/callback`
   - 在钉钉 App / 浏览器已登录会话里点「授权」
   - 回调到本机 127.0.0.1 监听端口后自动完成（窗口 5 分钟内要完成）
   - 浏览器没自动开时，手动访问终端打印的 URL。
2. 登录成功后跑补捕（见 §5）。若本机无浏览器会话（SSH/无头），改用 `dws auth login --device`（设备流，显示 user_code + 短 URL，手机/其他设备完成授权）。

---

## 1. 命令真值表 [help 实测]

### 1.1 关键结论（README/handoff 形状 vs 实测）

| README/handoff 写法 | 实测真值 | 说明 |
| --- | --- | --- |
| `dws doc search --query ...` | **`dws doc +search --query ...`** | 无 `doc search`；搜索入口是 `+search`（或投影版 `+find-doc`） |
| `dws doc fetch <id>` | **`dws doc +fetch --node <DOC_ID或URL>`** | fetch 无位置参数，用 `--node` |
| `dws doc create --title "x" --content @probe.md` | **`dws doc +create --name "x" --content @probe.md`** | 旗标是 `--name` 不是 `--title`；`@file` 通道只在 `+create`/`+update` 存在，原生 `doc create` 用 `--content-file` |
| `dws doc version-list <id>` | **`dws doc +version-list --node <DOC_ID>`**（或 `doc version list`） | 同上，`--node` |
| `version-revert`（README 未覆盖） | **`dws doc +version-revert --node <DOC_ID> --version <N>`**（或 `doc version revert`） | 版本轴旗标是 `--version`（int，必填）；effect=destructive, confirmation=user_required |
| `--expected-revision`（真实旗标名） | **`--expected-revision int`，在 `dws doc +update` 上**，且**仅 `--command overwrite` + `--doc-format jsonml` 时生效**（服务端原子条件写） | fetch 的 `--revision` 明确标注「不支持」 |

### 1.2 探针生命周期命令（Task 2/3/4 直接消费）

| 用途 | 命令 | 关键旗标 | Safety [help 实测] |
| --- | --- | --- | --- |
| 建探针文档 | `dws doc +create --name "<标题>" --content @<工作目录相对.md>` | `--doc-format markdown\|jsonml`（默认 markdown）、`--folder <doc folder nodeId>`、`--workspace <知识库ID>`（位置优先级 folder > workspace > 我的文档根目录） | effect=write risk=medium confirmation=not_required |
| 搜索探针 | `dws doc +search --query "kgent-phase2-probe"` | `--limit`（默认 10，最大 30）、`--page-all --max-pages/--max-items`（全量匹配必须用 page-all）、`--cursor`、`--extensions`（如 adoc） | effect=read risk=low idempotent |
| 读探针 | `dws doc +fetch --node <DOC_ID>` | `--detail simple\|with-ids\|full`（默认 simple）、`--scope full\|outline\|range\|section\|keyword\|tags`、`--version <N>`（读历史版本，0=初始）、`--query "<唯一标题>"` 可代替 `--node` | effect=read risk=low idempotent |
| 版本列表 | `dws doc +version-list --node <DOC_ID>` | `--limit` / alias `--page-size`、`--cursor` / alias `--page-token` | effect=read risk=low idempotent |
| 版本快照 | `dws doc +version-save --node <DOC_ID>` | 无其他必填 | effect=write |
| 版本回滚 | `dws doc +version-revert --node <DOC_ID> --version <N>` | `--version` 从 +version-list 取 | effect=destructive risk=high confirmation=user_required |
| 更新（update-first 的写入面） | `dws doc +update --node <DOC_ID> --command <动作> --content ...` | `--command append\|overwrite\|block_insert_before\|block_insert_after\|block_replace\|block_delete\|str_replace\|block_copy_insert_after`；条件写 `--expected-revision`（仅 overwrite+jsonml）；`--doc` 是 `--node` 的 alias，`--text` 是 `--content` 的 alias | effect=write risk=medium confirmation=user_required |
| 删除探针（teardown） | **`dws drive +delete --node <DOC_ID>`** | 移入回收站（非永久删）；反悔用 `dws drive +recycle-restore`；句柄定谳见 §7.3 [live-captured 2026-09-09] | effect=destructive risk=high confirmation=user_required |

注意：`doc` 树里**没有删除命令**——帮助明说「文件管理（…删除…）已迁移到 dws drive」，探针 teardown 走 `dws drive +delete`。`--node` 的真值（2026-09-09 定谳）是 **doc 域 DOC_ID 本体**（32 位字母数字；`drive +find-file` 的 `files[].dentryId` 与 `drive +info` 的 `data.fileId` 都等于它）；`drive +info` 的 `data.dentryId` 是 12 位内部号，**被 `drive +delete` 拒收**（「nodeId 须为 dentryUuid：32 位字母数字字符串」）。

### 1.3 组合入口（`+` 前缀）与原生入口的并行关系 [help 实测]

`+xxx` 是 CLI 侧的组合/投影命令（schema `interface_mode: composite`，canonical_path 如 `doc.shortcut_search`），原生入口也在：

- 搜索：`doc +search`（全字段）／`doc +find-doc --query <kw> --limit N`（只投影标题/URL/类型/token 四字段）
- 读取：`doc +fetch`（detail 保真度）／`doc read --node <id>`（Markdown，`--content-format jsonml` 可选，`--version` 历史版）／`doc info --node <id>`（元信息）
- 创建：`doc +create`（`--content` 支持 `@file`）／`doc create`（`--content` 字面量、`--content -` stdin、`--content-file <path>` 三通道，另带 `--fix-jsonml`）
- 版本：`doc +version-list|+version-revert|+version-save` ＝ `doc version list|revert|save`
- 更新：`doc +update`（组合动作）／`doc update`（原生，本任务未展开——update-first 语义以 `+update` 为准）

kgent adapter 建议固定用 `+` 组合入口（自带验证/读回/投影，schema 有 reviewed 返回契约），原生入口留作逃生舱。

### 1.4 通用旗标 [help 实测]

- 格式旗标：`-f, --format string`，可选 `json|table|raw|pretty|ndjson|csv`，**默认 json**（`-f json` 合法但冗余；`--format json` 同义）
- `--jq <expr>` 输出过滤、`--fields name,id,status` 字段投影
- `--timeout int`（秒，默认 30）、`-y/--yes`（AI Agent 跳确认——**未获用户明示确认前禁止加**，`+update`/`+version-revert`/`drive +delete` 都是 confirmation=user_required）
- `--profile <corpId:userId>` 一次性指定组织、`--mock`（开发调试 Mock 数据）
- 机器契约：`dws schema --cli-path "<path>" --compact -f json`（无凭据也可查，输出 parameters/effect/risk/confirmation/idempotency，但 compact 里**没有返回 payload 字段契约**，键位表必须靠真机捕获）

---

## 2. payload 键位表 —— **[live-captured 2026-09-09 定谳]**（原 PENDING 全部回填）

| payload | 定谳（原 PENDING 问题 → 真值） | fixture |
| --- | --- | --- |
| search hit | 命中容器键 **`documents`**（非 `items`/`data.items`）；hit 键 `nodeId`/`name`/`docType`/`url`/`modifiedTime`，**无 `snippet`、无 `rank`、无 `title`、无 `type`**；外层 `complete/contractVersion/count/documents/failures/hasMore/nextCursor/pagesRead/status/stopReason/truncated`（`doc.list.v1`） | `doc-search.json` |
| fetch | 目标块是**顶层 `content`**（`doc.content.v1`，外层无 `data`）；正文键默认档 **`markdown`**、with-ids/full 档 **`jsonml`**；`revision` **只在 with-ids/full 档**（字符串 `"1"`）——**没有任何单档同时携带 markdown 与 revision** | `doc-fetch.json`（with-ids）、`doc-fetch-simple.json`（默认档） |
| version-list | 外层 `hasMore/success/versions`；条目只有 `version`（int）+`createTime/updateTime/type/userId`，**无 revision 字段**——revision→version 映射走替代通道（§7.2） | `version-list.json` |
| create 响应 | `doc.operation.v1` 外层 `ok/compensation/complete/data/steps/warnings`；DOC_ID 在 **`data.nodeId`**（URL 在 `data.result.docUrl`）；**全块无 revision**；`data.verification.verified/readbackSha256` 自带读回校验 | （e2e 消费，未落 fixture） |
| `doc +update` 响应 | `data` 块只有 `nodeId/verified`，**全块无 revision**（revision_after 由写后 with-ids 档读回取）；overwrite+jsonml 通道 rc=1 `doc_write_verification_failed` 为**结构性假阴性**（写已落，写后验证以读回为准）→ §7.4 | （e2e 消费，未落 fixture） |
| drive +delete 响应 | `ok/outcome/data.nodeId/data.result.{message,success}/data.success`（回收站 30 天可恢复）；**删除句柄 = DOC_ID 本体**（§7.3） | `drive-delete.json` |
| drive +info / +find-file | `data.fileId` = **32 位 DOC_ID 本体**、`data.dentryId` = **12 位内部号**（拒收）；`files[].dentryId` = **DOC_ID 本体**——两域 ID 对应定谳 | `drive-info.json`、`drive-find-file.json` |

真机分页语义（值得注意）：3 命中（< 默认 limit 10）也报 `complete:false +
hasMore:true + stopReason:single_page`；0 命中才是 `complete:true +
stopReason:source_complete`——`complete` 不能当「读全」断言用。

---

## 3. 原生 URL 形状

- flat doc（文档空间文档）**[help 实测]**：`https://alidocs.dingtalk.com/i/nodes/<DOC_UUID>`（`dws doc info`/`doc read` 的 `--node` 示例原样给出；`--node` 同时接受裸 DOC_ID 或完整 URL）
- flat doc 另一形态：`alidocs.dingtalk.com/i/document/...`（dingtalk-doc skill 参考文档提及，未在本 CLI help 出现）
- workspace（知识库）节点 URL 形状：**[PENDING-凭据]** —— 从探针 `+create --workspace <WS_ID>` 或 `wiki +node-get` 输出捕获
- B11 类型判定规则所需的「URL → 类型」样本集：PENDING（依赖真实 URL 捕获）

---

## 4. 内容通道实测结论 [help 实测]

裁决链 `@file → stdin → argv 单行兜底` 按各命令实际旗标落实为：

| 命令 | `@file` | stdin | 字面量/单行 | 文件旗标 |
| --- | --- | --- | --- | --- |
| `doc +create` | **支持**（`--content @工作目录相对路径`） | 支持（`--content -`） | `--content "..."` | 无独立 --content-file |
| `doc create`（原生） | **不支持 `@`** | 支持（`--content -`） | `--content "..."`（推荐 <2KB 无换行） | `--content-file <path>`（优先于 --content） |
| `doc +update` | 支持（同 +create） | 支持（`--content -`） | `--content`/alias `--text` | 无 |

- `@` 路径是**工作目录相对**（help 原文「内容字面量、@工作目录相对文件或 - 表示 stdin」）——adapter 里 subprocess 的 cwd 语义要锚定
- 长内容/多行走 `@file`（+命令）或 `--content-file`（原生 create）；argv 单行只兜底短字面量
- 真机回读验证 [live-captured 2026-09-09]：`+create`/`+update` 自带 verify 步
  （`data.verification.verified/readbackSha256`，markdown 通道通过）；
  **overwrite+jsonml 通道 verify 假阴性**（§7.4）；B8 探针多段中文+emoji 经
  `@file` 写入读回全量保真（closure report §3.1 原文）

---

## 5. 安装与 npm shim 事实 [实测]

- 控制器裁决：npm 全局安装（`npm i -g dingtalk-workspace-cli`），不用 install.ps1。实测装出 `v1.0.61 (50eb73a0, 2026-08-31T14:46:17Z)`
- **本机 npm 全局前缀不是惯例的 `%APPDATA%\npm`（该目录不存在），而是 nvm4w 的 `C:\nvm4w\nodejs`** —— shim 位置随 npm prefix 走，adapter 不应硬编码路径，用 `npm prefix -g` 解析或直接依赖 PATH
- 同一前缀下三个 shim 并存 [实测文件头]：
  - `dws` —— `#!/bin/sh` 包装脚本，**Git Bash 里 `dws` 解析到它**
  - `dws.cmd` —— cmd.exe 批处理包装，**Windows `subprocess`（非 shell、非 bash）必须解析到它**（`shutil.which("dws")` 在纯 Windows 进程里要显式找 `dws.cmd`）
  - `dws.ps1` —— PowerShell 包装
- 三个 shim 都只是转发到 node 入口脚本；Task 4 adapter 的 subprocess 解析规则：Git Bash 环境用 `dws`，原生 Windows 进程用 `dws.cmd`（`shell=False` 时 PATHEXT 不会自动补 .cmd）

---

## 6. fixtures 状态

`tests/fixtures/dws/` 本次只含本文件。三个捕获件（`doc-search.json` / `doc-fetch.json` / `version-list.json`）**未创建**——必须是真实 payload，凭据就绪前不造数。补捕后：结构原样保存，标题中的「临时」换中性词，token/URL 保留（fixtures 是 B11/adapter 的真值来源）。

> **裁决指针（2026-09-08 最终评审修复波次补记）**：上段「凭据就绪前不造数」的原始禁令已被维护者 2026-09-08 无账号裁决取代——`doc-search.json` / `doc-fetch.json` 两份 fixtures 已按该裁决以 **documented-not-captured** 形态落盘（provenance 逐键见 `FIXTURES-NOTE.md`）；`version-list.json` 仍按「未消费的命令不发明形状」未建。真机补捕时以真实捕获件原样覆盖。
>
> **回填（2026-09-09，B6/B8 兑现轮修复半场）**：凭据就绪，本目录全部 fixtures 已按真机捕获件**原样覆盖/新增**（live-captured，userId 剥除）——本节纪法执行完毕，见 §7。

---

## 7. 真机定谳补记 [live-captured 2026-09-09]（B6/B8 兑现轮修复半场）

以下全部为 dws v1.0.61 真机（MergeGameStudio 租户）捕获定谳，payload 全文在
`FIXTURES-NOTE.md` 所列 fixtures；e2e 载体 `tests/e2e/test_dingtalk_undo_real.py`。

### 7.1 fetch 档位与读车道纪法

- 默认档（`--detail simple`）：`content.markdown` 正文，**无 revision**。
- `--detail with-ids`（`full` 同键集）：`content.revision`（**字符串** `"1"`）+
  `content.jsonml`（JSONML 字符串），**无 markdown**。
- ⇒ **没有任何单档同时携带 markdown 与 revision**：要两者就打两枪
  （adapter `read_document` 的做法：with-ids 取 revision/title，默认档取正文）。
- `+fetch` 不收 `--doc-format`（`blocked_flag`）；历史版本 `--version N` 与
  `--detail` 可同用。

### 7.2 revision→version 映射替代通道（version-list 条目无 revision）

version-list 条目只有 `version` int（+type/时间戳/userId）。两轴映射用
**`doc +fetch --version N --detail with-ids` 读 `content.revision`**：真机实测
1:1（`--version 0 → "0"`、`--version 1 → "1"`，跨三个探针复现）；历史档 `content`
另带 `historyVersion` 键。读车道、幂等。新建文档即有两个版本
（0=AUTO_SAVE、1=OVERWRITE），create 后 `content.revision = "1"`。

### 7.3 teardown 删除句柄 = DOC_ID 本体

- `drive +find-file --query <kw>` 的 `files[].dentryId`、`drive +info` 的
  `data.fileId` 都等于 **DOC_ID 本体**（32 位字母数字）。
- `drive +info` 的 `data.dentryId` 是 **12 位内部号**，`drive +delete` 拒收
  （「nodeId 格式不合法，非 URL 格式时 nodeId 须为 dentryUuid：32 位字母数字
  字符串」）——B6/B8 兑现轮 teardown 三连败根因。
- `drive +delete --node <DOC_ID> -y` 实测成功（回收站 30 天可恢复），手工通道
  与测试 teardown 通道同权。

### 7.4 `doc +update` overwrite+jsonml 的 CLI 回读验证假阴性

`--command overwrite --doc-format jsonml --expected-revision <rev>`（唯一条件写
通道）真机行为：**写执行成功但 rc=1**——错误 envelope（在 **stderr**）
`reason: doc_write_verification_failed`、cause「回读结果未包含预期内容」、
`execution_started: true`、steps=`[update_document: success, verify: failed]`、
`retryable: false`、status `partial_success`。四轮复现（两探针 + 两独立复跑 +
多次 e2e）全部同一现场；同场对照：`overwrite --doc-format markdown` verify 通过
（rc=0）。⇒ 判定为 CLI 对 jsonml 源文与 markdown 读数的比对形状问题（结构性
假阴性），**写实际已落**（读回 markdown/revision+1/新 version 全部到位）。
处置按其错误契约自证：「请先检查当前内容，不要直接重试写入」——读回确认写后
内容出现即视为成功（e2e `_conditional_overwrite` 的恢复路径；CLI 修复后自动走
rc=0 快路径）。update 响应 `data` 块只有 `nodeId/verified`，**无 revision**。

### 7.5 瞬态读超时（环境类）

create 后立刻 `doc +fetch --detail with-ids` 偶发服务端 HSF 读超时（rc=1
`business_error`/`server_error_code: internalError`，message 带
`HSFTimeOutException-HSF-0002`、timeout 3000ms）——with-ids 档要服务端现拼
JSONML，比 markdown 档重。读幂等，有界重试安全（e2e `_fetch_detail` 内置
2 次 × 2s）。六轮真机运行中出现一次。

### 7.6 kgent 侧契约（真机证实，非 dws）

- `kgent undo` 对 **rejected 计划按设计退 rc=1**，全量 JSON 证据在 stdout
  （`src/kgent/cli.py`：「return 0 if plan["status"] == "ok" else 1」）——
  消费方按 JSON 解析后断言 `status`，不能把 rc!=0 当命令失败。
- FM2 真机读数：第三方 append 后 undo → `status: rejected`、
  reason `document edited since the journaled write: expected revision 2,
  current 3`、`plan.revision_current: "3"`（新鲜度读经 DingTalkAdapter 读车道，
  `backends.dingtalk.enabled: true` 门内）。
- B6 真机读数：undo plan `status: ok`（mechanism version-revert、
  `history_hint: dws doc +version-list`、TOCTOU `revision_current` 与 fetch
  读数一致）→ `doc +version-revert --version 1` → 读回 AAA-CONTENT 还原、
  写后内容消失。
