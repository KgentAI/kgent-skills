# PROBE-NOTES — dws 命令真值单（Phase 2 Task 1）

- 探测日期：2026-09-08
- CLI：`dws version v1.0.61 (50eb73a0, 2026-08-31T14:46:17Z)`，npm 包 `dingtalk-workspace-cli`
- 环境：Windows 11 + Git Bash（win32）
- 探测方式标注：
  - **[help 实测]** = 在本机 `dws <path> --help` / `dws schema --cli-path ... --compact` 实际输出，逐字核对过
  - **[PENDING-凭据]** = 需要登录后真机捕获，本次**未捕获**，标注了补捕命令

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
| 删除探针（teardown） | **`dws drive +delete --node <dentryUuid>`** | 移入回收站（非永久删）；反悔用 `dws drive +recycle-restore` | effect=destructive risk=high confirmation=user_required |

注意：`doc` 树里**没有删除命令**——帮助明说「文件管理（…删除…）已迁移到 dws drive」，探针 teardown 走 `dws drive +delete`，`--node` 要的是 **dentryUuid**（drive 域的节点 ID），不是 doc 域的 DOC_ID；两域 ID 的对应关系是真机补捕时要顺带验证的点 [PENDING-凭据]。

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

## 2. payload 键位表 —— **[PENDING-凭据]**

真实 payload 未捕获（见 §0）。README 形状仅作占位假设，**禁止**在捕获前写进 fixtures 或硬编码进 adapter。补捕后按实测修正本节：

| payload | 需要确认的字段路径 | 状态 |
| --- | --- | --- |
| search hit | `id` / `title` / `url` / `type` 字段路径（是否在 `items[]` 下、外层分页键名 nextPageToken 等） | PENDING |
| fetch | `revision`（编辑版本号，供 +update --expected-revision 条件写）与 `content`（Markdown 正文）字段路径 | PENDING |
| version-list | 条目的 `(revision, version_id)` 字段路径——注意版本轴（version 号）与修订轴（revision 号）在 dws 里是**两个不同的轴**：`+fetch --revision` 被明确标注不支持，历史版本走 `--version` | PENDING |
| create 响应 | 新文档 DOC_ID 与原生 URL 字段路径 | PENDING |
| drive +delete 响应 | 回收站条目 ID 字段路径（teardown 验账用） | PENDING |

补捕命令（登录后原样执行，输出直接存 fixtures）：

```bash
mkdir -p /tmp/dws-probe && cd /tmp/dws-probe
printf '# kgent-phase2-probe-临时\n\nprobe body line for payload capture.\n' > probe.md
dws doc +create --name "kgent-phase2-probe-临时" --content @probe.md -f json | tee create.json
dws doc +search --query "kgent-phase2-probe" -f json | tee doc-search.json
dws doc +fetch --node <create.json 里的 DOC_ID> -f json | tee doc-fetch.json
dws doc +version-list --node <DOC_ID> -f json | tee version-list.json
dws drive +delete --node <drive 域 dentryUuid> -f json | tee delete.json   # teardown，必做
```

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
- 真机回读验证（写入后 +fetch 比对）PENDING-凭据

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
