# PROBE-NOTES — wecom-cli 命令真值单（Phase 3 Task 1）

- 探测日期：2026-09-08
- CLI：`wecom-cli 1.2.1 (wecom 2026-09-08T11:59:47Z e88bf90)`，npm 包 `@wecom/cli`
- 环境：Windows 11 + Git Bash（win32）
- 探测方式标注：
  - **[help 实测]** = 在本机 `wecom-cli <path> --help` 实际输出，逐字核对过
  - **[schema 实测]** = `wecom-cli schema get <service.resource.method>` 机器契约实际输出（无需凭据）
  - **[live 实测]** = 真机调用实测（本任务只有错误档/`--dry-run` 达成，正常档见 §0）
  - **[PENDING-凭据]** = 需要 auth 后真机捕获，本次**未捕获**，标注了补捕命令

## 0. auth 状态（本任务写入时的阻塞点）——**version 轴定谳未完成**

维护者本人扫码（人工闸②已批准，维护者在线等），两个扫码窗口均超时无人扫码，**auth 未建立**：

| 窗口 | 起止 | 结果 |
| --- | --- | --- |
| 第 1 次 | 16:17 → 16:22 | 超时：`{"error":{"type":"UnknownError","code":893999,"message":"QrTimeout: 扫码超时（5 分钟），请重试 [code=893202]"}}`，exit 1 |
| 第 2 次（重发） | 16:22 → 16:27 | 同上超时 |

- 扫码方式：`wecom-cli auth init --no-browser --output-qrcode qr.png`（终端二维码不回显到维护者可见界面，QR 落仓库根 PNG + 站内通知，维护者打开 PNG 扫码）[live 实测]
- 授权流程本身可用：二维码生成（终端 ASCII + PNG + `https://work.weixin.qq.com/ai/qc/gen?...scode=...` 链接）、「等待扫码中...」状态正常 [live 实测]
- 最终状态：`wecom-cli auth show --status` → `unauthorized`（exit 0，单行输出）[live 实测]
- `~/.config/wecom/` 已创建但**无 `credentials.enc`**（只有 `cache/`）——凭证文件只在授权成功后落盘 [live 实测]

**因此 Step 4 真机探针（version 轴 V1/V2/V3 三次读数）未执行，设计裁决第 4 条的门控事实仍未定谳。** §4 有一次跑完的补捕脚本；补捕后本节与 FIXTURES-NOTE 必须回填。

---

## 1. 命令真值表

### 1.1 关键结论（handoff/README 形状 vs 实测）

| handoff/README 写法 | 实测真值 | 方式 |
| --- | --- | --- |
| ⚠「正常输出是否 JSON 默认待定谳」 | **JSON 默认**，pretty-print（2 空格缩进）；错误档同为 JSON，exit 1 | [live 实测] |
| ⚠「错误 envelope 键：`errcode` vs `code`」 | **CLI 层错误统一 `{"error":{"type","code","message"}}`**（type=UnknownError、code=893999 兜底、message 内嵌 `[code=893201]` 原始码）；**类型化响应体内**另带 `errcode`(int32)/`errmsg` 字段族（schema 定义，正常档是否出现 PENDING-凭据） | [live 实测]+[schema 实测] |
| 「delete 动词存在性」 | **`doc` 域没有任何删除命令**：`doc --help` 全树只有 create/import/search/contents/members/names/rules；`schema list` 全量 90 个 method 里 delete 只有 `sheet.subsheets.delete`、`smartsheet.{charts,fields,records,sheets,views}.delete`、`todo.delete` → **rename 隔离 teardown 定案** | [help 实测]+[schema 实测] |
| （handoff 未提） | `smartpage pages update --delete-page <json>` 存在，但只删智能文档**内部子页**，不是顶层文档删除——不能当 doc 探针的 teardown | [help 实测] |
| 「identity whoami 仅 bot 身份」 | help 原文「获取当前会话身份, **涵盖机器人和真人双重身份**」——与「仅 bot」说法冲突，以 help 为准待真机复核 | [help 实测] |
| 「邮件 README 称 send/reply/forward vs docs 称只读」 | 顶层 help 原文「邮件服务，提供邮件发送、回复、转发、列表查询、详情读取与搜索能力」，且 `schema list` 有 `mail.send`——**CLI 层有发送通道**；docs 的「只读」说法按 SKILL.md 已知限制收录但降级为存疑 | [help 实测]+[schema 实测] |
| 「`doc contents get` 支持 text 和 ooxml」 | **`content_type` 枚举 `text|markdown|ooxml`，不传默认 markdown**（markdown 才是默认档，handoff 未强调） | [schema 实测] |
| 「`doc import` 的 doc_type 枚举 ⚠ 实测」 | **`doc|sheet|smartsheet`**（schema enum）——**不含 `smartpage`**；md → 智能文档走独立的 `smartpage.import` | [schema 实测] |

### 1.2 探针生命周期命令（Task 2/3/4 直接消费）

| 用途 | 命令 | `--json` 请求体参数（schema 名） | 关键限制 [schema 实测] |
| --- | --- | --- | --- |
| 建探针 | `wecom-cli doc import --json '{"doc_type":"doc","file_name":"...docx","file_path":"<本地路径>"}'` | `append_doc_id`(仅 sheet/smartsheet)、`content_path`(hidden)、`doc_type`、`file_content`、`file_name`(1-255)、`file_path`、`passwd` | `file_path` 与 `file_content` 二选一；响应 `docid/task_id/task_status(succ\|fail\|processing)/url` |
| 建探针（免文件） | `wecom-cli doc create --json '{"doc_name":"...","doc_type":"doc","content":"...","content_type":"text|markdown"}'` | `content`(≤1MB)、`content_path`、`content_type`、`doc_name`(1-255)、`doc_requests`、`doc_type` | 响应 `docid/doc_name/url`；`doc_requests[]` 支持块级编辑（含 `delete_content`——内容级删除，非文档删除） |
| 搜索 | `wecom-cli doc search --json '{"keywords":[...],"limit":10}'` | `created_after/before`、`creator_userids`、`cursor`、`doc_types`、`hl_fragment_len`(≤512)、`keywords`(**必填**)、`limit`(≤100)、`number_of_fragments`(≤10)、`opened_after/before`、`search_scope`、`sort_by`、`sort_script`、`visitor_userids` | `search_scope`: `title|title_content|content`（默认 title_content）；`sort_by`: `best_match|create_time|modify_time`；时间格式 `YYYY-MM-DD HH:mm:ss` |
| 读探针 | `wecom-cli doc contents get --json '{"docid":"..."}'` | `content_type`、`docid`(必填，minLength 5) | `docid` 接受 docid 或 url；响应族见 §2 |
| 追加 | `wecom-cli doc contents append --json '{"docid":"...","content":"..."}'` | `content`(≤**10000**)、`docid`(必填) | 仅 text；**无文件通道**（schema 无 file_path/content_path） |
| 覆盖写 | `wecom-cli doc contents overwrite --json '{"docid":"...","content_type":"text","file_path":"b.md"}'` | `content`(≤1MB)、`content_path`(hidden)、`content_type`、`docid`(必填)、`file_path` | `content_type`: `text|markdown`；`content` XOR `file_path`；清空传 `" "`（文档说法，真机 PENDING） |
| 改名（teardown） | `wecom-cli doc names update --json '{"docid":"...","new_name":"kgent-phase3-probe-DELETE-ME-..."}'` | `docid`(必填)、`new_name`(1-255，必填) | 成功返回空对象 `OaDocRenameTypedRsp: {}` |
| 身份 | `wecom-cli identity whoami` | 无必填 | help 称机器人+真人双重身份（§1.1 冲突项） |
| 状态 | `wecom-cli auth show --status` | —（`--status` 旗标） | 单行 `authorized`/`unauthorized`，exit 0 |

### 1.3 输入通道与通用旗标 [help 实测]

每个 doc 方法都有三层输入通道：

- `--json '<JSON>'` — 请求体原始 JSON 字符串（**kgent adapter 固定用这个**）
- `--set deep.path=val` — 深层路径覆盖，可重复
- 展开的同名长旗标（如 `--docid`/`--content-type`/`--file-path`；`--content-path` 是 `file_path` 的兼容别名，schema 标 `hidden`）

通用旗标（全方法一致）：

- `--dry-run` — 本地校验不发送；输出 `=== Dry Run ===` + method/URL/headers/payload，exit 0（headers 含 `x-wecom-trace`、`x-wecom-cli-info`）
- `--page-count <n>` — 启用自动分页，输出 **NDJSON**
- `--page-delay <ms>` — 默认 100
- `-o, --output <file>` / `--output-dir <dir>` — 响应落盘（文档称 0600）
- `--schema` / `--doc` — 服务级与方法级文档
- 隐藏内建：`wecom-cli schema list`、`wecom-cli schema get <service.resource.method>`、`wecom-cli cache status|clear`（cache 目录 `~/.config/wecom/cache/`）

### 1.4 错误契约 [live 实测 + schema 实测]

- exit code：成功 0；错误 1（文档所称 0/1/2 中的 2 未在本任务复现）
- CLI 层错误 envelope（真机三例一致：search / contents get / names update 未授权调用）：

```json
{
  "error": {
    "type": "UnknownError",
    "code": 893999,
    "message": "AuthError: 该请求需要授权，请先运行 `wecom-cli auth init` 登录 [code=893201]"
  }
}
```

- `message` 尾部 `[code=893xxx]` 携带服务端原始码（893201=AuthError、893202=QrTimeout）；`code` 顶层字段是 CLI 兜底 893999
- 类型化响应体（schema 定义）含 `errcode`(int32)/`errmsg`(string) 字段族——正常档是否返回 `errcode:0` **[PENDING-凭据]**

---

## 2. payload 键位表 [schema 实测]（叶子值 PENDING-凭据）

schema 机器契约已钉死字段名与类型；真实取值/递增性未捕获。

### 2.1 `doc.contents.get` → `OaWordGetContentTypedRsp`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `url` | string | 文档链接 |
| `name` | string | 文档标题 |
| `content` | string | 文档内容（**内容不长时直接返回原文**） |
| `file_path` | string | 内容超长时框架自动落盘，值为文件路径（`x-wecom-file-save fileName=doc_content`）——相对/绝对语义 **[PENDING-凭据]** |
| `version` | **integer (uint32)** | 文档版本 |
| `document` | object(OaNode) | 仅 `content_type=ooxml` 时返回 |
| `errcode`/`errmsg` | int/string | 见 §1.4 |

**`version` 类型已定谳为整数；「每次编辑是否递增」未定谳（§0）——B5/undo 新鲜度设计的门控事实。**

### 2.2 `doc.search` → `OaDocSearchTypedRsp`

容器键：`docs[]`、`docs_count`（框架自动生成的数组长度）、`has_more`、`next_cursor`。

hit（`OaDocSearchDocInfo`）字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `docid` | string | 文档 ID |
| `doc_name` | string | 文档标题 |
| `doc_type` | string | `doc/sheet/smartsheet/smartpage`（schema 描述） |
| `url` | string | 文档 URL |
| `creator_userid` | string | 创建人 userid（**cpp 层 encode 为 OpenID**） |
| `creator_name` | string | 创建人显示名（cpp 层注入） |
| `create_time` | **string** | `YYYY-MM-DD HH:mm:ss`（**不是 epoch int**） |
| `modify_time` | **string** | 同上 |
| `open_time` | string | 最近查看时间 |
| `ai_notice` | string | 智能助理来源提示语，非空可展示 |
| `title_highlight` | **string[]** | 标题高亮摘要（**数组**） |
| `sub_title_highlight` | **string[]** | 子标题高亮摘要（**数组**） |
| `text_highlight` | **string[]** | 正文高亮摘要（**数组**） |

### 2.3 `doc.import` → `OaDocImportTaskCreateTypedRsp`

`docid`（导入成功后的文档 ID）、`task_id`（导入任务 ID）、`task_status`（enum `succ|fail|processing`，查询任务时返回）、`url`。同一命令传 `taskid` 即查任务状态（轮询面）。

---

## 3. 原生 URL 形状

- schema 只说「文档链接」，未给模板；`doc.weixin.qq.com/<type>/<docid>?scode=...` 的 `<type>` 实测值集 **[PENDING-凭据]**（候选 doc/sheet/smartsheet/smartpage；`?scode=` 参数存在性同样待捕获）
- 补捕时从 `doc create`/`doc import` 响应 `url` + `doc search` hit `url` 两处交叉取值

---

## 4. teardown 定案与补捕脚本

**定案：rename 隔离**（`doc names update` → `kgent-phase3-probe-DELETE-ME-*` 前缀）+ leftover 点名。理由见 §1.1（doc 域零删除命令）。

**本次 leftover：无**——auth 未建立，探针文档根本没建成（`doc import` 在未授权下直接 893201），WeCom 侧零残留，无需清理。

补捕脚本（授权后原样执行；**version 轴三次读数是第一优先级**）：

```bash
mkdir -p /tmp/wecom-probe && cd /tmp/wecom-probe
# 探针 .docx 用 stdlib zipfile 生成（Task 5 e2e _write_probe_docx 同形态），见 task-1-brief Step 4
wecom-cli doc import --json '{"doc_type":"doc","file_name":"kgent-phase3-probe-临时.docx","file_path":"probe.docx"}' | tee import.json
wecom-cli doc contents get --json '{"docid":"<DOCID>"}' | tee doc-contents-get-v1.json   # version=V1
wecom-cli doc contents append --json '{"docid":"<DOCID>","content":"BBB-APPEND"}'
wecom-cli doc contents get --json '{"docid":"<DOCID>"}' | tee doc-contents-get-v2.json   # V2>V1?
wecom-cli doc contents overwrite --json '{"docid":"<DOCID>","content_type":"text","file_path":"c.md"}'
wecom-cli doc contents get --json '{"docid":"<DOCID>"}' | tee doc-contents-get-v3.json   # V3>V2?（裁决第 4 条定谳）
wecom-cli doc search --json '{"keywords":["kgent-phase3-probe"],"search_scope":"title_content","limit":10}' | tee doc-search.json
wecom-cli doc names update --json '{"docid":"<DOCID>","new_name":"kgent-phase3-probe-DELETE-ME-临时"}'  # teardown
```

V1<V2<V3 递增 → 裁决成立；不递增 → 立即停手上报（FM3 快照内容比对兜底路线）。真机补捕后：真实 payload 原样覆盖 `tests/fixtures/wecom-cli/` 两份 fixture，并回填本文件 §0/§2/§3 与 FIXTURES-NOTE。

---

## 5. 安装与 npm shim 事实 [实测]

- `npm install -g @wecom/cli` → 装出 **v1.2.1**（≥1.1.0 门槛达标；build 2026-09-08T11:59:47Z，commit e88bf90，distribution=wecom）
- npm 全局前缀 = **`C:\nvm4w\nodejs`**（nvm4w，非 `%APPDATA%\npm`——与 dws 探针结论一致，adapter 用 `npm prefix -g` 或 PATH 解析，勿硬编码）
- 同一前缀三 shim 并存：`wecom-cli`（sh 包装，**Git Bash 解析到它**）、`wecom-cli.cmd`（cmd 包装，**原生 Windows subprocess 必须解析到它**）、`wecom-cli.ps1`（PowerShell 包装）——Task 4 adapter 的 subprocess 解析规则与 dws 相同
- `npx skills add WeComTeam/wecom-cli -y -g`：14 个 `wecomcli-*` skill 对 **PromptScript 目标报「does not support global skill installation」**，但 **agents 目标安装成功**——14 个 skill 全部落 `~/.agents/skills/wecomcli-*`（`~/.claude/skills` 同名可见）；`wecomcli-shared/SKILL.md` 定义的前置检查即 `wecom-cli --version` ≥1.1.0 + `auth show --status`
- config 目录 `~/.config/wecom/`（`WECOM_CLI_CONFIG_DIR` 可覆写）；未授权时只有 `cache/`，无 `credentials.enc`
